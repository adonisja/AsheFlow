"""ADR-574: the web app's CSP and HSTS, built by scripts/security_headers.py.

Pins the policy's safety properties and checks the frontend source against it:
a new third-party origin the policy doesn't allow fails here, not as a blank
page after an enforced CSP ships.
"""
import importlib.util
import pathlib
import re
from urllib.parse import urlsplit

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
spec = importlib.util.spec_from_file_location("security_headers", ROOT / "scripts" / "security_headers.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def _directives(policy: str) -> dict[str, list[str]]:
    out = {}
    for part in policy.split(";"):
        name, *sources = part.split()
        out[name] = sources
    return out


def _allows(sources: list[str], origin: str) -> bool:
    host = urlsplit(origin).hostname
    for s in sources:
        if s == origin:
            return True
        if s.startswith("https://*.") and host.endswith(s[len("https://*"):]):
            return True
    return False


@pytest.mark.parametrize("env", sorted(H.ENVIRONMENTS))
class TestThePolicy:
    def test_scripts_cannot_be_inlined_or_evaluated(self, env):
        d = _directives(H.csp(H.ENVIRONMENTS[env]["api"]))
        assert "'unsafe-inline'" not in d["script-src"]
        assert "'unsafe-eval'" not in d["script-src"]
        assert "'unsafe-eval'" not in d["default-src"]

    def test_framing_plugins_and_base_are_closed(self, env):
        d = _directives(H.csp(H.ENVIRONMENTS[env]["api"]))
        assert d["frame-ancestors"] == ["'none'"]
        assert d["object-src"] == ["'none'"]
        assert d["base-uri"] == ["'self'"]

    def test_tokens_can_only_go_to_the_api_and_cognito(self, env):
        d = _directives(H.csp(H.ENVIRONMENTS[env]["api"]))
        assert H.ENVIRONMENTS[env]["api"] in d["connect-src"]
        assert H.COGNITO in d["connect-src"]
        assert "*" not in d["connect-src"] and "https:" not in d["connect-src"]

    def test_each_environment_talks_only_to_its_own_api(self, env):
        d = _directives(H.csp(H.ENVIRONMENTS[env]["api"]))
        others = [e["api"] for k, e in H.ENVIRONMENTS.items() if k != env]
        assert not any(o in d["connect-src"] for o in others)

    def test_report_only_by_default_and_never_both(self, env):
        ro = H.policy_config(env, enforce=False)
        assert [h["Header"] for h in ro["CustomHeadersConfig"]["Items"]] == ["Content-Security-Policy-Report-Only"]
        assert "ContentSecurityPolicy" not in ro["SecurityHeadersConfig"]
        enf = H.policy_config(env, enforce=True)
        assert "CustomHeadersConfig" not in enf
        assert enf["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"] == H.csp(H.ENVIRONMENTS[env]["api"])

    def test_hsts_and_the_companion_headers_are_sent(self, env):
        s = H.policy_config(env, enforce=False)["SecurityHeadersConfig"]
        assert s["StrictTransportSecurity"]["AccessControlMaxAgeSec"] >= 86400
        # D5: these reach every subdomain (or the browsers' preload list); a
        # separate decision, never a side effect of raising max-age.
        assert s["StrictTransportSecurity"]["IncludeSubdomains"] is False
        assert s["StrictTransportSecurity"]["Preload"] is False
        assert s["ContentTypeOptions"]["Override"] is True
        assert s["FrameOptions"]["FrameOption"] == "DENY"
        assert s["ReferrerPolicy"]["ReferrerPolicy"] == "strict-origin-when-cross-origin"


class TestTheFrontendFitsThePolicy:
    def _sources(self):
        return [p for p in (FRONTEND / "src").rglob("*") if p.suffix in {".ts", ".tsx", ".css"}]

    def test_index_html_has_no_inline_script(self):
        html = (FRONTEND / "index.html").read_text()
        for attrs, body in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S):
            assert "src=" in attrs and not body.strip(), (
                "an inline <script> is blocked by script-src (ADR-574 D4); "
                "move it to frontend/public/ and load it by src")

    def test_every_script_the_app_loads_is_allowed(self):
        d = _directives(H.csp(H.ENVIRONMENTS["staging"]["api"]))
        found = set()
        for p in self._sources():
            for m in re.finditer(r"\.src\s*=\s*[`'\"](https://[^/`'\"$]+)", p.read_text()):
                found.add(m.group(1))
        assert found, "the scan found no script loaders; the regex has gone stale"
        for origin in found:
            assert _allows(d["script-src"], origin), (
                f"{origin} is loaded as a script but script-src doesn't allow it: "
                "add it in scripts/security_headers.py (ADR-574)")

    def test_every_stylesheet_import_is_allowed(self):
        d = _directives(H.csp(H.ENVIRONMENTS["staging"]["api"]))
        found = set()
        for p in self._sources():
            for m in re.finditer(r"@import\s+url\(['\"]?(https://[^/'\")]+)", p.read_text()):
                found.add(m.group(1))
        for origin in found:
            assert _allows(d["style-src"], origin), f"{origin} @import blocked by style-src (ADR-574)"
