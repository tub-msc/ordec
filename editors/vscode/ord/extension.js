// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const path = require("path");
const { spawn } = require("child_process");
const vscode = require("vscode");

const LANGUAGE_ID = "ord";
const VIEWER_NAME = "ORDeC Viewer";

let viewerOutputChannel;
let viewerProcess;
let viewerLaunchKey;
let viewerStartPromise;
let viewerUrl;
let viewerStopRequested = false;

function activate(context) {
  viewerOutputChannel = vscode.window.createOutputChannel(VIEWER_NAME);
  context.subscriptions.push(viewerOutputChannel);

  context.subscriptions.push(
    vscode.commands.registerCommand("ord.openViewerForActiveFile", async () => {
      await openViewerForActiveFile(context);
    }),
    vscode.commands.registerCommand("ord.openViewerForCurrentView", async () => {
      await openViewerForCurrentView(context);
    }),
    vscode.commands.registerCommand("ord.stopViewer", async () => {
      await stopViewer(true);
    }),
    vscode.commands.registerCommand("ord.showViewerOutput", () => {
      viewerOutputChannel.show(true);
    }),
    vscode.workspace.onDidChangeConfiguration(event => {
      if (event.affectsConfiguration("ord.viewer")) {
        void stopViewer(false);
      }
    })
  );
}

async function deactivate() {
  await stopViewer(false);
}

async function openViewerForActiveFile(context) {
  await openViewer(context, false);
}

async function openViewerForCurrentView(context) {
  await openViewer(context, true);
}

async function openViewer(context, preferCurrentView) {
  const document = getActiveOrdDocument();
  if (!document) {
    return;
  }

  if (document.isDirty) {
    const saved = await document.save();
    if (!saved) {
      void vscode.window.showWarningMessage("Save the ORD file before opening it in ORDeC.");
      return;
    }
  }

  let launch;
  try {
    let viewName = null;
    if (preferCurrentView) {
      viewName = resolveCurrentViewName(
        document,
        vscode.window.activeTextEditor?.selection.active || new vscode.Position(0, 0)
      );
      if (!viewName) {
        void vscode.window.showWarningMessage(
          "No enclosing ORD view found at the cursor. Opening the module instead."
        );
      }
    }

    launch = createViewerLaunch(context, document, viewName);
  } catch (error) {
    void vscode.window.showWarningMessage(formatError(error));
    return;
  }

  try {
    const url = await ensureViewer(launch);
    await vscode.env.openExternal(vscode.Uri.parse(url));
  } catch (error) {
    const message = formatError(error);
    viewerOutputChannel.appendLine(`Failed to start ${VIEWER_NAME}: ${message}`);
    viewerOutputChannel.show(true);
    void vscode.window.showWarningMessage(
      `Failed to start ORDeC viewer. See '${VIEWER_NAME}' output for details.`
    );
  }
}

function getActiveOrdDocument() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== LANGUAGE_ID || editor.document.uri.scheme !== "file") {
    void vscode.window.showWarningMessage("Open a local ORD file to use the ORDeC viewer.");
    return null;
  }

  return editor.document;
}

function createViewerLaunch(context, document, viewName) {
  const config = vscode.workspace.getConfiguration("ord");
  const moduleName = resolveViewerModuleName(config, context, document);
  const moduleSpec = viewName ? `${moduleName}:${viewName}` : moduleName;
  const moduleRoot = resolveTemplate(
    config.get("viewer.moduleRoot", "${workspaceFolder}"),
    context,
    document
  );
  const cwd = resolveTemplate(
    config.get("viewer.cwd", "${workspaceFolder}"),
    context,
    document
  ) || moduleRoot;
  const command = resolveTemplate(
    config.get("viewer.command", "ordec"),
    context,
    document
  );
  const args = config
    .get("viewer.args", [])
    .map(arg => resolveTemplate(arg, context, document));
  const hostname = config.get("viewer.hostname", "127.0.0.1");
  const port = String(config.get("viewer.port", 8100));
  const urlAuthority = resolveTemplate(
    config.get("viewer.urlAuthority", ""),
    context,
    document
  );
  const envOverrides = config.get("viewer.env", {});

  args.push("--no-browser", "--hostname", hostname, "--port", port, "--module", moduleSpec);
  if (urlAuthority) {
    args.push("--url-authority", urlAuthority);
  }

  return {
    command,
    args,
    options: {
      cwd,
      env: {
        ...process.env,
        ...resolveEnv(envOverrides, context, document),
      },
    },
    key: JSON.stringify({
      command,
      args,
      cwd,
      file: document.uri.fsPath,
      viewName,
    }),
  };
}

function resolveViewerModuleName(config, context, document) {
  const moduleRoot = resolveTemplate(
    config.get("viewer.moduleRoot", "${workspaceFolder}"),
    context,
    document
  );
  if (!moduleRoot) {
    throw new Error("ORD viewer module root is empty.");
  }

  const relativePath = path.relative(moduleRoot, document.uri.fsPath);
  if (
    relativePath === "" ||
    relativePath.startsWith("..") ||
    path.isAbsolute(relativePath)
  ) {
    throw new Error("The ORD file must be inside ord.viewer.moduleRoot.");
  }

  const parsedPath = path.parse(relativePath);
  if (parsedPath.ext !== ".ord") {
    throw new Error("The ORDeC viewer command only supports .ord files.");
  }

  const segments = relativePath.split(path.sep);
  segments[segments.length - 1] = parsedPath.name;
  if (segments[segments.length - 1] === "__init__") {
    segments.pop();
  }

  if (segments.length === 0) {
    throw new Error("Could not derive a Python module name from the active ORD file.");
  }

  for (const segment of segments) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(segment)) {
      throw new Error(
        `Cannot derive an importable module name from '${relativePath}'.`
      );
    }
  }

  return segments.join(".");
}

function resolveCurrentViewName(document, position) {
  let cellName = null;
  let cellIndent = -1;
  let viewName = null;
  let viewIndent = -1;
  let generatedViewName = null;
  let generatedViewIndent = -1;
  let pendingGenerateIndent = null;

  for (let lineNumber = 0; lineNumber <= position.line; lineNumber += 1) {
    const text = document.lineAt(lineNumber).text;
    const trimmed = text.trim();
    const indent = text.length - text.trimStart().length;

    if (trimmed !== "") {
      if (generatedViewName && indent <= generatedViewIndent) {
        generatedViewName = null;
        generatedViewIndent = -1;
      }
      if (viewName && indent <= viewIndent) {
        viewName = null;
        viewIndent = -1;
      }
      if (cellName && indent <= cellIndent) {
        cellName = null;
        cellIndent = -1;
        viewName = null;
        viewIndent = -1;
        generatedViewName = null;
        generatedViewIndent = -1;
      }
    }

    if (trimmed === "" || trimmed.startsWith("#")) {
      continue;
    }

    const cellMatch = text.match(/^(\s*)cell\s+([A-Za-z_][A-Za-z0-9_]*)\b/);
    if (cellMatch) {
      cellName = cellMatch[2];
      cellIndent = cellMatch[1].length;
      viewName = null;
      viewIndent = -1;
      generatedViewName = null;
      generatedViewIndent = -1;
      pendingGenerateIndent = null;
      continue;
    }

    const decoratorMatch = text.match(/^(\s*)@generate(_func)?\b/);
    if (decoratorMatch) {
      pendingGenerateIndent = decoratorMatch[1].length;
      continue;
    }

    const viewgenMatch = text.match(/^(\s*)viewgen\s+([A-Za-z_][A-Za-z0-9_]*)\b/);
    if (cellName && viewgenMatch && viewgenMatch[1].length > cellIndent) {
      viewName = viewgenMatch[2];
      viewIndent = viewgenMatch[1].length;
      generatedViewName = null;
      generatedViewIndent = -1;
      pendingGenerateIndent = null;
      continue;
    }

    const defMatch = text.match(/^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\b/);
    if (defMatch && pendingGenerateIndent !== null && defMatch[1].length === pendingGenerateIndent) {
      if (cellName && defMatch[1].length > cellIndent) {
        generatedViewName = `${cellName}().${defMatch[2]}`;
        generatedViewIndent = defMatch[1].length;
      } else if (!cellName && pendingGenerateIndent === 0) {
        generatedViewName = `${defMatch[2]}()`;
        generatedViewIndent = 0;
      }
      pendingGenerateIndent = null;
      continue;
    }

    pendingGenerateIndent = null;
  }

  if (generatedViewName) {
    return generatedViewName;
  }
  if (cellName && viewName) {
    return `${cellName}().${viewName}`;
  }
  return null;
}

async function ensureViewer(launch) {
  if (viewerProcess && viewerLaunchKey === launch.key) {
    return viewerStartPromise;
  }

  await stopViewer(false);

  viewerOutputChannel.appendLine(
    `Starting ${VIEWER_NAME}: ${launch.command} ${launch.args.join(" ")}`
  );

  viewerLaunchKey = launch.key;
  viewerUrl = undefined;
  viewerStopRequested = false;

  viewerStartPromise = new Promise((resolve, reject) => {
    let resolved = false;
    let stdoutBuffer = "";

    viewerProcess = spawn(launch.command, launch.args, launch.options);

    viewerProcess.stdout.on("data", chunk => {
      const text = chunk.toString();
      viewerOutputChannel.append(text);
      stdoutBuffer += text;

      const match = stdoutBuffer.match(/To start ORDeC, navigate to:\s*(\S+)/);
      if (!match || resolved) {
        return;
      }

      viewerUrl = match[1];
      resolved = true;
      resolve(viewerUrl);
    });

    viewerProcess.stderr.on("data", chunk => {
      viewerOutputChannel.append(chunk.toString());
    });

    viewerProcess.on("error", error => {
      if (resolved) {
        return;
      }

      resolved = true;
      reject(error);
    });

    viewerProcess.on("exit", (code, signal) => {
      const stoppedProcess = viewerProcess;
      viewerProcess = undefined;
      viewerLaunchKey = undefined;
      viewerStartPromise = undefined;
      viewerUrl = undefined;

      if (viewerStopRequested) {
        viewerStopRequested = false;
        return;
      }

      viewerOutputChannel.appendLine(
        `${VIEWER_NAME} exited${code !== null ? ` with code ${code}` : ""}${signal ? ` (${signal})` : ""}.`
      );

      if (resolved) {
        return;
      }

      resolved = true;
      if (stoppedProcess) {
        reject(new Error(`${VIEWER_NAME} exited before publishing its launch URL.`));
      }
    });
  });

  return viewerStartPromise;
}

async function stopViewer(userInitiated) {
  if (!viewerProcess) {
    if (userInitiated) {
      void vscode.window.showInformationMessage("ORDeC viewer is not running.");
    }
    return;
  }

  const activeProcess = viewerProcess;
  viewerStopRequested = true;
  const stopped = new Promise(resolve => {
    activeProcess.once("exit", () => resolve());
  });
  activeProcess.kill();
  await stopped;

  if (userInitiated) {
    void vscode.window.showInformationMessage("ORDeC viewer stopped.");
  }
}

function resolveEnv(envOverrides, context, document) {
  const resolved = {};
  for (const [key, value] of Object.entries(envOverrides)) {
    resolved[key] = resolveTemplate(String(value), context, document);
  }
  return resolved;
}

function resolveTemplate(value, context, document) {
  const folder = document
    ? vscode.workspace.getWorkspaceFolder(document.uri) || vscode.workspace.workspaceFolders?.[0]
    : vscode.workspace.workspaceFolders?.[0];
  const workspaceFolder = folder ? folder.uri.fsPath : "";
  const workspaceFolderBasename = folder ? folder.name : "";
  const file = document ? document.uri.fsPath : "";
  const fileBasename = file ? path.basename(file) : "";
  const fileBasenameNoExtension = fileBasename ? path.parse(fileBasename).name : "";
  const fileDirname = file ? path.dirname(file) : "";

  return String(value)
    .replaceAll("${workspaceFolder}", workspaceFolder)
    .replaceAll("${workspaceFolderBasename}", workspaceFolderBasename)
    .replaceAll("${extensionPath}", context.extensionPath)
    .replaceAll("${file}", file)
    .replaceAll("${fileBasename}", fileBasename)
    .replaceAll("${fileBasenameNoExtension}", fileBasenameNoExtension)
    .replaceAll("${fileDirname}", fileDirname);
}

function formatError(error) {
  if (error instanceof Error) {
    return error.stack || error.message;
  }
  return String(error);
}

module.exports = {
  activate,
  deactivate,
};
