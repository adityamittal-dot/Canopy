import ast


def _call_name(func: ast.expr) -> str | None:
    """Render a Call's `func` as a dotted name, e.g. `self.foo.bar`. None if unresolvable."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f'{base}.{func.attr}' if base else func.attr
    return None


class _CallVisitor(ast.NodeVisitor):
    """Collects Call nodes in a function body, without descending into nested defs."""

    def __init__(self):
        self.calls: list[str] = []

    def visit_Call(self, node):
        name = _call_name(node.func)
        if name:
            self.calls.append(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def extract_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return the dotted name of every call made directly in `node`'s body (not in nested defs)."""
    visitor = _CallVisitor()
    for stmt in node.body:
        visitor.visit(stmt)
    return visitor.calls
