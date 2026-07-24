; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: Apache-2.0

; inherits: python

; Helix indent queries for ORD, using the Helix capture dialect. Python
; constructs come from the inherited Python queries, only the ORD
; block-introducing statements are added here. Their bodies are ordinary
; (block) nodes, so the inherited block handling applies to them too.

[
  (cell_definition)
  (viewgen_definition)
  (node_statement)
] @indent
