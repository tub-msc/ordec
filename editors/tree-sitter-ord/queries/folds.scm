; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: Apache-2.0

; Shared folding query for tree-sitter-aware editors.
; Keep this intentionally broad and structural so multiple editor frontends can
; reuse it without ORD-specific client logic.

[
  (block)
  (argument_list)
  (parameters)
  (dictionary)
  (list)
  (set)
  (tuple)
] @fold
