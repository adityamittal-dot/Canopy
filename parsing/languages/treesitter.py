"""One generic tree-sitter-backed LanguageAnalyzer, parameterized per language
by a small data-only TreeSitterLanguageSpec instead of a hand-written
NodeVisitor per language (see parsing/languages/specs.py for the actual
per-language tables).

Mirrors the shape of the original ast-based visitors in parsing/extract.py,
parsing/calls.py and parsing/metrics.py: a definition's calls/complexity are
computed by a bounded walk that stops at nested function/class boundaries,
while the outer symbol-collecting walk continues into those boundaries (with
an extended qualified-name scope) to record them as their own symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tree_sitter import Language, Node, Parser

from parsing.extract import Symbol
from parsing.parse import ParseError

# Leaf node types that tree-sitter grammars use for an already-plain
# identifier (as opposed to a composite declarator like C's
# `function_declarator`, which wraps an identifier rather than being one).
_IDENTIFIER_LEAF_TYPES = frozenset({
    'identifier', 'type_identifier', 'property_identifier', 'field_identifier',
    'constant', 'name',
})

CalleeReader = Callable[[Node], 'str | None']


def field_callee(field_name: str) -> CalleeReader:
    """Callee text = the raw source text of one field (e.g. JS call_expression's
    `function` field, which for `a.b.c()` is already the source substring
    "a.b.c" - no per-language member-expression reconstruction needed)."""
    def read(node: Node) -> str | None:
        target = node.child_by_field_name(field_name)
        return _decode(target.text) if target is not None else None
    return read


def split_callee(name_field: str, object_field: str | None = None) -> CalleeReader:
    """Callee text for grammars that split a call into separate receiver/name
    fields instead of one expression subtree (Java's method_invocation,
    Ruby's call, PHP's member/scoped call expressions)."""
    def read(node: Node) -> str | None:
        name_node = node.child_by_field_name(name_field)
        if name_node is None:
            return None
        name_text = _decode(name_node.text)
        if object_field is None:
            return name_text
        object_node = node.child_by_field_name(object_field)
        if object_node is None:
            return name_text
        return f'{_decode(object_node.text)}.{name_text}'
    return read


@dataclass(frozen=True)
class TreeSitterLanguageSpec:
    language_id: str
    extensions: frozenset[str]
    ts_language: Callable[[], object]        # the grammar module's language()-style capsule factory
    function_node_types: frozenset[str]
    class_node_types: frozenset[str] = frozenset()
    # Field holding a definition's name, keyed by node type; falls back to
    # 'name' for any node type not listed (true for most grammars - C/C++
    # are the odd ones out, where a function's name is buried inside a
    # composite `declarator` field rather than a plain `name` field).
    name_field_by_type: dict[str, str] = field(default_factory=dict)
    branch_node_types: frozenset[str] = frozenset()
    comment_node_types: frozenset[str] = frozenset({'comment'})
    call_specs: dict[str, CalleeReader] = field(default_factory=dict)
    import_node_types: frozenset[str] = frozenset()
    # Node types that are transparent containers for qualified-name purposes
    # (no Symbol of their own) but should extend the scope for their children
    # - e.g. Rust's `impl Widget { ... }` isn't itself a definition, but the
    # methods inside it should nest under `Widget`, not the module. Maps
    # node type -> the field holding the scope name.
    transparent_scope_types: dict[str, str] = field(default_factory=dict)
    # For definition node types where the "owner" isn't expressed via normal
    # nesting but via a field on the definition itself (Go's receiver
    # methods: `func (w *Widget) Render()` isn't nested inside `Widget`
    # anywhere in the tree - `Widget` only appears in Render's own receiver
    # field). Maps node type -> the field holding the receiver.
    receiver_field: dict[str, str] = field(default_factory=dict)
    # Optional extra gate on whether a matched definition node type should
    # actually be recorded (e.g. Go's `type_spec` covers struct types, type
    # aliases, and named types alike via one node type - only struct/
    # interface ones should become class-kind symbols). A node that fails
    # its filter is treated as transparent (still walked for nested
    # definitions, just not recorded itself), not dropped.
    definition_filter: dict[str, Callable[[Node], bool]] = field(default_factory=dict)


def _decode(raw: bytes) -> str:
    return raw.decode('utf-8', errors='replace')


def _find_identifier(node: Node) -> Node | None:
    """First identifier-like descendant of `node`, depth-first in child
    order. Used to drill into composite declarators (C/C++'s `declarator`
    field is a function_declarator wrapping the name, not a leaf identifier)
    - safe because a declarator subtree never contains a nested function
    body, so there's no risk of this wandering into unrelated code."""
    for child in node.named_children:
        if child.type in _IDENTIFIER_LEAF_TYPES:
            return child
        found = _find_identifier(child)
        if found is not None:
            return found
    return None


def _resolve_name(node: Node, field_name: str) -> str | None:
    target = node.child_by_field_name(field_name)
    if target is None:
        return None
    if target.type not in _IDENTIFIER_LEAF_TYPES:
        target = _find_identifier(target)
        if target is None:
            return None
    return _decode(target.text)


def _find_type_identifier(node: Node) -> Node | None:
    """Like _find_identifier, but specifically hunts for a `type_identifier`
    rather than the first identifier-like leaf of any kind. Needed for
    receiver_field resolution: Go's receiver clause `(w *Widget)` contains
    both the receiver variable's plain `identifier` (w) and the type's
    `type_identifier` (Widget) - _find_identifier's depth-first "first match"
    would grab the variable name since it comes first in the clause, when
    what we actually want for a qualified name is the type."""
    for child in node.named_children:
        if child.type == 'type_identifier':
            return child
        found = _find_type_identifier(child)
        if found is not None:
            return found
    return None


def _resolve_receiver_type(node: Node, field_name: str) -> str | None:
    target = node.child_by_field_name(field_name)
    if target is None:
        return None
    type_node = _find_type_identifier(target) if target.type != 'type_identifier' else target
    return _decode(type_node.text) if type_node is not None else None


def _clean_comment(text: str) -> str:
    text = text.strip()
    if text.startswith('/**') or text.startswith('/*'):
        text = text.removeprefix('/**').removeprefix('/*').removesuffix('*/').strip()
        lines = [line.strip().removeprefix('*').strip() for line in text.splitlines()]
        return '\n'.join(line for line in lines if line)
    if text.startswith('///'):
        return text.removeprefix('///').strip()
    if text.startswith('//'):
        return text.removeprefix('//').strip()
    if text.startswith('#'):
        return text.removeprefix('#').strip()
    return text


def _normalize_callee(text: str) -> str:
    """Collapse every language's member/scope-access separator (`.`, `::`,
    `->`) onto `.` and drop PHP's `$` sigil, so parsing.resolve.bare_name's
    `.rsplit('.', 1)[-1]` keeps working unmodified for every language, and
    same-instance calls normalize onto the `self.`/`this.`-style prefix
    parsing.resolve._looks_local already recognizes."""
    return text.replace('::', '.').replace('->', '.').replace('$', '')


class TreeSitterAnalyzer:
    def __init__(self, spec: TreeSitterLanguageSpec):
        self.spec = spec
        self._language: Language | None = None
        self._bounded_types = spec.function_node_types | spec.class_node_types

    @property
    def extensions(self) -> frozenset[str]:
        return self.spec.extensions

    @property
    def language_id(self) -> str:
        return self.spec.language_id

    @property
    def language(self) -> Language:
        if self._language is None:
            self._language = Language(self.spec.ts_language())
        return self._language

    def parse(self, path: str):
        try:
            with open(path, 'rb') as f:
                source = f.read()
        except OSError as exc:
            raise ParseError(f'Failed to parse {path}: {exc}') from exc
        tree = Parser(self.language).parse(source)
        return tree

    # --- symbol extraction ---------------------------------------------

    def extract_symbols(self, tree, file: str, module_name: str) -> list[Symbol]:
        symbols = [Symbol(kind='module', name=module_name, file=file, language=self.spec.language_id)]
        self._walk(tree.root_node, [module_name], symbols, file)
        return symbols

    def _walk(self, node: Node, scope: list[str], symbols: list[Symbol], file: str):
        # Iterative pre-order over an explicit stack, not Python recursion -
        # real-world files (deeply nested if/else or switch chains, generated
        # code, ...) can nest well past Python's ~1000-frame recursion limit,
        # which used to surface as an uncaught RecursionError here. Each
        # stack entry is (node, scope, pending_record): pending_record means
        # `node` itself is a not-yet-recorded definition, so its symbol must
        # be appended (via _record) before its own children are pushed -
        # doing that at pop time (rather than when the entry is pushed)
        # keeps symbols in the same left-to-right document order the old
        # recursive version produced, which graph_data.py's parent-lookup
        # relies on. Children are pushed in reverse so the leftmost pops
        # (and so gets fully expanded) first, matching recursive pre-order.
        stack: list[tuple[Node, list[str], bool]] = [(node, scope, False)]
        while stack:
            current, current_scope, pending_record = stack.pop()
            if pending_record:
                new_scope = self._record(current, current_scope, symbols, file)
                if new_scope is None:
                    continue  # name resolution failed - skip this subtree, as before
                current_scope = new_scope

            for child in reversed(current.named_children):
                if child.type in self._bounded_types and self._passes_filter(child):
                    stack.append((child, current_scope, True))
                elif child.type in self.spec.transparent_scope_types:
                    scope_name = _resolve_name(child, self.spec.transparent_scope_types[child.type])
                    new_scope = current_scope + [scope_name] if scope_name else current_scope
                    stack.append((child, new_scope, False))
                else:
                    stack.append((child, current_scope, False))

    def _passes_filter(self, node: Node) -> bool:
        predicate = self.spec.definition_filter.get(node.type)
        return predicate is None or predicate(node)

    def _record(self, node: Node, scope: list[str], symbols: list[Symbol], file: str) -> list[str] | None:
        """Append `node`'s Symbol and return the scope its own children should
        see - or None if name resolution failed, telling the caller to skip
        its subtree entirely (matching the pre-iterative behavior)."""
        name_field = self.spec.name_field_by_type.get(node.type, 'name')
        name = _resolve_name(node, name_field)
        if name is None:
            return None
        if node.type in self.spec.receiver_field:
            receiver = _resolve_receiver_type(node, self.spec.receiver_field[node.type])
            if receiver:
                name = f'{receiver}.{name}'

        kind = 'function' if node.type in self.spec.function_node_types else 'class'
        new_scope = scope + [name]
        symbols.append(Symbol(
            kind=kind,
            name='.'.join(new_scope),
            file=file,
            docstring=self._doc_comment(node),
            lineno=node.start_point.row + 1,
            end_lineno=node.end_point.row + 1,
            calls=self._extract_calls(node) if kind == 'function' else [],
            complexity=self._compute_complexity(node) if kind == 'function' else 1,
            language=self.spec.language_id,
        ))
        return new_scope

    def _doc_comment(self, def_node: Node) -> str | None:
        # Adjacency is checked as "at most one row of gap" rather than an
        # exact +1, because grammars disagree on whether a `//`-style
        # comment's span includes its trailing newline (tree-sitter-rust's
        # line_comment does; tree-sitter-javascript's comment doesn't) - both
        # conventions land within 1 row of the next node when truly adjacent,
        # while a real blank-line gap is always 2+.
        #
        # Some grammars (Ruby's) wrap a container's first statement in an
        # extra node (`body_statement`) that has no sibling of its own to
        # look at - the preceding comment is actually a sibling of that
        # wrapper, one level up. If this def has no direct previous sibling
        # but is the first named child of its parent, look for the comment
        # from the parent's position instead (still measuring adjacency
        # against this node's own row, since a synthetic wrapper starts at
        # the same position as its first child).
        sib = def_node.prev_named_sibling
        if sib is None and def_node.parent is not None:
            parent = def_node.parent
            if parent.named_children and parent.named_children[0].id == def_node.id:
                sib = parent.prev_named_sibling

        comments = []
        anchor_row = def_node.start_point.row
        while sib is not None and sib.type in self.spec.comment_node_types and anchor_row - sib.end_point.row <= 1:
            comments.append(sib)
            anchor_row = sib.start_point.row
            sib = sib.prev_named_sibling
        if not comments:
            return None
        comments.reverse()
        text = '\n'.join(_clean_comment(_decode(c.text)) for c in comments)
        return text.strip() or None

    # --- bounded walks (stop at nested function/class boundaries) ------

    def _extract_calls(self, def_node: Node) -> list[str]:
        # Iterative for the same reason as _walk above - a single function
        # body can nest well past Python's recursion limit.
        calls: list[str] = []
        stack = list(reversed(def_node.named_children))
        while stack:
            node = stack.pop()
            if node.type in self._bounded_types:
                continue
            reader = self.spec.call_specs.get(node.type)
            if reader is not None:
                text = reader(node)
                if text:
                    calls.append(_normalize_callee(text))
            stack.extend(reversed(node.named_children))
        return calls

    def _compute_complexity(self, def_node: Node) -> int:
        complexity = 1
        stack = list(reversed(def_node.named_children))
        while stack:
            node = stack.pop()
            if node.type in self._bounded_types:
                continue
            if node.type in self.spec.branch_node_types:
                complexity += 1
            stack.extend(reversed(node.named_children))
        return complexity

    # --- imports ----------------------------------------------------------

    def extract_imports(self, tree) -> list[str]:
        imports: list[str] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in self.spec.import_node_types:
                text = _decode(node.text).strip()
                if text:
                    imports.append(text)
                continue
            stack.extend(reversed(node.named_children))
        return imports
