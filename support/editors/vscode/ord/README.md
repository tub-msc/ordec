<!--
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: Apache-2.0
-->

# ORD for Visual Studio Code

Work with ORD designs directly in Visual Studio Code. The extension
recognizes `.ord` files, highlights ORD syntax, and keeps familiar Python
syntax highlighting available.

ORD is the hardware description language included with ORDeC, the Open Rapid
Design Composer. ORDeC helps you create custom integrated circuit designs
using Python and a concise language for cells, views, circuit elements, nets,
and design constraints.

## Language server

The extension starts the `ordec-lsp` language server automatically for ORD
files. Install ORDeC in an environment visible to VS Code and verify that
`ordec-lsp` runs from a terminal. If VS Code uses a different environment, set
`ord.languageServer.command` to the executable's absolute path. The server can
be disabled with `ord.languageServer.enabled`.

Visit the [ORDeC documentation](https://ordec.readthedocs.io) to get started,
or find the project on [GitHub](https://github.com/tub-msc/ordec).
