"""The one resolver of the architecture tests, with the standard library `ast`: what each name of a module stands for, the modules a module imports and the call that each call site resolves to.

Every module under a root is found with `rglob`, subpackages included, and named by its dotted path (`pkg/sub/__init__.py` is `pkg.sub`). A relative import is resolved against
the module that holds it to the absolute module it names, so `from ..core import y` in `hypotrail.agentic.run` is `hypotrail.core.y`.

A call is resolved by what its name stands for in the module that holds it: an import (`import a.b as c`, `from a import b as c`, also inside a function), a function defined in
the module (a bare name), or a name that is assigned another name (`g = layout.find_by_request`). The resolved name is `package.module.function`; it is built from the names,
not read from the target's file, so a call of a function that was removed still resolves. A call that no name of the module explains (a method of a parameter, a builtin)
has no resolved name, only its dotted spelling.
"""

import ast
from pathlib import Path
from typing import NamedTuple

SOURCE = Path(__file__).resolve().parent.parent / "src"


class Site(NamedTuple):
    """One call: the module and the outermost function that hold it (`module:function`, `module:<module>` outside any), what it resolves to, its spelling, its node, and the innermost function that holds it."""

    module: str
    owner: str
    callee: str | None
    raw: str | None
    node: ast.Call
    innermost: str


def dotted(node):
    """`a.b.c` for a name or a chain of attributes on a name, None for anything else (a method of a literal or of a call's result)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def module_name(root, path) -> str:
    parts = list(Path(path).relative_to(root).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def parse_all(root) -> dict:
    """{module name: its tree} for every `.py` under `root`, subpackages included; the tree of a package's `__init__.py` has `is_package` set."""
    trees = {}
    for path in sorted(Path(root).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tree.is_package = path.name == "__init__.py"
        trees[module_name(root, path)] = tree
    return trees


def import_targets(module: str, tree):
    """Yield (the name the import binds, what that name stands for, the absolute name the import names) for every import of the tree, relative imports resolved.

    `import a.b` binds `a`, which stands for `a`, and names `a.b`; `import a.b as c` binds `c`, which stands for `a.b`; `from . import x` in `pkg.m` binds `x`, which stands for `pkg.x`.
    """
    package = module if getattr(tree, "is_package", False) else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                yield alias.asname or head, alias.name if alias.asname else head, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".") if package else []
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                yield alias.asname or alias.name, full, full


def imports(trees: dict) -> dict:
    """{module: the absolute names it imports}: `from a import b` is `a.b`, which names a module or a name of `a`."""
    return {module: {target for _, _, target in import_targets(module, tree)} for module, tree in trees.items()}


def names_of(module: str, tree) -> dict:
    """What each name of the module stands for: {name: qualified name}."""
    names: dict = {}
    for bound, stands_for, _ in import_targets(module, tree):
        names[bound] = stands_for
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = f"{module}.{node.name}"
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant):
            names[node.targets[0].id] = f"{module}.{node.targets[0].id}"
    # a name assigned another name, as often as it takes to follow a chain of them
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                spelling = dotted(node.value)
                resolved = resolve(names, spelling) if spelling else None
                if resolved is not None:
                    names[node.targets[0].id] = resolved
    return names


def resolve(names: dict, spelling: str | None) -> str | None:
    """The qualified name that the dotted `spelling` stands for in a module whose names are `names`, or None."""
    if spelling is None:
        return None
    head, _, rest = spelling.partition(".")
    if head not in names:
        return None
    return f"{names[head]}.{rest}" if rest else names[head]


def owners_in(module: str, tree):
    """Yield (node, owner) for every node of the tree: the outermost function or method that holds it, `<module>` when none does."""

    def visit(node, owner):
        if owner is None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node.name
        yield node, f"{module}:{owner or '<module>'}"
        for child in ast.iter_child_nodes(node):
            if isinstance(node, ast.ClassDef) and owner is None and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from visit(child, f"{node.name}.{child.name}")
            else:
                yield from visit(child, owner)

    yield from visit(tree, None)


def innermost_owners_in(module: str, tree) -> dict:
    """{id(node): `module:function`} for every node of the tree: the innermost function that holds it, `module:<module>` when none does."""
    found = {}

    def visit(node, owner):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node.name
        found[id(node)] = f"{module}:{owner or '<module>'}"
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, None)
    return found


def calls(trees: dict) -> list:
    """Every call of every module, as a `Site`."""
    found = []
    for module, tree in trees.items():
        names = names_of(module, tree)
        innermost = innermost_owners_in(module, tree)
        for node, owner in owners_in(module, tree):
            if isinstance(node, ast.Call):
                spelling = dotted(node.func)
                found.append(Site(module, owner, resolve(names, spelling), spelling, node, innermost[id(node)]))
    return found


def defined_functions(trees: dict) -> set:
    """{`module.function`} and {`module.Class.method`} of every function and method of every module (not the nested ones)."""
    found = set()
    for module, tree in trees.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(f"{module}.{node.name}")
            elif isinstance(node, ast.ClassDef):
                found |= {f"{module}.{node.name}.{child.name}" for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return found


def reached_from(sites: list, defined: set, starts, *, stop_in: str) -> set:
    """The `module.function` names that run, directly or not, from the `starts` (`module:function`), without entering the module `stop_in`.

    A call that resolves to a function defined in `src` is followed; a nested function's calls belong to the function that holds it.
    """
    edges: dict = {}
    for site in sites:
        key = site.owner.replace(":", ".")
        if site.callee in defined and site.module != stop_in:
            edges.setdefault(key, set()).add(site.callee)
    seen = {start.replace(":", ".") for start in starts}
    pending = list(seen)
    while pending:
        for callee in edges.get(pending.pop(), ()):
            if callee not in seen and not callee.startswith(stop_in + "."):
                seen.add(callee)
                pending.append(callee)
    return seen
