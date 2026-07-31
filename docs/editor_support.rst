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
tree-sitter-based editors.

Sublime Text
------------

``support/editors/sublime/`` provides a syntax definition that extends
Sublime Text's built-in Python syntax at runtime.

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
the ORD constructs. It requires an IDE with Python support on platform
2024.2 or newer, either PyCharm or IntelliJ IDEA with the Python plugin.
Building the plugin needs only a JDK (17 or newer) to launch the
committed Gradle wrapper, which pins the Gradle version and
auto-provisions the JDK the IntelliJ Platform needs, so builds do not
depend on locally installed tool versions. The first build downloads the
pinned Gradle distribution (checksum-verified) and the IDE SDK::

    cd support/editors/jetbrains
    ./gradlew buildPlugin

Install the archive from ``build/distributions/`` via
``Settings > Plugins > (gear icon) > Install Plugin from Disk``, restart,
and open a ``.ord`` file to verify highlighting and the ORD file icon.
Everything that is plain Python gets the IDE's usual Python
intelligence.

VS Code
-------

``support/editors/vscode/ord/`` provides a VS Code extension with TextMate
highlighting for ``.ord`` files. Package and install it with::

    cd support/editors/vscode/ord
    npx @vscode/vsce package
    code --install-extension *.vsix

Highlighting needs no configuration and no bundled color theme: the ORD
constructs carry standard TextMate scopes that stock themes already
style (``viewgen`` colors like ``def``, the ``--`` and ``!`` operators
like flow keywords, SI suffixes like CSS units). Every scope keeps an
``.ord``-specific tail, so single constructs can still be re-colored
via ``editor.tokenColorCustomizations`` in ``settings.json``.

tree-sitter (Neovim, Helix)
---------------------------

``support/editors/tree-sitter-ord/`` provides a tree-sitter grammar for
ORD, a real parser in contrast to the regex-based Sublime and VS Code
packages. tree-sitter powers highlighting in Neovim, Helix and other
tree-sitter-based editors.

The parser sources are generated from ``grammar.js``. Generate them once
before installing the grammar into an editor (this requires Node.js)::

    cd support/editors/tree-sitter-ord
    npm ci
    npm run generate

The ``queries/`` directory holds the editor-neutral queries
``highlights.scm`` (highlighting), ``folds.scm`` (folding),
``locals.scm`` (scopes) and ``tags.scm`` (symbol tags), plus
``highlights-helix.scm`` (the same highlight rules with Helix theme
scope names) and ``textobjects.scm`` and ``indents.scm`` (Helix
structural selections and auto-indent). Then install the grammar in
your editor:

- **Neovim** (0.9 or newer): no plugin is required, since Neovim's built-in
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

  If you already use the nvim-treesitter plugin (its ``master`` branch,
  since the rewritten ``main`` branch uses a different API), you can instead
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

  ``:TSInstall ord`` is an interactive command. Do not put it into
  ``init.lua``, or it re-runs on every start. The filetype mapping and
  queries link from above are still needed, as is
  ``highlight = { enable = true }`` in the nvim-treesitter setup.
- **Helix**: declare the language and the local grammar source in
  ``~/.config/helix/languages.toml``::

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

  The ``use-grammars`` line keeps ``hx --grammar build`` from
  rebuilding every grammar Helix knows, but it also limits all later
  ``hx --grammar fetch``/``build`` runs to ord. Remove it again if you
  build other grammars from source.

  Build the grammar and link the queries, still in
  ``support/editors/tree-sitter-ord/``. Helix 25.07 or newer is
  required: since that release Helix resolves overlapping captures
  last-match-wins like Neovim (older releases applied the first match
  and are not supported). Helix styles captures by looking them up as
  theme scopes, so it gets ``highlights-helix.scm``, the same rules
  with Helix scope names, linked under the name Helix expects::

      mkdir -p ~/.config/helix/runtime/grammars ~/.config/helix/runtime/queries/ord
      hx --grammar build
      ln -sf "$PWD/queries/highlights-helix.scm" \
          ~/.config/helix/runtime/queries/ord/highlights.scm
      ln -sf "$PWD/queries/textobjects.scm" "$PWD/queries/indents.scm" \
          "$PWD/queries/locals.scm" ~/.config/helix/runtime/queries/ord/

  Afterwards ``hx --health ord`` must report the highlight, textobject
  and indent queries as found (a leftover symlink from an earlier
  layout can dangle, ``ln -sf`` above replaces it). After grammar
  changes, rerun ``npm run generate`` and ``hx --grammar build``.

Implementation details
----------------------

All packages follow one design: since ORD is a superset of Python, each
package extends its editor's existing Python support instead of
reimplementing a full language. The Sublime syntax extends the
built-in Python syntax at runtime, the VS Code grammar injects ORD
rules into a grammar that delegates to Python, the JetBrains plugin
subclasses the Python plugin's parser, and the tree-sitter grammar
inherits from tree-sitter-python. Only the ORD delta is maintained
here.

ORD's grammar is defined in ``src/ordec/ord/ord.lark``, and the editor
packages must follow it. The tests in
``support/editors/tests/test_editor_grammars.py`` compare them against
this definition: each ``.ord`` file in the repository is parsed with
ORDeC's own parser, and every construct it finds must also be
recognized by the Sublime and VS Code rules and by the compiled
tree-sitter parser, with no false positives on other lines. After
changing ``ord.lark``, update the grammars until these tests pass
again. They are not part of the default ``pytest`` run: run them with
``pytest support/editors/tests/``, which additionally needs the
``pyyaml`` and ``tree-sitter`` Python packages, or let the ``editors``
CI workflow run them on changes under ``support/editors/``,
``src/ordec/ord/`` and the repository ``.ord`` files. The tree-sitter tests
skip unless a C compiler is available and the parser sources have been
generated as described below.

In ``support/editors/tree-sitter-ord/``, the ``src/`` directory is
generated from ``grammar.js``: ``npm run generate`` copies the
external scanner from the pinned tree-sitter-python version and
generates the parser. ``npm test`` runs the corpus tests and validates
the query files.
``highlights.scm`` orders its rules for last-match-wins capture
resolution, which Neovim, Helix 25.07+ and the tree-sitter CLI share:
generic captures come first, ORD-specific refinements last.
``highlights-helix.scm`` repeats the same rules in the same order with
Helix theme scope names as captures, since Helix styles captures by
theme scope lookup and does not know ``@property``, ``@number`` or
``@escape``. A test compares the two files modulo capture names.

In ``support/editors/jetbrains/``, ``./gradlew runIde`` starts a
sandboxed IDE for development and ``./gradlew test`` runs the plugin's
test suite, which checks the same repository ``.ord`` files and
constructs as the Python tests above. One known limitation: ORD
statements in the one-line suite of a Python compound statement
(``if x: net a``) are not recognized, since Python's own suite parsing
handles those bodies.
