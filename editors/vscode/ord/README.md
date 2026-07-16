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
- an optional ORD-specific dark theme

See the [Editor support](https://ordec.readthedocs.io/en/latest/editor_support.html)
page of the ORDeC documentation for the list of highlighted ORD constructs.

## Repository Layout

Key files in this extension folder:

- `package.json`
- `language-configuration.json`
- `syntaxes/ord.tmLanguage.json`
- `syntaxes/ord-injection.tmLanguage.json`
- `themes/ord-color-theme.json`

## Installation

### Option 1: Package As VSIX

From `editors/vscode/ord/`:

```bash
npx @vscode/vsce package
code --install-extension *.vsix
```

If you also want the viewer bridge, make sure an `ordec` command is available
on your `PATH`, or configure the viewer command through the extension settings.

### Option 2: Development Mode

1. Open `editors/vscode/ord/` in VS Code.
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

## Theme

The extension includes an optional ORD-specific dark theme.

To enable it:

1. open the command palette
2. run `Preferences: Color Theme`
3. select the ORD theme

## Notes

- The shipped highlighting remains TextMate/scope based.
- `ord.tmLanguage.json` is a thin ORDeC wrapper around `source.python`.
- `ord-injection.tmLanguage.json` carries ORD-specific rules adapted from the
  JetBrains/MagicPython-derived TextMate grammar in this repository.
- The viewer bridge launches `ordec --no-browser --module ...`, reads the signed
  local-mode URL from stdout, and opens it in your browser.
- `ORD: Open Current View in ORDeC Viewer` derives view names like
  `Inv().schematic` or `Amp().layout` from the current cursor position.
- The active `.ord` file is saved before launching the viewer, because ORDeC
  local mode reads from the file system.
- The active file must live under `ord.viewer.moduleRoot`, and its relative path
  must map cleanly to a Python-style import path such as `mylib.nmux`.
- `LICENSE.md` documents the package's redistribution obligations and contains
  the MIT and Apache-2.0 license texts.

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
