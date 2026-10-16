"""Update a Cognito user pool WITHOUT dropping anything else (ADR-525).

Usage: python scripts/cognito_pool_update.py <pool-id> [--apply]

As written it (re)asserts ADR-385's DeviceConfiguration; to change something
else, edit TARGET/request(). Never hand-build an update-user-pool call: it is
a full replace, and four incidents (2026-09-02 trigger, 09-29 SES sender, 09-29
DeviceConfiguration on BOTH pools) came from omitted fields.

Originally: restore DeviceConfiguration on a Cognito pool WITHOUT dropping anything else.

update-user-pool is a FULL REPLACE: an omitted field is reset. So the request is
built from the pool's own current config, keeping every field UpdateUserPool
accepts, and only DeviceConfiguration is added. Default is a DRY RUN that prints
the diff between the live config and what would be sent; --apply sends it and
then re-reads and diffs live-before vs live-after.
"""
import copy, json, subprocess, sys

UPDATABLE = [  # every top-level input UpdateUserPool accepts (botocore model)
    "Policies", "DeletionProtection", "LambdaConfig", "AutoVerifiedAttributes", "SmsVerificationMessage",
    "EmailVerificationMessage", "EmailVerificationSubject", "VerificationMessageTemplate",
    "SmsAuthenticationMessage", "UserAttributeUpdateSettings", "MfaConfiguration", "DeviceConfiguration",
    "EmailConfiguration", "SmsConfiguration", "UserPoolTags", "AdminCreateUserConfig",
    "UserPoolAddOns", "AccountRecoverySetting", "PoolName", "UserPoolTier",
]
TARGET = {"ChallengeRequiredOnNewDevice": True, "DeviceOnlyRememberedOnUserPrompt": False}

def live(pool):
    out = subprocess.run(["aws", "cognito-idp", "describe-user-pool", "--region", "us-east-2",
                          "--user-pool-id", pool, "--output", "json"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["UserPool"]

def request(cfg):
    cfg = copy.deepcopy(cfg)   # never mutate the snapshot the diff is taken against
    req = {"UserPoolId": cfg["Id"]}
    for k in UPDATABLE:
        if k == "PoolName" and "Name" in cfg:
            req["PoolName"] = cfg["Name"]
        elif k in cfg and cfg[k] is not None:
            req[k] = cfg[k]
    # describe returns read-only bits inside some structures; strip them
    req.get("AdminCreateUserConfig", {}).pop("UnusedAccountValidityDays", None)
    req["DeviceConfiguration"] = TARGET
    return req

def flat(d, p=""):
    if isinstance(d, dict):
        r = {}
        for k, v in d.items(): r.update(flat(v, f"{p}.{k}" if p else k))
        return r
    return {p: json.dumps(d, sort_keys=True)}

pool, apply = sys.argv[1], "--apply" in sys.argv
before = live(pool)
req = request(before)
# what the request would CHANGE, among the fields it carries
b = flat({k: before.get("Name" if k == "PoolName" else k) for k in req if k != "UserPoolId"})
a = flat({k: v for k, v in req.items() if k != "UserPoolId"})
changes = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
print(f"{before['Name']}: request carries {len(req)-1} fields; differences from live:")
for k in changes: print(f"  {k}: {b.get(k)} -> {a.get(k)}")
missing = sorted(k for k in UPDATABLE if k not in req)
print("  updatable fields absent from live (left unset):", missing)
if not apply:
    print("DRY RUN — nothing sent."); sys.exit(0)
inp = "/tmp/pool_req.json"; json.dump(req, open(inp, "w"))
subprocess.run(["aws", "cognito-idp", "update-user-pool", "--region", "us-east-2", "--cli-input-json", f"file://{inp}"], check=True)
after = live(pool)
fb, fa = flat(before), flat(after)
skip = ("LastModifiedDate",)
moved = sorted(k for k in set(fb) | set(fa) if fb.get(k) != fa.get(k) and not k.startswith(skip))
print("LIVE before -> after, every key that moved:")
for k in moved: print(f"  {k}: {fb.get(k)} -> {fa.get(k)}")
