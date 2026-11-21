"""The code of the paths that take the writer lock, read with the standard library `ast`: which functions take it, and the calls that follow their stale check."""

import ast
import builtins
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src"


def dotted(node):
    """`a.b.c` for a name or a chain of attributes on a name, None for anything else (a method of a literal or of a call's result)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def _parse(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def _calls(node):
    """Every call under `node`, in the order they run (the arguments of a call before the call), without those of a nested function."""
    found = []

    def walk(child):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and child is not node:
            return
        if isinstance(child, ast.Call):
            found.append(child)
        for each in ast.iter_child_nodes(child):
            walk(each)

    walk(node)
    return sorted(found, key=lambda call: (call.end_lineno, call.end_col_offset))


def _module_name(root, path):
    return ".".join(Path(path).relative_to(root).with_suffix("").parts)


def locked_functions(root):
    """{`module:function`} of every function under `root` that calls `writer_lock`; a call outside any function is `module:<module>`."""
    found = set()
    for path in sorted(Path(root).rglob("*.py")):
        module = _module_name(root, path)

        def visit(node, inside):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inside = node.name
            if isinstance(node, ast.Call) and (dotted(node.func) or "").split(".")[-1] == "writer_lock":
                found.add(f"{module}:{inside or '<module>'}")
            for child in ast.iter_child_nodes(node):
                visit(child, inside)

        visit(_parse(path), None)
    return found


def takes_the_read_sequence(root, path_key):
    """True when the function `module:function` has a `read_sequence` parameter."""
    module, function = path_key.split(":")
    node = _function(_parse(Path(root) / (module.replace(".", "/") + ".py")), function)
    return "read_sequence" in {argument.arg for argument in [*node.args.args, *node.args.kwonlyargs]}


def _function(tree, name):
    [node] = [each for each in ast.walk(tree) if isinstance(each, (ast.FunctionDef, ast.AsyncFunctionDef)) and each.name == name]
    return node


def _counted(call):
    """The name of a call that counts, or None for a builtin and for a method of a value that is no name."""
    name = dotted(call.func)
    if name is None or ("." not in name and hasattr(builtins, name)):
        return None
    return name


def calls_after_the_stale_check(root, path_key, *, stale_check_in=None, then=None):
    """The names of the calls that run after `require_current` in the path `module:function`, in order.

    `require_current` is in the function itself, or in `stale_check_in`, which the function must call (that one call is followed). `then` is a function
    of the same module that the code after `require_current` calls: its calls stand in the place of the call to it.
    """
    module, function = path_key.split(":")
    tree = _parse(Path(root) / (module.replace(".", "/") + ".py"))
    locked = _function(tree, function)
    holder = locked
    if stale_check_in is not None:
        assert stale_check_in in {_counted(call) for call in _calls(locked)}, f"{path_key} does not call {stale_check_in}"
        holder = _function(tree, stale_check_in)
    calls = _calls(holder)
    [stale] = [call for call in calls if (dotted(call.func) or "").split(".")[-1] == "require_current"]
    after = [call for call in calls if (call.end_lineno, call.end_col_offset) > (stale.end_lineno, stale.end_col_offset)]
    names = []
    for call in after:
        if then is not None and dotted(call.func) == then:
            names += [name for name in map(_counted, _calls(_function(tree, then))) if name]
        elif _counted(call):
            names.append(_counted(call))
    return names


def first_call_after_the_stale_check(names, skipped):
    """(the first of `names` that is not in `skipped`, the skipped names that do not stand before it)."""
    first = next(name for name in names if name not in skipped)
    before = names[: names.index(first)]
    return first, sorted(set(skipped) - set(before))
