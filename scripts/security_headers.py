"""Build and attach the web app's security headers: CSP and HSTS (ADR-574).

Usage: python scripts/security_headers.py <staging|prod> [--enforce] [--apply]

The one source of the policy. A CloudFront response-headers policy sets the
headers, because S3 can't. Default is a DRY RUN that prints the policy and,
where one exists, the diff from the live one. --apply creates or updates the
policy and attaches it to the distribution.

CSP is sent as Content-Security-Policy-Report-Only unless --enforce (D2):
violations show in the browser console and nothing breaks. CloudFront's
built-in CSP field can only send the enforcing header, so report-only travels
as a custom header, and the two never coexist.

Attaching re-sends the distribution's LIVE config with one field changed.
UpdateDistribution is a full replace, the trap ADR-525 hit four times with
Cognito.
"""
import json
import sys

ENVIRONMENTS = {
    "staging": {"distribution": "E2VJ2CDF4A0MUW", "api": "https://api-staging.asheflow.com"},
    "prod": {"distribution": "E22NJCS9JDU8FG", "api": "https://api.asheflow.com"},
}

# D5: ramp. One day first; a year once a week has passed with nothing broken.
# includeSubDomains and preload are separate decisions (they reach api. too).
HSTS_MAX_AGE = 86400

COGNITO = "https://cognito-idp.us-east-2.amazonaws.com"
MAPS_SCRIPT = ["https://maps.googleapis.com", "https://maps.gstatic.com"]
GOOGLE_ASSETS = ["https://*.googleapis.com", "https://*.gstatic.com"]


def csp(api_origin: str) -> str:
    """D3. Each source is here because the built bundle uses it."""
    directives = {
        "default-src": ["'self'"],
        # 'wasm-unsafe-eval' compiles Tesseract's wasm; it does not allow eval().
        "script-src": ["'self'", "'wasm-unsafe-eval'", *MAPS_SCRIPT],
        # React style={} and Google Maps set inline styles.
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "https://fonts.gstatic.com", "data:"],
        "img-src": ["'self'", "data:", "blob:", *GOOGLE_ASSETS,
                    "https://*.google.com", "https://*.googleusercontent.com"],
        "connect-src": ["'self'", api_origin, COGNITO, *GOOGLE_ASSETS],
        # Tesseract starts its worker from a blob: URL.
        "worker-src": ["'self'", "blob:"],
        "frame-src": ["https://*.google.com"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{k} {' '.join(v)}" for k, v in directives.items())


def policy_config(env: str, enforce: bool) -> dict:
    policy = csp(ENVIRONMENTS[env]["api"])
    security = {
        "StrictTransportSecurity": {"Override": True, "AccessControlMaxAgeSec": HSTS_MAX_AGE,
                                    "IncludeSubdomains": False, "Preload": False},
        "ContentTypeOptions": {"Override": True},
        # D6: protects now, while frame-ancestors is only reported.
        "FrameOptions": {"Override": True, "FrameOption": "DENY"},
        "ReferrerPolicy": {"Override": True, "ReferrerPolicy": "strict-origin-when-cross-origin"},
    }
    custom = []
    if enforce:
        security["ContentSecurityPolicy"] = {"Override": True, "ContentSecurityPolicy": policy}
    else:
        custom.append({"Header": "Content-Security-Policy-Report-Only", "Value": policy, "Override": True})
    config = {
        "Name": f"asheflow-security-headers-{env}",
        "Comment": f"ADR-574: CSP ({'enforced' if enforce else 'report-only'}) + HSTS. Built by scripts/security_headers.py",
        "SecurityHeadersConfig": security,
    }
    if custom:
        config["CustomHeadersConfig"] = {"Quantity": len(custom), "Items": custom}
    return config


def _find_policy(cf, name: str):
    for item in cf.list_response_headers_policies(Type="custom").get(
            "ResponseHeadersPolicyList", {}).get("Items", []):
        p = item["ResponseHeadersPolicy"]
        if p["ResponseHeadersPolicyConfig"]["Name"] == name:
            return p["Id"]
    return None


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ENVIRONMENTS:
        print(__doc__)
        return 2
    env, enforce, apply = argv[0], "--enforce" in argv, "--apply" in argv
    config = policy_config(env, enforce)
    print(json.dumps(config, indent=2))
    if not apply:
        print("\nDRY RUN: nothing sent. Re-run with --apply.")
        return 0

    import boto3
    cf = boto3.client("cloudfront")
    policy_id = _find_policy(cf, config["Name"])
    if policy_id:
        live = cf.get_response_headers_policy_config(Id=policy_id)
        cf.update_response_headers_policy(ResponseHeadersPolicyConfig=config, Id=policy_id,
                                          IfMatch=live["ETag"])
        print(f"updated policy {policy_id}")
    else:
        policy_id = cf.create_response_headers_policy(
            ResponseHeadersPolicyConfig=config)["ResponseHeadersPolicy"]["Id"]
        print(f"created policy {policy_id}")

    dist = ENVIRONMENTS[env]["distribution"]
    live = cf.get_distribution_config(Id=dist)
    dc = live["DistributionConfig"]
    before = dc["DefaultCacheBehavior"].get("ResponseHeadersPolicyId")
    if before == policy_id:
        print(f"{dist} already uses {policy_id}; the policy update is live")
        return 0
    dc["DefaultCacheBehavior"]["ResponseHeadersPolicyId"] = policy_id
    cf.update_distribution(Id=dist, DistributionConfig=dc, IfMatch=live["ETag"])
    after = cf.get_distribution_config(Id=dist)["DistributionConfig"]
    changed = [k for k in after if k != "DefaultCacheBehavior" and after[k] != dc[k]]
    print(f"{dist}: ResponseHeadersPolicyId {before} -> "
          f"{after['DefaultCacheBehavior'].get('ResponseHeadersPolicyId')}; "
          f"other top-level fields changed: {changed or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
