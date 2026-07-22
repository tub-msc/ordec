// SPDX-FileCopyrightText: 2016 Max Brunsfeld
// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: MIT AND Apache-2.0

/**
 * @file ORD grammar for tree-sitter, extending the tree-sitter-python grammar
 *
 * ORD is not an unrelated language. It extends Python with domain-specific
 * declarations and inline constructs used by ORDeC. Editors cannot layer
 * those onto the stock Python parser at runtime (constructs such as
 * `Nmos n1:` or `! .pos == (0, 0)` would become ERROR nodes), so this file
 * extends the tree-sitter-python grammar at the source level instead — the
 * same mechanism tree-sitter-typescript uses to extend JavaScript. Python
 * comes from the tree-sitter-python npm devDependency, and only the ORD
 * delta is defined here. `npm run generate` copies the external scanner
 * from the same tree-sitter-python version (renaming its exported symbols)
 * and then generates the parser.
 *
 * The authoritative ORD grammar is ordec/ord/ord.lark in the ORDeC
 * repository. tests/test_editor_grammars.py cross-checks this parser
 * against it on all repository .ord files.
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

const python = require('tree-sitter-python/grammar');

// Mirrors tree-sitter-python's PREC.call for the ORD postfix rules.
const PREC_CALL = 22;

const ORD_SI_SUFFIX = /[afpnumkMGT]/;

module.exports = grammar(python, {
  name: 'ord',

  conflicts: ($, original) => original.concat([
    // Soft keywords: `match x:`, `cell = 5`, `path a` etc. also parse as
    // expressions or node statements. GLR forks decide, with dynamic
    // precedence matching ord.lark's preference for the keyword reading.
    [$.match_statement, $._node_kind],
    [$.cell_definition, $._node_kind],
    [$.viewgen_definition, $._node_kind],
    [$.path_net_statement, $._node_kind],
    [$.type_alias_statement, $._node_kind],
    [$.node_statement, $.node_statement_nobody, $.primary_expression],
    [$.node_statement, $.node_statement_nobody, $._node_kind],
    [$.node_statement_nobody, $.primary_expression],
    [$.node_statement_nobody, $._node_kind],
  ]),

  rules: {
    // Python 2 legacy print/exec statements are removed: ORD treats `print`
    // and `exec` as plain names, and `print foo:` must parse as a node
    // statement.
    _simple_statement: $ => choice(
      $.future_import_statement,
      $.import_statement,
      $.import_from_statement,
      $.path_net_statement,
      $.constrain_statement,
      $.node_statement_nobody,
      $.ord_connection_statement,
      $.assert_statement,
      $.expression_statement,
      $.return_statement,
      $.delete_statement,
      $.raise_statement,
      $.pass_statement,
      $.break_statement,
      $.continue_statement,
      $.global_statement,
      $.nonlocal_statement,
      $.type_alias_statement,
    ),

    _compound_statement: $ => choice(
      $.if_statement,
      $.for_statement,
      $.while_statement,
      $.try_statement,
      $.with_statement,
      $.cell_definition,
      $.viewgen_definition,
      $.node_statement,
      $.function_definition,
      $.class_definition,
      $.decorated_definition,
      $.match_statement,
    ),

    // Dynamic precedence: `match x:` is also a valid node statement with
    // kind `match`, but ord.lark prefers the match statement, so we do too.
    match_statement: $ => prec.dynamic(1, seq(
      'match',
      commaSep1(field('subject', $.expression)),
      optional(','),
      ':',
      field('body', alias($._match_block, $.block)),
    )),

    decorated_definition: $ => seq(
      repeat1($.decorator),
      field('definition', choice(
        $.class_definition,
        $.function_definition,
        $.cell_definition,
        $.viewgen_definition,
      )),
    ),

    // Dynamic precedence 1 on the keyword-introduced statements: `cell X:`
    // or `path a, b` are also valid node statements with a soft-keyword
    // kind, but ord.lark prefers the keyword reading, so we do too.
    cell_definition: $ => prec.dynamic(1, seq(
      'cell',
      field('name', $.identifier),
      ':',
      field('body', $._suite),
    )),

    viewgen_definition: $ => seq(
      'viewgen',
      field('name', $.identifier),
      '->',
      field('return_type', $.type),
      ':',
      field('body', $._suite),
    ),

    // Node statement with body, e.g. `Nmos n1:` or `Nmos(w=4u, l=400n) m1:`.
    // The kind is an expression chain (atom_expr in ord.lark), not a keyword.
    node_statement: $ => seq(
      optional('anonymous'),
      field('kind', $._node_kind),
      field('target', $.context_target),
      ':',
      field('body', $._suite),
    ),

    // Bodyless node statement, e.g. `Net vdd` or `Inv i1, i2`.
    node_statement_nobody: $ => seq(
      optional('anonymous'),
      field('kind', $._node_kind),
      commaSep1(field('target', $.context_target)),
    ),

    _node_kind: $ => choice(
      $.identifier,
      $.keyword_identifier,
      $.attribute,
      $.subscript,
      $.call,
    ),

    path_net_statement: $ => prec.dynamic(1, seq(
      field('keyword', choice('path', 'net')),
      commaSep1(field('name', $.context_target)),
    )),

    context_target: $ => seq(
      $.identifier,
      repeat(choice(
        seq('.', $.identifier),
        seq(
          '[',
          commaSep1(field('subscript', choice($.expression, $.slice))),
          optional(','),
          ']',
        ),
      )),
    ),

    // Leading-dot access to the current node, e.g. `.align` or the
    // bare `.` (dotted_atom in ord.lark). A regular expression atom.
    ord_local_attribute: $ => seq(
      '.',
      optional(field('attribute', $.identifier)),
    ),

    // Parameter access `.$w` or `t.$w` (getparam in ord.lark). The `$` must
    // immediately follow the dot, like the single `.$` token in ord.lark.
    ord_parameter_access: $ => prec(PREC_CALL, seq(
      optional(field('object', $.primary_expression)),
      '.',
      token.immediate('$'),
      field('attribute', $.identifier),
    )),

    // Connection statement, e.g. `.p -- vss`. In ord.lark this is plain
    // subtraction of a negation, but a dedicated statement gives editors a
    // stable node for the `--` convention.
    ord_connection_statement: $ => seq(
      field('left', $.expression),
      '--',
      field('right', $.expression),
    ),

    constrain_statement: $ => seq(
      '!',
      field('constraint', $.expression),
    ),

    primary_expression: ($, original) => choice(
      original,
      $.ord_local_attribute,
      $.ord_parameter_access,
    ),

    pattern: ($, original) => choice(
      original,
      $.ord_local_attribute,
      $.ord_parameter_access,
    ),

    // ORD soft keywords, usable as plain names like `match` and `type`
    keyword_identifier: ($, original) => choice(
      original,
      alias(
        choice('cell', 'viewgen', 'path', 'net', 'anonymous'),
        $.identifier,
      ),
    ),

    // Python number literals extended with ORD SI-suffixed rationals
    integer: _ => token(choice(
      seq(
        choice('0x', '0X'),
        repeat1(/_?[A-Fa-f0-9]+/),
        optional(/[Ll]/),
      ),
      seq(
        choice('0o', '0O'),
        repeat1(/_?[0-7]+/),
        optional(/[Ll]/),
      ),
      seq(
        choice('0b', '0B'),
        repeat1(/_?[0-1]+/),
        optional(/[Ll]/),
      ),
      seq(
        repeat1(/[0-9]+_?/),
        optional(choice(
          /[Ll]/, // long numbers
          /[jJ]/, // complex numbers
          ORD_SI_SUFFIX, // ORD SI-suffixed rationals like 400n
        )),
      ),
    )),

    float: _ => {
      const digits = repeat1(/[0-9]+_?/);
      const exponent = seq(/[eE][\+-]?/, digits);

      return token(seq(
        choice(
          seq(digits, '.', optional(digits), optional(exponent)),
          seq(optional(digits), '.', digits, optional(exponent)),
          seq(digits, exponent),
        ),
        optional(choice(
          /[jJ]/,
          ORD_SI_SUFFIX, // ORD SI-suffixed rationals like 1.2u
        )),
      ));
    },
  },
});

/**
 * Creates a rule to match one or more of the rules separated by a comma
 *
 * @param {RuleOrLiteral} rule
 *
 * @returns {SeqRule}
 */
function commaSep1(rule) {
  return seq(rule, repeat(seq(',', rule)));
}
