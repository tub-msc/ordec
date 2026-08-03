// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const Module = require("node:module");
const test = require("node:test");

let createdClient;
let stopped = false;

class FakeLanguageClient {
  constructor(id, name, serverOptions, clientOptions) {
    createdClient = { id, name, serverOptions, clientOptions };
  }

  async start() {}

  async stop() {
    stopped = true;
  }
}

const vscode = {
  workspace: {
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
  await extension.activate();

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

test("package manifest wires up the language client", () => {
  const pkg = require("./package.json");

  assert.equal(pkg.main, "./extension.js");
  assert.ok(pkg.activationEvents.includes("onLanguage:ord"));
  assert.ok(pkg.dependencies["vscode-languageclient"]);
  const properties = pkg.contributes.configuration.properties;
  assert.equal(properties["ord.languageServer.command"].default, "ordec-lsp");
  assert.equal(properties["ord.languageServer.enabled"].default, true);
});
