from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parsing.extract import Symbol


def compute_loc(symbol: Symbol) -> int:
    """Lines of code spanned by `symbol`, from its recorded line range."""
    if symbol.end_lineno is None:
        return 0
    return symbol.end_lineno - symbol.lineno + 1


class _ComplexityVisitor(ast.NodeVisitor):
    """Counts branching nodes in a function body, without descending into nested defs."""

    def __init__(self):
        self.complexity = 1

    def visit_If(self, node):
        self.complexity += 1
        self.generic_visit(node)

    visit_For = visit_If
    visit_While = visit_If
    visit_ExceptHandler = visit_If

    def visit_BoolOp(self, node):
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def compute_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Rough cyclomatic complexity: 1 + one per if/for/while/except/elif/boolean operator."""
    visitor = _ComplexityVisitor()
    for stmt in node.body:
        visitor.visit(stmt)
    return visitor.complexity
