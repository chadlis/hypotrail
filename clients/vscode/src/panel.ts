// The one webview panel of the extension. It holds in memory only, for as long as it is open, the target it was
// opened on, the last object a read gave back with `success`, the arguments of a write that got no answer until that
// call is answered, whether a call is in flight, and the last figures read. It reads the Study through the bridge when it
// is opened, after each write the CLI answered and on the control "Read again", and at no other time, each status read
// that succeeds followed by the figures call; it writes only through `recordDecision`, on the control that records and on
// "Send again".
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, newRequestId, readFigures, readStudy, recordDecision, type DecisionInput, type Outcome } from "./bridge";
import { bodyOf, usableFigures, type View } from "./content";

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
let figures: Record<string, unknown> | undefined;

export function openPanel(next: Target): void {
  if (panel && (inFlight || unanswered)) {
    panel.reveal();
    return;
  }
  target = next;
  held = undefined;
  figures = undefined;
  if (panel) {
    panel.reveal();
  } else {
    panel = vscode.window.createWebviewPanel("hypotrail.study", "Hypotrail", vscode.ViewColumn.Active, panelOptions());
    panel.webview.onDidReceiveMessage(receive);
    panel.onDidDispose(() => {
      panel = undefined;
      target = undefined;
      held = undefined;
      figures = undefined;
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
  show({ reading: false, writing: true, object: held, figures, unanswered: unanswered !== undefined, sent: input, decision: target!.decision, study: target!.study });
  const outcome = await recordDecision(ROOT, target!.study, input);
  if (panel !== opened) return;
  inFlight = false;
  unanswered = outcome.outcome === "no_answer" ? input : undefined;
  if (outcome.outcome === "no_answer" || outcome.outcome === "client_refusal") {
    show({ reading: false, object: held, figures, written: outcome, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study: target!.study });
  } else {
    await read(outcome);
  }
}

// `written` is the answer of the write this read follows, if any. The panel stays in flight, with no new document, until the
// figures call that follows a successful status read has answered; only a figures read usable beside that status read is kept.
async function read(written?: Outcome): Promise<void> {
  const opened = panel!;
  const study = target!.study;
  inFlight = true;
  show({ reading: true, object: held, figures, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study });
  const outcome = await readStudy(ROOT, study);
  if (panel !== opened) return;
  const object = outcome.outcome === "success" ? outcome.object : undefined;
  const answer = object === undefined ? undefined : await readFigures(ROOT, study);
  if (panel !== opened) return;
  inFlight = false;
  held = object;
  figures = answer?.outcome === "success" ? usableFigures(object, answer.object) : undefined;
  const failure = outcome.outcome === "success" ? undefined : outcome;
  show({ reading: false, object: held, figures, failure, written, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study });
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
// active. The notice of a write the CLI recorded takes the focus, which keeps the view at the top; otherwise the view scrolls to the
// Decision a link names.
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
  'if (document.querySelector("a[data-recorded]") !== null) document.querySelector(\'[data-element="notice"]\')?.focus();',
  'else document.querySelector("[data-linked]")?.scrollIntoView();',
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
  "h2 { font-size: 0.8em; letter-spacing: 0.06em; text-transform: uppercase; color: var(--vscode-descriptionForeground); margin: 0.7em 0 0.25em; padding-bottom: 0.15em; border-bottom: 1px solid var(--vscode-panel-border); }",
  "h3 { font-size: 1.08em; margin: 0.3em 0 0.2em; }",
  "h4 { font-size: 0.85em; color: var(--vscode-descriptionForeground); margin: 0.5em 0 0.1em; }",
  "p, ul { margin: 0.2em 0; }",
  "ul { padding-left: 1.2em; }",
  "button { font: inherit; padding: 0.2em 0.8em; color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: 1px solid var(--vscode-contrastBorder, transparent); border-radius: 2px; cursor: pointer; }",
  "button:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }",
  "button:disabled { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); border-style: dashed; cursor: default; }",
  ":focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 2px; }",
  'input[type="radio"] { accent-color: var(--vscode-button-background); margin: 0.2em 0 0; }',
  '[data-element="notice"], [data-element="failure"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--vscode-focusBorder); background: var(--vscode-textBlockQuote-background); }',
  '[data-element="failure"] { border-left-color: var(--vscode-inputValidation-errorBorder); }',
  '[data-element="unknown"] { font-weight: 600; }',
  '[data-element="unknown"]::first-letter { text-transform: uppercase; }',
  '[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.4em 0; }',
  'div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"], [data-element="limits"] { font-size: 0.9em; color: var(--vscode-descriptionForeground); }',
  '[data-element="controls"] a { align-self: center; }',
  '[data-element="count"] { margin: 0 0 0.2em; font-size: 0.85em; line-height: 1.2; color: var(--vscode-descriptionForeground); }',
  '[data-element="delta"] a[data-kind="delta"] { font-size: 1.25em; font-weight: 600; }',
  "hr { border: 0; border-top: 1px solid var(--vscode-panel-border); margin: 1em 0 0.6em; }",
  "fieldset { margin: 0.5em 0; padding: 0.3em 0.5em 0.5em; border: 1px solid var(--vscode-panel-border); border-radius: 4px; }",
  "label { display: grid; grid-template-columns: auto 1fr; column-gap: 0.5em; padding: 0.3em; border-radius: 3px; cursor: pointer; }",
  "label:hover { background: var(--vscode-list-hoverBackground); }",
  "label:has(input:checked) { background: var(--vscode-list-inactiveSelectionBackground); outline: 1px solid var(--vscode-contrastActiveBorder, transparent); }",
  "label:has(input:disabled) { cursor: default; }",
  "label:has(input:checked) small { color: inherit; }",
  "label input { grid-row: 1 / span 2; align-self: start; }",
  "label small { grid-column: 2; font-size: 0.92em; color: var(--vscode-descriptionForeground); }",
  "fieldset button { margin-top: 0.4em; }",
  "[data-chart] { display: grid; grid-template-columns: 6.5em minmax(3em, 1fr) auto; align-items: center; gap: 0.3em 0.5em; margin: 0.4em 0; }",
  "li[data-chart] { list-style: none; }",
  "[data-chart] > p { grid-column: 1 / -1; }",
  "[data-bar] { display: contents; }",
  "[data-bar] > span:last-child { grid-column: 3; }",
  "[data-bar] svg { display: block; width: 100%; height: 0.75em; background: var(--vscode-editorWidget-background); }",
  "rect { stroke: var(--vscode-contrastBorder, transparent); vector-effect: non-scaling-stroke; }",
  "rect.control { fill: var(--vscode-charts-blue); }",
  "rect.candidate { fill: var(--vscode-charts-orange); }",
  "rect.scored-control { fill: var(--vscode-charts-blue); }",
  "rect.scored-candidate { fill: var(--vscode-charts-orange); }",
  "rect.rest { fill: transparent; stroke: var(--vscode-charts-lines); stroke-dasharray: 2 2; }",
  "rect.cited { fill: var(--vscode-charts-lines); }",
  "rect.latest { fill: var(--vscode-charts-foreground); }",
  "[data-figures] { margin: 0.6em 0 0.9em; }",
  "[data-figure] svg { display: block; width: 100%; }",
  '[data-figure="histogram"] svg { height: 4.5em; border-bottom: 1px solid var(--vscode-charts-lines); }',
  '[data-figure="box"] svg { height: 1.9em; margin-top: 0.3em; }',
  '[data-element="counts"] { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.8em; line-height: 1.3; }',
  '[data-element="counts"] td { padding: 0.1em 0 0; text-align: center; overflow: hidden; }',
  '[data-element="counts"] caption { caption-side: bottom; text-align: left; color: var(--vscode-descriptionForeground); }',
  '[data-element="axis"] { display: flex; justify-content: space-between; font-size: 0.85em; margin: 0.1em 0 0.3em; }',
  '[data-element="axis"] a:only-child { margin: 0 auto; }',
  '[data-element="quartiles"] { display: flex; flex-wrap: wrap; gap: 0.1em 1em; font-size: 0.9em; }',
  "[data-key]::before { content: \"\"; display: inline-block; width: 0.25em; height: 0.9em; margin-right: 0.35em; vertical-align: -0.1em; }",
  '[data-key="median"]::before { background: var(--vscode-foreground); }',
  '[data-key="delta"]::before { height: 1.2em; vertical-align: -0.25em; background: var(--vscode-charts-yellow); }',
  "rect.column { fill: var(--vscode-charts-purple); }",
  "rect.whisker { fill: var(--vscode-charts-purple); }",
  "rect.cap { fill: var(--vscode-charts-purple); }",
  "rect.box { fill: var(--vscode-charts-purple); fill-opacity: 0.35; stroke: var(--vscode-charts-purple); }",
  "rect.median { fill: var(--vscode-foreground); }",
  "rect.delta { fill: var(--vscode-charts-yellow); }",
  "rect.whisker, rect.cap, rect.median, rect.delta { stroke: none; }",
  'section[data-part="decision"] { margin: 0.4em 0 0.8em; padding: 0.1em 0.6em; border-left: 3px solid var(--vscode-panel-border); }',
  "section[data-linked], section[data-recorded] { border-left-color: var(--vscode-focusBorder); }",
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
