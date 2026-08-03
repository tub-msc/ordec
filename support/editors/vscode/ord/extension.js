// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;

async function activate() {
  const config = vscode.workspace.getConfiguration("ord.languageServer");
  if (!config.get("enabled", true)) {
    return;
  }

  // config.get only falls back on undefined, so an explicit null or
  // non-string setting value must not crash activation.
  const command = String(config.get("command", "ordec-lsp") ?? "").trim();
  const args = config.get("arguments", []);
  if (!command) {
    void vscode.window.showWarningMessage(
      "ORD-LSP is enabled, but ord.languageServer.command is empty."
    );
    return;
  }

  const serverOptions = {
    command,
    args,
  };
  const clientOptions = {
    documentSelector: [
      { scheme: "file", language: "ord" },
      { scheme: "untitled", language: "ord" },
    ],
    synchronize: {
      // .py is watched because ORD imports Python modules, whose edits
      // must invalidate the server's Python module index.
      fileEvents: vscode.workspace.createFileSystemWatcher("**/*.{ord,py}"),
    },
  };

  client = new LanguageClient(
    "ordec-lsp",
    "ORD Language Server",
    serverOptions,
    clientOptions
  );
  await client.start();
}

async function deactivate() {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = { activate, deactivate };
