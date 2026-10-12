"""The campaign tree verifies, and the maintained source is the measured one.

The records of campaign rc20261008 bind every measurement to the hashes of
the source that ran. Those exact files are released under campaign/source/.
The top-level packages are the maintained copy, formatted for this release;
these tests hold them to the measured code statement for statement, so a fix
made at the top level cannot silently diverge from what was measured.
"""

import ast
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
MEASURED = ROOT / "campaign/source/measured"
TPCC_RUN = ROOT / "campaign/source/tpcc-run"
# v1.1.0 resolved the project root from the script's own location; the
# measured file assumed it ran from the repository root.
ROOT_FIX = (
    'django_app_dir = Path(__file__).parent.parent / "django_app"\n'
    "project_root = Path(__file__).parent.parent\n",
    "project_root = Path(__file__).resolve().parents[2]\n"
    'django_app_dir = project_root / "django_app"\n',
)


def statements(source: str) -> str:
    """The module's AST without docstrings: what executes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree)


def measured_files():
    files = {p.relative_to(MEASURED): p for p in MEASURED.rglob("*.py")}
    # The transaction run used two corrected modules and its own configuration.
    files.update({p.relative_to(TPCC_RUN): p for p in TPCC_RUN.rglob("*.py")})
    return sorted(files.items())


def test_maintained_source_executes_as_measured():
    differing = []
    for rel, measured in measured_files():
        maintained = ROOT / rel
        assert maintained.is_file(), f"{rel} is measured but not maintained"
        expected = measured.read_text(encoding="utf-8")
        if rel.as_posix() == "scripts/1-setup/manage_indexes.py":
            actual = maintained.read_text(encoding="utf-8")
            assert ROOT_FIX[1] in actual
            expected_tree = statements(expected)
            actual_tree = statements(actual.replace(ROOT_FIX[1], ROOT_FIX[0]))
            assert expected_tree == actual_tree, rel
            continue
        if statements(expected) != statements(maintained.read_text(encoding="utf-8")):
            differing.append(rel.as_posix())
    assert not differing, (
        f"maintained source differs from the measured source: {differing}"
    )


def test_campaign_tree_verifies():
    sys.path.insert(0, str(ROOT / "analysis"))
    import campaign

    report = campaign.verify()
    assert report["campaign_rows"] == 728
    assert report["measured_source_files"] == 109
    assert sum(report["inventories_bound_to_source"].values()) > 0


def test_campaign_code_compiles():
    for path in (ROOT / "campaign").rglob("*.py"):
        if "source" in path.relative_to(ROOT / "campaign").parts[:1]:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
