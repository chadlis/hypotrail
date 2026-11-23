// The one webview panel of the extension. It holds in memory only, for as long as it is open, the target it was
// opened on, the last object a read gave back with `success`, and whether a call is in flight; it reads the Study
// through the bridge when it is opened and on the control "Read again", and at no other time.
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, readStudy } from "./bridge";
import { bodyOf, type View } from "./content";

export type Target = { study: string; decision?: string };

// The checkout that holds this extension: its compiled sources sit in `out/src/` of the extension's folder.
const ROOT = checkoutRoot(path.resolve(__dirname, "..", ".."));

let panel: vscode.WebviewPanel | undefined;
let target: Target | undefined;
let held: Record<string, unknown> | undefined;
let inFlight = false;

export function openPanel(next: Target): void {
  if (panel && inFlight) {
    panel.reveal();
    return;
  }
  target = next;
  held = undefined;
  if (panel) {
    panel.reveal();
  } else {
    panel = vscode.window.createWebviewPanel("hypotrail.study", "Hypotrail", vscode.ViewColumn.Active, panelOptions());
    panel.webview.onDidReceiveMessage(receive);
    panel.onDidDispose(() => {
      panel = undefined;
      target = undefined;
      held = undefined;
      inFlight = false;
    });
  }
  void read();
}

function receive(message: unknown): void {
  if (inFlight || !panel) return;
  if ((message as { message?: unknown } | null)?.message === contract.read_again_message) void read();
}

async function read(): Promise<void> {
  const opened = panel!;
  const study = target!.study;
  inFlight = true;
  show({ reading: true, object: held, decision: target!.decision });
  const outcome = await readStudy(ROOT, study);
  if (panel !== opened) return;
  inFlight = false;
  held = outcome.outcome === "success" ? outcome.object : undefined;
  show({ reading: false, object: held, failure: outcome.outcome === "success" ? undefined : outcome, decision: target!.decision });
}

function show(view: View): void {
  panel!.webview.html = documentFor(newNonce(), view);
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

// The document's script: each control sends the fixed message its attribute names, and nothing else; the view
// scrolls to the Decision a link names.
const SCRIPT = [
  '"use strict";',
  "const api = acquireVsCodeApi();",
  'for (const control of document.querySelectorAll("button[data-message]")) {',
  '  control.addEventListener("click", () => api.postMessage({ message: control.getAttribute("data-message") }));',
  "}",
  'document.querySelector("[data-linked]")?.scrollIntoView();',
].join("\n");

// Every document the client gives to a webview is built here.
function documentFor(nonce: string, view: View): string {
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
    `<main id="study">${bodyOf(view)}</main>`,
    `<script nonce="${nonce}">${SCRIPT}</script>`,
    "</body>",
    "</html>",
  ].join("\n");
}
