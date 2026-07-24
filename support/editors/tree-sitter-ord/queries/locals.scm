; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: Apache-2.0

; Shared locals query for tree-sitter-aware editors.
; This stays intentionally conservative: prefer under-classifying references to
; baking in pseudo-semantics that drift from the authoritative ORDeC analyzer.

[
  (module)
  (block)
  (lambda)
  (list_comprehension)
  (dictionary_comprehension)
  (set_comprehension)
  (generator_expression)
] @local.scope

(function_definition
  name: (identifier) @local.definition)

(class_definition
  name: (identifier) @local.definition)

(cell_definition
  name: (identifier) @local.definition)

(viewgen_definition
  name: (identifier) @local.definition)

(parameters
  (identifier) @local.definition)

(default_parameter
  name: (identifier) @local.definition)

(typed_parameter
  (identifier) @local.definition)

(typed_default_parameter
  name: (identifier) @local.definition)

(list_splat_pattern
  (identifier) @local.definition)

(dictionary_splat_pattern
  (identifier) @local.definition)

(assignment
  left: (identifier) @local.definition)

(for_statement
  left: (identifier) @local.definition)

(aliased_import
  alias: (identifier) @local.definition)

(path_net_statement
  name: (context_target
    . (identifier) @local.definition))

(node_statement
  target: (context_target
    . (identifier) @local.definition))

(node_statement_nobody
  target: (context_target
    . (identifier) @local.definition))

(identifier) @local.reference
