// The controls that open a file of the Study: one beside each output path the document shows, the message the document's script posts
// for it, and what the extension opens, or refuses to open, when it is given that message.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, pageOf, startChrome } from "./chrome";
import { KEPT_FIGURES, KEPT_READS, documentFor, elementOf, heldRecorder, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, withFigures, workspace, FIGURES_FAILED } from "./panel-harness";
import { exit, recorder, type RecordedCall } from "./recorder";
import { themed } from "./themes";
import * as stub from "./vscode-stub";

type Entry = Record<string, any>;

const [READ_AGAIN, RECORD, , OPEN] = contract.messages;
const [PER_ITEM, PAIRED_DELTAS, POPULATION] = contract.open_refs;
// "then runs the command `workbench.action.files.setActiveEditorReadonlyInSession` on that editor, so that the file is shown read-only"
// (chadlis/hypotrail#227, T1-4).
const READ_ONLY = "workbench.action.files.setActiveEditorReadonlyInSession";
const OPEN_THE_FILE = "Open the file";
const NOT_OPENED = "The file was not opened.";
// Each ref of an output path: the listing whose records hold it, the kind of their part, and the key of the ref in a record.
const OUTPUT_REFS: Record<string, [string, string, string]> = {
  [PER_ITEM]: ["assessments", "assessment", "per_item_ref"],
  [PAIRED_DELTAS]: ["comparisons", "comparison", "paired_deltas_ref"],
  [POPULATION]: ["comparisons", "comparison", "population_ref"],
};
// The kinds of part a control that opens may name.
const PART_KINDS = ["assessment", "comparison"];
const TIMEOUT = { error: { code: null, killed: true, signal: "SIGTERM" } };

const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");

// A control that opens, as its tag and its text give it.
type Control = { tag: string; text: string; kind?: string; index?: string; ref?: string; describedBy?: string; disabled: boolean };
const attribute = (tag: string, name: string): string | undefined => new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1];

function controlsOf(html: string): Control[] {
  return [...html.matchAll(/(<button [^>]*>)([^<]*)<\/button>/g)]
    .filter((match) => attribute(match[1], "data-message") === OPEN)
    .map(([, tag, text]) => ({
      tag,
      text,
      kind: attribute(tag, "data-part-kind"),
      index: attribute(tag, "data-index"),
      ref: attribute(tag, "data-ref"),
      describedBy: attribute(tag, "aria-describedby"),
      disabled: /\sdisabled(?=[\s>])/.test(tag),
    }));
}

// Each output path of a read: the path, and the part's kind, the place of its record in its listing and the ref that name it.
type Output = { path: string; kind: string; index: number; ref: string };
function outputsOf(read: Entry): Output[] {
  return Object.entries(OUTPUT_REFS).flatMap(([ref, [list, kind, key]]) =>
    (read[list] ?? []).flatMap((record: Entry, index: number) => (typeof record[key]?.path === "string" ? [{ path: record[key].path, kind, index, ref }] : [])),
  );
}

// Each paragraph of a document.
const paragraphsOf = (document: string): string[] => [...document.matchAll(/<p(?=[\s>])[^>]*>/g)].map((match) => elementOf(document.slice(match.index), match[0])!);

// The element whose `id` is `id`.
function elementWithId(document: string, id: string | undefined): string | undefined {
  const opening = [...document.matchAll(/<[a-z0-9]+ [^>]*\bid="([^"]*)"[^>]*>/g)].find((match) => match[1] === id);
  return opening ? elementOf(document.slice(opening.index), opening[0]) : undefined;
}

// Each output path the document shows stands in a paragraph with exactly one control that opens it, named by its label and described
// by the element that holds the path, a marked text with no link; and each control of an output ref stands beside one, both ways.
function assertOneControlPerPath(document: string, read: Entry, name: string): void {
  const outputs = outputsOf(read);
  const paths = new Set(outputs.map((output) => output.path));
  const shown = paragraphsOf(document).flatMap((paragraph) => markedTexts(paragraph).filter((text) => paths.has(text)).map((text) => ({ text, paragraph })));
  assert.equal(shown.length, markedTexts(document).filter((text) => paths.has(text)).length, `${name}: each output path shown stands in a paragraph`);
  const controls = controlsOf(document).filter((control) => control.ref !== undefined && control.ref in OUTPUT_REFS);
  assert.equal(controls.length, shown.length, `${name}: one control of an output ref per output path shown, both ways`);
  for (const { text, paragraph } of shown) {
    assert.equal(markedTexts(paragraph).filter((each) => paths.has(each)).length, 1, `${name}: one output path in the paragraph of ${text}`);
    const beside = controlsOf(paragraph);
    assert.equal(beside.length, 1, `${name}: one control beside ${text}`);
    const [control] = beside;
    assert.ok(contract.labels.includes(control.text) && control.text === OPEN_THE_FILE, `${name}: the control beside ${text} is named ${control.text}`);
    const described = elementWithId(document, control.describedBy);
    assert.ok(described !== undefined && paragraph.includes(described), `${name}: the control beside ${text} is described by an element of its paragraph`);
    assert.deepEqual(markedTexts(described), [text], `${name}: the element that describes the control holds the path`);
    assert.ok(!paragraph.includes("<a "), `${name}: no link beside ${text}`);
    const [list, kind, key] = OUTPUT_REFS[control.ref!];
    assert.equal(control.kind, kind, `${name}: the kind of the control beside ${text}`);
    assert.equal(read[list][Number(control.index)]?.[key]?.path, text, `${name}: the control beside ${text} names its record and its ref`);
  }
}

for (const name of KEPT_READS) {
  test(`each output path the document shows stands beside exactly one control that opens it, described by the path, which stays a marked text with no link: ${name}`, async (t) => {
    const read = keptObject(name);
    assertOneControlPerPath((await documentFor(t, success(read))).document, read, name);
  });
}

for (const key of ["paired_deltas_ref", "population_ref"]) {
  test(`status-success with the ${key} of its Comparison null: no path and no control for it, and one control beside each other path`, async (t) => {
    const read = keptObject("status-success");
    const path = read.comparisons[0][key].path;
    read.comparisons[0][key] = null;
    const { document } = await documentFor(t, success(read));
    assert.ok(!document.includes(path), path);
    const ref = Object.keys(OUTPUT_REFS).find((each) => OUTPUT_REFS[each][2] === key);
    assert.deepEqual(controlsOf(document).filter((control) => control.ref === ref && control.index === "0"), [], `no control of ${ref}`);
    assertOneControlPerPath(document, read, `status-success without ${key}`);
  });
}

// Every control of the document names a kind of part and a ref of `open_refs`, so that none names the References or an Attempt; no
// path of an Attempt and no path of the References stands in the document.
function assertNothingOfAnAttemptOrTheReferences(document: string, read: Entry, name: string): void {
  for (const control of controlsOf(document)) {
    assert.ok(PART_KINDS.includes(control.kind!), `${name}: the control ${control.tag} names a kind of part`);
    assert.ok(contract.open_refs.includes(control.ref!), `${name}: the control ${control.tag} names a ref of open_refs`);
  }
  for (const attempt of read.attempts ?? []) for (const artifact of attempt.artifacts ?? []) assert.ok(!document.includes(artifact.path), `${name}: ${artifact.path}`);
  for (const assessment of read.assessments ?? []) assert.ok(!document.includes(assessment.references_ref.path), `${name}: ${assessment.references_ref.path}`);
}

for (const name of KEPT_READS) {
  test(`every control that opens names a kind of part and a ref of open_refs, and no path of an Attempt or of the References is in the document: ${name}`, async (t) => {
    const read = keptObject(name);
    assertNothingOfAnAttemptOrTheReferences((await documentFor(t, success(read))).document, read, name);
  });
}

test("a planted control that names the References is found", async (t) => {
  const read = keptObject("status-success");
  const { document } = await documentFor(t, success(read));
  const planted = document.replace("</main>", `<button data-message="${OPEN}" data-part-kind="assessment" data-index="0" data-ref="references">${OPEN_THE_FILE}</button></main>`);
  assert.throws(() => assertNothingOfAnAttemptOrTheReferences(planted, read, "planted"), /names a ref of open_refs/);
});

// --- In a browser -------------------------------------------------------------------------------------------------------------------

type Keys = { key: (name: "Tab" | "Enter") => Promise<void>; evaluate: (expression: string) => Promise<any> };

// `document` opened in a page of the browser at 420 by 700 px, in the Light theme, the messages its script posts kept in
// `window.posted`, and its keys; undefined, with the test skipped, when Chrome is missing or does not start.
async function keyboardPage(t: TestContext, document: string): Promise<Keys | undefined> {
  if (!hasChrome(t, "the controls that open, reached by the keyboard")) return undefined;
  const address = await startChrome(t);
  if (address === undefined) {
    t.skip(`the controls that open, reached by the keyboard, are skipped: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
    return undefined;
  }
  const page = await pageOf(t, address);
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-open-")), "panel.html");
  t.after(() => fs.rmSync(path.dirname(file), { recursive: true, force: true }));
  fs.writeFileSync(file, document);
  await page.send("Emulation.setDeviceMetricsOverride", { width: 420, height: 700, deviceScaleFactor: 1, mobile: false });
  await page.send("Page.enable");
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.posted = []; window.acquireVsCodeApi = () => ({ postMessage: (message) => window.posted.push(message), getState() {}, setState() {} });" });
  await page.send("Page.navigate", { url: pathToFileURL(file).href });
  while (!page.events.some((event) => event.method === "Page.loadEventFired")) await new Promise((resolve) => setTimeout(resolve, 20));
  const KEYS = { Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 }, Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" } };
  const evaluate = async (expression: string) => {
    const answer = await page.send("Runtime.evaluate", { expression, returnByValue: true });
    if (answer.exceptionDetails) throw new Error(`${expression}: ${answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text}`);
    return answer.result.value;
  };
  await evaluate(themed("light"));
  return {
    key: async (name) => {
      await page.send("Input.dispatchKeyEvent", { type: "keyDown", ...KEYS[name] });
      await page.send("Input.dispatchKeyEvent", { type: "keyUp", ...KEYS[name], text: undefined });
    },
    evaluate,
  };
}

const CONTROLS = `[...document.querySelectorAll('button[data-message="${OPEN}"]')]`;

// Tab from the top of the page until each control that opens has held the focus once; `reached` runs at each, with its place among them.
async function eachControlByTab(keys: Keys, reached: (place: number) => Promise<void>): Promise<number> {
  const count: number = await keys.evaluate(`${CONTROLS}.length`);
  const visited = new Set<number>();
  for (let turn = 0; turn < 3000 && visited.size < count; turn += 1) {
    await keys.key("Tab");
    const place: number = await keys.evaluate(`${CONTROLS}.indexOf(document.activeElement)`);
    if (place >= 0 && !visited.has(place)) {
      visited.add(place);
      await reached(place);
    }
  }
  assert.equal(visited.size, count, "Tab reaches each control that opens");
  return count;
}

test("in a browser, Enter on each control that opens of status-success, reached by Tab, posts one message of four keys, the message, the part's kind, its index and the ref, and no value holds a path of the read", { timeout: 120000 }, async (t) => {
  const read = keptObject("status-success");
  const { document } = await documentFor(t, success(read), success(keptObject(KEPT_FIGURES["status-success"])));
  const keys = await keyboardPage(t, document);
  if (keys === undefined) return;
  const paths = [...outputsOf(read).map((output) => output.path), ...((read.record_files ?? []) as Entry[]).map((entry) => entry.path)];
  const count = await eachControlByTab(keys, async (place) => {
    const control = await keys.evaluate(`(() => { const c = ${CONTROLS}[${place}]; return { kind: c.getAttribute("data-part-kind"), index: c.getAttribute("data-index"), ref: c.getAttribute("data-ref") }; })()`);
    await keys.key("Enter");
    const posted: Entry[] = await keys.evaluate("window.posted.splice(0)");
    assert.equal(posted.length, 1, `one message posted by control ${place}`);
    const [message] = posted;
    for (const each of paths) for (const value of Object.values(message)) assert.ok(!String(value).includes(each), `the message of control ${place} holds ${each}`);
    assert.deepEqual(Object.keys(message).sort(), ["index", "kind", "message", "ref"], `the keys of the message of control ${place}`);
    assert.equal(message.message, OPEN);
    assert.equal(message.kind, control.kind);
    assert.equal(message.index, Number(control.index));
    assert.equal(message.ref, control.ref);
  });
  assert.ok(count >= outputsOf(read).length, `${count} controls that open`);
});

test("in a browser, each control that opens of status-success, reached by Tab, shows a focus outline", { timeout: 120000 }, async (t) => {
  const { document } = await documentFor(t, success(keptObject("status-success")), success(keptObject(KEPT_FIGURES["status-success"])));
  const keys = await keyboardPage(t, document);
  if (keys === undefined) return;
  await eachControlByTab(keys, async (place) => {
    const outline = await keys.evaluate(`(() => { const style = getComputedStyle(document.activeElement); return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), visible: document.activeElement.matches(":focus-visible") }; })()`);
    assert.ok(outline.visible && outline.style !== "none" && outline.width > 0, `control ${place}: ${JSON.stringify(outline)}`);
  });
});

// --- In the extension ---------------------------------------------------------------------------------------------------------------

// A Study folder that holds `files`, each a small text, in a new workspace.
function studyWith(t: TestContext, files: string[]): string {
  const [study] = workspace(t, ["bike"]);
  for (const file of files) {
    fs.mkdirSync(path.dirname(path.join(study, file)), { recursive: true });
    fs.writeFileSync(path.join(study, file), "kept\n");
  }
  return study;
}

// The panel opened on a Study folder that holds `files`, its status read answered with what `held` makes of the folder (a refused read,
// which leaves no object held, when that is undefined), then its figures call with a failure. Gives the folder and the calls recorded.
async function openedOn(t: TestContext, files: string[], held: (study: string) => Entry | undefined): Promise<{ study: string; calls: RecordedCall[] }> {
  const study = studyWith(t, files);
  const read = held(study);
  const calls = recorder(t, ...(read === undefined ? [exit(2, JSON.stringify({ ok: false, error: { code: "STUDY_NOT_FOUND", message: "no Study" } }))] : withFigures(success(read))));
  await runCommand();
  await settle();
  return { study, calls };
}

// Lets the checks of the opening and the calls to VS Code answer.
async function settled(): Promise<void> {
  for (let turn = 0; turn < 4; turn += 1) {
    await settle();
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

const messageOf = (output: Output): Entry => ({ message: OPEN, kind: output.kind, index: output.index, ref: output.ref });

for (const output of outputsOf(keptObject("status-success"))) {
  test(`the open message of ${output.ref} of ${output.kind} ${output.index} of status-success shows that file of the Study once, then makes it read-only, and starts nothing and builds no document`, async (t) => {
    const read = keptObject("status-success");
    const { study, calls } = await openedOn(t, outputsOf(read).map((each) => each.path), () => read);
    const [processes, documents, before] = [calls.length, panelOf().documents.length, stub.calls.length];
    panelOf().send(messageOf(output));
    await settled();
    const shown = stub.callsOf("showTextDocument");
    assert.equal(shown.length, 1, "one file shown");
    assert.equal((shown[0].args[0] as { fsPath: string }).fsPath, path.join(study, output.path), "the Study folder joined to the path the read gives");
    assert.deepEqual(stub.calls.slice(before).map((call) => call.name), ["showTextDocument", "executeCommand"], "the read-only command follows the opening");
    assert.deepEqual(stub.callsOf("executeCommand").map((call) => call.args), [[READ_ONLY]], "the command that makes the editor read-only");
    assert.equal(calls.length, processes, "no process started");
    assert.equal(panelOf().documents.length, documents, "no document assigned");
  });
}

// A file outside every Study, which a symbolic link from inside one reaches.
function outside(t: TestContext): string {
  const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-outside-")));
  t.after(() => fs.rmSync(folder, { recursive: true, force: true }));
  fs.writeFileSync(path.join(folder, "elsewhere.csv"), "outside\n");
  return path.join(folder, "elsewhere.csv");
}

// The cases of an open message given to the panel on status-success: the object the panel holds, made from the read and the Study folder
// (none when it gives undefined), what the folder holds besides the read's files, the message, what VS Code answers, whether the message is
// sent while a call is in flight, and whether the file is opened.
type Case = { name: string; held?: (read: Entry, study: string) => Entry | undefined; files?: (study: string, t: TestContext) => void; message?: (output: Output) => Entry; shows?: () => Promise<unknown>; inFlight?: boolean; opens: boolean };
const FIRST = (read: Entry): Output => outputsOf(read)[0];
const withPath = (read: Entry, value: string): Entry => ((read.assessments[FIRST(read).index].per_item_ref.path = value), read);

const CASES: Case[] = [
  { name: "the valid message", opens: true },
  { name: "a kind that names nothing in the object held", message: (output) => ({ ...messageOf(output), kind: "attempt" }), opens: false },
  { name: "an index that names nothing in the object held", message: (output) => ({ ...messageOf(output), index: 99 }), opens: false },
  { name: "a ref that names nothing in the object held", message: (output) => ({ ...messageOf(output), ref: "zq_none" }), opens: false },
  { name: "the ref of the References", message: (output) => ({ ...messageOf(output), ref: "references" }), opens: false },
  { name: "no object held", held: () => undefined, opens: false },
  { name: "an absolute path, of a file of the Study", held: (read, study) => withPath(read, path.join(study, FIRST(read).path)), opens: false },
  { name: "a path with a .. segment, to a file of the Study", held: (read) => withPath(read, `assessments/../${FIRST(read).path}`), opens: false },
  { name: "a path whose real path lies outside the Study, through a symbolic link", held: (read) => withPath(read, "elsewhere.csv"), files: (study, t) => fs.symlinkSync(outside(t), path.join(study, "elsewhere.csv")), opens: false },
  { name: "a file that does not exist", held: (read) => withPath(read, "assessments/zq-none/per_item.csv"), opens: false },
  { name: "a file VS Code does not show", shows: () => Promise.reject(new Error("not shown")), opens: false },
  { name: "a message sent while a call is in flight", inFlight: true, opens: false },
];

for (const each of CASES) {
  const outcome = each.opens ? "opens the file and shows no line" : each.inFlight ? "drops it, opens nothing, starts nothing and shows no line" : "opens nothing, starts nothing and shows the one fixed line in the notice";
  test(`given the open message on status-success with ${each.name}, the panel ${outcome}`, async (t) => {
    const read = keptObject("status-success");
    const files = outputsOf(read).map((output) => output.path);
    const message = (each.message ?? messageOf)(FIRST(read));
    let processes: () => number;
    let answerFigures = (): void => {};
    if (each.inFlight) {
      studyWith(t, files);
      const recorded = heldRecorder(t);
      await runCommand();
      recorded.answer(success(read));
      await settle();
      processes = () => recorded.calls.length;
      answerFigures = () => recorded.answer(FIGURES_FAILED);
    } else {
      const opened = await openedOn(t, files, (study) => (each.held === undefined ? read : each.held(structuredClone(read), study)));
      each.files?.(opened.study, t);
      processes = () => opened.calls.length;
    }
    if (each.shows) stub.state.shown = each.shows;
    const [started, documents] = [processes(), panelOf().documents.length];
    panelOf().send(message);
    await settled();
    assert.equal(stub.callsOf("showTextDocument").length, each.opens || each.shows ? 1 : 0, "what was asked of the editor");
    assert.deepEqual(stub.callsOf("executeCommand").map((call) => call.args), each.opens ? [[READ_ONLY]] : [], "the read-only command");
    assert.equal(processes(), started, "no process started");
    if (each.opens || each.inFlight) {
      assert.equal(panelOf().documents.length, documents, "no document assigned");
      answerFigures();
      await settled();
      assert.ok(!lastDocument().includes(NOT_OPENED), "no line");
    } else {
      assert.equal(panelOf().documents.length, documents + 1, "one document");
      assert.ok(contract.labels.includes(NOT_OPENED));
      assert.equal(words(elementOf(lastDocument(), '<div data-element="notice"')), NOT_OPENED, "the notice holds the one fixed line");
    }
  });
}

// --- Inert while a call is in flight -------------------------------------------------------------------------------------------------

test("each control that opens is disabled in the document of a read in flight on status-success", async (t) => {
  workspace(t, ["bike"]);
  const { answer } = heldRecorder(t);
  await runCommand();
  answer(success(keptObject("status-success")));
  await settle();
  answer(FIGURES_FAILED);
  await settle();
  panelOf().send({ message: READ_AGAIN });
  const controls = controlsOf(lastDocument());
  assert.ok(lastDocument().includes('aria-busy="true"') && controls.length > 0, "a read in flight, with controls that open");
  for (const control of controls) assert.ok(control.disabled, control.tag);
});

test("no control that opens is disabled in the document of a write with no answer on status-success", async (t) => {
  workspace(t, ["bike"]);
  recorder(t, ...withFigures(success(keptObject("status-success")), TIMEOUT));
  await runCommand();
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  await settled();
  const controls = controlsOf(lastDocument());
  assert.ok(lastDocument().includes(contract.write_no_answer_words) && controls.length > 0, "a write with no answer held, with controls that open");
  for (const control of controls) assert.ok(!control.disabled, control.tag);
});

// --- The style -----------------------------------------------------------------------------------------------------------------------

// The rules of the panel's style before the controls that open, one per line.
const KEPT_STYLE = String.raw`
body.vscode-dark, body.vscode-high-contrast:not(.vscode-high-contrast-light) { color-scheme: dark; }
body { color: var(--vscode-foreground); background: var(--vscode-editor-background); font-family: var(--vscode-font-family); line-height: 1.4; }
main { max-width: 46em; overflow-wrap: anywhere; }
h1 { font-size: 0.9em; font-weight: normal; margin: 0.4em 0; color: var(--vscode-descriptionForeground); overflow-wrap: anywhere; }
h2 { font-size: 0.8em; letter-spacing: 0.06em; text-transform: uppercase; color: var(--vscode-descriptionForeground); margin: 0.7em 0 0.25em; padding-bottom: 0.15em; border-bottom: 1px solid var(--vscode-panel-border); }
h3 { font-size: 1.08em; margin: 0.3em 0 0.2em; }
h4 { font-size: 0.85em; color: var(--vscode-descriptionForeground); margin: 0.5em 0 0.1em; }
p, ul { margin: 0.2em 0; }
ul { padding-left: 1.2em; }
button { font: inherit; padding: 0.2em 0.8em; color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: 1px solid var(--vscode-contrastBorder, transparent); border-radius: 2px; cursor: pointer; }
button:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }
button:disabled { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); border-style: dashed; cursor: default; }
:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 2px; }
input[type="radio"] { accent-color: var(--vscode-button-background); margin: 0.2em 0 0; }
[data-element="notice"], [data-element="failure"], [data-element="figures-failed"], [data-element="figures-unavailable"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--vscode-focusBorder); background: var(--vscode-textBlockQuote-background); }
[data-element="failure"], [data-element="figures-failed"] { border-left-color: var(--vscode-inputValidation-errorBorder); }
[data-element="unknown"] { font-weight: 600; }
[data-element="unknown"]::first-letter { text-transform: uppercase; }
[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.4em 0; }
div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"], [data-element="caption"], [data-element="limits"] { font-size: 0.9em; color: var(--vscode-descriptionForeground); }
[data-element="controls"] a { align-self: center; }
[data-element="count"] { margin: 0 0 0.2em; font-size: 0.85em; line-height: 1.2; color: var(--vscode-descriptionForeground); }
[data-element="delta"] a[data-kind="delta"] { font-size: 1.25em; font-weight: 600; }
hr { border: 0; border-top: 1px solid var(--vscode-panel-border); margin: 1em 0 0.6em; }
fieldset { margin: 0.5em 0; padding: 0.3em 0.5em 0.5em; border: 1px solid var(--vscode-panel-border); border-radius: 4px; }
label { display: grid; grid-template-columns: auto 1fr; column-gap: 0.5em; padding: 0.3em; border-radius: 3px; cursor: pointer; }
label:hover { background: var(--vscode-list-hoverBackground); }
label:has(input:checked) { background: var(--vscode-list-inactiveSelectionBackground); outline: 1px solid var(--vscode-contrastActiveBorder, transparent); }
label:has(input:disabled) { cursor: default; }
label:has(input:checked) small { color: inherit; }
label input { grid-row: 1 / span 2; align-self: start; }
label small { grid-column: 2; font-size: 0.92em; color: var(--vscode-descriptionForeground); }
fieldset button { margin-top: 0.4em; }
[data-chart] { display: grid; grid-template-columns: 6.5em minmax(3em, 1fr) auto; align-items: center; gap: 0.3em 0.5em; margin: 0.4em 0; }
li[data-chart] { list-style: none; }
[data-chart] > p { grid-column: 1 / -1; }
[data-bar] { display: contents; }
[data-bar] > span:last-child { grid-column: 3; }
[data-bar] svg { display: block; width: 100%; height: 0.75em; background: var(--vscode-editorWidget-background); }
rect { stroke: var(--vscode-contrastBorder, transparent); vector-effect: non-scaling-stroke; }
rect.control { fill: var(--vscode-charts-blue); }
rect.candidate { fill: var(--vscode-charts-orange); }
rect.scored-control { fill: var(--vscode-charts-blue); }
rect.scored-candidate { fill: var(--vscode-charts-orange); }
rect.rest { fill: transparent; stroke: var(--vscode-charts-lines); stroke-dasharray: 2 2; }
rect.cited { fill: var(--vscode-charts-lines); }
rect.latest { fill: var(--vscode-charts-foreground); }
[data-figures] { margin: 0.6em 0 0.9em; }
[data-figure] svg { display: block; width: 100%; }
[data-figure="dots"] { margin-bottom: 0.5em; }
:not([data-figures]) > [data-figure="dots"] { column-width: 18em; column-gap: 1.5em; }
[data-figure="dots"] > h4, [data-element="dot-key"], [data-element="dot-order"] { column-span: all; }
[data-figure="histogram"] svg { height: 4.5em; border-bottom: 1px solid var(--vscode-charts-lines); }
[data-figure="box"] svg { height: 1.9em; margin-top: 0.3em; }
[data-element="counts"] { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.8em; line-height: 1.3; }
[data-element="counts"] td { padding: 0.1em 0 0; text-align: center; overflow: hidden; }
[data-element="counts"] caption { caption-side: top; text-align: left; color: var(--vscode-descriptionForeground); }
[data-element="axis"] { display: flex; justify-content: space-between; gap: 0.5em; font-size: 0.85em; margin: 0.1em 0 0; }
[data-element="axis"] > span { color: var(--vscode-descriptionForeground); }
[data-element="axis"] a:only-child { margin: 0 auto; }
[data-element="quartiles"] { display: flex; flex-wrap: wrap; gap: 0.1em 0.7em; font-size: 0.82em; }
[data-key]::before { content: ""; display: inline-block; width: 0.25em; height: 0.9em; margin-right: 0.3em; vertical-align: -0.1em; }
[data-key="median"]::before { background: var(--vscode-foreground); }
[data-key="delta"]::before { width: 0.4em; height: 1.2em; vertical-align: -0.25em; background: var(--vscode-charts-green); }
[data-key="zero"]::before { width: 0.15em; height: 1.2em; vertical-align: -0.25em; background: var(--vscode-charts-lines); }
rect.column { fill: var(--vscode-charts-purple); }
rect.whisker { fill: var(--vscode-charts-purple); }
rect.cap { fill: var(--vscode-charts-purple); }
rect.box { fill: var(--vscode-charts-purple); fill-opacity: 0.35; stroke: var(--vscode-charts-purple); }
rect.median { fill: var(--vscode-foreground); }
rect.delta { fill: var(--vscode-charts-green); }
rect.zero { fill: var(--vscode-charts-lines); }
rect.whisker, rect.cap, rect.median, rect.delta, rect.zero { stroke: none; }
[data-element="dots"] { display: grid; grid-template-columns: fit-content(9.5em) minmax(3em, 1fr); align-items: center; gap: 0.1em 0.5em; }
[data-dot] { display: contents; }
[data-dot] > span { font-size: 0.8em; line-height: 1.2; overflow-wrap: anywhere; color: var(--vscode-descriptionForeground); }
[data-dot] svg { height: 0.8em; background: var(--vscode-editorWidget-background); }
[data-dot] rect { stroke: none; }
rect.between { fill: var(--vscode-charts-lines); }
rect.favours-control { fill: var(--vscode-charts-blue); }
rect.favours-candidate { fill: var(--vscode-charts-orange); }
[data-element="dot-ends"] { grid-column: 2; display: flex; justify-content: space-between; font-size: 0.85em; margin: 0 0 0.1em; }
[data-element="dot-ends"] a:only-child { margin: 0 auto; }
[data-element="dot-key"] { display: flex; gap: 1em; font-size: 0.9em; }
[data-element="dot-order"] { font-size: 0.85em; color: var(--vscode-descriptionForeground); }
[data-key="control"]::before { background: var(--vscode-charts-blue); }
[data-key="candidate"]::before { width: 0.35em; height: 0.45em; vertical-align: 0.1em; background: var(--vscode-charts-orange); }
section[data-part="decision"] { margin: 0.4em 0 0.8em; padding: 0.1em 0.6em; border-left: 3px solid var(--vscode-panel-border); }
section[data-linked], section[data-recorded] { border-left-color: var(--vscode-focusBorder); }
[data-applies] { font-size: 0.8em; font-weight: normal; padding: 0 0.5em; border-radius: 1em; color: var(--vscode-badge-foreground); background: var(--vscode-badge-background); }
[data-applies="no"] { color: inherit; background: transparent; border: 1px solid var(--vscode-editorWarning-foreground); }
[data-element="question"] { color: var(--vscode-descriptionForeground); }
[data-element="evidence"] { font-weight: 600; }
`.trim().split("\n");

// A rule whose every selector names a button of the class of the controls that open, with pseudo-classes only.
const ofTheControls = (rule: string): boolean => rule.slice(0, rule.indexOf("{")).split(",").every((selector) => /^\s*button\.open(:[a-z-]+(\([^()]*\))?)*\s*$/.test(selector));

test("each rule of the panel's style is a rule it held before the controls that open, or a rule of the class of those controls", async (t) => {
  const { style } = partsOf((await documentFor(t, success(keptObject("status-success")))).document);
  for (const rule of style.split("\n")) assert.ok(KEPT_STYLE.includes(rule) || ofTheControls(rule), rule);
  for (const rule of KEPT_STYLE) assert.ok(style.split("\n").includes(rule), `kept: ${rule}`);
});

test("a planted rule on body is neither a kept rule nor a rule of the class of the controls that open", () => {
  const rule = "body { padding: 0; }";
  assert.ok(!KEPT_STYLE.includes(rule) && !ofTheControls(rule));
  assert.ok(ofTheControls("button.open:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }"));
});
