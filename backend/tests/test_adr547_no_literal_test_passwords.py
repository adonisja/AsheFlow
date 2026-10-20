"""No test writes a password down; it asks make_test_password() (ADR-547).

A password-shaped literal in a test stopped PR #80 at GitGuardian (incident
38384008), and an earlier one (ADR-456) was a real credential copied from a
screenshot. Splitting it into "Tm" + "p" + ... beat the scanner and kept the
fixed value. This walks every test file and fails on:

1. a password-NAMED target (keyword, dict key, assignment) given a literal,
   an f-string, or a + chain of constants;
2. a password-SHAPED constant anywhere (upper+lower+digit+symbol), which is
   how a positional argument with no name gets caught;
3. the same name rule in the JS test files.

Each detector is first run against planted samples, so one that has stopped
matching anything fails here rather than passing forever (ADR-499).
"""
import ast
import pathlib
import re

from tests._credentials import make_test_password

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS = ROOT / "backend" / "tests"
EXEMPT = {TESTS / "_credentials.py"}

NAME = re.compile(r"pass(word|wd|phrase|code)|pwd|temp_?pw", re.I)
# No spaces or code punctuation, so CSS, regexes and paths don't trip it.
SHAPE = re.compile(r"^[A-Za-z0-9!@#$%^&*?_.\-]{8,64}$")


def _is_literal(node: ast.AST) -> bool:
    """A value that is fixed in the source: a non-empty string, an f-string
    whose {} parts are constants of ANY type, or a + chain of those.

    f"pw-{1}" is fixed: the 1 is an int constant, not a string, and the first
    draft (which recursed into _is_literal) let it through. Probe 3 caught it."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value != ""
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(v, ast.Constant)
                   or (isinstance(v, ast.FormattedValue)
                       and (isinstance(v.value, ast.Constant) or _is_literal(v.value)))
                   for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_literal(node.left) and _is_literal(node.right)
    return False


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _shaped(s: str) -> bool:
    return bool(SHAPE.match(s)) and all(
        any(c in pool for c in s)
        for pool in ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz",
                     "0123456789", "!@#$%^&*?"))


def named_literals(tree: ast.AST) -> list[tuple[int, str]]:
    hits = []
    for n in ast.walk(tree):
        pairs = []
        if isinstance(n, ast.keyword) and n.arg:
            pairs.append((n.arg, n.value))
        elif isinstance(n, ast.Dict):
            pairs += [(_target_name(k), v) for k, v in zip(n.keys, n.values) if k is not None]
        elif isinstance(n, ast.Assign):
            pairs += [(_target_name(t), n.value) for t in n.targets]
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            pairs.append((_target_name(n.target), n.value))
        for name, value in pairs:
            if name and NAME.search(name) and _is_literal(value):
                hits.append((getattr(value, "lineno", 0), name))
    return hits


def shaped_constants(tree: ast.AST) -> list[tuple[int, str]]:
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and _shaped(n.value)]


def _test_files():
    return [p for p in TESTS.rglob("*.py") if p not in EXEMPT and "__pycache__" not in p.parts]


# ---------------------------------------------------------------- the planted samples

def _plant(src: str) -> str:
    """Fill each <PW> with a fresh generated password.

    Planted samples are test code too, and a scanner reads the SOURCE, string
    contents included: the first draft's typed samples were flagged twice, once
    by this guard (Case 4) and once by GitGuardian (incident 38439881, the JS
    sample sitting in a Python string). <PW> is the one placeholder EMBEDDED
    accepts."""
    while "<PW>" in src:
        src = src.replace("<PW>", make_test_password(), 1)
    return src


def test_the_detectors_still_catch_what_they_exist_for():
    positional = make_test_password()
    planted = _plant('''
f(password="<PW>")
f(new_password="<PW>" + "<PW>")
f(temp_password=f"x{'<PW>'}")
kw = {"old_password": "<PW>"}
SEED_PASSWORD = "<PW>"
kw2 = {"passcode": f"<PW>-{1}"}
pw_hash: str = "<PW>"
''') + f'Login(user, "{positional}")\n'
    tree = ast.parse(planted)
    names = {n for _, n in named_literals(tree)}
    assert names == {"password", "new_password", "temp_password", "old_password",
                     "SEED_PASSWORD", "passcode"}, names
    assert positional in [v for _, v in shaped_constants(tree)]


def test_the_detectors_leave_generated_and_non_password_values_alone():
    clean = '''
f(password=make_test_password())
f(password="")
f(password=pw)
f(password=f"{make_test_password()}")
kw = {"password": _NEW_PASSWORD, "label": "Password"}
NAMES = ["BOT_PASSWORD", "postgres_password"]
style = "translateX(-50%)"
'''
    tree = ast.parse(clean)
    assert named_literals(tree) == []
    assert shaped_constants(tree) == []


# ---------------------------------------------------------------- the real walk

def test_the_walk_reaches_the_test_tree():
    files = _test_files()
    assert len(files) > 200, f"only {len(files)} test files found; is TESTS wrong?"
    assert TESTS / "routers" / "test_adr541_credential_changes.py" in files


def test_no_test_hands_a_password_name_a_literal():
    offenders = []
    for p in _test_files():
        for line, name in named_literals(ast.parse(p.read_text())):
            offenders.append(f"{p.relative_to(ROOT)}:{line} {name}=<literal>")
    assert not offenders, (
        "Tests generate passwords; they never write one (ADR-547). Use "
        "tests._credentials.make_test_password():\n  " + "\n  ".join(offenders))


def test_no_test_holds_a_password_shaped_string():
    offenders = []
    for p in _test_files():
        for line, _ in shaped_constants(ast.parse(p.read_text())):
            offenders.append(f"{p.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "A password-shaped string literal in a test (ADR-547). Generate it with "
        "make_test_password(); the value is never shown here so this message is "
        "not itself a leak:\n  " + "\n  ".join(offenders))


# A password-named key or variable followed by a non-empty quoted value, in any
# language's syntax. <PW> (see _plant) is the only value it accepts.
EMBEDDED = re.compile(
    r"""\b\w*(?:pass(?:word|wd|phrase|code)|pwd)\w*['"]?\s*[:=]\s*(['"`])(?!\1)(?!<PW>)""", re.I)
JS_NAMED = EMBEDDED


def _js_test_files():
    out = []
    for base in (ROOT / "mobile", ROOT / "frontend" / "src"):
        for p in base.rglob("*"):
            if "node_modules" in p.parts or p.suffix not in {".ts", ".tsx", ".js"}:
                continue
            if "__tests__" in p.parts or re.search(r"\.(test|spec)\.[jt]sx?$", p.name):
                out.append(p)
    return out


def test_js_detector_catches_its_planted_sample():
    assert JS_NAMED.search(_plant("const newPassword = '<PW>';"))
    assert JS_NAMED.search(_plant('login({ password: "<PW>" })'))
    assert not JS_NAMED.search("const newPassword = '<PW>';")
    assert not JS_NAMED.search("login({ password: makeTestPassword() })")
    assert not JS_NAMED.search('const password = "";')


def test_no_js_test_writes_a_password():
    files = _js_test_files()
    assert files, "found no JS test files; has the mobile test tree moved?"
    offenders = [f"{p.relative_to(ROOT)}:{i}"
                 for p in files
                 for i, line in enumerate(p.read_text().splitlines(), 1)
                 if JS_NAMED.search(line)]
    assert not offenders, "A password literal in a JS test (ADR-547):\n  " + "\n  ".join(offenders)


def test_no_test_embeds_password_code_in_a_string():
    """Code inside a string is still code to a scanner: GitGuardian flagged
    this file's own JS sample, a newPassword assignment held in a Python
    string (incident 38439881). Quoting the line in this docstring tripped
    the rule too, so it is described, not quoted."""
    planted = ast.parse(_plant('''x = "login({ password: '<PW>' })"\n'''))
    assert any(EMBEDDED.search(n.value) for n in ast.walk(planted)
               if isinstance(n, ast.Constant) and isinstance(n.value, str))
    offenders = [f"{p.relative_to(ROOT)}:{n.lineno}"
                 for p in _test_files()
                 for n in ast.walk(ast.parse(p.read_text()))
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and EMBEDDED.search(n.value)]
    assert not offenders, (
        "Password-assigning code inside a test string (ADR-547). Plant it with "
        "_plant() and a <PW> placeholder:\n  " + "\n  ".join(offenders))
