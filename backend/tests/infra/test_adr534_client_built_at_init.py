"""The sign-in trigger builds its AWS client at import, not on first call (ADR-534).

Cold sign-ins took ~3 s at 128 MB, ~2.7 s of it inside the handler because
the boto3 client was built lazily -- against Cognito's hard 5 s trigger limit,
where a timeout fails the sign-in and the handler's fail-open cannot help.
"""
import ast
import importlib.util
import pathlib
import sys

HANDLER = pathlib.Path(__file__).resolve().parents[3] / "infra" / "lambda" / "cognito-pre-auth" / "handler.py"


def test_the_client_is_built_at_module_level():
    tree = ast.parse(HANDLER.read_text())
    built_at_top = [
        n for n in tree.body if isinstance(n, ast.Try)
        and any(isinstance(s, ast.Assign) and any(getattr(t, "id", "") == "_client" for t in s.targets)
                and isinstance(s.value, ast.Call) and getattr(s.value.func, "id", "") == "_make_client"
                for s in n.body)
    ]
    assert built_at_top, "_client must be built at import (init phase), inside a try"


def test_loading_the_module_yields_a_client():
    spec = importlib.util.spec_from_file_location("pre_auth_handler_534", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_auth_handler_534"] = mod
    spec.loader.exec_module(mod)
    assert mod._client is not None


def test_a_failed_init_still_leaves_a_lazy_path():
    """Init must never stop the function loading; _cognito() builds it later."""
    src = HANDLER.read_text()
    i = src.index("def _cognito():")
    assert "if _client is None:" in src[i:i + 200]
