"""The library boundaries in the round 3 proof. Offline and independent of installed packages."""

import ast
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REJECTED_DISTRIBUTIONS = {
    "aim", "altair", "catboost", "dalex", "deepchecks", "deepeval", "dvc",
    "feast", "featuretools", "func-timeout", "great-expectations", "great-tables",
    "inspect-evals", "interpret", "jupyter-book", "leakage-analysis", "marimo",
    "matplotlib", "mlflow", "mlxtend", "mo-sql-parsing", "netcal", "pingouin",
    "plotly", "polars", "promptfoo", "quarto", "ragas", "ranx", "scikit-lego",
    "shap", "skore", "sqlfluff", "sqlparse", "temporian", "tsfresh", "vl-convert",
    "vl-convert-python", "xgboost",
}
FORBIDDEN_IMPORTS = REJECTED_DISTRIBUTIONS | {"hypothesis", "sklego"}
# AggJoiner and MultiAggJoiner depend on the point-in-time filter, which needs a behavioral check.
FORBIDDEN_APIS = {"AggTarget", "GridSearchCV", "LLMEncoder", "TimeSeriesSplit"}


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_names(requirements: list) -> set[str]:
    names = set()
    for requirement in requirements:
        # A PEP 735 include refers to another group, which is checked separately.
        if isinstance(requirement, str):
            match = re.match(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", requirement.lstrip())
            assert match, requirement
            names.add(normalise(match.group()))
    return names


def test_rejected_libraries_are_not_declared_directly():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    runtime_groups = [
        manifest.get("build-system", {}).get("requires", []),
        project.get("dependencies", []),
        *project.get("optional-dependencies", {}).values(),
    ]
    test_groups = list(manifest.get("dependency-groups", {}).values())
    runtime = dependency_names([item for group in runtime_groups for item in group])
    declared = runtime | dependency_names([item for group in test_groups for item in group])
    assert not declared & REJECTED_DISTRIBUTIONS, sorted(declared & REJECTED_DISTRIBUTIONS)
    assert "hypothesis" not in runtime


def test_runtime_avoids_rejected_imports_and_forbidden_apis():
    violations = []
    for directory in ("src", "examples"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                forbidden = set()
                if isinstance(node, ast.Import):
                    forbidden = {normalise(alias.name.split(".")[0]) for alias in node.names} & FORBIDDEN_IMPORTS
                elif isinstance(node, ast.ImportFrom):
                    if not node.level and node.module:
                        name = normalise(node.module.split(".")[0])
                        forbidden = {name} & FORBIDDEN_IMPORTS
                    forbidden |= {alias.name for alias in node.names} & FORBIDDEN_APIS
                elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_APIS:
                    forbidden = {node.attr}
                violations.extend((str(path.relative_to(ROOT)), node.lineno, name) for name in sorted(forbidden))
    assert not violations, "\n".join(f"{path}:{line}: {name}" for path, line, name in violations)


def test_client_does_not_declare_rejected_libraries():
    manifest = json.loads((ROOT / "clients/vscode/package.json").read_text(encoding="utf-8"))
    declared = {
        normalise(name)
        for group in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
        for name in manifest.get(group, {})
    }
    assert not declared & REJECTED_DISTRIBUTIONS, sorted(declared & REJECTED_DISTRIBUTIONS)
