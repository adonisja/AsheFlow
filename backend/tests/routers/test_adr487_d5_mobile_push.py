"""Mobile push registration: Android-only, additive, revoked before sign-out (ADR-487 D5).

Python over TypeScript for the same reason as test_adr494_mobile_surface.py: the
mobile app has no test runner in CI and this suite runs on every push.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOBILE = ROOT / "mobile"
REG = MOBILE / "src/api/pushRegistration.ts"
AUTH = MOBILE / "src/contexts/AuthContext.tsx"
NAV = MOBILE / "src/navigation/index.tsx"
RNCFG = MOBILE / "react-native.config.js"
APP_GRADLE = MOBILE / "android/app/build.gradle"


def _code(path: Path) -> str:
    """Comments stripped — this repo has 18 recorded prose-not-code false passes."""
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


class TestFirebaseNeverLoadsOnIos:
    """iOS needs the raw APNs token, and the Apple step is parked. Firebase is
    linked on Android only, so its JS must never execute on iOS — a top-level
    import would evaluate there and could take the app down."""

    def test_no_top_level_import_of_firebase(self):
        src = _code(REG)
        assert not re.search(r"^import .*@react-native-firebase", src, re.M), (
            "pushRegistration imports Firebase at the top level, so it evaluates "
            "on iOS where the native module is not linked"
        )

    def test_the_require_is_behind_an_android_guard(self):
        src = _code(REG)
        fn = src[src.index("function messaging()"):]
        fn = fn[: fn.index("\n}\n") + 2]
        assert "Platform.OS !== 'android'" in fn
        assert fn.index("Platform.OS !== 'android'") < fn.index("require("), (
            "the Firebase require runs before the Android check"
        )

    def test_autolinking_excludes_ios(self):
        src = _code(RNCFG)
        for pkg in ("@react-native-firebase/app", "@react-native-firebase/messaging"):
            block = src[src.index(f"'{pkg}'"):]
            block = block[: block.index("},\n    },") + 1]
            assert "ios: null" in block, f"{pkg} is autolinked on iOS"


class TestRevokeRunsBeforeTheSessionEnds:
    def test_unregister_precedes_clear_tokens(self):
        """The revoke is an authenticated DELETE; after clearTokens it 401s and
        the phone keeps receiving the previous user's notifications."""
        src = _code(AUTH)
        body = src[src.index("const signOut = useCallback"):]
        body = body[: body.index("}, [])")]
        assert "unregisterFromPush()" in body, "signOut never revokes the device"
        assert body.index("unregisterFromPush()") < body.index("clearTokens()"), (
            "the device is revoked AFTER the tokens are cleared, so the DELETE "
            "is unauthenticated and fails"
        )


class TestPushIsAdditive:
    def test_registration_happens_after_sign_in(self):
        """MainShell mounts only when signed in — the permission prompt then has
        context instead of appearing on the login screen."""
        src = _code(NAV)
        shell = src[src.index("function MainShell()"):]
        assert "registerForPush()" in shell[: shell.index("return (")]

    def test_every_network_call_is_guarded(self):
        src = _code(REG)
        assert src.count("try {") >= 4, "a push failure could reach sign-in or sign-out"

    def test_unregister_never_throws(self):
        src = _code(REG)
        fn = src[src.index("export async function unregisterFromPush"):]
        assert "catch" in fn[: fn.index("\n}\n")]


class TestTheBuildSurvivesAMissingFirebaseConfig:
    """google-services.json comes from the Firebase console. An unconditional
    plugin breaks EVERY Android build until it exists."""

    def test_the_plugin_is_conditional(self):
        src = APP_GRADLE.read_text()
        assert 'file("google-services.json").exists()' in src
        lines = [l for l in src.splitlines()
                 if "com.google.gms.google-services" in l and "apply plugin" in l]
        assert len(lines) == 1, "the plugin is applied more than once"
        idx = src.index(lines[0])
        assert src.rfind('if (file("google-services.json").exists())', 0, idx) != -1, (
            "the google-services plugin is applied unconditionally"
        )


class TestVersionsArePinned:
    def test_firebase_packages_are_exact(self):
        deps = json.loads((MOBILE / "package.json").read_text())["dependencies"]
        for pkg in ("@react-native-firebase/app", "@react-native-firebase/messaging"):
            assert pkg in deps
            assert re.fullmatch(r"\d+\.\d+\.\d+", deps[pkg]), (
                f"{pkg} is {deps[pkg]!r}; the two must move together, and a range "
                f"lets one drift from the other"
            )
        assert deps["@react-native-firebase/app"] == deps["@react-native-firebase/messaging"]


class TestItUsesTheModularApi:
    """React Native Firebase v26 has no default export.

    The first version called `(mod.default ?? mod)()`. On v26 that calls the
    module object, throws, and the throw was swallowed, so registration quit
    before the permission prompt and push was silently off on every Android
    device. Found only by signing in on a real emulator: no dialog, no row.

    These read source and package.json rather than node_modules, because CI's
    backend job does not install the mobile dependencies, and a test that only
    runs where node_modules happens to exist is the environment-dependent
    test this file exists to avoid.
    """

    def _code(self) -> str:
        return re.sub(r"//[^\n]*|/\*.*?\*/", "", REG.read_text(), flags=re.S)

    def test_the_pinned_major_is_one_without_a_default_export(self):
        deps = json.loads((MOBILE / "package.json").read_text())["dependencies"]
        major = int(re.match(r"\D*(\d+)", deps["@react-native-firebase/messaging"]).group(1))
        assert major >= 22, (
            "below v22 the modular API did not exist; this class assumes it does"
        )

    def test_it_calls_getMessaging_not_the_module(self):
        code = self._code()
        assert "getMessaging" in code, "the v26 entry point is getMessaging()"
        assert ".default" not in code, (
            "v26 has no default export — `.default` is undefined, and calling "
            "the module object instead throws inside a catch that hides it"
        )

    def test_token_calls_take_the_instance(self):
        code = self._code()
        assert re.search(r"\bgetToken\(\s*instance\s*\)", code), (
            "modular getToken takes the Messaging instance as its first argument"
        )
        assert re.search(r"\bonTokenRefresh\(\s*instance\s*,", code), (
            "modular onTokenRefresh takes (instance, listener)"
        )

    def test_the_require_catch_is_not_silent(self):
        code = REG.read_text()
        fn = code[code.index("function messaging()"):code.index("async function ensurePermission")]
        assert "console.warn" in fn, (
            "the catch around the Firebase require must log in dev: a silent "
            "catch is what hid the removed API"
        )
