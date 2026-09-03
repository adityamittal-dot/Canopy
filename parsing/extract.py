import ast
from dataclasses import dataclass, field

from parsing.calls import extract_calls
from parsing.metrics import compute_complexity


@dataclass
class Symbol:
    kind: str
    name: str
    file: str
    docstring: str | None = None
    lineno: int = 1
    end_lineno: int | None = None
    calls: list[str] = field(default_factory=list)
    complexity: int = 1


class SymbolVisitor(ast.NodeVisitor):
    """Records every class and function definition in a module, including nested ones."""

    def __init__(self, file: str, module_name: str, tree: ast.Module):
        self.file = file
        self.symbols = [
            Symbol(
                kind='module',
                name=module_name,
                file=file,
                docstring=ast.get_docstring(tree),
            )
        ]
        self._scope = [module_name]

    def _record(self, kind: str, node):
        self.symbols.append(
            Symbol(
                kind=kind,
                name='.'.join(self._scope + [node.name]),
                file=self.file,
                docstring=ast.get_docstring(node),
                lineno=node.lineno,
                end_lineno=node.end_lineno,
                calls=extract_calls(node) if kind == 'function' else [],
                complexity=compute_complexity(node) if kind == 'function' else 1,
            )
        )
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node):
        self._record('class', node)

    def visit_FunctionDef(self, node):
        self._record('function', node)

    visit_AsyncFunctionDef = visit_FunctionDef


def extract_symbols(tree: ast.Module, file: str, module_name: str) -> list[Symbol]:
    visitor = SymbolVisitor(file, module_name, tree)
    visitor.visit(tree)
    return visitor.symbols
