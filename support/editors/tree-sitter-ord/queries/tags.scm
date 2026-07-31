; SPDX-FileCopyrightText: 2016 Max Brunsfeld
; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: MIT AND Apache-2.0

; Derived from tree-sitter-python's tags queries
; (https://github.com/tree-sitter/tree-sitter-python).

(module (expression_statement (assignment left: (identifier) @name) @definition.constant))

(cell_definition
  name: (identifier) @name) @definition.class

(viewgen_definition
  name: (identifier) @name) @definition.function

(node_statement
  target: (context_target . (identifier) @name)) @definition.constant

(node_statement_nobody
  target: (context_target . (identifier) @name)) @definition.constant

(path_net_statement
  name: (context_target . (identifier) @name)) @definition.constant

(class_definition
  name: (identifier) @name) @definition.class

(function_definition
  name: (identifier) @name) @definition.function

(call
  function: [
      (identifier) @name
      (attribute
        attribute: (identifier) @name)
  ]) @reference.call
