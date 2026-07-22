Editor support
==============

The ``editors/`` directory of the ORDeC repository contains syntax
highlighting packages for ``.ord`` files, so ORDeC designs can be edited in a
regular IDE alongside the browser-based viewer.

ORD is syntactically close to Python, but adds its own constructs, such as:

- ``cell`` declarations
- ``viewgen`` declarations (``viewgen schematic -> Schematic:``)
- node statements like ``output y:``, ``Nmos m1:``, or ``Nmos(w=4u, l=400n) m1:``
- ``anonymous`` node statements and bodyless forms like ``Net vdd``
- ``path`` and ``net`` statements
- the connection operator ``--`` and the constrain operator ``!``
- parameter access like ``.$l`` and SI-suffixed numbers like ``100n``

The highlighting packages extend each editor's Python support with these
ORD-specific rules. The Sublime, JetBrains and VS Code packages are
regex/scope based. ``editors/tree-sitter-ord/`` additionally provides a real
tree-sitter parser for tree-sitter-based editors. The final colors always
depend on your editor's active color scheme.

Sublime Text
------------

``editors/sublime/`` provides a syntax definition that extends Sublime Text's
built-in Python syntax at runtime. It does not redistribute Sublime's Python
syntax files.

Install it either as a user syntax by copying ``Ord.sublime-syntax`` into
``Packages/User/``, or as its own package::

    mkdir -p ~/.config/sublime-text/Packages/Ord
    cp editors/sublime/Ord.sublime-syntax ~/.config/sublime-text/Packages/Ord/

The Sublime packages directory is located at:

- Linux: ``~/.config/sublime-text/Packages/``
- macOS: ``~/Library/Application Support/Sublime Text/Packages/``
- Windows: ``%APPDATA%\Sublime Text\Packages\``

Restart Sublime Text and open a ``.ord`` file. If syntax selection does not
happen automatically, click the syntax selector in the bottom-right corner
and choose ``Ord``.

PyCharm / JetBrains IDEs
------------------------

``editors/jetbrains/`` provides a TextMate bundle that works in PyCharm and
other JetBrains IDEs with TextMate support (IntelliJ IDEA, CLion, WebStorm,
GoLand, ...). It provides syntax highlighting for ORD without requiring a
custom JetBrains plugin.

1. Open the IDE settings (Linux/Windows: ``Ctrl+Alt+S``, macOS: ``Cmd+,``).
2. Go to ``Editor > TextMate Bundles``.
3. Click ``+`` and select the ``editors/jetbrains/ord.tmbundle`` directory
   (not its parent directory).
4. Apply the changes and reopen the ``.ord`` file if needed.

Open a ``.ord`` file to verify that TextMate-based highlighting is applied.
If the file is not recognized automatically, use ``Associate with File
Type`` if prompted, or check the TextMate bundle settings again.

VS Code
-------

``editors/vscode/ord/`` provides a VS Code extension with TextMate
highlighting and a viewer bridge: VS Code commands that launch the ORDeC
local viewer for the active ``.ord`` file and open the view under the cursor
in the browser. Package and install it with::

    cd editors/vscode/ord
    npx @vscode/vsce package
    code --install-extension *.vsix

The viewer bridge requires an ``ordec`` command on the ``PATH`` (or a
configured ``ord.viewer.command``). See ``editors/vscode/ord/README.md`` for
the viewer settings and alternative installation options.

tree-sitter (Neovim, Emacs, Helix)
----------------------------------

``editors/tree-sitter-ord/`` provides a tree-sitter grammar for ORD — a real
parser, in contrast to the regex-based packages above. tree-sitter powers
highlighting in Neovim, Emacs 29+, Helix and other tree-sitter-based
editors.

The parser sources are generated from ``grammar.js``. Generate them once
before installing the grammar into an editor (this requires Node.js)::

    cd editors/tree-sitter-ord
    npm ci
    npm run generate

The ``queries/`` directory holds the editor-neutral queries:
``highlights.scm`` (highlighting), ``folds.scm`` (folding),
``locals.scm`` (scopes), ``tags.scm`` (symbol tags) and
``highlights-emacs.scm`` (an Emacs-specific variant). Then install the
grammar in your editor:

- **Emacs 29+** (built with tree-sitter support): compile the shared
  library — the file name matters, Emacs looks the ``ord`` language up
  as ``libtree-sitter-ord.so`` — and place it where treesit searches::

      cc -O2 -fPIC -shared -I src src/parser.c src/scanner.c \
          -o libtree-sitter-ord.so
      mkdir -p ~/.emacs.d/tree-sitter
      cp libtree-sitter-ord.so ~/.emacs.d/tree-sitter/

  Verify with ``M-: (treesit-ready-p 'ord)``, which must return ``t``.
  ``queries/highlights-emacs.scm`` contains the ORD font-lock rules
  for ``treesit-font-lock-rules``. They are written to layer over
  Python highlighting with ``:override t``; a minimal standalone mode
  that highlights just the ORD constructs::

      (add-to-list 'auto-mode-alist '("\\.ord\\'" . ord-ts-mode))

      (define-derived-mode ord-ts-mode prog-mode "ORD"
        "Minimal tree-sitter mode for ORD."
        (when (treesit-ready-p 'ord)
          (treesit-parser-create 'ord)
          (setq-local treesit-font-lock-settings
                      (treesit-font-lock-rules
                       :language 'ord
                       :feature 'ord
                       (with-temp-buffer
                         (insert-file-contents
                          "/path/to/ordec/editors/tree-sitter-ord/queries/highlights-emacs.scm")
                         (buffer-string))))
          (setq-local treesit-font-lock-feature-list '((ord)))
          (treesit-major-mode-setup)))
- **Neovim** (0.9 or newer): no plugin is required — Neovim's built-in
  tree-sitter support finds parsers and queries on its runtime path.

  1. In a shell (still in ``editors/tree-sitter-ord/``), compile the
     parser and install it and the queries into Neovim's config
     directory::

         cc -O2 -fPIC -shared -I src src/parser.c src/scanner.c -o ord.so
         mkdir -p ~/.config/nvim/parser ~/.config/nvim/queries
         cp ord.so ~/.config/nvim/parser/
         ln -s "$PWD/queries" ~/.config/nvim/queries/ord

  2. In ``~/.config/nvim/init.lua`` (create it if needed), map the
     ``.ord`` extension and attach the highlighter::

         vim.filetype.add({ extension = { ord = "ord" } })
         vim.api.nvim_create_autocmd("FileType", {
           pattern = "ord",
           callback = function()
             vim.treesitter.start()
           end,
         })

  To verify, open a ``.ord`` file and run ``:InspectTree``: the tree
  should contain ORD nodes such as ``node_statement``. After grammar
  changes, rerun ``npm run generate`` and the ``cc`` line, then
  restart Neovim.

  If you already use the nvim-treesitter plugin (``master`` branch —
  the rewritten ``main`` branch uses a different API), you can instead
  register the checkout in the plugin's configuration and compile the
  parser by running ``:TSInstall ord`` once inside Neovim::

      local parsers = require("nvim-treesitter.parsers").get_parser_configs()
      parsers.ord = {
        install_info = {
          url = "/path/to/ordec/editors/tree-sitter-ord",
          files = { "src/parser.c", "src/scanner.c" },
        },
        filetype = "ord",
      }

  ``:TSInstall ord`` is an interactive command — do not put it into
  ``init.lua``, or it re-runs on every start. The filetype mapping and
  queries link from above are still needed, as is
  ``highlight = { enable = true }`` in the nvim-treesitter setup.
- **Helix**: declare the language and the local grammar source in
  ``~/.config/helix/languages.toml``::

      [[language]]
      name = "ord"
      scope = "source.ord"
      file-types = ["ord"]
      comment-token = "#"
      indent = { tab-width = 4, unit = "    " }

      [[grammar]]
      name = "ord"
      source = { path = "/path/to/ordec/editors/tree-sitter-ord" }

  Build the grammar and link the queries (still in
  ``editors/tree-sitter-ord/``; Helix picks the query files it knows
  by name and ignores the rest)::

      hx --grammar build
      mkdir -p ~/.config/helix/runtime/queries
      ln -s "$PWD/queries" ~/.config/helix/runtime/queries/ord

  ``hx --health ord`` shows whether the grammar and queries were
  found. After grammar changes, rerun ``npm run generate`` and
  ``hx --grammar build``.

For working on the grammar itself, see
``editors/tree-sitter-ord/README.md``.

Licensing
---------

The editor packages are free software. ORDeC-authored files are licensed
under Apache-2.0. The JetBrains and VS Code grammars are adapted from the
MIT-licensed MagicPython grammar, and the tree-sitter grammar is derived
from the MIT-licensed tree-sitter-python grammar. Files containing such
upstream material are licensed ``MIT AND Apache-2.0``.

Each installable package — ``ord.tmbundle``, the VS Code extension and
``tree-sitter-ord`` — includes a ``LICENSE.md`` with the complete license
texts. The Sublime syntax uses Sublime Text's built-in Python syntax at
runtime and does not redistribute it.
