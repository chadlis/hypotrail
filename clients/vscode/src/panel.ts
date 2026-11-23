// The one webview panel of the extension. It holds the target it was opened on in memory only, for as long as it is
// open; its document carries the content security policy of contract.json and nothing of a Study yet.
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import contract from "../contract.json";

export type Target = { study: string; decision?: string };

let panel: vscode.WebviewPanel | undefined;
let target: Target | undefined;

export function openPanel(next: Target): void {
  target = next;
  if (panel) {
    panel.reveal();
  } else {
    panel = vscode.window.createWebviewPanel("hypotrail.study", "Hypotrail", vscode.ViewColumn.Active, panelOptions());
    panel.onDidDispose(() => {
      panel = undefined;
      target = undefined;
    });
  }
  panel.webview.html = documentFor(newNonce());
}

// Each entry of `panel_options` is `name=value`, the value written as JSON.
function panelOptions(): vscode.WebviewPanelOptions & vscode.WebviewOptions {
  return Object.fromEntries(
    contract.panel_options.map((entry) => {
      const at = entry.indexOf("=");
      return [entry.slice(0, at), JSON.parse(entry.slice(at + 1))];
    }),
  );
}

// Letters and digits only, new for each document.
function newNonce(): string {
  return randomBytes(16).toString("hex");
}

// Every document the client gives to a webview is built here.
function documentFor(nonce: string): string {
  const policy = contract.csp_directives.map((directive) => directive.replace("{nonce}", nonce)).join("; ");
  return [
    "<!doctype html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${policy}">`,
    "<title>Hypotrail</title>",
    `<style nonce="${nonce}">body { color: var(--vscode-foreground); background: var(--vscode-editor-background); font-family: var(--vscode-font-family); }</style>`,
    "</head>",
    "<body>",
    '<main id="study"></main>',
    `<script nonce="${nonce}">"use strict";</script>`,
    "</body>",
    "</html>",
  ].join("\n");
}
