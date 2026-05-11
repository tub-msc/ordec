ORD Language Server
===================

ORDeC installs a small language server for ``.ord`` files as ``ordec-lsp``.
It communicates over standard input/output using the Language Server Protocol.

The server currently provides:

* document and workspace symbols
* go-to-definition and hover
* references and rename
* completion, folding ranges, selection ranges, and semantic tokens
* diagnostics for ORD syntax errors

Editor setup
------------

The language server command is::

    ordec-lsp

Use ``.ord`` as the file extension and ``ord`` as the language id when your
editor asks for one.

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

For editors with generic LSP support, configure a stdio language server with
``ordec-lsp`` as the command and the project directory as the workspace root.

Behavior notes
--------------

The server keeps the last successful analysis while reporting syntax errors
from the current edit. This keeps navigation and document symbols useful while
typing incomplete code.

Workspace-wide references and rename use the current workspace's ORD import
graph. Configure the workspace root to the project directory so reverse
dependencies can be found.
