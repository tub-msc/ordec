# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Keeps the editor highlighting grammars in editors/ aligned with the ORD
grammar. Every .ord file in the repository is parsed with the authoritative
Lark parser, each ORD construct line must be matched by the corresponding
highlighting rule, and the node statement rules must not fire on other lines.
"""

import json
import re
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
    block = textmate_regex(repo['context-element-block']['begin'])
    inline = textmate_regex(repo['context-element-inline']['begin'])
    bare = textmate_regex(repo['context-element-bare']['match'])
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


def test_pycharm_grammar(parsed_ord_files):
    grammar_file = EDITORS / 'pycharm/ord.tmbundle/Syntaxes/ord.tmLanguage.json'
    repo = json.loads(grammar_file.read_text())['repository']
    context_element = textmate_regex(repo['context-element']['begin'])
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
            return anonymous.match(line) and context_element.match(after_keyword)
        if rule in NODE_RULES + NOBODY_RULES:
            return context_element.match(line)
        return keyword[KEYWORD_RULES[rule]].match(line)

    # the context-element rule is not line-anchored, so no line-based false
    # positive sweep is meaningful for it
    verify(parsed_ord_files, matches, [])
    for negative in SOFT_KEYWORD_NEGATIVES:
        for matcher in (context_element, anonymous, *keyword.values()):
            assert not matcher.match(negative)


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
    anonymous = sublime_regex(contexts['ord-context-elements'][0]['match'])
    node_statement = sublime_regex(contexts['ord-context-elements'][1]['match'])
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
