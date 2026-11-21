"""The one resolver of the architecture tests, with the standard library `ast`, and the receiver rule of the Study-write contract that is built on it.

The resolver: every module under a root is found with `rglob`, subpackages included, and named by its dotted path (`pkg/sub/__init__.py` is `pkg.sub`). A relative import is resolved against
the module that holds it to the absolute module it names, so `from ..core import y` in `hypotrail.agentic.run` is `hypotrail.core.y`.

A call is resolved by what its name stands for in the module that holds it: an import (`import a.b as c`, `from a import b as c`, also inside a function), a function defined in
the module (a bare name), or a name that is assigned another name (`g = layout.find_by_request`). The resolved name is `package.module.function`; it is built from the names,
not read from the target's file, so a call of a function that was removed still resolves. A call that no name of the module explains (a method of a parameter, a builtin)
has no resolved name, only its dotted spelling.

The receiver rule (`receiver_violations`): how the `Write` that `study_write.locked(...)` yields is held, named and passed on, and who may build one.
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


class Function(NamedTuple):
    """A function or method of a module: its module, the qualified name of its class (None for a function), its node, its positional parameters (all of them, `self` and `cls` included), its keyword-only ones and its kind (`function`, `method`, `classmethod` or `staticmethod`)."""

    module: str
    cls: str | None
    node: ast.FunctionDef | ast.AsyncFunctionDef
    parameters: list
    keyword_only: list
    kind: str


FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def signature(node, module: str, cls: str | None, method: bool = False) -> Function:
    decorators = {dotted(decorator) for decorator in node.decorator_list}
    kind = "function" if not method else "staticmethod" if "staticmethod" in decorators else "classmethod" if "classmethod" in decorators else "method"
    positional = [a.arg for a in [*node.args.posonlyargs, *node.args.args]]
    return Function(module, cls, node, positional, [a.arg for a in node.args.kwonlyargs], kind)


def functions_of(trees: dict) -> dict:
    """{`module.function` or `module.Class.method`: its `Function`} for every function and method of every module (not the nested ones)."""
    found = {}
    for module, tree in trees.items():
        for node in tree.body:
            if isinstance(node, FUNCTION_NODES):
                found[f"{module}.{node.name}"] = signature(node, module, None)
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, FUNCTION_NODES):
                        found[f"{module}.{node.name}.{child.name}"] = signature(child, module, f"{module}.{node.name}", method=True)
    return found


def defined_functions(trees: dict) -> set:
    """{`module.function`} and {`module.Class.method`} of every function and method of every module (not the nested ones)."""
    return set(functions_of(trees))


class Binding(NamedTuple):
    """One `with <factory>(...) as <target>`: its module, its node, its target (None without `as`) and the innermost function that holds it."""

    module: str
    node: ast.With | ast.AsyncWith
    target: ast.expr | None
    innermost: str


def write_bindings(trees: dict, factory: str) -> list:
    """Every `with` of a call that resolves to `factory`, outside the module that defines it."""
    found = []
    for module, tree in trees.items():
        if module == factory.rpartition(".")[0]:
            continue
        names, innermost = names_of(module, tree), innermost_owners_in(module, tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                found += [
                    Binding(module, node, item.optional_vars, innermost[id(node)])
                    for item in node.items
                    if isinstance(item.context_expr, ast.Call) and resolve(names, dotted(item.context_expr.func)) == factory
                ]
    return found


def binds_name(function, name: str) -> bool:
    """Whether the function or lambda has its own `name`: a parameter, or a name it assigns."""
    arguments = function.args
    own = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *filter(None, [arguments.vararg, arguments.kwarg])]
    if any(argument.arg == name for argument in own):
        return True
    pending = list(ast.iter_child_nodes(function))
    while pending:
        node = pending.pop()
        if isinstance(node, (*FUNCTION_NODES, ast.Lambda)):
            continue
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store):
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


def used_outside(scope, name: str):
    """Every read of `name` in the scope, the functions nested in it included, except in a nested function or lambda that has its own `name`."""
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, (*FUNCTION_NODES, ast.Lambda)) and binds_name(node, name):
            continue
        if isinstance(node, ast.Name) and node.id == name and not isinstance(node.ctx, ast.Store):
            yield node
        pending.extend(ast.iter_child_nodes(node))


def receiver_violations(root, factory: str, receiver: str, written: str = "Write") -> list:
    """What breaks the receiver rule: every `with <factory>(...) as <name>` and every parameter that receives the object is named `receiver`, the object is used in the closed ways only,
    the factory is called only as the item of a `with`, the bound name is read nowhere outside its block, and the `written` class is built only in the module of the factory.

    The object is followed from the `with` that binds it, in the `with`'s body and in the functions nested there, through every call that passes it as a bare positional or keyword
    argument, into the function the call resolves to (a function or method of `src`, a nested function, `self.method` when the class is known, `Class.method` with `self` given
    explicitly), and on through that function's calls. Its uses are a method call on it and such an argument. Any other use is a violation: a rebinding, a `*args`, an attribute read,
    an argument of a call that does not resolve.

    The factory, by any name that resolves to it, appears only as the call that is the item of a `with`; a call elsewhere (`cm = factory(...)`, an argument) and a reference that is
    not called are violations. The bound name is read outside the block in the scope that holds the `with`, in a function nested there that is defined before or after it, and in a lambda,
    except in a function or lambda that has its own parameter or assignment of that name.
    """
    trees = parse_all(root)
    sites = {id(site.node): site for site in calls(trees)}
    functions = functions_of(trees)
    innermost = {module: innermost_owners_in(module, tree) for module, tree in trees.items()}
    parents = {module: {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)} for module, tree in trees.items()}
    found, seen = set(), set()

    def ancestor(module, node, kinds):
        while node is not None and not isinstance(node, kinds):
            node = parents[module].get(id(node))
        return node

    def target_of(module, cls, call, local):
        func = call.func
        if isinstance(func, ast.Name) and func.id in local:
            nested = local[func.id]
            enclosing = innermost[module][id(parents[module][id(nested)])].replace(":", ".")
            return f"{enclosing}.{nested.name}", signature(nested, module, cls), False
        callee = sites[id(call)].callee if id(call) in sites else None
        if callee in functions:
            return callee, functions[callee], False
        if cls and isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self" and f"{cls}.{func.attr}" in functions:
            return f"{cls}.{func.attr}", functions[f"{cls}.{func.attr}"], True
        return None

    def follow(module, cls, scope, body, held):
        local = {n.name: n for n in ast.walk(scope) if isinstance(n, FUNCTION_NODES) and n is not scope}
        for statement in body:
            for node in ast.walk(statement):
                if not (isinstance(node, ast.Name) and node.id == held):
                    continue
                parent, where = parents[module][id(node)], innermost[module][id(node)]
                if not isinstance(node.ctx, ast.Load):
                    found.add(f"{where} rebinds the Write `{held}`")
                elif isinstance(parent, ast.Attribute) and isinstance(parents[module][id(parent)], ast.Call) and parents[module][id(parent)].func is parent:
                    continue
                elif isinstance(parent, ast.Call) and any(argument is node for argument in parent.args):
                    argument = next(i for i, each in enumerate(parent.args) if each is node)
                    hand_over(module, cls, local, where, parent, argument)
                elif isinstance(parent, ast.keyword) and parent.arg is not None:
                    hand_over(module, cls, local, where, parents[module][id(parent)], parent.arg)
                else:
                    found.add(f"{where} uses the Write in `{ast.unparse(parent)}`")

    def hand_over(module, cls, local, where, call, argument):
        resolved = target_of(module, cls, call, local)
        if resolved is None:
            found.add(f"{where} passes the Write to a call that does not resolve: `{ast.unparse(call)}`")
            return
        name, function, through_self = resolved
        # `self.m(...)` supplies `self` or `cls`; `C.m(...)` supplies `cls` of a classmethod and leaves `self` of a method to the call
        supplied = 1 if function.kind == "classmethod" or (through_self and function.kind == "method") else 0
        explicit = function.parameters[supplied:]
        if isinstance(argument, int):
            parameter = explicit[argument] if argument < len(explicit) else None
        else:
            parameter = argument if argument in [*explicit, *function.keyword_only] else None
        if parameter is None:
            found.add(f"{where} passes the Write where {name} has no parameter for it")
            return
        if parameter != receiver:
            found.add(f"{name} receives the Write as `{parameter}`")
        if (id(function.node), parameter) not in seen:
            seen.add((id(function.node), parameter))
            follow(function.module, function.cls, function.node, function.node.body, parameter)

    blocks: dict = {}  # (module, the scope that holds the `with`, the bound name) -> (scope, the ids of the nodes of the blocks that bind it)
    for binding in write_bindings(trees, factory):
        if isinstance(binding.target, ast.Name):
            if binding.target.id != receiver:
                found.add(f"{binding.innermost} binds the Write as `{binding.target.id}`")
            enclosing_class = ancestor(binding.module, binding.node, ast.ClassDef)
            scope = ancestor(binding.module, binding.node, FUNCTION_NODES) or ancestor(binding.module, binding.node, ast.Module)
            follow(binding.module, f"{binding.module}.{enclosing_class.name}" if enclosing_class else None, scope, binding.node.body, binding.target.id)
            inside = blocks.setdefault((binding.module, id(scope), binding.target.id), (scope, set()))[1]
            inside.update(id(node) for statement in binding.node.body for node in ast.walk(statement))
            inside.add(id(binding.target))
        elif binding.target is not None:
            found.add(f"{binding.innermost} binds the Write by unpacking")
    for (module, _, name), (scope, inside) in blocks.items():
        for node in used_outside(scope, name):
            if id(node) not in inside:
                found.add(f"{innermost[module][id(node)]} uses the Write `{name}` outside its block")
    factory_module = factory.rpartition(".")[0]
    for module, tree in trees.items():
        if module == factory_module:
            continue
        names = names_of(module, tree)
        for node in ast.walk(tree):
            parent = parents[module].get(id(node))
            where = innermost[module][id(node)]
            if isinstance(node, ast.Call) and resolve(names, dotted(node.func)) == f"{factory_module}.{written}":
                found.add(f"{where} constructs the Write: `{ast.unparse(node)}`")
            if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(node.ctx, ast.Load) or isinstance(parent, ast.Attribute):
                continue
            if resolve(names, dotted(node)) != factory:
                continue
            if isinstance(parent, ast.Call) and parent.func is node:
                node, parent = parent, parents[module][id(parent)]
            if not (isinstance(parent, ast.withitem) and parent.context_expr is node):
                found.add(f"{where} uses `{ast.unparse(node)}` other than as the item of a `with`")
    return sorted(found)


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
