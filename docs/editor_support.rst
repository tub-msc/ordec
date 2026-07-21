Editor support
==============

The ``editors/`` directory of the ORDeC repository contains syntax
highlighting packages for ``.ord`` files, so ORDeC designs can be edited in a
regular IDE alongside the browser-based viewer.

ORD is syntactically close to Python, but adds its own constructs, such as:

- ``cell`` declarations
- ``viewgen`` declarations (``viewgen schematic -> Schematic:``)
- node statements like ``output y:``, ``Nmos m1:``, or ``Series(gap=4) core:``
- ``anonymous`` node statements and bodyless forms like ``Net vdd``
- ``path`` and ``net`` statements
- the connection operator ``--`` and the constrain operator ``!``
- parameter access like ``.$l`` and SI-suffixed numbers like ``100n``

The highlighting packages extend each editor's Python support with these
ORD-specific rules. The Sublime, PyCharm and VS Code packages are
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

``editors/pycharm/`` provides a TextMate bundle that works in PyCharm and
other JetBrains IDEs with TextMate support (IntelliJ IDEA, CLion, WebStorm,
GoLand, ...). It provides syntax highlighting for ORD without requiring a
custom JetBrains plugin.

1. Open the IDE settings (Linux/Windows: ``Ctrl+Alt+S``, macOS: ``Cmd+,``).
2. Go to ``Editor > TextMate Bundles``.
3. Click ``+`` and select the ``editors/pycharm/ord.tmbundle`` directory
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

tree-sitter (Neovim, Emacs, Helix, Zed, Pulsar)
-----------------------------------------------

``editors/tree-sitter-ord/`` provides a tree-sitter grammar for ORD — a real
parser, in contrast to the regex-based packages above. tree-sitter was
originally developed for GitHub's Atom editor and today powers highlighting
in Atom's community successor Pulsar as well as in Neovim, Emacs 29+, Helix,
Zed and other tree-sitter-based editors.

The parser sources are generated from ``grammar.js``. Generate them once
before installing the grammar into an editor (this requires Node.js)::

    cd editors/tree-sitter-ord
    npm ci
    npm run generate

Then install the grammar in your editor:

- **Emacs 29+**: build the shared library and place it in
  ``~/.emacs.d/tree-sitter/``::

      cc -fPIC -shared -I src src/parser.c src/scanner.c \
          -o libtree-sitter-ord.so

  ``queries/highlights-emacs.scm`` contains the Emacs highlight rules,
  ready for use with ``treesit-font-lock-rules``.
- **Neovim**: register the grammar with nvim-treesitter as a custom parser
  (repository URL plus ``location = "editors/tree-sitter-ord"``,
  ``requires_generate_from_grammar = true`` and
  ``generate_requires_npm = true`` in ``install_info``) and copy the
  ``queries/`` files into a ``queries/ord/`` runtime directory.
- **Helix, Zed, Pulsar**: point the editor's grammar source at this
  repository subdirectory. ``queries/highlights.scm`` is the generic
  highlight query, and ``folds.scm``, ``locals.scm`` and ``tags.scm``
  provide folding, scopes and symbol tags.

For working on the grammar itself, see
``editors/tree-sitter-ord/README.md``.

Licensing
---------

The editor packages are free software. ORDeC-authored files are licensed
under Apache-2.0. The PyCharm and VS Code grammars are adapted from the
MIT-licensed MagicPython grammar, and the tree-sitter grammar is derived
from the MIT-licensed tree-sitter-python grammar. Files containing such
upstream material are licensed ``MIT AND Apache-2.0``.

Each installable package — ``ord.tmbundle``, the VS Code extension and
``tree-sitter-ord`` — includes a ``LICENSE.md`` with the complete license
texts. The Sublime syntax uses Sublime Text's built-in Python syntax at
runtime and does not redistribute it.
