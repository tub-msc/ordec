ORD Language Server
===================

ORDeC includes a language server for ``.ord`` files. It is installed as
``ordec-lsp`` and communicates over standard input/output using the Language
Server Protocol (LSP).

The language server is intended for local project work in an editor. It does
not execute ORD code; it parses source files and performs lightweight semantic
analysis to provide editor features while the design itself remains in ORD and
Python source files.

Installation
------------

Install ORDeC in the environment used by your editor::

    pip install -e .

After installation, the language server command should be available as::

    ordec-lsp

If your editor cannot find the command, configure it with the absolute path to
the ``ordec-lsp`` script inside the Python environment.

Editor setup
------------

Use ``.ord`` as the file extension and ``ord`` as the language id when your
editor asks for one. Configure ``ordec-lsp`` as a stdio language server and set
the workspace root to the project directory.

For Neovim with ``nvim-lspconfig``::

    vim.api.nvim_create_autocmd({"BufRead", "BufNewFile"}, {
        pattern = "*.ord",
        callback = function()
            vim.bo.filetype = "ord"
        end,
    })

    vim.lsp.config("ordec", {
        cmd = {"ordec-lsp"},
        filetypes = {"ord"},
        root_markers = {"pyproject.toml", ".git"},
    })

    vim.lsp.enable("ordec")

For editors with generic LSP support, configure:

* command: ``ordec-lsp``
* transport: stdio
* file extension: ``*.ord``
* language id: ``ord``
* workspace root: the ORDeC project or design project directory

Capabilities
------------

The server currently provides:

* document and workspace symbols
* go-to-definition, hover, references, and document highlights
* prepare-rename and workspace rename
* local name completions
* member and parameter completions for known ORD/Python types
* folding ranges and selection ranges
* semantic tokens
* parser diagnostics for ORD syntax errors
* semantic diagnostics for unresolved imports, unresolved ORD node types,
  invalid view generator return types, invalid constraint contexts, unknown
  members or parameters, and schematic ports missing from the symbol view
* quick fixes for selected diagnostics, including missing symbol ports

Behavior notes
--------------

The server keeps the last successful structural analysis while reporting syntax
errors from the current edit. This keeps navigation, symbols, and completions
useful while typing incomplete code.

Workspace-wide references and rename use the current workspace's ORD import
graph. Configure the workspace root to the project directory so reverse
dependencies can be found.

The server also performs shallow Python analysis for imported Python modules.
This is used for go-to-definition and member completion of exported classes,
functions, variables, and simple class members. It is intentionally lightweight
and does not execute imported Python modules.

Known limitations
-----------------

The language server is not a full Python type checker. Python expression types
are inferred only where the ORD analysis can derive useful local information.
For complex Python control flow or dynamic imports, completion and diagnostics
may be conservative.

Rename is deliberately restricted to identifiers and does not rename ORD member
accesses such as ``x.member`` or parameter accesses such as ``x.$param``.

Workspace-wide features depend on the editor passing the correct workspace root
and on file watching notifications for changed files. Saving a file also
refreshes diagnostics and cached import data.
