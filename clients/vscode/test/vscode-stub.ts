// The stand-in for the `vscode` module in the client tests. It records each call the client makes, and answers
// with what the test set in `state`.

export type Call = { name: string; args: unknown[] };

export type StubPanel = {
  viewType: string;
  options: unknown;
  documents: string[];
  reveals: number;
  disposed: boolean;
  webview: { html: string; cspSource: string };
  reveal(): void;
  onDidDispose(listener: () => void): { dispose(): void };
  dispose(): void;
};

export const calls: Call[] = [];

export const state = {
  folders: [] as string[],
  pick: (items: readonly string[]): string | undefined => items[0],
  commands: new Map<string, (...args: unknown[]) => unknown>(),
  uriHandlers: [] as { handleUri(uri: unknown): unknown }[],
  panels: [] as StubPanel[],
};

export function reset(): void {
  calls.length = 0;
  state.folders = [];
  state.pick = (items) => items[0];
  state.commands.clear();
  state.uriHandlers.length = 0;
  state.panels.length = 0;
}

export function callsOf(name: string): Call[] {
  return calls.filter((call) => call.name === name);
}

function record(name: string, args: unknown[]): void {
  calls.push({ name, args });
}

const disposable = { dispose(): void {} };

export const ViewColumn = { Active: -1, One: 1 };

export const workspace = {
  get workspaceFolders() {
    return state.folders.length === 0 ? undefined : state.folders.map((fsPath, index) => ({ uri: { fsPath }, name: fsPath, index }));
  },
};

function makePanel(viewType: string, options: unknown): StubPanel {
  const listeners: (() => void)[] = [];
  let html = "";
  const panel: StubPanel = {
    viewType,
    options,
    documents: [],
    reveals: 0,
    disposed: false,
    webview: {
      get html() {
        return html;
      },
      set html(value: string) {
        html = value;
        panel.documents.push(value);
      },
      cspSource: "vscode-webview://stub",
    },
    reveal() {
      record("reveal", []);
      panel.reveals += 1;
    },
    onDidDispose(listener) {
      listeners.push(listener);
      return disposable;
    },
    dispose() {
      panel.disposed = true;
      for (const listener of listeners) listener();
    },
  };
  return panel;
}

export const window = {
  showInformationMessage(...args: unknown[]) {
    record("showInformationMessage", args);
    return Promise.resolve(undefined);
  },
  showWarningMessage(...args: unknown[]) {
    record("showWarningMessage", args);
    return Promise.resolve(undefined);
  },
  showErrorMessage(...args: unknown[]) {
    record("showErrorMessage", args);
    return Promise.resolve(undefined);
  },
  showQuickPick(items: readonly string[], ...rest: unknown[]) {
    record("showQuickPick", [items, ...rest]);
    return Promise.resolve(state.pick(items));
  },
  showOpenDialog(...args: unknown[]) {
    record("showOpenDialog", args);
    return Promise.resolve(undefined);
  },
  showSaveDialog(...args: unknown[]) {
    record("showSaveDialog", args);
    return Promise.resolve(undefined);
  },
  showWorkspaceFolderPick(...args: unknown[]) {
    record("showWorkspaceFolderPick", args);
    return Promise.resolve(undefined);
  },
  createWebviewPanel(viewType: string, title: string, column: unknown, options: unknown) {
    record("createWebviewPanel", [viewType, title, column, options]);
    const panel = makePanel(viewType, options);
    state.panels.push(panel);
    return panel;
  },
  registerUriHandler(handler: { handleUri(uri: unknown): unknown }) {
    record("registerUriHandler", [handler]);
    state.uriHandlers.push(handler);
    return disposable;
  },
};

export const commands = {
  registerCommand(id: string, callback: (...args: unknown[]) => unknown) {
    record("registerCommand", [id]);
    state.commands.set(id, callback);
    return disposable;
  },
};

// Marks this module, so that a test can tell the stub from any other module named `vscode`.
export const isTheStub = true;
