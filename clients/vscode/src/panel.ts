// The one webview panel of the extension. It holds in memory only, for as long as it is open, the target it was
// opened on, the last object a read gave back with `success`, the arguments of a write that got no answer until that
// call is answered, and whether a call is in flight. It reads the Study through the bridge when it is opened, after
// each write the CLI answered and on the control "Read again", and at no other time; it writes only through
// `recordDecision`, on the control that records and on "Send again".
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, newRequestId, readStudy, recordDecision, type DecisionInput, type Outcome } from "./bridge";
import { bodyOf, type View } from "./content";

export type Target = { study: string; decision?: string };

// What the document's script posts: the name of a message and, for the control that records, the indexes of the
// pending decision and of the option selected.
type Message = { message?: unknown; pending?: unknown; option?: unknown };

// The checkout that holds this extension: its compiled sources sit in `out/src/` of the extension's folder.
const ROOT = checkoutRoot(path.resolve(__dirname, "..", ".."));

let panel: vscode.WebviewPanel | undefined;
let target: Target | undefined;
let held: Record<string, unknown> | undefined;
let unanswered: DecisionInput | undefined;
let inFlight = false;

export function openPanel(next: Target): void {
  if (panel && (inFlight || unanswered)) {
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
      unanswered = undefined;
      inFlight = false;
    });
  }
  void read();
}

// The handler of each message the document's script posts, by the message's name.
export const HANDLERS: Record<string, (message: Message) => void> = {
  [contract.messages[0]]: () => void read(),
  [contract.messages[1]]: (message) => record(message),
  [contract.messages[2]]: () => {
    if (unanswered) void write(unanswered);
  },
};

function receive(message: unknown): void {
  if (inFlight || !panel) return;
  const name = (message as Message | null)?.message;
  if (typeof name === "string" && Object.hasOwn(HANDLERS, name)) HANDLERS[name](message as Message);
}

const entries = (content: unknown): Record<string, unknown>[] => (Array.isArray(content) ? content : []);
const at = (list: Record<string, unknown>[], index: unknown) => (Number.isInteger(index) ? list[index as number] : undefined);

// The second action: the extension resolves the indexes it is sent in the object it holds.
function record(message: Message): void {
  if (unanswered || !held) return;
  const pending = at(entries(held.pending_decisions), message.pending);
  const option = at(entries(pending?.options), message.option);
  if (!pending || !option) return;
  void write({
    question: (pending.question as { text?: unknown } | undefined)?.text as string,
    option: option.text as string,
    author: contract.decide_author,
    cited_ids: [pending.comparison_id as string],
    request_id: newRequestId(),
    read_sequence: held.write_sequence as number,
  });
}

async function write(input: DecisionInput): Promise<void> {
  const opened = panel!;
  inFlight = true;
  show({ reading: false, writing: true, object: held, unanswered: unanswered !== undefined, decision: target!.decision, study: target!.study });
  const outcome = await recordDecision(ROOT, target!.study, input);
  if (panel !== opened) return;
  inFlight = false;
  unanswered = outcome.outcome === "no_answer" ? input : undefined;
  if (outcome.outcome === "no_answer" || outcome.outcome === "client_refusal") {
    show({ reading: false, object: held, written: outcome, unanswered: unanswered !== undefined, decision: target!.decision, study: target!.study });
  } else {
    await read(outcome);
  }
}

// `written` is the answer of the write this read follows, if any.
async function read(written?: Outcome): Promise<void> {
  const opened = panel!;
  const study = target!.study;
  inFlight = true;
  show({ reading: true, object: held, unanswered: unanswered !== undefined, decision: target!.decision, study });
  const outcome = await readStudy(ROOT, study);
  if (panel !== opened) return;
  inFlight = false;
  held = outcome.outcome === "success" ? outcome.object : undefined;
  const failure = outcome.outcome === "success" ? undefined : outcome;
  show({ reading: false, object: held, failure, written, unanswered: unanswered !== undefined, decision: target!.decision, study });
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

// The document's script: each control sends the message its attribute names, and the control that records sends with
// it the indexes of its pending decision and of the option selected there; selecting an option makes that control
// active. The view scrolls to the Decision a link names, and to the Decision a write recorded, whose notice takes the focus.
const SCRIPT = [
  '"use strict";',
  "const api = acquireVsCodeApi();",
  'for (const control of document.querySelectorAll("button[data-message]")) {',
  '  control.addEventListener("click", () => {',
  '    const message = { message: control.getAttribute("data-message") };',
  '    const pending = control.getAttribute("data-pending");',
  "    if (pending !== null) {",
  "      const chosen = document.querySelector(`input[data-pending=\"${pending}\"]:checked`);",
  "      if (chosen === null) return;",
  "      message.pending = Number(pending);",
  '      message.option = Number(chosen.getAttribute("data-option"));',
  "    }",
  "    api.postMessage(message);",
  "  });",
  "}",
  'for (const choice of document.querySelectorAll("input[data-option]")) {',
  '  choice.addEventListener("change", () => {',
  '    const control = document.querySelector(`button[data-pending=\"${choice.getAttribute("data-pending")}\"]`);',
  "    if (control !== null) control.disabled = false;",
  "  });",
  "}",
  'document.querySelector("[data-linked]")?.scrollIntoView();',
  'const recorded = document.querySelector("a[data-recorded]");',
  "if (recorded !== null) {",
  '  document.querySelector(recorded.getAttribute("href"))?.scrollIntoView();',
  '  document.querySelector(\'[data-element="notice"]\')?.focus({ preventScroll: true });',
  "}",
].join("\n");

// The document's style. Every colour it sets is a theme variable of VS Code, or `transparent` where a High Contrast theme
// defines a border the others leave out; its margins are small, so that at 420 px the question and the first evidence number
// stand near the top of the panel. VS Code marks the body of a webview with the class of its theme's kind, which sets the
// scheme the radio inputs are drawn in.
const STYLE = [
  "body.vscode-dark, body.vscode-high-contrast:not(.vscode-high-contrast-light) { color-scheme: dark; }",
  "body { color: var(--vscode-foreground); background: var(--vscode-editor-background); font-family: var(--vscode-font-family); line-height: 1.4; }",
  "main { max-width: 46em; overflow-wrap: anywhere; }",
  "h1 { font-size: 0.9em; font-weight: normal; margin: 0.4em 0; color: var(--vscode-descriptionForeground); overflow-wrap: anywhere; }",
  "h2 { font-size: 0.8em; letter-spacing: 0.06em; text-transform: uppercase; color: var(--vscode-descriptionForeground); margin: 0.9em 0 0.3em; padding-bottom: 0.15em; border-bottom: 1px solid var(--vscode-panel-border); }",
  "h3 { font-size: 1.08em; margin: 0.3em 0 0.2em; }",
  "h4 { font-size: 0.85em; color: var(--vscode-descriptionForeground); margin: 0.5em 0 0.1em; }",
  "p, ul { margin: 0.2em 0; }",
  "ul { padding-left: 1.2em; }",
  "button { font: inherit; padding: 0.2em 0.8em; color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: 1px solid var(--vscode-contrastBorder, transparent); border-radius: 2px; cursor: pointer; }",
  "button:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }",
  "button:disabled { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); opacity: 0.6; cursor: default; }",
  ":focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 2px; }",
  'input[type="radio"] { accent-color: var(--vscode-button-background); margin: 0.2em 0 0; }',
  '[data-element="notice"], [data-element="failure"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--vscode-focusBorder); background: var(--vscode-textBlockQuote-background); }',
  '[data-element="failure"] { border-left-color: var(--vscode-inputValidation-errorBorder); }',
  '[data-element="unknown"] { font-weight: 600; }',
  '[data-element="unknown"]::first-letter { text-transform: uppercase; }',
  '[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.4em 0; }',
  'div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"] { font-size: 0.9em; color: var(--vscode-descriptionForeground); }',
  '[data-element="delta"] a[data-kind="delta"] { font-size: 1.25em; font-weight: 600; }',
  "hr { border: 0; border-top: 1px solid var(--vscode-panel-border); margin: 1em 0 0.6em; }",
  "fieldset { margin: 0.5em 0; padding: 0.3em 0.5em 0.5em; border: 1px solid var(--vscode-panel-border); border-radius: 4px; }",
  "label { display: grid; grid-template-columns: auto 1fr; column-gap: 0.5em; padding: 0.3em; border-radius: 3px; cursor: pointer; }",
  "label:hover { background: var(--vscode-list-hoverBackground); }",
  "label:has(input:checked) { background: var(--vscode-list-inactiveSelectionBackground); }",
  "label:has(input:disabled) { cursor: default; opacity: 0.7; }",
  "label input { grid-row: 1 / span 2; }",
  "label small { grid-column: 2; font-size: 0.92em; color: var(--vscode-descriptionForeground); }",
  "fieldset button { margin-top: 0.4em; }",
  "[data-chart] { margin: 0.4em 0; }",
  "li[data-chart] { list-style: none; }",
  "[data-bar] { display: grid; grid-template-columns: 6.5em minmax(3em, 1fr) auto; align-items: center; column-gap: 0.5em; margin: 0.15em 0; }",
  "[data-bar] svg { display: block; width: 100%; height: 0.75em; background: var(--vscode-editorWidget-background); }",
  "rect { stroke: var(--vscode-contrastBorder, transparent); vector-effect: non-scaling-stroke; }",
  "rect.control { fill: var(--vscode-charts-blue); }",
  "rect.candidate { fill: var(--vscode-charts-orange); }",
  "rect.scored-control { fill: var(--vscode-charts-blue); }",
  "rect.scored-candidate { fill: var(--vscode-charts-orange); }",
  "rect.rest { fill: transparent; stroke: var(--vscode-charts-lines); stroke-dasharray: 2 2; }",
  "rect.cited { fill: var(--vscode-charts-lines); }",
  "rect.latest { fill: var(--vscode-charts-foreground); }",
  'section[data-part="decision"] { margin: 0.4em 0 0.8em; padding: 0.1em 0.6em; border-left: 3px solid var(--vscode-panel-border); }',
  "section[data-linked] { border-left-color: var(--vscode-focusBorder); }",
  "[data-applies] { font-size: 0.8em; font-weight: normal; padding: 0 0.5em; border-radius: 1em; color: var(--vscode-badge-foreground); background: var(--vscode-badge-background); }",
  '[data-applies="no"] { color: inherit; background: transparent; border: 1px solid var(--vscode-editorWarning-foreground); }',
  '[data-element="question"] { color: var(--vscode-descriptionForeground); }',
  '[data-element="evidence"] { font-weight: 600; }',
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
    `<style nonce="${nonce}">${STYLE}</style>`,
    "</head>",
    "<body>",
    `<main id="study"${view.reading || view.writing ? ' aria-busy="true"' : ""}>${bodyOf(view)}</main>`,
    `<script nonce="${nonce}">${SCRIPT}</script>`,
    "</body>",
    "</html>",
  ].join("\n");
}
