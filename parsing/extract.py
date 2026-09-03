import ast
from dataclasses import dataclass


@dataclass
class Symbol:
    kind: str
    name: str
    file: str


class SymbolVisitor(ast.NodeVisitor):
    """Records every class and function definition in a module, including nested ones."""

    def __init__(self, file: str, module_name: str):
        self.file = file
        self.symbols = [Symbol(kind='module', name=module_name, file=file)]
        self._scope = [module_name]

    def _record(self, kind: str, node):
        self.symbols.append(
            Symbol(kind=kind, name='.'.join(self._scope + [node.name]), file=self.file)
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
    visitor = SymbolVisitor(file, module_name)
    visitor.visit(tree)
    return visitor.symbols
