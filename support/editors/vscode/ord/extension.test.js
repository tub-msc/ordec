// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

let createdClient;
let stopped = false;
let startError;
let errorMessages = [];

class FakeLanguageClient {
  constructor(id, name, serverOptions, clientOptions) {
    createdClient = { id, name, serverOptions, clientOptions };
  }

  async start() {
    if (startError) {
      throw startError;
    }
  }

  async stop() {
    stopped = true;
  }
}

let trustListener;

const vscode = {
  workspace: {
    isTrusted: true,
    onDidGrantWorkspaceTrust(listener) {
      trustListener = listener;
      return { dispose() {} };
    },
    createFileSystemWatcher(pattern) {
      return { pattern };
    },
    getConfiguration(section) {
      assert.equal(section, "ord.languageServer");
      return {
        get(key, fallback) {
          return {
            enabled: true,
            command: "/opt/ordec/bin/ordec-lsp",
            arguments: ["--example"],
          }[key] ?? fallback;
        },
      };
    },
  },
  window: {
    showWarningMessage() {
      throw new Error("unexpected warning");
    },
    showErrorMessage(message) {
      errorMessages.push(message);
    },
  },
};

const load = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "vscode") {
    return vscode;
  }
  if (request === "vscode-languageclient/node") {
    return { LanguageClient: FakeLanguageClient };
  }
  return load.call(this, request, parent, isMain);
};
const extension = require("./extension");
Module._load = load;

test("launches ORD-LSP for ORD documents", async () => {
  await extension.activate({ subscriptions: [] });

  assert.equal(createdClient.id, "ordec-lsp");
  assert.deepEqual(createdClient.serverOptions, {
    command: "/opt/ordec/bin/ordec-lsp",
    args: ["--example"],
  });
  assert.deepEqual(createdClient.clientOptions.documentSelector, [
    { scheme: "file", language: "ord" },
    { scheme: "untitled", language: "ord" },
  ]);
  assert.equal(
    createdClient.clientOptions.synchronize.fileEvents.pattern,
    "**/*.{ord,py}"
  );

  await extension.deactivate();
  assert.equal(stopped, true);
});

test("defers ORD-LSP start until workspace trust is granted", async () => {
  createdClient = undefined;
  vscode.workspace.isTrusted = false;
  const context = { subscriptions: [] };

  await extension.activate(context);
  assert.equal(createdClient, undefined);
  assert.equal(context.subscriptions.length, 1);

  vscode.workspace.isTrusted = true;
  await trustListener();
  assert.equal(createdClient.id, "ordec-lsp");

  await extension.deactivate();
});

test("reports trust-start failures without stopping an unstarted client", async () => {
  createdClient = undefined;
  stopped = false;
  startError = new Error("missing executable");
  errorMessages = [];
  vscode.workspace.isTrusted = false;

  await extension.activate({ subscriptions: [] });
  vscode.workspace.isTrusted = true;
  trustListener();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(errorMessages, [
    "ORD-LSP failed to start: Error: missing executable",
  ]);
  await extension.deactivate();
  assert.equal(stopped, false);

  startError = undefined;
  vscode.workspace.isTrusted = true;
});

test("package manifest wires up the language client", () => {
  const pkg = require("./package.json");

  assert.equal(pkg.main, "./extension.js");
  assert.ok(pkg.activationEvents.includes("onLanguage:ord"));
  assert.ok(pkg.dependencies["vscode-languageclient"]);
  const properties = pkg.contributes.configuration.properties;
  assert.equal(properties["ord.languageServer.command"].default, "ordec-lsp");
  assert.equal(properties["ord.languageServer.enabled"].default, true);

  // Restricted Mode must keep the grammar active and pin the server
  // command settings to trusted user level values.
  const untrusted = pkg.capabilities.untrustedWorkspaces;
  assert.equal(untrusted.supported, "limited");
  assert.deepEqual(untrusted.restrictedConfigurations, [
    "ord.languageServer.command",
    "ord.languageServer.arguments",
  ]);
});
