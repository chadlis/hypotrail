// The one webview panel of the extension. It holds in memory only, for as long as it is open, the target it was
// opened on, the last object a read gave back with `success`, the arguments of a write that got no answer until that
// call is answered, whether a call is in flight, and the last figures read. It reads the Study through the bridge when it
// is opened, after each write the CLI answered and on the control "Read again", and at no other time, each status read
// that succeeds followed by the figures call; it writes only through `recordDecision`, on the control that records and on
// "Send again". On a control that opens, it shows in the editor, read-only, a file of the Study whose path the object held names.
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, newRequestId, readFigures, readStudy, recordDecision, type DecisionInput, type Outcome } from "./bridge";
import { bodyOf, usableFigures, type View } from "./content";

export type Target = { study: string; decision?: string };

// What the document's script posts: the name of a message and, for the control that records, the indexes of the
// pending decision and of the option selected; for a control that opens, the kind of the record's part, its index in its listing and
// the ref.
type Message = { message?: unknown; pending?: unknown; option?: unknown; kind?: unknown; index?: unknown; ref?: unknown };

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
  [contract.messages[3]]: (message) => void open(message),
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

// Each kind of part a control that opens names: the listing of the object read that holds its records, the key of a record's id, and the
// kind of the entry of `record_files` that names a record's own file.
const LISTINGS: Record<string, [string, string, string]> = {
  assessment: ["assessments", "assessment_id", "assessment"],
  comparison: ["comparisons", "comparison_id", "comparison"],
  decision: ["decisions", "decision_id", "decision"],
  deviation: ["declared_deviations", "declared_deviation_id", "declared_deviation"],
};
// The ref of a record's own file, which `record_files` names; every other ref is a key of the record.
const RECORD_FILE = contract.open_refs[3];
// "then runs the command `workbench.action.files.setActiveEditorReadonlyInSession` on that editor, so that the file is shown read-only"
// (chadlis/hypotrail#227, T1-4).
const READ_ONLY = "workbench.action.files.setActiveEditorReadonlyInSession";

// The path relative to the Study folder that the object held gives at the message's kind, index and ref, if any: for a record's own file,
// the path of the entry of `record_files` of that kind whose id is the record's.
function namedPath(message: Message): string | undefined {
  if (!held || typeof message.kind !== "string" || !Object.hasOwn(LISTINGS, message.kind)) return undefined;
  if (typeof message.ref !== "string" || !contract.open_refs.includes(message.ref)) return undefined;
  const [listing, key, kind] = LISTINGS[message.kind];
  const entry = at(entries(held[listing]), message.index);
  if (entry === undefined) return undefined;
  const found =
    message.ref === RECORD_FILE
      ? entries(held.record_files).find((each) => each.kind === kind && each.id === entry[key])?.path
      : (entry[`${message.ref}_ref`] as { path?: unknown } | null | undefined)?.path;
  return typeof found === "string" ? found : undefined;
}

// The Study folder joined to `relative`, when `relative` is not absolute, has no `..` segment, and names a file whose real path lies
// inside the Study folder's real path; the real paths are resolved and no content is read.
async function insideStudy(study: string, relative: string): Promise<string | undefined> {
  if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) return undefined;
  const joined = path.join(study, relative);
  try {
    const [root, real] = await Promise.all([fs.promises.realpath(study), fs.promises.realpath(joined)]);
    const within = path.relative(root, real);
    return within !== "" && !path.isAbsolute(within) && within.split(path.sep)[0] !== ".." ? joined : undefined;
  } catch {
    return undefined;
  }
}

// A control that opens: the file the object held names, shown in the editor and made read-only there. A file the panel does not open, or
// that VS Code does not show, gives a document built from the object held with one fixed line in its notice, unless a call has started
// or the panel has read again meanwhile.
async function open(message: Message): Promise<void> {
  const opened = panel!;
  const object = held;
  const relative = namedPath(message);
  const file = relative === undefined ? undefined : await insideStudy(target!.study, relative);
  try {
    if (file === undefined) throw new Error("not opened");
    await vscode.window.showTextDocument(vscode.Uri.file(file), { preview: true, viewColumn: vscode.ViewColumn.Beside });
    await vscode.commands.executeCommand(READ_ONLY);
  } catch {
    if (panel !== opened || inFlight || held !== object) return;
    show({ reading: false, object: held, figures, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study: target!.study, unopened: true });
  }
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
// it the indexes of its pending decision and of the option selected there, a control that opens the kind, the index and the ref its
// attributes name; selecting an option makes that control active. The notice of a write the CLI recorded takes the focus, which keeps the view at the top; otherwise the view scrolls to the
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
  '    const ref = control.getAttribute("data-ref");',
  "    if (ref !== null) {",
  '      message.kind = control.getAttribute("data-part-kind");',
  '      message.index = Number(control.getAttribute("data-index"));',
  "      message.ref = ref;",
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
  // A control that opens stands beside a path, in the theme's secondary button colours, so that it does not read as the control that records.
  "button.open { padding: 0 0.5em; color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }",
  "button.open:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground, var(--vscode-button-secondaryBackground)); }",
  'input[type="radio"] { accent-color: var(--vscode-button-background); margin: 0.2em 0 0; }',
  '[data-element="notice"], [data-element="failure"], [data-element="figures-failed"], [data-element="figures-unavailable"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--vscode-focusBorder); background: var(--vscode-textBlockQuote-background); }',
  '[data-element="failure"], [data-element="figures-failed"] { border-left-color: var(--vscode-inputValidation-errorBorder); }',
  '[data-element="unknown"] { font-weight: 600; }',
  '[data-element="unknown"]::first-letter { text-transform: uppercase; }',
  '[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.4em 0; }',
  'div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"], [data-element="caption"], [data-element="limits"] { font-size: 0.9em; color: var(--vscode-descriptionForeground); }',
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
  '[data-figure="dots"] { margin-bottom: 0.5em; }',
  // Only the dots that stand after the choices, from ten pairs, run on in columns; under ten they stand among the figures, under their scale.
  ':not([data-figures]) > [data-figure="dots"] { column-width: 18em; column-gap: 1.5em; }',
  '[data-figure="dots"] > h4, [data-element="dot-key"], [data-element="dot-order"] { column-span: all; }',
  '[data-figure="histogram"] svg { height: 4.5em; border-bottom: 1px solid var(--vscode-charts-lines); }',
  '[data-figure="box"] svg { height: 1.9em; margin-top: 0.3em; }',
  '[data-element="counts"] { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.8em; line-height: 1.3; }',
  '[data-element="counts"] td { padding: 0.1em 0 0; text-align: center; overflow: hidden; }',
  '[data-element="counts"] caption { caption-side: top; text-align: left; color: var(--vscode-descriptionForeground); }',
  '[data-element="axis"] { display: flex; justify-content: space-between; gap: 0.5em; font-size: 0.85em; margin: 0.1em 0 0; }',
  '[data-element="axis"] > span { color: var(--vscode-descriptionForeground); }',
  '[data-element="axis"] a:only-child { margin: 0 auto; }',
  '[data-element="quartiles"] { display: flex; flex-wrap: wrap; gap: 0.1em 0.7em; font-size: 0.82em; }',
  "[data-key]::before { content: \"\"; display: inline-block; width: 0.25em; height: 0.9em; margin-right: 0.3em; vertical-align: -0.1em; }",
  '[data-key="median"]::before { background: var(--vscode-foreground); }',
  '[data-key="delta"]::before { width: 0.4em; height: 1.2em; vertical-align: -0.25em; background: var(--vscode-charts-green); }',
  '[data-key="zero"]::before { width: 0.15em; height: 1.2em; vertical-align: -0.25em; background: var(--vscode-charts-lines); }',
  "rect.column { fill: var(--vscode-charts-purple); }",
  "rect.whisker { fill: var(--vscode-charts-purple); }",
  "rect.cap { fill: var(--vscode-charts-purple); }",
  "rect.box { fill: var(--vscode-charts-purple); fill-opacity: 0.35; stroke: var(--vscode-charts-purple); }",
  "rect.median { fill: var(--vscode-foreground); }",
  "rect.delta { fill: var(--vscode-charts-green); }",
  "rect.zero { fill: var(--vscode-charts-lines); }",
  "rect.whisker, rect.cap, rect.median, rect.delta, rect.zero { stroke: none; }",
  '[data-element="dots"] { display: grid; grid-template-columns: fit-content(9.5em) minmax(3em, 1fr); align-items: center; gap: 0.1em 0.5em; }',
  "[data-dot] { display: contents; }",
  "[data-dot] > span { font-size: 0.8em; line-height: 1.2; overflow-wrap: anywhere; color: var(--vscode-descriptionForeground); }",
  "[data-dot] svg { height: 0.8em; background: var(--vscode-editorWidget-background); }",
  "[data-dot] rect { stroke: none; }",
  "rect.between { fill: var(--vscode-charts-lines); }",
  "rect.favours-control { fill: var(--vscode-charts-blue); }",
  "rect.favours-candidate { fill: var(--vscode-charts-orange); }",
  '[data-element="dot-ends"] { grid-column: 2; display: flex; justify-content: space-between; font-size: 0.85em; margin: 0 0 0.1em; }',
  '[data-element="dot-ends"] a:only-child { margin: 0 auto; }',
  '[data-element="dot-key"] { display: flex; gap: 1em; font-size: 0.9em; }',
  '[data-element="dot-order"] { font-size: 0.85em; color: var(--vscode-descriptionForeground); }',
  '[data-key="control"]::before { background: var(--vscode-charts-blue); }',
  '[data-key="candidate"]::before { width: 0.35em; height: 0.45em; vertical-align: 0.1em; background: var(--vscode-charts-orange); }',
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
