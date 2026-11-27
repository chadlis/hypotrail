// The one webview panel of the extension. It holds in memory only, for as long as it is open, the target it was
// opened on, the last object a read gave back with `success`, the arguments of a write that got no answer until that
// call is answered, whether a call is in flight, the last figures read, the answer of the last profile read and the last lesson read
// usable beside the object held. It reads the Study through the bridge when it is opened, after each write the CLI answered and on the
// control "Read again", and at no other time, each status read that succeeds followed by the figures call, then, once its document is
// drawn, the profile call and the lesson call; it writes only through `recordDecision`, on the control that records and on
// "Send again". On a control that opens, it shows in the editor, read-only, a file of the Study whose path the object held names.
import * as vscode from "vscode";
import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, isLessonTrack, newRequestId, readFigures, readLesson, readProfile, readStudy, readTrackLesson, recordDecision, type DecisionInput, type LessonTrack, type Outcome } from "./bridge";
import { bodyOf, cardsOf, packStationsOf, pendingLessonPart, usableFigures, usableLesson, type View } from "./content";

export type Target = { study: string; decision?: string };

// What the document's script posts: the name of a message and, for the control that records, the indexes of the
// pending decision and of the option selected and the text of its box of words; for a control that opens, the kind of the record's part, its index in its listing and
// the ref.
type Message = { message?: unknown; pending?: unknown; option?: unknown; words?: unknown; kind?: unknown; index?: unknown; ref?: unknown };

// The checkout that holds this extension: its compiled sources sit in `out/src/` of the extension's folder.
const ROOT = checkoutRoot(path.resolve(__dirname, "..", ".."));

let panel: vscode.WebviewPanel | undefined;
let target: Target | undefined;
let held: Record<string, unknown> | undefined;
let unanswered: DecisionInput | undefined;
let inFlight = false;
let figures: Record<string, unknown> | undefined;
let profile: Outcome | undefined;
let lesson: Record<string, unknown> | undefined;

function panelFor(next: Target | undefined): boolean {
  if (panel && (inFlight || unanswered)) {
    panel.reveal();
    return false;
  }
  target = next;
  held = undefined;
  figures = undefined;
  profile = undefined;
  lesson = undefined;
  if (panel) {
    panel.reveal();
  } else {
    panel = vscode.window.createWebviewPanel("hypotrail.study", "Hypotrail", vscode.ViewColumn.Active, panelOptions());
    panel.webview.onDidReceiveMessage(receive);
    panel.onDidChangeViewState(({ webviewPanel }) => cacheLessonWhenHidden(webviewPanel));
    panel.onDidDispose(() => {
      panel = undefined;
      target = undefined;
      held = undefined;
      figures = undefined;
      profile = undefined;
      lesson = undefined;
      unanswered = undefined;
      inFlight = false;
    });
  }
  return true;
}

export function openPanel(next: Target): void {
  if (panelFor(next)) void read();
}

export function openStationsPanel(): void {
  if (panelFor(undefined)) {
    setDocument(stationsDocument(newNonce(), undefined, '<p>Choose a Track to see its stations.</p>'));
  }
}

async function readStationSelection(opened: vscode.WebviewPanel, message: { nonce?: unknown; track?: unknown } | null): Promise<void> {
  const activeNonce = /<script nonce="([a-f0-9]+)">/.exec(opened.webview.html)?.[1];
  if (activeNonce === undefined || message?.nonce !== activeNonce || !isLessonTrack(message.track)) return;
  const track = message.track, nonce = newNonce();
  const awaiting = stationsDocument(nonce, track, '<p role="status">Reading lesson packs…</p>');
  setDocument(awaiting);
  const result = await readTrackLesson(ROOT, track);
  if (panel !== opened || target !== undefined || opened.webview.html !== awaiting) return;
  const content = result.outcome === "success" && result.object.track === track
    ? packStationsOf(result.object)
    : '<p role="status">The lesson read did not return content. Select a Track to try again.</p>';
  setDocument(stationsDocument(nonce, track, content));
}

function stationsDocument(nonce: string, selected: LessonTrack | undefined, content: string): string {
  const button = (track: LessonTrack, label: string): string =>
    `<button type="button" data-track="${track}" aria-pressed="${track === selected}">${label}</button>`;
  const policy = contract.csp_directives.map((directive) => directive.replace("{nonce}", nonce)).join("; ");
  return [
    '<!doctype html>',
    '<html lang="en"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<meta http-equiv="Content-Security-Policy" content="${policy}">`,
    `<style nonce="${nonce}">${STYLE}</style></head><body><main>`,
    '<h1>Hypotrail Stations</h1>',
    '<div aria-label="Track">',
    button("temporal_regression", "Temporal regression"),
    button("tool_using_agent", "Tool-using agent"),
    '</div>',
    content,
    '</main>',
    `<script nonce="${nonce}">`,
    "const vscode = acquireVsCodeApi();",
    'for (const button of document.querySelectorAll("button[data-track]")) {',
    `  button.addEventListener("click", () => vscode.postMessage({ nonce: "${nonce}", track: button.dataset.track }));`,
    "}",
    '</script></body></html>',
  ].join("\n");
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
  if (target === undefined) {
    void readStationSelection(panel, message as { nonce?: unknown; track?: unknown } | null);
    return;
  }
  const name = (message as Message | null)?.message;
  if (typeof name === "string" && Object.hasOwn(HANDLERS, name)) HANDLERS[name](message as Message);
}

const entries = (content: unknown): Record<string, unknown>[] => (Array.isArray(content) ? content : []);
const at = (list: Record<string, unknown>[], index: unknown) => (Number.isInteger(index) ? list[index as number] : undefined);

// The channel the panel declares for the words typed in its box. "The panel sends no `by`: it knows no person. `channel` is "panel", with
// `authenticated` false." (D-151, answer 6)
const PANEL_CHANNEL = "panel";

// The second action: the extension resolves the indexes it is sent in the object it holds, with the ids of the question and of the option
// that object gives; the text of the box, sent whole when it is not empty, is the person's words.
function record(message: Message): void {
  if (unanswered || !held) return;
  const pending = at(entries(held.pending_decisions), message.pending);
  const option = at(entries(pending?.options), message.option);
  if (!pending || !option) return;
  const question = pending.question as { text?: unknown; id?: unknown } | undefined;
  const words = typeof message.words === "string" && message.words !== "" ? { words: [message.words], channel: PANEL_CHANNEL } : {};
  void write({
    question: question?.text as string,
    option: option.text as string,
    author: contract.decide_author,
    question_id: question?.id as string,
    option_id: option.id as string,
    ...words,
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

// The folders of the Attempts of the object held that no Assessment cites: "`open` refuses any path under that Attempt's folder" (D-143,
// correction 1). An Attempt is cited when an Assessment holds the `observation_set_id` the read gives the Attempt.
function uncitedFolders(): string[] {
  const cited = new Set(entries(held?.assessments).map((assessment) => assessment.observation_set_id));
  return entries(held?.attempts)
    .filter((attempt) => attempt.observation_set_id === null || attempt.observation_set_id === undefined || !cited.has(attempt.observation_set_id))
    .map((attempt) => `attempts/${attempt.attempt_id as string}/`);
}

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
  if (typeof found !== "string") return undefined;
  return uncitedFolders().some((folder) => found.replace(/\\/g, "/").startsWith(folder)) ? undefined : found;
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
    show({ reading: false, object: held, figures, profile, lesson, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study: target!.study, unopened: true });
  }
}

async function write(input: DecisionInput): Promise<void> {
  const opened = panel!;
  inFlight = true;
  show({ reading: false, writing: true, object: held, figures, profile, lesson, unanswered: unanswered !== undefined, sent: input, decision: target!.decision, study: target!.study });
  const outcome = await recordDecision(ROOT, target!.study, input);
  if (panel !== opened) return;
  inFlight = false;
  unanswered = outcome.outcome === "no_answer" ? input : undefined;
  if (outcome.outcome === "no_answer" || outcome.outcome === "client_refusal") {
    // A write the bridge refuses keeps its choice and its words in the document, so that the person can correct them.
    const sent = outcome.outcome === "client_refusal" ? input : unanswered;
    show({ reading: false, object: held, figures, profile, lesson, written: outcome, unanswered: unanswered !== undefined, sent, decision: target!.decision, study: target!.study });
  } else {
    await read(outcome);
  }
}

// `written` is the answer of the write this read follows, if any. The panel stays in flight, with no new document, until the
// figures call that follows a successful status read has answered; only a figures read usable beside that status read is kept. The
// profile call follows, out of flight.
async function read(written?: Outcome): Promise<void> {
  const opened = panel!;
  const study = target!.study;
  inFlight = true;
  show({ reading: true, object: held, figures, profile, lesson, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study });
  const sequence = held?.write_sequence;
  const outcome = await readStudy(ROOT, study, Number.isSafeInteger(sequence) && (sequence as number) >= 0 ? (sequence as number) : 0);
  if (panel !== opened) return;
  const object = outcome.outcome === "success" ? outcome.object : undefined;
  const answer = object === undefined ? undefined : await readFigures(ROOT, study);
  if (panel !== opened) return;
  inFlight = false;
  held = object;
  figures = answer?.outcome === "success" ? usableFigures(object, answer.object) : undefined;
  profile = undefined;
  lesson = undefined;
  const failure = outcome.outcome === "success" ? undefined : outcome;
  show({ reading: false, object: held, figures, profile, lesson, failure, written, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study });
  if (object !== undefined) void readProfileOf(opened, object, study, written);
  if (object !== undefined) void readLessonOf(opened, object, study);
}

// The profile call, made once the document of the status and figures reads is drawn, so that nothing waits for it: its answer is kept for
// the object it was made beside, and the document is built again with it unless a call is in flight or the panel has read again meanwhile.
async function readProfileOf(opened: vscode.WebviewPanel, object: Record<string, unknown>, study: string, written?: Outcome): Promise<void> {
  const answer = await readProfile(ROOT, study);
  if (panel !== opened || held !== object) return;
  profile = answer;
  if (!inFlight) show({ reading: false, object: held, figures, profile, lesson, written, unanswered: unanswered !== undefined, sent: unanswered, decision: target!.decision, study });
}

// The lesson call, made once the document of the status and figures reads is drawn, as the profile call is, so that the Pending decision,
// its choices and Record never wait for it. Keep only a usable lesson beside the same status object, and deliver it to the existing
// document without replacing the Pending decision's form.
async function readLessonOf(opened: vscode.WebviewPanel, object: Record<string, unknown>, study: string): Promise<void> {
  const answer = await readLesson(ROOT, study);
  if (panel !== opened || held !== object) return;
  lesson = answer.outcome === "success" ? usableLesson(object, answer.object) : undefined;
  if (inFlight || lesson === undefined) return;

  if (!opened.visible) {
    cacheLessonWhenHidden(opened);
    return;
  }
  const document = opened.webview.html;
  const nonce = /<script nonce="([a-f0-9]+)">/.exec(document)?.[1];
  const cards = newLessonCards(document);
  if (nonce !== undefined && cards !== "") void opened.webview.postMessage({ lesson: cards, nonce });
}

function newLessonCards(document: string): string {
  return document.includes('<div data-part="lesson">') ? "" : cardsOf(usableLesson(held, lesson), document);
}

// A hidden webview can be recreated from the HTML assigned by the extension. Add only the lesson to that cached document.
function cacheLessonWhenHidden(opened: vscode.WebviewPanel): void {
  if (panel !== opened || opened.visible || inFlight) return;
  const document = opened.webview.html;
  const cards = newLessonCards(document);
  const pending = pendingLessonPart();
  if (cards !== "") setDocument(document.replace(pending, () => cards));
}

function show(view: View): void {
  setDocument(documentFor(newNonce(), view));
}

function setDocument(document: string): void {
  panel!.webview.html = document;
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
// attributes name; selecting an option makes that control active. A link of the document opens the folds that hold its target, then moves
// the view to it. The notice of a write the CLI recorded takes the focus, which keeps the view at the top; otherwise the folds of the Decision
// a link names open and the view scrolls to it.
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
  "      const box = document.querySelector(`textarea[data-words=\"${pending}\"]`);",
  "      if (box !== null) message.words = box.value;",
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
  // "a deep link builds the document with the target's folds open" (D-136, I3): each fold that holds an element is opened before the
  // view moves to it, for a link of the document and for the Decision a link of the second form names.
  "const reveal = (element) => {",
  '  for (let fold = element.closest("details"); fold !== null; fold = fold.parentElement.closest("details")) fold.open = true;',
  "  element.scrollIntoView();",
  "};",
  'for (const anchor of document.querySelectorAll(\'a[href^="#"]:not([data-pack-figure])\')) {',
  '  anchor.addEventListener("click", (event) => {',
  '    const target = document.getElementById(anchor.getAttribute("href").slice(1));',
  "    if (target === null) return;",
  "    event.preventDefault();",
  "    reveal(target);",
  "  });",
  "}",
  'document.addEventListener("click", (event) => {',
  '  const anchor = event.target.closest?.("a[data-pack-figure]");',
  '  if (!anchor) return;',
  '  const target = document.getElementById(anchor.getAttribute("href").slice(1));',
  '  if (!target) return;',
  '  event.preventDefault();',
  '  reveal(target);',
  '  target.focus({ preventScroll: true });',
  '});',
  // Mark every rendered value named by an open card.
  "const mark = () => {",
  `  const paths = new Set([...document.querySelectorAll('details[data-element="card"][open] [data-shows]')].map((item) => item.getAttribute("data-shows")));`,
  '  for (const value of document.querySelectorAll("[data-lesson-value]")) value.toggleAttribute("data-highlighted", paths.has(value.getAttribute("data-lesson-value")));',
  "};",
  'document.addEventListener("toggle", (event) => {',
  `  if (event.target.matches('details[data-element="card"]')) mark();`,
  '}, true);',
  "const nonce = document.currentScript.nonce;",
  'window.addEventListener("message", ({data}) => {',
  `  if (!data || data.nonce !== nonce || typeof data.lesson !== "string" || document.querySelector('[data-part="lesson"]')) return;`,
  '  const cards = new DOMParser().parseFromString(data.lesson, "text/html");',
  `  const part = cards.querySelector('div[data-part="lesson"]');`,
  `  const pending = document.querySelector('[data-part="lesson-pending"]');`,
  '  if (!pending || !part) return;',
  `  const before = pending.querySelector('details[data-element="lesson-packs"]');`,
  `  const fold = part.querySelector('details[data-element="lesson-packs"]');`,
  '  const focused = pending.contains(document.activeElement);',
  '  fold.open = before.open;',
  '  pending.replaceWith(part);',
  '  if (focused) fold.querySelector("summary").focus({ preventScroll: true });',
  '});',
  'if (document.querySelector("a[data-recorded]") !== null) document.querySelector(\'[data-element="notice"]\')?.focus();',
  "else {",
  '  const linked = document.querySelector("[data-linked]");',
  "  if (linked !== null) reveal(linked);",
  "}",
].join("\n");

// The document's style. Its first three rules are the palettes: "one charter palette block per theme kind" (D-136, C4 amended), the
// blackboard for the dark themes and the whiteboard for the light ones, with the values of the mockups v2, and a third block for the
// two high-contrast themes that names VS Code's own variables only. VS Code marks the body of a webview with the class of its theme's
// kind; a High Contrast Light body holds both high-contrast classes. No other rule holds a literal colour: each takes a variable of the
// palettes. Its margins are small, so that at 420 px the question and the first evidence number stand near the top of the panel.
const STYLE = [
  'body.vscode-dark{ --board:#20312C;--board2:#1A2925;--chalk:#EDE8DA;--chalk2:#C9C4B6;--faint:#9AA59E;--line:rgba(237,232,218,.16);--line2:rgba(237,232,218,.32);--yellow:#F0D178;--pink:#EFA3B8;--mint:#B9E2C4;--teal:#9FE0D2;--violet:#C8B6F5;--coral:#F3A28F;--card:#F5F1E6;--cardink:#22302B;--cardmuted:#4E5A55;--cardline:rgba(34,48,43,.18);--cardline2:rgba(34,48,43,.36);--cardsoft:#ECE7D8;--paperbg:repeating-linear-gradient(0deg,rgba(38,72,124,.045) 0 1px,transparent 1px 12px),repeating-linear-gradient(90deg,rgba(38,72,124,.045) 0 1px,transparent 1px 12px);--red:#B8322A;--pen:#1E4E9E;--orange:#C2571A;--leaf:#17643A;--plum:#6B46C1;--ochre:#B07418;--ochre-ink:#7E5310;--slate:#2E5446;--btnfg:#F5F1E6;--btnborder:#2E5446;--refgrey:#6E767B;--hl:rgba(240,209,120,.28);--focus:#F0D178;--focuspaper:#1E4E9E;--shadow:0 14px 26px -16px rgba(0,0,0,.6),0 1px 0 rgba(0,0,0,.2);--hit:rgba(255,222,64,.55);--hitcur:#F0A500;color-scheme:dark}',
  'body.vscode-light{ --board:#F1F3F1;--board2:#E4E8E4;--chalk:#1E2A36;--chalk2:#3E4A57;--faint:#56616D;--line:rgba(30,42,54,.14);--line2:rgba(30,42,54,.32);--yellow:#7A5D00;--pink:#A3304D;--mint:#17643A;--teal:#0B6B60;--violet:#5B3AAE;--coral:#A8361F;--card:#FFFFFF;--cardink:#22302B;--cardmuted:#4E5A55;--cardline:rgba(34,48,43,.16);--cardline2:rgba(34,48,43,.34);--cardsoft:#F1EFE9;--paperbg:repeating-linear-gradient(0deg,rgba(38,72,124,.035) 0 1px,transparent 1px 12px),repeating-linear-gradient(90deg,rgba(38,72,124,.035) 0 1px,transparent 1px 12px);--red:#B8322A;--pen:#1E4E9E;--orange:#C2571A;--leaf:#17643A;--plum:#6B46C1;--ochre:#B07418;--ochre-ink:#7E5310;--slate:#2E5446;--btnfg:#FFFFFF;--btnborder:#2E5446;--refgrey:#6E767B;--hl:rgba(183,121,31,.16);--focus:#1E4E9E;--focuspaper:#1E4E9E;--shadow:0 10px 22px -16px rgba(30,42,54,.45),0 1px 0 rgba(30,42,54,.12);--hit:rgba(255,222,64,.55);--hitcur:#F0A500;color-scheme:light}',
  'body.vscode-high-contrast{ --board:var(--vscode-editor-background);--board2:var(--vscode-editor-background);--chalk:var(--vscode-editor-foreground);--chalk2:var(--vscode-foreground);--faint:var(--vscode-foreground);--line:var(--vscode-contrastBorder);--line2:var(--vscode-contrastBorder);--yellow:var(--vscode-contrastActiveBorder);--pink:var(--vscode-errorForeground);--mint:var(--vscode-charts-green);--teal:var(--vscode-textLink-foreground);--violet:var(--vscode-charts-purple);--coral:var(--vscode-editorWarning-foreground);--card:var(--vscode-editor-background);--cardink:var(--vscode-editor-foreground);--cardmuted:var(--vscode-foreground);--cardline:var(--vscode-contrastBorder);--cardline2:var(--vscode-contrastBorder);--cardsoft:var(--vscode-editor-background);--paperbg:none;--red:var(--vscode-errorForeground);--pen:var(--vscode-textLink-foreground);--orange:var(--vscode-editorWarning-foreground);--leaf:var(--vscode-charts-green);--plum:var(--vscode-charts-purple);--ochre:var(--vscode-editorWarning-foreground);--ochre-ink:var(--vscode-textLink-foreground);--slate:var(--vscode-button-background,var(--vscode-editor-background));--btnfg:var(--vscode-button-foreground,var(--vscode-editor-foreground));--btnborder:var(--vscode-button-border,var(--vscode-contrastBorder));--refgrey:var(--vscode-foreground);--hl:var(--vscode-editor-background);--focus:var(--vscode-focusBorder);--focuspaper:var(--vscode-focusBorder);--shadow:none;--hit:var(--vscode-editor-background);--hitcur:var(--vscode-contrastActiveBorder)} ',
  "body.vscode-dark, body.vscode-high-contrast:not(.vscode-high-contrast-light) { color-scheme: dark; }",
  "body { color: var(--chalk); background: var(--board); font-family: var(--vscode-font-family); line-height: 1.4; }",
  "main { max-width: 46em; overflow-wrap: anywhere; }",
  "a { color: var(--teal); }",
  'section[data-part="now"] > h2 { color: var(--yellow); }',
  '[data-element="band"] { margin: 0 0 0.2em; font-size: 0.9em; color: var(--chalk2); }',
  'section[data-part="path"] h3 { font-size: 0.85em; color: var(--chalk2); margin: 0.5em 0 0.1em; }',
  "details[data-step] { margin: 0.15em 0; }",
  "details[data-step] > summary { color: var(--chalk); }",
  '[data-element="form"], [data-element="chart"], [data-element="limitation"] { margin: 0.2em 0 0.4em 1em; }',
  '[data-element="limitation"] { font-size: 0.9em; color: var(--chalk2); }',
  "[data-mark] { font-weight: 700; color: var(--coral); }",
  'div[data-part="study"] { font-size: 0.85em; }',
  "h1 { font-size: 0.9em; font-weight: normal; margin: 0.4em 0; color: var(--chalk2); overflow-wrap: anywhere; }",
  "h2 { font-size: 0.9em; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--chalk2); margin: 0.5em 0 0.2em; padding-bottom: 0.1em; border-bottom: 1px solid var(--line2); }",
  "h3 { font-size: 1.08em; margin: 0.3em 0 0.2em; }",
  "h4 { font-size: 0.85em; color: var(--chalk2); margin: 0.5em 0 0.1em; }",
  "p, ul { margin: 0.2em 0; }",
  "ul { padding-left: 1.2em; }",
  "button { font: inherit; padding: 0.2em 0.8em; color: var(--btnfg); background: var(--slate); border: 1px solid var(--chalk2); border-radius: 2px; cursor: pointer; }",
  "button:hover:not(:disabled) { background: var(--pen); }",
  "button:disabled { color: var(--cardink); background: var(--cardsoft); border-style: dashed; cursor: default; }",
  ":focus-visible { outline: 1px solid var(--focus); outline-offset: 2px; }",
  // A control that opens stands beside a path, in the theme's secondary button colours, so that it does not read as the control that records.
  "button.open { padding: 0 0.5em; color: var(--cardink); background: var(--cardsoft); }",
  "button.open:hover:not(:disabled) { background: var(--card); }",
  'input[type="radio"] { accent-color: var(--slate); margin: 0.2em 0 0; }',
  '[data-element="notice"], [data-element="failure"], [data-element="figures-failed"], [data-element="figures-unavailable"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--focus); background: var(--board2); }',
  '[data-element="failure"], [data-element="figures-failed"] { border-left-color: var(--red); }',
  '[data-element="unknown"] { font-weight: 600; }',
  '[data-element="unknown"]::first-letter { text-transform: uppercase; }',
  '[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.3em 0 0.2em; }',
  'div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"], [data-element="caption"], [data-element="limits"] { font-size: 0.9em; color: var(--chalk2); }',
  '[data-element="controls"] a { align-self: center; }',
  '[data-element="count"] { margin: 0 0 0.2em; font-size: 0.85em; line-height: 1.2; color: var(--chalk2); }',
  '[data-element="now-heading"] { display: flex; align-items: baseline; gap: 0.5em; margin: 0.5em 0 0.2em; padding-bottom: 0.1em; border-bottom: 1px solid var(--line2); }',
  '[data-element="now-heading"] > h2 { margin: 0; padding: 0; border: none; }',
  '[data-element="delta"] a[data-kind="delta"] { font-size: 1.25em; font-weight: 600; }',
  "hr { border: 0; border-top: 1px solid var(--line2); margin: 1em 0 0.6em; }",
  "fieldset { margin: 0.5em 0; padding: 0.3em 0.5em 0.5em; border: 1px solid var(--line2); border-radius: 4px; }",
  "label { display: grid; grid-template-columns: auto 1fr; column-gap: 0.5em; padding: 0.3em; border-radius: 3px; cursor: pointer; }",
  "label:hover { background: var(--hl); }",
  "label:has(input:checked) { background: var(--hl); outline: 1px solid var(--yellow); }",
  "label:has(input:disabled) { cursor: default; }",
  "label:has(input:checked) small { color: inherit; }",
  "label input { grid-row: 1 / span 2; align-self: start; }",
  "label small { grid-column: 2; font-size: 0.92em; color: var(--chalk2); }",
  "fieldset button { margin-top: 0.4em; }",
  'details[data-element="add-words"] { margin-top: 0.3em; font-size: 0.9em; }',
  'label[data-element="words"] { display: block; margin-top: 0.2em; padding: 0; color: var(--chalk2); cursor: default; }',
  'label[data-element="words"]:hover { background: transparent; }',
  "textarea { display: block; box-sizing: border-box; width: 100%; margin-top: 0.15em; font: inherit; color: var(--chalk); background: var(--board2); border: 1px solid var(--chalk2); border-radius: 2px; resize: vertical; }",
  "[data-chart] { display: grid; grid-template-columns: 6.5em minmax(3em, 1fr) auto; align-items: center; gap: 0.3em 0.5em; margin: 0.4em 0; }",
  "li[data-chart] { list-style: none; }",
  "[data-chart] > p { grid-column: 1 / -1; }",
  "[data-bar] { display: contents; }",
  "[data-bar] > span:last-child { grid-column: 3; }",
  "[data-bar] svg { display: block; width: 100%; height: 0.75em; background: var(--board2); }",
  "rect { stroke: var(--line); vector-effect: non-scaling-stroke; }",
  "rect.control { fill: var(--pen); }",
  "rect.candidate { fill: var(--orange); }",
  "rect.scored-control { fill: var(--pen); }",
  "rect.scored-candidate { fill: var(--orange); }",
  "rect.rest { fill: transparent; stroke: var(--line2); stroke-dasharray: 2 2; }",
  "rect.cited { fill: var(--line2); }",
  "rect.latest { fill: var(--chalk2); }",
  "rect.feature { fill: var(--faint); }",
  'details[data-element="charts"] { margin: 0.4em 0; }',
  "summary { cursor: pointer; color: var(--teal); }",
  'details[data-element="consequence"] > summary { font-size: 0.85em; }',
  '[data-element="interval"], [data-element="context"], [data-element="cited-delta"], [data-element="frame"] { font-size: 0.9em; color: var(--chalk2); }',
  '[data-element="interval"] { display: block; }',
  "[data-figures] { margin: 0.6em 0 0.9em; }",
  "[data-figure] svg { display: block; width: 100%; }",
  '[data-figure="dots"] { margin-bottom: 0.5em; }',
  // Only the dots that stand after the choices, from ten pairs, run on in columns; under ten they stand among the figures, under their scale.
  ':not([data-figures]) > [data-figure="dots"] { column-width: 18em; column-gap: 1.5em; }',
  '[data-figure="dots"] > h4, [data-element="dot-key"], [data-element="dot-order"] { column-span: all; }',
  '[data-figure="histogram"] svg { height: 4.5em; border-bottom: 1px solid var(--line2); }',
  '[data-figure="box"] svg { height: 1.9em; margin-top: 0.3em; }',
  '[data-element="counts"] { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.8em; line-height: 1.3; }',
  '[data-element="counts"] td { padding: 0.1em 0 0; text-align: center; overflow: hidden; }',
  '[data-element="counts"] caption { caption-side: top; text-align: left; color: var(--chalk2); }',
  '[data-element="axis"] { display: flex; justify-content: space-between; gap: 0.5em; font-size: 0.85em; margin: 0.1em 0 0; }',
  '[data-element="axis"] > span { color: var(--chalk2); }',
  '[data-element="axis"] a:only-child { margin: 0 auto; }',
  '[data-element="quartiles"] { display: flex; flex-wrap: wrap; gap: 0.1em 0.7em; font-size: 0.82em; }',
  "[data-key]::before { content: \"\"; display: inline-block; width: 0.25em; height: 0.9em; margin-right: 0.3em; vertical-align: -0.1em; }",
  '[data-key="median"]::before { background: var(--chalk); }',
  '[data-key="delta"]::before { width: 0.4em; height: 1.2em; vertical-align: -0.25em; background: var(--mint); }',
  '[data-key="zero"]::before { width: 0.15em; height: 1.2em; vertical-align: -0.25em; background: var(--line2); }',
  "rect.column { fill: var(--violet); }",
  "rect.whisker { fill: var(--violet); }",
  "rect.cap { fill: var(--violet); }",
  "rect.box { fill: var(--violet); fill-opacity: 0.35; stroke: var(--violet); }",
  "rect.median { fill: var(--chalk); }",
  "rect.delta { fill: var(--mint); }",
  "rect.zero { fill: var(--line2); }",
  "rect.whisker, rect.cap, rect.median, rect.delta, rect.zero { stroke: none; }",
  '[data-element="dots"] { display: grid; grid-template-columns: fit-content(9.5em) minmax(3em, 1fr); align-items: center; gap: 0.1em 0.5em; }',
  "[data-dot] { display: contents; }",
  "[data-dot] > span { font-size: 0.8em; line-height: 1.2; overflow-wrap: anywhere; color: var(--chalk2); }",
  "[data-dot] svg { height: 0.8em; background: var(--board2); }",
  "[data-dot] rect { stroke: none; }",
  "rect.between { fill: var(--line2); }",
  "rect.favours-control { fill: var(--pen); }",
  "rect.favours-candidate { fill: var(--orange); }",
  '[data-element="dot-ends"] { grid-column: 2; display: flex; justify-content: space-between; font-size: 0.85em; margin: 0 0 0.1em; }',
  '[data-element="dot-ends"] a:only-child { margin: 0 auto; }',
  '[data-element="dot-key"] { display: flex; gap: 1em; font-size: 0.9em; }',
  '[data-element="dot-order"] { font-size: 0.85em; color: var(--chalk2); }',
  '[data-key="control"]::before { background: var(--pen); }',
  '[data-key="candidate"]::before { width: 0.35em; height: 0.45em; vertical-align: 0.1em; background: var(--orange); }',
  // The figures of the Data profile: each mark takes its colour from its class, and a mark too small for a stroke has none.
  '[data-figure^="profile-"] rect { stroke: none; }',
  '[data-figure="profile-target"] svg { height: 6em; background: var(--board2); }',
  '[data-element="distribution"] svg { height: 3em; border-bottom: 1px solid var(--line2); }',
  '[data-figure="profile-matrix"] svg { width: 16em; max-width: 100%; height: 16em; background: var(--board2); }',
  '[data-element="against"] svg { height: 7em; background: var(--board2); }',
  'details[data-element="distribution"], details[data-element="numbers"] { margin: 0.2em 0; }',
  '[data-element="profile-numbers"] { border-collapse: collapse; font-size: 0.85em; }',
  '[data-element="profile-numbers"] th, [data-element="profile-numbers"] td { padding: 0 0.6em 0 0; text-align: left; }',
  '[data-element="profile-numbers"] th { color: var(--chalk2); font-weight: normal; }',
  '[data-element="unavailable"], [data-element="differs"], [data-element="profile-failed"] { color: var(--coral); }',
  '[data-element="band-key"] { display: flex; gap: 1em; font-size: 0.85em; }',
  '[data-key="band"]::before { background: var(--line2); }',
  '[data-key="band-read"]::before { background: var(--yellow); }',
  "rect.day, rect.point { fill: var(--teal); }",
  "rect.band { fill: var(--line2); }",
  "rect.band-read { fill: var(--yellow); }",
  "rect.cell { fill: var(--violet); }",
  "rect.flagged { fill: var(--pink); }",
  "rect.no-value { fill: var(--line); }",
  // The places an open card names: an outline in the theme's focus colour, which changes no size and no text.
  "[data-highlighted] { outline: 2px dashed var(--focus); outline-offset: 2px; }",
  'details[data-element="card"] li { font-size: 0.85em; color: var(--chalk2); }',
  'section[data-part="decision"] { margin: 0.4em 0 0.8em; padding: 0.1em 0.6em; border-left: 3px solid var(--line2); }',
  "section[data-linked], section[data-recorded] { border-left-color: var(--focus); }",
  "[data-applies] { font-size: 0.8em; font-weight: normal; padding: 0 0.5em; border-radius: 1em; color: var(--cardink); background: var(--card); }",
  '[data-applies="no"] { color: inherit; background: transparent; border: 1px solid var(--coral); }',
  '[data-element="question"] { color: var(--chalk2); }',
  '[data-element="evidence"] { font-weight: 600; }',
  '[data-element="lesson-packs"], [data-element="pack-station"] { margin: 0.4em 0; padding: 0.15em 0.55em; border-left: 2px solid var(--line2); }',
  '[data-element="pack-lesson"] { margin: 0.45em 0; padding: 0.4em 0.65em; border: 1px solid var(--cardline); background: var(--paperbg), var(--card); color: var(--cardink); }',
  '[data-element="pack-lesson"] > summary { color: var(--cardink); }',
  '[data-element="pack-lesson"] dt { margin-top: 0.5em; font-weight: 650; }',
  '[data-element="pack-lesson"] dd { margin: 0; }',
  '[data-element="pack-lesson"] dd ul { padding-left: 1.35em; }',
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
