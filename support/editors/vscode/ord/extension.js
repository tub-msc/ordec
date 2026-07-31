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

  const command = config.get("command", "ordec-lsp").trim();
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
      fileEvents: vscode.workspace.createFileSystemWatcher("**/*.ord"),
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
