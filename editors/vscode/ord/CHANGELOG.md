<!--
SPDX-FileCopyrightText: Microsoft Corporation
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: MIT AND Apache-2.0
-->

# Change Log

All notable changes to the "ord" extension will be documented in this file.

Check [Keep a Changelog](http://keepachangelog.com/) for recommendations on how to structure this file.

## [0.1.0] - 2026-07-16

Initial release, providing TextMate-based ORD highlighting and an ORDeC
viewer bridge.

- Highlighting matches the current ORD grammar: viewgens take no parameter
  list, `anonymous` node statements, constructor arguments on node types
  (`Series(gap=4) core:`), and bodyless node statements (`Net vdd`,
  `Nmos m1, m2`) are highlighted, and the removed rational literal (`1/3`) is
  not treated as a number.
- ORD injection rules do not fire inside strings and comments.
- Auto-indent triggers after node statement headers such as `Nmos m1:` or
  `Series(gap=4) core:`.
- No bundled color theme: ORD scopes extend standard TextMate scope
  prefixes, so any theme colors them. The README documents optional
  `editor.tokenColorCustomizations` rules for ORD-specific accents.
- The extension does not include a language client. It can be reintroduced
  once `ordec-lsp` ships with ORDeC.
