import ast


def extract_imports(tree: ast.Module) -> list[str]:
    """Return every name imported by `tree`, as dotted module.name strings."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            imports += [f'{module}.{alias.name}'.lstrip('.') for alias in node.names]
    return imports
