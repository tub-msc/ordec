// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;
let startPromise;

async function startLanguageServer() {
  if (client) {
    return;
  }
  if (startPromise) {
    await startPromise;
    return;
  }

  const config = vscode.workspace.getConfiguration("ord.languageServer");
  if (!config.get("enabled", true)) {
    return;
  }

  // config.get only falls back on undefined, so an explicit null or
  // mistyped setting value must not crash activation.
  const command = String(config.get("command", "ordec-lsp") ?? "").trim();
  const rawArgs = config.get("arguments", []);
  const args = Array.isArray(rawArgs) ? rawArgs.map(String) : [];
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

  const nextClient = new LanguageClient(
    "ordec-lsp",
    "ORD Language Server",
    serverOptions,
    clientOptions
  );
  startPromise = nextClient.start();
  try {
    await startPromise;
    client = nextClient;
  } finally {
    startPromise = undefined;
  }
}

function startLanguageServerWithGuidance() {
  // A missing ordec-lsp executable must not fail activation: syntax
  // highlighting stays useful without the server.
  return startLanguageServer().catch((error) => {
    void vscode.window.showErrorMessage("ORD-LSP failed to start: " + error);
  });
}

async function activate(context) {
  // In Restricted Mode only the declarative features (grammar and
  // language configuration) stay active. The server spawns a workspace
  // configured executable, so it starts only once trust is granted.
  if (!vscode.workspace.isTrusted) {
    context.subscriptions.push(
      vscode.workspace.onDidGrantWorkspaceTrust(() => {
        void startLanguageServerWithGuidance();
      })
    );
    return;
  }
  await startLanguageServerWithGuidance();
}

async function deactivate() {
  if (startPromise) {
    try {
      await startPromise;
    } catch {}
  }

  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = { activate, deactivate };
