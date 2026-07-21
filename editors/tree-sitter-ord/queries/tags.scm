; SPDX-FileCopyrightText: 2016 Max Brunsfeld
; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: MIT AND Apache-2.0

(module (expression_statement (assignment left: (identifier) @name) @definition.constant))

(cell_definition
  name: (identifier) @name) @definition.class

(viewgen_definition
  name: (identifier) @name) @definition.function

(context_definition
  target: (context_target . (identifier) @name)) @definition.constant

(context_declaration
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
