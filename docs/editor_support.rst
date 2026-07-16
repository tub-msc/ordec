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
ORD-specific rules. All of them are regex/scope based, not parser based, and
the final colors depend on your editor's active color scheme.

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

Licensing
---------

- ORDeC-authored editor assets are licensed under Apache-2.0.
- The PyCharm grammar and the VS Code injection grammar are adapted from the
  MIT-licensed MagicPython Python TextMate grammar. Some VS Code extension
  scaffold files originate from MIT-licensed Microsoft templates. Their
  copyright and ``MIT AND Apache-2.0`` licensing are declared in
  ``REUSE.toml``.
- ``ord.tmbundle`` and the VS Code extension each contain a ``LICENSE.md``
  with the MIT and Apache-2.0 license texts, so the notices travel with these
  artifacts when they are installed or packaged outside the repository.
- ``editors/sublime/Ord.sublime-syntax`` references Sublime Text's built-in
  Python syntax at runtime and does not redistribute it.
