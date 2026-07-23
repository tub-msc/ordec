<!--
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: Apache-2.0
-->

# ORD Language Support for VS Code

VS Code extension assets for `.ord` files.

This integration currently provides two layers:

- TextMate-based highlighting and language configuration
- a local-viewer bridge for launching ORDeC on the active `.ord` file

The highlighting layer works on its own. The viewer bridge requires an
installed `ordec` command.

## What It Provides

- syntax highlighting for `.ord` files
- ORD-specific token scopes for declarations and inline constructs
- file association for the `.ord` extension
- language configuration
- VS Code commands for launching and stopping an ORDeC local viewer for the active file
- VS Code command for opening the current ORD view at the cursor in ORDeC
- settings for launching the ORDeC local viewer process
- suggested per-scope color customizations that layer on top of any theme
  (see `Highlight Colors` below)

See the [Editor support](https://ordec.readthedocs.io/en/latest/editor_support.html)
page of the ORDeC documentation for the list of highlighted ORD constructs.

## Repository Layout

Key files in this extension folder:

- `package.json`
- `language-configuration.json`
- `syntaxes/ord.tmLanguage.json`
- `syntaxes/ord-injection.tmLanguage.json`

## Installation

### Option 1: Package As VSIX

From `support/editors/vscode/ord/`:

```bash
npx @vscode/vsce package
code --install-extension *.vsix
```

If you also want the viewer bridge, make sure an `ordec` command is available
on your `PATH`, or configure the viewer command through the extension settings.

### Option 2: Development Mode

1. Open `support/editors/vscode/ord/` in VS Code.
2. Press `F5`.
3. A new Extension Development Host window will open.
4. Open a `.ord` file in that window.

### Option 3: Manual Local Installation

Copy the extension folder into your VS Code extensions directory.

- Linux: `~/.vscode/extensions/ord/`
- macOS: `~/.vscode/extensions/ord/`
- Windows: `%USERPROFILE%\\.vscode\\extensions\\ord\\`

Then restart VS Code.

## Runtime Setup

### Regular ORDeC Installation

For a normal packaged ORDeC installation, the extension should usually work with
minimal configuration:

- install ORDeC so that `ordec` is on your `PATH`
- set `ord.viewer.moduleRoot` to the root directory of your ORD project
- optionally set `ord.viewer.cwd` if ORDeC should start from a different working
  directory than the workspace root

In this setup, the default command setting is typically sufficient:

- `ord.viewer.command = "ordec"`

### Editable / Source Checkout ORDeC Installation

If ORDeC is installed from a source checkout in editable mode, you will usually
need explicit command paths and viewer arguments.

Example settings when the VS Code workspace is the ORDeC source checkout:

```json
{
  "ord.viewer.command": "${workspaceFolder}/.venv/bin/ordec",
  "ord.viewer.args": [
    "-r",
    "${workspaceFolder}/web/dist"
  ],
  "ord.viewer.env": {
    "PYTHONUNBUFFERED": "1"
  }
}
```

If the VS Code workspace is your design project instead of the ORDeC source
checkout, replace `${workspaceFolder}` with the absolute path to the ORDeC
checkout or virtual environment.

Notes for editable installs:

- `ordec` may need `-r /path/to/ordec/web/dist` because `webdist.tar` is not
  bundled in editable mode
- `PYTHONUNBUFFERED=1` can help the viewer bridge see ORDeC's printed launch URL
  immediately

## Highlight Colors

Standard color themes already color ORD code: the ORD scopes are suffixed
variants of common TextMate scopes (`keyword.operator.connect.ord`,
`constant.numeric.suffix.ord`, ...), so prefix matching applies your theme's
generic colors — the connection operator gets normal operator coloring, SI
suffixes get normal number coloring, and so on.

To make ORD-specific constructs visually distinct without switching themes,
add per-scope rules to your `settings.json`. They layer on top of whatever
theme is active:

```jsonc
"editor.tokenColorCustomizations": {
  "textMateRules": [
    // connection operator --
    { "scope": "keyword.operator.connect.ord",
      "settings": { "foreground": "#C586C0", "fontStyle": "bold" } },
    // constrain operator !
    { "scope": "keyword.operator.constrain.ord",
      "settings": { "foreground": "#ff6b6b" } },
    // parameter access .$name
    { "scope": ["keyword.operator.parameter.ord", "punctuation.accessor.dot.ord"],
      "settings": { "foreground": "#ff9e71" } },
    // SI number suffixes (400n, 1.5u)
    { "scope": "constant.numeric.suffix.ord",
      "settings": { "foreground": "#f86aff", "fontStyle": "bold" } },
    // node statement kinds (Nmos n1:) and the anonymous modifier
    { "scope": "storage.type.ord",
      "settings": { "foreground": "#4EC9B0" } },
    { "scope": "storage.modifier.ord",
      "settings": { "foreground": "#C586C0", "fontStyle": "italic" } },
    // .member accesses and node statement targets
    { "scope": "variable.other.member.ord",
      "settings": { "foreground": "#e2c08d" } },
    { "scope": "variable.other.context-target.ord",
      "settings": { "foreground": "#9CDCFE" } }
  ]
}
```

The values above are dark-theme suggestions. Adjust the colors to taste for
light themes.

## Notes

- The shipped highlighting remains TextMate/scope based.
- `ord.tmLanguage.json` is a thin ORDeC wrapper around `source.python`.
- `ord-injection.tmLanguage.json` carries ORD-specific rules adapted from the
  MIT-licensed MagicPython TextMate grammar.
- The viewer bridge launches `ordec --no-browser --module ...`, reads the signed
  local-mode URL from stdout, and opens it in your browser.
- `ORD: Open Current View in ORDeC Viewer` derives view names like
  `Inv().schematic` or `Amp().layout` from the current cursor position.
- The active `.ord` file is saved before launching the viewer, because ORDeC
  local mode reads from the file system.
- The active file must live under `ord.viewer.moduleRoot`, and its relative path
  must map cleanly to a Python-style import path such as `mylib.nmux`.
- The extension is licensed `MIT AND Apache-2.0`, see `LICENSE.md` for the
  complete license texts.

## Troubleshooting

- `webdist.tar not found`
  In editable ORDeC installs, add `-r /path/to/ordec/web/dist` through
  `ord.viewer.args`.

- Viewer process starts but no browser opens
  Set `ord.viewer.env.PYTHONUNBUFFERED = "1"` so the extension can read the
  printed launch URL without waiting for buffered stdout.

## Viewer Settings

The extension contributes the following settings:

- `ord.viewer.command`
- `ord.viewer.args`
- `ord.viewer.cwd`
- `ord.viewer.moduleRoot`
- `ord.viewer.env`
- `ord.viewer.hostname`
- `ord.viewer.port`
- `ord.viewer.urlAuthority`

The viewer settings support `${workspaceFolder}`, `${extensionPath}`,
`${file}`, `${fileDirname}`, `${fileBasename}`, and
`${fileBasenameNoExtension}` placeholders.

## Viewer Commands

- `ORD: Open Active File in ORDeC Viewer`
- `ORD: Open Current View in ORDeC Viewer`
- `ORD: Stop ORDeC Viewer`
- `ORD: Show ORDeC Viewer Output`
