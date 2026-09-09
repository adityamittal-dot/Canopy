"""Per-language config tables for the generic TreeSitterAnalyzer, plus the
one Python (ast-based) analyzer - registered together into LANGUAGE_REGISTRY.

Node type / field names below come from parsing real samples through each
grammar during development (tree-sitter ships no bundled node-types.json for
these PyPI packages), not from documentation alone - see the PR description
for the exploration approach. A handful of less-common constructs (Java/C#
constructors, Rust traits/enums, Ruby singleton methods and modules, PHP
interfaces) are educated-guess extensions following each grammar's
established naming convention; a wrong guess just never matches anything
(silently skipped), it can't crash extraction.
"""

import tree_sitter_c as _tsc
import tree_sitter_c_sharp as _tscs
import tree_sitter_cpp as _tscpp
import tree_sitter_go as _tsgo
import tree_sitter_java as _tsjava
import tree_sitter_javascript as _tsjs
import tree_sitter_php as _tsphp
import tree_sitter_ruby as _tsruby
import tree_sitter_rust as _tsrust
import tree_sitter_typescript as _tsts

from parsing.languages.base import register
from parsing.languages.python_lang import PYTHON_ANALYZER
from parsing.languages.treesitter import TreeSitterAnalyzer, TreeSitterLanguageSpec, field_callee, split_callee

register(PYTHON_ANALYZER)

_JS_LIKE_BRANCHES = frozenset({
    'if_statement', 'for_statement', 'for_in_statement', 'while_statement',
    'do_statement', 'catch_clause', 'switch_case', 'switch_default', 'ternary_expression',
})

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='javascript',
    extensions=frozenset({'.js', '.jsx', '.mjs', '.cjs'}),
    ts_language=_tsjs.language,
    function_node_types=frozenset({'function_declaration', 'method_definition', 'generator_function_declaration'}),
    class_node_types=frozenset({'class_declaration'}),
    branch_node_types=_JS_LIKE_BRANCHES,
    call_specs={'call_expression': field_callee('function')},
    import_node_types=frozenset({'import_statement'}),
)))

for _ts_ext, _ts_lang_fn in (('.ts', _tsts.language_typescript), ('.tsx', _tsts.language_tsx)):
    register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
        language_id='typescript',
        extensions=frozenset({_ts_ext}),
        ts_language=_ts_lang_fn,
        function_node_types=frozenset({'function_declaration', 'method_definition', 'generator_function_declaration'}),
        class_node_types=frozenset({'class_declaration', 'interface_declaration'}),
        branch_node_types=_JS_LIKE_BRANCHES,
        call_specs={'call_expression': field_callee('function')},
        import_node_types=frozenset({'import_statement'}),
    )))

def _is_go_struct_or_interface(node):
    # Go's `type_spec` covers struct types, interface types, plain type
    # aliases and named types under one node type - only the first two are
    # worth surfacing as class-kind symbols (also gives receiver methods, see
    # receiver_field below, a real parent symbol to nest under).
    type_field = node.child_by_field_name('type')
    return type_field is not None and type_field.type in ('struct_type', 'interface_type')


register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='go',
    extensions=frozenset({'.go'}),
    ts_language=_tsgo.language,
    function_node_types=frozenset({'function_declaration', 'method_declaration'}),
    class_node_types=frozenset({'type_spec'}),
    definition_filter={'type_spec': _is_go_struct_or_interface},
    receiver_field={'method_declaration': 'receiver'},
    branch_node_types=frozenset({'if_statement', 'for_statement', 'expression_case', 'default_case'}),
    call_specs={'call_expression': field_callee('function')},
    import_node_types=frozenset({'import_spec'}),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='java',
    extensions=frozenset({'.java'}),
    ts_language=_tsjava.language,
    function_node_types=frozenset({'method_declaration', 'constructor_declaration'}),
    class_node_types=frozenset({'class_declaration', 'interface_declaration', 'enum_declaration'}),
    branch_node_types=frozenset({
        'if_statement', 'for_statement', 'enhanced_for_statement', 'while_statement',
        'catch_clause', 'switch_block_statement_group',
    }),
    comment_node_types=frozenset({'line_comment', 'block_comment'}),
    call_specs={'method_invocation': split_callee(name_field='name', object_field='object')},
    import_node_types=frozenset({'import_declaration'}),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='rust',
    extensions=frozenset({'.rs'}),
    ts_language=_tsrust.language,
    function_node_types=frozenset({'function_item'}),
    class_node_types=frozenset({'struct_item', 'enum_item', 'trait_item'}),
    branch_node_types=frozenset({'if_expression', 'for_expression', 'while_expression', 'match_arm'}),
    comment_node_types=frozenset({'line_comment', 'block_comment'}),
    call_specs={'call_expression': field_callee('function')},
    transparent_scope_types={'impl_item': 'type'},
    import_node_types=frozenset({'use_declaration'}),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='c',
    extensions=frozenset({'.c', '.h'}),
    ts_language=_tsc.language,
    function_node_types=frozenset({'function_definition'}),
    name_field_by_type={'function_definition': 'declarator'},
    branch_node_types=frozenset({'if_statement', 'for_statement', 'while_statement', 'case_statement'}),
    call_specs={'call_expression': field_callee('function')},
    import_node_types=frozenset({'preproc_include'}),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='cpp',
    extensions=frozenset({'.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx'}),
    ts_language=_tscpp.language,
    function_node_types=frozenset({'function_definition'}),
    class_node_types=frozenset({'class_specifier', 'struct_specifier'}),
    name_field_by_type={'function_definition': 'declarator'},
    branch_node_types=frozenset({'if_statement', 'for_statement', 'while_statement', 'catch_clause'}),
    call_specs={'call_expression': field_callee('function')},
    import_node_types=frozenset({'preproc_include'}),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='ruby',
    extensions=frozenset({'.rb'}),
    ts_language=_tsruby.language,
    function_node_types=frozenset({'method', 'singleton_method'}),
    class_node_types=frozenset({'class', 'module'}),
    branch_node_types=frozenset({'if', 'elsif', 'unless', 'while', 'until', 'for', 'case', 'rescue'}),
    call_specs={'call': split_callee(name_field='method', object_field='receiver')},
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='php',
    extensions=frozenset({'.php'}),
    ts_language=_tsphp.language_php,
    function_node_types=frozenset({'function_definition', 'method_declaration'}),
    class_node_types=frozenset({'class_declaration', 'interface_declaration'}),
    branch_node_types=frozenset({
        'if_statement', 'else_if_clause', 'for_statement', 'while_statement',
        'catch_clause', 'case_statement',
    }),
    call_specs={
        'function_call_expression': field_callee('function'),
        'member_call_expression': split_callee(name_field='name', object_field='object'),
        'scoped_call_expression': split_callee(name_field='name', object_field='scope'),
    },
    import_node_types=frozenset({
        'require_expression', 'require_once_expression', 'include_expression', 'include_once_expression',
    }),
)))

register(TreeSitterAnalyzer(TreeSitterLanguageSpec(
    language_id='csharp',
    extensions=frozenset({'.cs'}),
    ts_language=_tscs.language,
    function_node_types=frozenset({'method_declaration', 'constructor_declaration'}),
    class_node_types=frozenset({'class_declaration', 'interface_declaration', 'struct_declaration'}),
    branch_node_types=frozenset({
        'if_statement', 'for_statement', 'foreach_statement', 'while_statement',
        'catch_clause', 'switch_section',
    }),
    call_specs={'invocation_expression': field_callee('function')},
    import_node_types=frozenset({'using_directive'}),
)))
