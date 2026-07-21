; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: Apache-2.0

; inherits: python

; Helix textobject queries for ORD, using the Helix capture dialect
; (.inside/.around suffixes). Python constructs come from the inherited
; Python queries, only the ORD constructs are added here.

(cell_definition
  body: (block)? @class.inside) @class.around

(viewgen_definition
  body: (block)? @function.inside) @function.around

; Node statements with a body select like functions, e.g. `Nmos m1:`.
(node_statement
  body: (block)? @function.inside) @function.around
