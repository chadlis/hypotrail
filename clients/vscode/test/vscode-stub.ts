// The stand-in for the `vscode` module in the client tests. It records each call the client makes, and answers
// with what the test set in `state`.

export type Call = { name: string; args: unknown[] };

export type StubPanel = {
  viewType: string;
  options: unknown;
  documents: string[];
  updates: unknown[];
  visible: boolean;
  reveals: number;
  disposed: boolean;
  webview: { html: string; cspSource: string; postMessage(message: unknown): Promise<boolean>; onDidReceiveMessage(listener: (message: unknown) => void): { dispose(): void } };
  // Sends a message as the document's script would.
  send(message: unknown): void;
  reveal(): void;
  setVisible(visible: boolean): void;
  onDidChangeViewState(listener: (event: { webviewPanel: StubPanel }) => void): { dispose(): void };
  onDidDispose(listener: () => void): { dispose(): void };
  dispose(): void;
};

// A tool registered through `lm.registerTool`, with the disposable the call gave back.
export type RegisteredTool = { name: string; tool: StubTool; disposable: { dispose(): void } };

export type StubTool = {
  invoke(options: { input: unknown; toolInvocationToken: undefined }, token: unknown): Promise<LanguageModelToolResult>;
  prepareInvocation?(options: { input: unknown }, token: unknown): Promise<unknown>;
};

export const calls: Call[] = [];

export const state = {
  folders: [] as string[],
  pick: (items: readonly string[]): string | undefined => items[0],
  informationChoice: undefined as string | undefined,
  commands: new Map<string, (...args: unknown[]) => unknown>(),
  uriHandlers: [] as { handleUri(uri: unknown): unknown }[],
  panels: [] as StubPanel[],
  tools: [] as RegisteredTool[],
  // What `window.showTextDocument` answers: an editor, or a rejection a test sets.
  shown: (): Promise<unknown> => Promise.resolve({}),
};

export function reset(): void {
  calls.length = 0;
  state.folders = [];
  state.pick = (items) => items[0];
  state.informationChoice = undefined;
  state.commands.clear();
  state.uriHandlers.length = 0;
  state.panels.length = 0;
  state.tools.length = 0;
  state.shown = () => Promise.resolve({});
}

export function callsOf(name: string): Call[] {
  return calls.filter((call) => call.name === name);
}

function record(name: string, args: unknown[]): void {
  calls.push({ name, args });
}

const disposable = { dispose(): void {} };

export const ViewColumn = { Active: -1, Beside: -2, One: 1 };

export const Uri = {
  file: (fsPath: string) => ({ scheme: "file", fsPath }),
};

export const workspace = {
  get workspaceFolders() {
    return state.folders.length === 0 ? undefined : state.folders.map((fsPath, index) => ({ uri: { fsPath }, name: fsPath, index }));
  },
};

function makePanel(viewType: string, options: unknown): StubPanel {
  const listeners: (() => void)[] = [];
  const receivers: ((message: unknown) => void)[] = [];
  const viewStates: ((event: { webviewPanel: StubPanel }) => void)[] = [];
  let html = "";
  const panel: StubPanel = {
    viewType,
    options,
    documents: [],
    updates: [],
    visible: true,
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
      async postMessage(message) {
        if (!panel.visible) return false;
        panel.updates.push(message);
        return true;
      },
      onDidReceiveMessage(listener) {
        receivers.push(listener);
        return disposable;
      },
    },
    send(message) {
      for (const receiver of receivers) receiver(message);
    },
    reveal() {
      record("reveal", []);
      panel.reveals += 1;
    },
    setVisible(visible) {
      if (panel.visible === visible) return;
      panel.visible = visible;
      for (const listener of viewStates) listener({ webviewPanel: panel });
    },
    onDidChangeViewState(listener) {
      viewStates.push(listener);
      return disposable;
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
    return Promise.resolve(state.informationChoice);
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
  showTextDocument(...args: unknown[]) {
    record("showTextDocument", args);
    return state.shown();
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
  executeCommand(id: string, ...args: unknown[]) {
    record("executeCommand", [id, ...args]);
    return Promise.resolve(undefined);
  },
};

export const lm = {
  registerTool(name: string, tool: StubTool) {
    record("registerTool", [name]);
    const registered = { name, tool, disposable: { dispose(): void {} } };
    state.tools.push(registered);
    return registered.disposable;
  },
};

export class LanguageModelTextPart {
  constructor(public value: string) {}
}

export class LanguageModelToolResult {
  constructor(public content: LanguageModelTextPart[]) {}
}

// Marks this module, so that a test can tell the stub from any other module named `vscode`.
export const isTheStub = true;
