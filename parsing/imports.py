import ast


def extract_imports(tree: ast.Module) -> list[str]:
    """Return every name imported by `tree`, as dotted module.name strings."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            prefix = '.' * node.level + (node.module or '')
            imports += [
                f'{prefix}{alias.name}' if not node.module else f'{prefix}.{alias.name}'
                for alias in node.names
            ]
    return imports
