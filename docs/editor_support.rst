Editor support
==============

The ``support/editors/`` directory of the ORDeC repository contains editor
support packages for ``.ord`` files, so ORDeC designs can be edited in a
regular IDE alongside the browser-based viewer.

Editor support has two parts: syntax highlighting packages that teach each
editor the ORD constructs, and the ORD language server that adds semantic
features such as diagnostics and navigation on top.

Syntax highlighting
-------------------

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
~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~

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
Everything that is plain Python gets the usual IDE Python
intelligence.

VS Code
~~~~~~~

``support/editors/vscode/ord/`` provides a VS Code extension with TextMate
highlighting for ``.ord`` files. Package and install it with::

    cd support/editors/vscode/ord
    npm ci
    npx @vscode/vsce package
    code --install-extension *.vsix

Highlighting needs no configuration and no bundled color theme: the ORD
constructs carry standard TextMate scopes that stock themes already
style (``viewgen`` colors like ``def``, the ``--`` and ``!`` operators
like flow keywords, SI suffixes like CSS units). Every scope keeps an
``.ord``-specific tail, so single constructs can still be re-colored
via ``editor.tokenColorCustomizations`` in ``settings.json``.

tree-sitter (Neovim, Helix)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
      roots = ["pyproject.toml", ".git"]
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
~~~~~~~~~~~~~~~~~~~~~~

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

Language server
---------------

ORDeC installs ``ordec-lsp``, a stdio language server providing diagnostics,
completion, navigation, rename, symbols, and other semantic editor features.
It does not execute ORD code: source files are parsed and analyzed
statically, so opening a project in an editor cannot run its designs.

The server ships with the ``ordec`` Python package, so installing ORDeC into
a Python environment is the entire installation. Verify the command before
configuring an editor::

    pip install -e .
    ordec-lsp

The editor must then be able to find that command:

- **Project virtualenv**: the command lands in ``.venv/bin/`` (Windows:
  ``.venv\Scripts\``), which editors launched from the desktop do not have
  on ``PATH``. Configure the editor with the absolute path to the
  executable, for example ``/path/to/project/.venv/bin/ordec-lsp``. Each
  project then gets the server matching its ORDeC version.
- **Global install**: ``pipx install --editable /path/to/ordec`` (or
  ``pip install --user``) places ``ordec-lsp`` in ``~/.local/bin``, which
  desktop sessions usually have on ``PATH``, so editors find the bare
  command without configuration. On distributions that block global pip
  installs (PEP 668), ``pipx`` is the supported route. A single global
  server analyzes every project against that one ORDeC version.

The server provides document and workspace symbols (nested by cell and
view generator when the editor supports hierarchical symbols),
go-to-definition and go-to-type-definition, hover (markdown with cell
parameter signatures and docstrings when the editor supports it),
references, document highlights, rename, local and member/parameter
completions with documentation, signature help for cell instantiations and
function calls, inferred-type inlay hints, call hierarchy over the cell
instantiation graph, folding and selection ranges, semantic tokens, parser
diagnostics for ORD syntax errors, semantic diagnostics (unresolved imports
and node types, invalid view generator return types, invalid constraint
contexts, unknown members or parameters, schematic ports missing from the
symbol view), and quick fixes for selected diagnostics. Document
synchronization is incremental, with full-document replacement as the
fallback.

The editor subsections below contain the matching launch configurations.
For an editor with generic LSP support that is not covered, configure:

* command: ``ordec-lsp``
* transport: stdio
* file extension: ``*.ord``
* language id: ``ord``
* workspace root: the project directory

The workspace root matters: workspace-wide references and rename follow the
workspace's ORD import graph, so reverse dependencies are only found when
the project directory is the root. While typing incomplete code, the server
keeps the last successful structural analysis and reports syntax errors on
top, so navigation, symbols, and completions stay useful. Saving a file
refreshes diagnostics and cached import data.

Sublime Text
~~~~~~~~~~~~

Install the ``LSP`` package from Package Control and merge this client
entry into ``Packages/User/LSP.sublime-settings``, keeping any other
servers in an existing ``clients`` object. Open the project directory as a
Sublime folder so the server receives the correct workspace root::

    {
      "clients": {
        "ordec-lsp": {
          "command": ["ordec-lsp"],
          "enabled": true,
          "languageId": "ord",
          "scopes": ["source.ord"],
          "syntaxes": ["Packages/User/Ord.sublime-syntax"]
        }
      },
      // Off by default in the LSP package: show the server's
      // inferred-type hints and semantic tokens.
      "show_inlay_hints": true,
      "semantic_highlighting": true
    }

For troubleshooting, the ``LSP: Toggle Log Panel`` command shows the
exchanged JSON-RPC messages.

PyCharm / JetBrains IDEs
~~~~~~~~~~~~~~~~~~~~~~~~

The ORD plugin itself does not launch ORD-LSP: retaining the 2024.2
Community build target excludes the built-in JetBrains LSP module, so that
integration needs a separate compatibility decision.

The LSP4IJ plugin (by Red Hat, available from the JetBrains marketplace)
provides the connection instead and works alongside the ORD plugin's
native highlighting. After installing it, add a user-defined server under
``Settings | Languages & Frameworks | Language Servers``:

* Server: name ``ordec-lsp``, command ``ordec-lsp`` (use the absolute path
  of a project virtualenv executable, as described above)
* Mappings: file name pattern ``*.ord`` with language id ``ord``

The server starts when the first ``.ord`` file opens. For troubleshooting,
the LSP consoles in the Language Servers tool window show the exchanged
JSON-RPC messages.

VS Code
~~~~~~~

The extension starts ``ordec-lsp`` automatically when an ORD file opens. Set
``ord.languageServer.command`` to an absolute path if the executable is not on
the VS Code ``PATH``, or disable it with ``ord.languageServer.enabled``.
Extra command arguments go into ``ord.languageServer.arguments``. For
troubleshooting, ``"ordec-lsp.trace.server": "verbose"`` logs the exchanged
JSON-RPC messages to the ORD Language Server output channel.

Neovim
~~~~~~

With the tree-sitter setup from the syntax highlighting section in place,
the ``.ord`` filetype mapping already exists. Start ORD-LSP from
``init.lua`` using the Neovim 0.11+ ``vim.lsp.config`` API::

    vim.lsp.config("ordec", {
      cmd = { "ordec-lsp" },
      filetypes = { "ord" },
      root_markers = { "pyproject.toml", ".git" },
    })
    vim.lsp.enable("ordec")
    vim.lsp.inlay_hint.enable(true)

Semantic tokens are used automatically. Folding follows tree-sitter as
configured in the syntax highlighting section. To fold via the language
server instead, set ``foldmethod=expr`` with
``foldexpr=v:lua.vim.lsp.foldexpr()``.

Helix
~~~~~

Add the server to the ORD language block created in the syntax
highlighting section of ``~/.config/helix/languages.toml``::

    [[language]]
    # ...the ORD language block from the syntax highlighting section...
    language-servers = ["ordec-lsp"]

    [language-server.ordec-lsp]
    command = "ordec-lsp"

Implementation details
~~~~~~~~~~~~~~~~~~~~~~

The installed ``ordec-lsp`` command starts ``ordec.lsp.server``. The
stdio server uses a method dispatch table: each supported LSP method is
handled by a small ``handle_*`` method, while shared helpers convert
between LSP's zero-based positions and the analysis layer's one-based
positions.

A daemon reader thread frames stdin onto a queue, and a single consumer
dispatches messages in arrival order, so handlers stay synchronous and the
analysis session is only ever touched by one thread. Draining the queue
backlog before dispatching lets ``$/cancelRequest`` cancel still-queued
requests (error ``-32800``) before they are computed and collapses
consecutive ``didChange`` bursts for one document onto a newer
full-document replacement. Incremental changes are never skipped, since
each one builds on the document state left by its predecessor. A request
that is already being handled is never interrupted.

Most language intelligence lives in ``ordec.lsp.analysis``:

* ``model.py`` defines shared positions, ranges, diagnostics, symbols, import
  records, and ``DocumentAnalysis``.
* ``parser_pass.py`` parses ORD source and uses an ``_OrdAnalysisBuilder`` to
  walk the parse tree and collect scopes, bindings, occurrences, imports, ORD
  node contexts, view generator return records, constraint records, and
  inferred-type records for assignment targets.
* ``session.py`` is the public analysis facade. It owns open document snapshots,
  last-good analysis caching, file invalidation, ORD import resolution,
  workspace dependency indexing, and navigation/reference features.
* ``python_index.py`` owns shallow Python module indexing. It resolves Python
  imports, parses Python source with ``ast``, caches module information, and
  exposes exported symbols, class members, docstrings, function signatures,
  and cell parameter defaults without importing or executing workspace
  modules.
* ``completions.py``, ``diagnostics.py``, ``rename.py``, ``signatures.py``,
  ``hierarchy.py``, and ``typeflow.py`` add feature-specific methods to
  ``AnalysisSession`` through mixin classes.

``AnalysisSession`` intentionally remains the API boundary used by the LSP
server and tests. The smaller analysis modules keep implementation details
separated while preserving calls such as ``session.definition(...)``,
``session.completions(...)``, and ``session.python_definition(...)``.

The Python analysis is intentionally lightweight: workspace Python modules
are parsed without executing them, while resolving installed packages may
import parent ``__init__.py`` files through ``importlib.util.find_spec``.
The server is not a full Python type checker, so Python expression types
are inferred only where the ORD analysis can derive useful local
information, and completion and diagnostics may be conservative for complex
Python control flow or dynamic imports. Rename is deliberately restricted
to identifiers and does not rename ORD member accesses such as
``x.member`` or parameter accesses such as ``x.$param``. Workspace-wide
features depend on the editor passing the correct workspace root and on
file watching notifications for changed files.
