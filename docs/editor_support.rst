Editor support
==============

The ``support/editors/`` directory of the ORDeC repository contains editor
support packages for ``.ord`` files, so ORDeC designs can be edited in a
regular IDE alongside the browser-based viewer.

ORD is syntactically close to Python, but adds its own constructs, such as:

- ``cell`` declarations
- ``viewgen`` declarations (``viewgen schematic -> Schematic:``)
- node statements like ``output y:``, ``Nmos m1:``, or ``Nmos(w=4u, l=400n) m1:``
- ``anonymous`` node statements and bodyless forms like ``Net vdd``
- ``path`` and ``net`` statements
- the connection operator ``--`` and the constrain operator ``!``
- parameter access like ``.$l`` and SI-suffixed numbers like ``100n``

The packages extend each editor's Python support with these ORD-specific
rules. The Sublime and VS Code packages are regex/scope based, the
JetBrains plugin parses ORD natively as a Python dialect, and
``support/editors/tree-sitter-ord/`` provides a real parser for
tree-sitter-based editors. The final colors always depend on your
editor's active color scheme.

Sublime Text
------------

``support/editors/sublime/`` provides a syntax definition that extends Sublime Text's
built-in Python syntax at runtime. It does not redistribute Sublime's Python
syntax files.

Install it either as a user syntax by copying ``Ord.sublime-syntax`` into
``Packages/User/``, or as its own package::

    mkdir -p ~/.config/sublime-text/Packages/Ord
    cp support/editors/sublime/Ord.sublime-syntax ~/.config/sublime-text/Packages/Ord/

The Sublime packages directory is located at:

- Linux: ``~/.config/sublime-text/Packages/``
- macOS: ``~/Library/Application Support/Sublime Text/Packages/``
- Windows: ``%APPDATA%\Sublime Text\Packages\``

Restart Sublime Text and open a ``.ord`` file. If syntax selection does not
happen automatically, click the syntax selector in the bottom-right corner
and choose ``Ord``.

PyCharm / JetBrains IDEs
------------------------

``support/editors/jetbrains/`` provides an IDE plugin that parses ORD
natively as a Python dialect, extending the IDE's own Python parser with
the ORD constructs. It requires an IDE with Python support: PyCharm, or
IntelliJ IDEA with the Python plugin. Building the plugin needs only a
JDK (the committed Gradle wrapper provides everything else)::

    cd support/editors/jetbrains
    ./gradlew buildPlugin

Install the archive from ``build/distributions/`` via
``Settings > Plugins > (gear icon) > Install Plugin from Disk``, restart,
and open a ``.ord`` file to verify highlighting and the ORD file icon.
See ``support/editors/jetbrains/README.md`` for details.

VS Code
-------

``support/editors/vscode/ord/`` provides a VS Code extension with TextMate
highlighting and a viewer bridge: VS Code commands that launch the ORDeC
local viewer for the active ``.ord`` file and open the view under the cursor
in the browser. Package and install it with::

    cd support/editors/vscode/ord
    npx @vscode/vsce package
    code --install-extension *.vsix

The viewer bridge requires an ``ordec`` command on the ``PATH`` (or a
configured ``ord.viewer.command``). See ``support/editors/vscode/ord/README.md`` for
the viewer settings and alternative installation options.

tree-sitter (Neovim, Emacs, Helix)
----------------------------------

``support/editors/tree-sitter-ord/`` provides a tree-sitter grammar for ORD — a real
parser, in contrast to the regex-based Sublime and VS Code packages.
tree-sitter powers
highlighting in Neovim, Emacs 29+, Helix and other tree-sitter-based
editors.

The parser sources are generated from ``grammar.js``. Generate them once
before installing the grammar into an editor (this requires Node.js)::

    cd support/editors/tree-sitter-ord
    npm ci
    npm run generate

The ``queries/`` directory holds the editor-neutral queries
``highlights.scm`` (highlighting), ``folds.scm`` (folding),
``locals.scm`` (scopes) and ``tags.scm`` (symbol tags), plus
editor-specific variants: ``highlights-emacs.scm`` (Emacs),
``highlights-helix.scm`` (the highlight rules in Helix capture order),
``textobjects.scm`` and ``indents.scm`` (Helix structural selections
and auto-indent). Then install the grammar in your editor:

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
  Python highlighting with ``:override t``. A minimal standalone mode
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
                          "/path/to/ordec/support/editors/tree-sitter-ord/queries/highlights-emacs.scm")
                         (buffer-string))))
          (setq-local treesit-font-lock-feature-list '((ord)))
          (treesit-major-mode-setup)))
- **Neovim** (0.9 or newer): no plugin is required — Neovim's built-in
  tree-sitter support finds parsers and queries on its runtime path.

  1. In a shell (still in ``support/editors/tree-sitter-ord/``), compile the
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
          url = "/path/to/ordec/support/editors/tree-sitter-ord",
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

      # optional, restricts the hx --grammar commands to the ORD grammar
      use-grammars = { only = ["ord"] }

      [[language]]
      name = "ord"
      scope = "source.ord"
      file-types = ["ord"]
      comment-token = "#"
      indent = { tab-width = 4, unit = "    " }

      [[grammar]]
      name = "ord"
      source = { path = "/path/to/ordec/support/editors/tree-sitter-ord" }

  Build the grammar and link the queries, still in
  ``support/editors/tree-sitter-ord/``. Helix applies the first
  matching highlight capture, the reverse of Neovim, so it gets its own
  ordering of the highlight rules — ``highlights-helix.scm``, linked
  under the name Helix expects — while the other query files are shared::

      mkdir -p ~/.config/helix/runtime/grammars ~/.config/helix/runtime/queries/ord
      hx --grammar build
      ln -s "$PWD/queries/highlights-helix.scm" \
          ~/.config/helix/runtime/queries/ord/highlights.scm
      ln -s "$PWD/queries/textobjects.scm" "$PWD/queries/indents.scm" \
          "$PWD/queries/locals.scm" ~/.config/helix/runtime/queries/ord/

  Afterwards ``hx --health ord`` should report the highlight,
  textobject and indent queries as found. After grammar changes, rerun
  ``npm run generate`` and ``hx --grammar build``.

For working on the grammar itself, see
``support/editors/tree-sitter-ord/README.md``.

Licensing
---------

The editor packages are free software. ORDeC-authored files are licensed
under Apache-2.0. The VS Code grammar is adapted from the MIT-licensed
MagicPython grammar, and the tree-sitter grammar is derived from the
MIT-licensed tree-sitter-python grammar. Files containing such upstream
material are licensed ``MIT AND Apache-2.0``.

The VS Code extension and ``tree-sitter-ord`` each include a ``LICENSE.md``
with the complete license texts. The Sublime syntax and the JetBrains
plugin build on each editor's own Python support at runtime and
redistribute no third-party material.
