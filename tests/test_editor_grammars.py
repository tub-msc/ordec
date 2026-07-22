# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Keeps the editor highlighting grammars in editors/ aligned with the ORD
grammar. Every .ord file in the repository is parsed with the authoritative
Lark parser, each ORD construct line must be matched by the corresponding
highlighting rule, and the node statement rules must not fire on other lines.
The tree-sitter grammar is held to a stricter standard: its generated parser
must accept every file and agree with the Lark parser on the location of all
ORD constructs. The generated parser sources are gitignored, so these tests
skip until `npm ci && npm run generate` has been run in
editors/tree-sitter-ord/.
"""

import ctypes
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from lark import Token

from ordec.ord.parser import parser as ord_parser

REPO_ROOT = Path(__file__).parent.parent
EDITORS = REPO_ROOT / 'editors'

NODE_RULES = ('node_stmt', 'anon_node_stmt')
NOBODY_RULES = ('node_stmt_nobody', 'anon_node_stmt_nobody')
ANON_RULES = ('anon_node_stmt', 'anon_node_stmt_nobody')
KEYWORD_RULES = {
    'celldef': 'cell',
    'viewgen': 'viewgen',
    'path_stmt': 'path_net',
    'net_stmt': 'path_net',
}

# Valid ORD statements that use soft keywords as plain names and must not be
# highlighted as declarations or node statements
SOFT_KEYWORD_NEGATIVES = [
    'cell = 5', 'viewgen = f()', 'net = row[i]', 'path = "/tmp"',
    'match point:', 'case Point(x=0):', 'return x',
]

# Node statement kinds and path/net targets using the full atom_expr /
# context_target forms of ord.lark (dotted, subscripted and called kinds,
# dotted and subscripted path/net targets). No repository .ord file uses
# these forms, so they are checked as synthetic positives.
ATOM_EXPR_POSITIVES = [
    ('lib.Inv i0:', 'node_stmt'),
    ('lib.Inv() i1:', 'node_stmt'),
    ('rows[0] r0:', 'node_stmt'),
    ('anonymous lib.Vdc(dc=1) v0:', 'anon_node_stmt'),
    ('lib.Inv i2, i3', 'node_stmt_nobody'),
    ('net vdd, ring.vx', 'net_stmt'),
    ('path ctr[0], ctr[1].sub', 'path_stmt'),
]


def wrap_in_viewgen(line, rule):
    """Embed a synthetic statement in a minimal cell/viewgen skeleton."""
    body = '\n            pass' if rule in NODE_RULES else ''
    return f'cell C:\n    viewgen v -> Schematic:\n        {line}{body}\n'


def test_atom_expr_positives_are_valid_ord():
    """The synthetic positives really are the ORD constructs they claim."""
    for line, rule in ATOM_EXPR_POSITIVES:
        tree = ord_parser.parse(wrap_in_viewgen(line, rule))
        rules = {subtree.data for subtree in tree.iter_subtrees()}
        assert rule in rules, (line, rule)


def textmate_regex(pattern):
    # translate the Oniguruma POSIX classes used by the grammars to Python re
    return re.compile(pattern.replace('[_[:alpha:]]', '[A-Za-z_]'))


@pytest.fixture(scope='module')
def parsed_ord_files():
    """Parse repository .ord files and locate their ORD-specific constructs.

    Returns:
        List of (path, source lines, {line number: construct rule},
        line numbers inside multi-line strings) tuples.
    """
    interesting = NODE_RULES + NOBODY_RULES + tuple(KEYWORD_RULES)
    files = sorted(set((REPO_ROOT / 'ordec').rglob('*.ord'))
                   | set((REPO_ROOT / 'tests').rglob('*.ord')))
    assert files, 'no .ord files found in the repository'
    parsed = []
    for path in files:
        source = path.read_text()
        tree = ord_parser.parse(source + '\n')
        constructs = {}
        for subtree in tree.iter_subtrees():
            if subtree.data in interesting and not subtree.meta.empty:
                constructs.setdefault(subtree.meta.line, subtree.data)
        in_string = set()
        for token in tree.scan_values(lambda v: isinstance(v, Token)):
            if token.type in ('STRING', 'LONG_STRING', 'F_LONG_STRING') \
                    and token.end_line > token.line:
                in_string.update(range(token.line, token.end_line + 1))
        parsed.append((path, source.split('\n'), constructs, in_string))
    return parsed


def verify(parsed_files, matches, statement_matchers):
    """Check construct lines match and other lines stay unmatched.

    Args:
        parsed_files: the parsed_ord_files fixture value.
        matches: callable (construct rule, raw source line) -> truthy when
            the grammar's rule for that construct fires on the line.
        statement_matchers: node statement matchers to sweep over all
            remaining lines for false positives (multi-line strings and
            comments are exempt because the grammars exclude them).
    """
    for path, lines, constructs, in_string in parsed_files:
        for line_number, rule in constructs.items():
            line = lines[line_number - 1]
            assert matches(rule, line), \
                f'{path}:{line_number}: {rule} not matched: {line.strip()!r}'
        for line_number, line in enumerate(lines, 1):
            skip = (line_number in constructs or line_number in in_string
                    or not line.strip() or line.strip().startswith('#'))
            if skip:
                continue
            for matcher in statement_matchers:
                assert not matcher(line), \
                    f'{path}:{line_number}: false positive: {line.strip()!r}'


def test_vscode_injection_grammar(parsed_ord_files):
    grammar_file = EDITORS / 'vscode/ord/syntaxes/ord-injection.tmLanguage.json'
    repo = json.loads(grammar_file.read_text())['repository']
    block = textmate_regex(repo['node-statement-block']['begin'])
    inline = textmate_regex(repo['node-statement-inline']['begin'])
    bare = textmate_regex(repo['node-statement-bare']['match'])
    keyword = {
        'cell': textmate_regex(repo['cell-declaration']['begin']),
        'viewgen': textmate_regex(repo['viewgen-declaration']['begin']),
        'path_net': textmate_regex(repo['path-net']['begin']),
    }

    def matches(rule, line):
        if rule in NODE_RULES:
            return block.match(line) or inline.match(line)
        if rule in NOBODY_RULES:
            return bare.match(line)
        return keyword[KEYWORD_RULES[rule]].match(line.lstrip())

    verify(parsed_ord_files, matches, [block.match, inline.match, bare.match])
    for negative in SOFT_KEYWORD_NEGATIVES:
        for matcher in (block, inline, bare, *keyword.values()):
            assert not matcher.match('    ' + negative) and not matcher.match(negative)
    for line, rule in ATOM_EXPR_POSITIVES:
        assert matches(rule, line), f'atom_expr positive not matched: {line!r}'


def test_jetbrains_grammar(parsed_ord_files):
    grammar_file = EDITORS / 'jetbrains/ord.tmbundle/Syntaxes/ord.tmLanguage.json'
    repo = json.loads(grammar_file.read_text())['repository']
    node_statement = textmate_regex(repo['node-statement']['begin'])
    anonymous = textmate_regex(repo['anonymous-modifier']['match'])
    keyword = {
        'cell': textmate_regex(repo['class-declaration']['patterns'][1]['begin']),
        'viewgen': textmate_regex(repo['viewgen-declaration']['begin']),
        'path_net': textmate_regex(repo['path-net']['begin']),
    }

    def matches(rule, line):
        line = line.lstrip()
        if rule in ANON_RULES:
            after_keyword = line.split(None, 1)[1]
            return anonymous.match(line) and node_statement.match(after_keyword)
        if rule in NODE_RULES + NOBODY_RULES:
            return node_statement.match(line)
        return keyword[KEYWORD_RULES[rule]].match(line)

    # the node-statement rule is not line-anchored, so no line-based false
    # positive sweep is meaningful for it
    verify(parsed_ord_files, matches, [])
    for negative in SOFT_KEYWORD_NEGATIVES:
        for matcher in (node_statement, anonymous, *keyword.values()):
            assert not matcher.match(negative)
    for line, rule in ATOM_EXPR_POSITIVES:
        assert matches(rule, line), f'atom_expr positive not matched: {line!r}'


def test_sublime_syntax(parsed_ord_files):
    yaml = pytest.importorskip('yaml')
    syntax = yaml.safe_load((EDITORS / 'sublime/Ord.sublime-syntax').read_text())
    variables = syntax['variables']

    def sublime_regex(pattern):
        while '{{' in pattern:
            for name, value in variables.items():
                pattern = pattern.replace('{{%s}}' % name, value)
        pattern = pattern.replace('[[:alpha:]_]', '[A-Za-z_]')
        pattern = pattern.replace('[[:alnum:]_]', '[A-Za-z0-9_]')
        return re.compile(pattern)

    contexts = syntax['contexts']
    anonymous = sublime_regex(contexts['ord-node-statements'][0]['match'])
    node_statement = sublime_regex(contexts['ord-node-statements'][1]['match'])
    keyword = {
        'cell': sublime_regex(contexts['class-definitions'][1]['match']),
        'viewgen': sublime_regex(contexts['ord-viewgen-definitions'][0]['match']),
        'path_net': sublime_regex(contexts['ord-path-net-statements'][0]['match']),
    }

    def matches(rule, line):
        line = line.lstrip()
        if rule in ANON_RULES:
            return anonymous.match(line)
        if rule in NODE_RULES + NOBODY_RULES:
            return node_statement.match(line)
        return keyword[KEYWORD_RULES[rule]].match(line)

    verify(parsed_ord_files, matches,
           [lambda line: node_statement.match(line.lstrip())])
    for negative in SOFT_KEYWORD_NEGATIVES:
        for matcher in (node_statement, anonymous, *keyword.values()):
            assert not matcher.match(negative)
    for line, rule in ATOM_EXPR_POSITIVES:
        assert matches(rule, line), f'atom_expr positive not matched: {line!r}'


# Lark rule -> tree-sitter node type produced for the same construct
TREE_SITTER_RULES = {
    'node_stmt': 'node_statement',
    'anon_node_stmt': 'node_statement',
    'node_stmt_nobody': 'node_statement_nobody',
    'anon_node_stmt_nobody': 'node_statement_nobody',
    'celldef': 'cell_definition',
    'viewgen': 'viewgen_definition',
    'path_stmt': 'path_net_statement',
    'net_stmt': 'path_net_statement',
}


@pytest.fixture(scope='module')
def ord_tree_sitter_parser(tmp_path_factory):
    """Compile the generated tree-sitter parser and load it via py-tree-sitter."""
    tree_sitter = pytest.importorskip('tree_sitter')
    cc = shutil.which('cc')
    if cc is None:
        pytest.skip('no C compiler available')
    src = EDITORS / 'tree-sitter-ord' / 'src'
    if not (src / 'parser.c').exists():
        pytest.skip('parser not generated, run npm ci && npm run generate '
                    'in editors/tree-sitter-ord')
    library = tmp_path_factory.mktemp('tree_sitter_ord') / 'ord.so'
    subprocess.run(
        [cc, '-fPIC', '-shared', '-I', str(src), str(src / 'parser.c'),
         str(src / 'scanner.c'), '-o', str(library)], check=True)
    handle = ctypes.CDLL(str(library))
    handle.tree_sitter_ord.restype = ctypes.c_void_p
    # tree_sitter.Language expects the TSLanguage pointer as a PyCapsule
    capsule_new = ctypes.pythonapi.PyCapsule_New
    capsule_new.restype = ctypes.py_object
    capsule_new.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p)
    capsule = capsule_new(handle.tree_sitter_ord(),
                          b'tree_sitter.Language', None)
    return tree_sitter.Parser(tree_sitter.Language(capsule))


def tree_sitter_nodes(tree):
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def test_tree_sitter_grammar(parsed_ord_files, ord_tree_sitter_parser):
    """The parser accepts every .ord file and finds the same constructs."""
    ord_node_types = set(TREE_SITTER_RULES.values())
    for path, lines, constructs, _ in parsed_ord_files:
        tree = ord_tree_sitter_parser.parse(path.read_bytes())
        assert not tree.root_node.has_error, f'{path}: tree-sitter parse error'
        found = {}
        for node in tree_sitter_nodes(tree):
            if node.type in ord_node_types:
                found.setdefault(node.start_point[0] + 1, node.type)
        for line_number, rule in constructs.items():
            assert found.get(line_number) == TREE_SITTER_RULES[rule], \
                (f'{path}:{line_number}: expected {TREE_SITTER_RULES[rule]}: '
                 f'{lines[line_number - 1].strip()!r}')
        for line_number, node_type in found.items():
            rule = constructs.get(line_number)
            assert rule and TREE_SITTER_RULES[rule] == node_type, \
                (f'{path}:{line_number}: stray {node_type}: '
                 f'{lines[line_number - 1].strip()!r}')


def test_tree_sitter_soft_keywords(ord_tree_sitter_parser):
    ord_node_types = set(TREE_SITTER_RULES.values())
    for negative in SOFT_KEYWORD_NEGATIVES:
        if negative == 'case Point(x=0):':
            continue  # only valid inside a match block
        tree = ord_tree_sitter_parser.parse((negative + '\n').encode())
        assert not tree.root_node.has_error, negative
        types = {node.type for node in tree_sitter_nodes(tree)}
        assert not (ord_node_types & types), negative


def test_tree_sitter_atom_expr_positives(ord_tree_sitter_parser):
    for line, rule in ATOM_EXPR_POSITIVES:
        source = wrap_in_viewgen(line, rule)
        tree = ord_tree_sitter_parser.parse(source.encode())
        assert not tree.root_node.has_error, line
        types = {node.type for node in tree_sitter_nodes(tree)}
        assert TREE_SITTER_RULES[rule] in types, line
