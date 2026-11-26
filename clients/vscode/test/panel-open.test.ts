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
const [PER_ITEM, PAIRED_DELTAS, POPULATION, RECORD_FILE] = contract.open_refs;
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
const PART_KINDS = ["assessment", "comparison", "decision", "deviation"];
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
    // A control inside a closed fold is reached as a person reaches it: Enter on the fold's summary opens it, then Tab goes on.
    if (await keys.evaluate(`document.activeElement.tagName === "SUMMARY" && !document.activeElement.parentElement.open`)) {
      await keys.key("Enter");
      continue;
    }
    const place: number = await keys.evaluate(`${CONTROLS}.indexOf(document.activeElement)`);
    if (place >= 0 && !visited.has(place)) {
      visited.add(place);
      await reached(place);
    }
  }
  assert.equal(visited.size, count, "Tab reaches each control that opens");
  return count;
}

for (const name of ["status-success", "status-decided", "status-deviation"]) {
test(`in a browser, Enter on each control that opens, reached by Tab, posts one message of four keys, the message, the part's kind, its index and the ref, and no value holds a path of the read: ${name}`, { timeout: 120000 }, async (t) => {
  const read = keptObject(name);
  const { document } = await documentFor(t, success(read), ...(KEPT_FIGURES[name] ? [success(keptObject(KEPT_FIGURES[name]))] : [FIGURES_FAILED]));
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
  assert.ok(count >= outputsOf(read).length + (read.record_files ?? []).length - read.assessments.length, `${count} controls that open`);
  if (name !== "status-success") assert.ok(await keys.evaluate(`${CONTROLS}.some((c) => c.getAttribute("data-ref") === "${RECORD_FILE}" && c.getAttribute("data-part-kind") === "${name === "status-decided" ? "decision" : "deviation"}")`), "a control of the ref record of a Decision or a Declared deviation");
});
}

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

// What a case opens: a read, the message's target in it, the read with that target's path made `value`, and the files its Study folder
// holds: each output path and each record's own file that the read names.
type Target = { read: string; first: (read: Entry) => Output; withPath: (read: Entry, value: string) => Entry };
const filesOf = (read: Entry): string[] => [...outputsOf(read).map((output) => output.path), ...((read.record_files ?? []) as Entry[]).map((entry) => entry.path)];
const recordOf = (read: Entry, kind: string): Entry => read.record_files.find((entry: Entry) => entry.kind === kind);
const TARGETS: Target[] = [
  {
    read: "status-success",
    first: (read) => outputsOf(read)[0],
    withPath: (read, value) => ((read.assessments[outputsOf(read)[0].index].per_item_ref.path = value), read),
  },
  {
    read: "status-decided",
    first: (read) => ({ path: recordOf(read, "decision").path, kind: "decision", index: 0, ref: RECORD_FILE }),
    withPath: (read, value) => ((recordOf(read, "decision").path = value), read),
  },
];

// The cases of an open message given to the panel: the object the panel holds, made from the read and the Study folder (none when it
// gives undefined), what the folder holds besides the read's files, the message, what VS Code answers, whether the message is sent while a
// call is in flight, and whether the file is opened. `ref` limits a case to the target of that ref.
type Case = { name: string; held?: (read: Entry, study: string, target: Target) => Entry | undefined; files?: (study: string, t: TestContext) => void; message?: (output: Output) => Entry; shows?: () => Promise<unknown>; inFlight?: boolean; opens: boolean; ref?: string };

const CASES: Case[] = [
  { name: "the valid message", opens: true },
  { name: "a kind that names nothing in the object held", message: (output) => ({ ...messageOf(output), kind: "attempt" }), opens: false },
  { name: "an index that names nothing in the object held", message: (output) => ({ ...messageOf(output), index: 99 }), opens: false },
  { name: "a ref that names nothing in the object held", message: (output) => ({ ...messageOf(output), ref: "zq_none" }), opens: false },
  { name: "the ref of the References", message: (output) => ({ ...messageOf(output), ref: "references" }), opens: false },
  { name: "no object held", held: () => undefined, opens: false },
  { name: "an absolute path, of a file of the Study", held: (read, study, target) => target.withPath(read, path.join(study, target.first(read).path)), opens: false },
  { name: "a path with a .. segment, to a file of the Study", held: (read, _, target) => target.withPath(read, `assessments/../${target.first(read).path}`), opens: false },
  { name: "a path whose real path lies outside the Study, through a symbolic link", held: (read, _, target) => target.withPath(read, "elsewhere.csv"), files: (study, t) => fs.symlinkSync(outside(t), path.join(study, "elsewhere.csv")), opens: false },
  { name: "a file that does not exist", held: (read, _, target) => target.withPath(read, "assessments/zq-none/per_item.csv"), opens: false },
  { name: "a file VS Code does not show", shows: () => Promise.reject(new Error("not shown")), opens: false },
  { name: "a message sent while a call is in flight", inFlight: true, opens: false },
  { name: "no entry of record_files of that kind and id", held: (read) => ((read.record_files = read.record_files.filter((entry: Entry) => entry.kind !== "decision")), read), opens: false, ref: RECORD_FILE },
];

for (const target of TARGETS) {
  for (const each of CASES.filter((one) => one.ref === undefined || one.ref === target.first(keptObject(target.read)).ref)) {
    const outcome = each.opens ? "opens the file and shows no line" : each.inFlight ? "drops it, opens nothing, starts nothing and shows no line" : "opens nothing, starts nothing and shows the one fixed line in the notice";
    const { ref, kind } = target.first(keptObject(target.read));
    test(`given the open message of ${ref} of ${kind} on ${target.read} with ${each.name}, the panel ${outcome}`, async (t) => {
      const read = keptObject(target.read);
      const files = filesOf(read);
      const message = (each.message ?? messageOf)(target.first(read));
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
        const opened = await openedOn(t, files, (study) => (each.held === undefined ? read : each.held(structuredClone(read), study, target)));
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
}

// --- The own file of each record ----------------------------------------------------------------------------------------------------

// The listing, the key of a record's id and the kind of its entry of `record_files`, by the kind of a record part.
const RECORD_PARTS: Record<string, [string, string, string]> = {
  assessment: ["assessments", "assessment_id", "assessment"],
  comparison: ["comparisons", "comparison_id", "comparison"],
  decision: ["decisions", "decision_id", "decision"],
  deviation: ["declared_deviations", "declared_deviation_id", "declared_deviation"],
};
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
// The id a part shows first, outside its marked texts.
const firstId = (html: string): string | undefined => partsOf(html.replace(/<([a-z0-9]+) data-text>[^<]*<\/\1>/g, "")).between.match(UUID)?.[0];
const partsOfKind = (document: string, kind: string): string[] => [...document.matchAll(new RegExp(`<([a-z0-9]+) data-part="${kind}"[^>]*>`, "g"))].map((match) => elementOf(document.slice(match.index), match[0])!);
const withoutParts = (html: string, kind: string): string => partsOfKind(html, kind).reduce((rest, part) => rest.replace(part, ""), html);

// The one control of the ref `record` for the record of `kind` at `index`, in `html`, beside the path of its entry of `record_files`.
function assertRecordControl(html: string, document: string, read: Entry, kind: string, index: number, name: string): void {
  const [listing, key, fileKind] = RECORD_PARTS[kind];
  const id = read[listing][index][key];
  const entry = (read.record_files ?? []).find((each: Entry) => each.kind === fileKind && each.id === id);
  const controls = controlsOf(html).filter((control) => control.ref === RECORD_FILE && control.kind === kind && Number(control.index) === index);
  assert.ok(entry, `${name}: record_files lists ${kind} ${id}`);
  assert.equal(controls.length, 1, `${name}: one control of the ref record for ${kind} ${id}`);
  assert.ok(contract.labels.includes(controls[0].text), controls[0].text);
  const described = elementWithId(document, controls[0].describedBy);
  assert.deepEqual(markedTexts(described ?? ""), [entry.path], `${name}: the control of ${kind} ${id} is described by its path`);
  const holder = [...html.matchAll(/<(p|span) data-element="record-file">/g)].map((match) => elementOf(html.slice(match.index), match[0])!).find((each) => each.includes(controls[0].tag));
  assert.ok(holder?.includes(described!) && !holder.includes("<a "), `${name}: the path stands beside the control, with no link`);
}

function assertOneRecordControlPerPart(document: string, read: Entry, name: string): void {
  for (const [kind, [listing, key, fileKind]] of Object.entries(RECORD_PARTS)) {
    for (const part of partsOfKind(document, kind)) {
      const id = firstId(part);
      const index = (read[listing] as Entry[]).findIndex((record) => record[key] === id);
      const listed = (read.record_files ?? []).some((entry: Entry) => entry.kind === fileKind && entry.id === id);
      if (listed) assertRecordControl(part, document, read, kind, index, name);
      else assert.deepEqual(controlsOf(part).filter((control) => control.ref === RECORD_FILE && control.kind === kind), [], `${name}: no control of the ref record for ${kind} ${id}`);
    }
  }
  read.decisions.forEach((decision: Entry, at: number) => {
    const part = partsOfKind(document, "decision").find((each) => firstId(each) === decision.decision_id);
    if (part === undefined) return;
    const named = new Set<string>((decision.evidence_change?.lines ?? []).flatMap((line: Entry) => [line.assessment_id, line.latest_assessment_id]));
    for (const id of named) {
      const index = read.assessments.findIndex((each: Entry) => each.assessment_id === id);
      if (index < 0 || !(read.record_files ?? []).some((entry: Entry) => entry.kind === "assessment" && entry.id === id)) continue;
      assertRecordControl(withoutParts(part, "assessment"), document, read, "assessment", index, `${name}, Decision ${at}`);
    }
  });
  const study = elementOf(document, '<div data-part="study"') ?? "";
  assert.deepEqual(controlsOf(study), [], `${name}: the Study's part holds no control that opens`);
  for (const summary of [...document.matchAll(/<div data-summary="comparison">/g)].map((match) => elementOf(document.slice(match.index), match[0])!)) {
    assert.deepEqual(controlsOf(summary), [], `${name}: a Comparison's summary holds no control that opens`);
  }
}

for (const name of KEPT_READS) {
  test(`each record part whose record record_files lists holds one control that opens its own file, beside its path, and each Decision's part one for each Assessment of its evidence: ${name}`, async (t) => {
    const read = keptObject(name);
    assertOneRecordControlPerPart((await documentFor(t, success(read))).document, read, name);
  });
}

test("a read without record_files gives no control of the ref record", async (t) => {
  for (const name of ["status-success", "status-decided", "status-deviation", "status-result-changed"]) {
    const read = keptObject(name);
    delete read.record_files;
    const { document } = await documentFor(t, success(read));
    assert.deepEqual(controlsOf(document).filter((control) => control.ref === RECORD_FILE), [], name);
  }
});

for (const name of ["status-decided", "status-deviation"]) {
  test(`the open message of each control of the ref record of ${name} shows the Study folder joined to the path of its entry of record_files, then makes it read-only`, async (t) => {
    const read = keptObject(name);
    const { study } = await openedOn(t, filesOf(read), () => read);
    const controls = controlsOf(lastDocument()).filter((control) => control.ref === RECORD_FILE);
    assert.ok(controls.length >= read.record_files.length - read.assessments.length, `${controls.length} controls of the ref record`);
    for (const control of controls) {
      const before = stub.calls.length;
      panelOf().send({ message: OPEN, kind: control.kind, index: Number(control.index), ref: control.ref });
      await settled();
      const [listing, key, fileKind] = RECORD_PARTS[control.kind!];
      const entry = read.record_files.find((each: Entry) => each.kind === fileKind && each.id === read[listing][Number(control.index)][key]);
      const calls = stub.calls.slice(before);
      assert.deepEqual(calls.map((call) => call.name), ["showTextDocument", "executeCommand"], control.tag);
      assert.equal((calls[0].args[0] as { fsPath: string }).fsPath, path.join(study, entry.path), control.tag);
    }
  });
}

test("status-success whose entry of record_files for its first Assessment names another file of the Study: that file is shown, and no path is composed from the id", async (t) => {
  const read = keptObject("status-success");
  const entry = recordOf(read, "assessment");
  const index = read.assessments.findIndex((each: Entry) => each.assessment_id === entry.id);
  const other = read.assessments[index].per_item_ref.path;
  const composed = `assessments/${entry.id}/assessment.json`;
  assert.equal(entry.path, composed);
  entry.path = other;
  const { study } = await openedOn(t, filesOf(read).concat([composed]), () => read);
  panelOf().send({ message: OPEN, kind: "assessment", index, ref: RECORD_FILE });
  await settled();
  assert.deepEqual(stub.callsOf("showTextDocument").map((call) => (call.args[0] as { fsPath: string }).fsPath), [path.join(study, other)]);
});

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

// The rules of the panel's style but those of the controls that open, one per line, each colour taken from the palettes.
const KEPT_STYLE = String.raw`
body.vscode-dark{ --board:#20312C;--board2:#1A2925;--chalk:#EDE8DA;--chalk2:#C9C4B6;--faint:#9AA59E;--line:rgba(237,232,218,.16);--line2:rgba(237,232,218,.32);--yellow:#F0D178;--pink:#EFA3B8;--mint:#B9E2C4;--teal:#9FE0D2;--violet:#C8B6F5;--coral:#F3A28F;--card:#F5F1E6;--cardink:#22302B;--cardmuted:#4E5A55;--cardline:rgba(34,48,43,.18);--cardline2:rgba(34,48,43,.36);--cardsoft:#ECE7D8;--paperbg:repeating-linear-gradient(0deg,rgba(38,72,124,.045) 0 1px,transparent 1px 12px),repeating-linear-gradient(90deg,rgba(38,72,124,.045) 0 1px,transparent 1px 12px);--red:#B8322A;--pen:#1E4E9E;--orange:#C2571A;--leaf:#17643A;--plum:#6B46C1;--ochre:#B07418;--ochre-ink:#7E5310;--slate:#2E5446;--btnfg:#F5F1E6;--btnborder:#2E5446;--refgrey:#6E767B;--hl:rgba(240,209,120,.28);--focus:#F0D178;--focuspaper:#1E4E9E;--shadow:0 14px 26px -16px rgba(0,0,0,.6),0 1px 0 rgba(0,0,0,.2);--hit:rgba(255,222,64,.55);--hitcur:#F0A500;color-scheme:dark}
body.vscode-light{ --board:#F1F3F1;--board2:#E4E8E4;--chalk:#1E2A36;--chalk2:#3E4A57;--faint:#56616D;--line:rgba(30,42,54,.14);--line2:rgba(30,42,54,.32);--yellow:#7A5D00;--pink:#A3304D;--mint:#17643A;--teal:#0B6B60;--violet:#5B3AAE;--coral:#A8361F;--card:#FFFFFF;--cardink:#22302B;--cardmuted:#4E5A55;--cardline:rgba(34,48,43,.16);--cardline2:rgba(34,48,43,.34);--cardsoft:#F1EFE9;--paperbg:repeating-linear-gradient(0deg,rgba(38,72,124,.035) 0 1px,transparent 1px 12px),repeating-linear-gradient(90deg,rgba(38,72,124,.035) 0 1px,transparent 1px 12px);--red:#B8322A;--pen:#1E4E9E;--orange:#C2571A;--leaf:#17643A;--plum:#6B46C1;--ochre:#B07418;--ochre-ink:#7E5310;--slate:#2E5446;--btnfg:#FFFFFF;--btnborder:#2E5446;--refgrey:#6E767B;--hl:rgba(183,121,31,.16);--focus:#1E4E9E;--focuspaper:#1E4E9E;--shadow:0 10px 22px -16px rgba(30,42,54,.45),0 1px 0 rgba(30,42,54,.12);--hit:rgba(255,222,64,.55);--hitcur:#F0A500;color-scheme:light}
body.vscode-high-contrast{ --board:var(--vscode-editor-background);--board2:var(--vscode-editor-background);--chalk:var(--vscode-editor-foreground);--chalk2:var(--vscode-foreground);--faint:var(--vscode-foreground);--line:var(--vscode-contrastBorder);--line2:var(--vscode-contrastBorder);--yellow:var(--vscode-contrastActiveBorder);--pink:var(--vscode-errorForeground);--mint:var(--vscode-charts-green);--teal:var(--vscode-textLink-foreground);--violet:var(--vscode-charts-purple);--coral:var(--vscode-editorWarning-foreground);--card:var(--vscode-editor-background);--cardink:var(--vscode-editor-foreground);--cardmuted:var(--vscode-foreground);--cardline:var(--vscode-contrastBorder);--cardline2:var(--vscode-contrastBorder);--cardsoft:var(--vscode-editor-background);--paperbg:none;--red:var(--vscode-errorForeground);--pen:var(--vscode-textLink-foreground);--orange:var(--vscode-editorWarning-foreground);--leaf:var(--vscode-charts-green);--plum:var(--vscode-charts-purple);--ochre:var(--vscode-editorWarning-foreground);--ochre-ink:var(--vscode-textLink-foreground);--slate:var(--vscode-button-background,var(--vscode-editor-background));--btnfg:var(--vscode-button-foreground,var(--vscode-editor-foreground));--btnborder:var(--vscode-button-border,var(--vscode-contrastBorder));--refgrey:var(--vscode-foreground);--hl:var(--vscode-editor-background);--focus:var(--vscode-focusBorder);--focuspaper:var(--vscode-focusBorder);--shadow:none;--hit:var(--vscode-editor-background);--hitcur:var(--vscode-contrastActiveBorder)} 
body.vscode-dark, body.vscode-high-contrast:not(.vscode-high-contrast-light) { color-scheme: dark; }
body { color: var(--chalk); background: var(--board); font-family: var(--vscode-font-family); line-height: 1.4; }
main { max-width: 46em; overflow-wrap: anywhere; }
a { color: var(--teal); }
section[data-part="now"] > h2 { color: var(--yellow); }
[data-element="band"] { margin: 0 0 0.2em; font-size: 0.9em; color: var(--chalk2); }
section[data-part="path"] h3 { font-size: 0.85em; color: var(--chalk2); margin: 0.5em 0 0.1em; }
details[data-step] { margin: 0.15em 0; }
details[data-step] > summary { color: var(--chalk); }
[data-element="form"], [data-element="chart"], [data-element="limitation"] { margin: 0.2em 0 0.4em 1em; }
[data-element="limitation"] { font-size: 0.9em; color: var(--chalk2); }
[data-mark] { font-weight: 700; color: var(--coral); }
div[data-part="study"] { font-size: 0.85em; }
h1 { font-size: 0.9em; font-weight: normal; margin: 0.4em 0; color: var(--chalk2); overflow-wrap: anywhere; }
h2 { font-size: 0.9em; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--chalk2); margin: 0.5em 0 0.2em; padding-bottom: 0.1em; border-bottom: 1px solid var(--line2); }
h3 { font-size: 1.08em; margin: 0.3em 0 0.2em; }
h4 { font-size: 0.85em; color: var(--chalk2); margin: 0.5em 0 0.1em; }
p, ul { margin: 0.2em 0; }
ul { padding-left: 1.2em; }
button { font: inherit; padding: 0.2em 0.8em; color: var(--btnfg); background: var(--slate); border: 1px solid var(--chalk2); border-radius: 2px; cursor: pointer; }
button:hover:not(:disabled) { background: var(--pen); }
button:disabled { color: var(--cardink); background: var(--cardsoft); border-style: dashed; cursor: default; }
:focus-visible { outline: 1px solid var(--focus); outline-offset: 2px; }
input[type="radio"] { accent-color: var(--slate); margin: 0.2em 0 0; }
[data-element="notice"], [data-element="failure"], [data-element="figures-failed"], [data-element="figures-unavailable"] { margin: 0.3em 0; padding: 0.3em 0.6em; border-left: 3px solid var(--focus); background: var(--board2); }
[data-element="failure"], [data-element="figures-failed"] { border-left-color: var(--red); }
[data-element="unknown"] { font-weight: 600; }
[data-element="unknown"]::first-letter { text-transform: uppercase; }
[data-element="controls"] { display: flex; gap: 0.4em; margin: 0.3em 0 0.2em; }
div[data-part="comparison"] > p:first-child, div[data-summary="comparison"] > p:first-child, [data-element="coverage"], [data-element="definition"], [data-element="caption"], [data-element="limits"] { font-size: 0.9em; color: var(--chalk2); }
[data-element="controls"] a { align-self: center; }
[data-element="count"] { margin: 0 0 0.2em; font-size: 0.85em; line-height: 1.2; color: var(--chalk2); }
[data-element="delta"] a[data-kind="delta"] { font-size: 1.25em; font-weight: 600; }
hr { border: 0; border-top: 1px solid var(--line2); margin: 1em 0 0.6em; }
fieldset { margin: 0.5em 0; padding: 0.3em 0.5em 0.5em; border: 1px solid var(--line2); border-radius: 4px; }
label { display: grid; grid-template-columns: auto 1fr; column-gap: 0.5em; padding: 0.3em; border-radius: 3px; cursor: pointer; }
label:hover { background: var(--hl); }
label:has(input:checked) { background: var(--hl); outline: 1px solid var(--yellow); }
label:has(input:disabled) { cursor: default; }
label:has(input:checked) small { color: inherit; }
label input { grid-row: 1 / span 2; align-self: start; }
label small { grid-column: 2; font-size: 0.92em; color: var(--chalk2); }
fieldset button { margin-top: 0.4em; }
details[data-element="add-words"] { margin-top: 0.3em; font-size: 0.9em; }
label[data-element="words"] { display: block; margin-top: 0.2em; padding: 0; color: var(--chalk2); cursor: default; }
label[data-element="words"]:hover { background: transparent; }
textarea { display: block; box-sizing: border-box; width: 100%; margin-top: 0.15em; font: inherit; color: var(--chalk); background: var(--board2); border: 1px solid var(--chalk2); border-radius: 2px; resize: vertical; }
[data-chart] { display: grid; grid-template-columns: 6.5em minmax(3em, 1fr) auto; align-items: center; gap: 0.3em 0.5em; margin: 0.4em 0; }
li[data-chart] { list-style: none; }
[data-chart] > p { grid-column: 1 / -1; }
[data-bar] { display: contents; }
[data-bar] > span:last-child { grid-column: 3; }
[data-bar] svg { display: block; width: 100%; height: 0.75em; background: var(--board2); }
rect { stroke: var(--line); vector-effect: non-scaling-stroke; }
rect.control { fill: var(--pen); }
rect.candidate { fill: var(--orange); }
rect.scored-control { fill: var(--pen); }
rect.scored-candidate { fill: var(--orange); }
rect.rest { fill: transparent; stroke: var(--line2); stroke-dasharray: 2 2; }
rect.cited { fill: var(--line2); }
rect.latest { fill: var(--chalk2); }
rect.feature { fill: var(--faint); }
details[data-element="charts"] { margin: 0.4em 0; }
summary { cursor: pointer; color: var(--teal); }
details[data-element="consequence"] > summary { font-size: 0.85em; }
[data-element="interval"], [data-element="context"], [data-element="cited-delta"], [data-element="frame"] { font-size: 0.9em; color: var(--chalk2); }
[data-element="interval"] { display: block; }
[data-figures] { margin: 0.6em 0 0.9em; }
[data-figure] svg { display: block; width: 100%; }
[data-figure="dots"] { margin-bottom: 0.5em; }
:not([data-figures]) > [data-figure="dots"] { column-width: 18em; column-gap: 1.5em; }
[data-figure="dots"] > h4, [data-element="dot-key"], [data-element="dot-order"] { column-span: all; }
[data-figure="histogram"] svg { height: 4.5em; border-bottom: 1px solid var(--line2); }
[data-figure="box"] svg { height: 1.9em; margin-top: 0.3em; }
[data-element="counts"] { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.8em; line-height: 1.3; }
[data-element="counts"] td { padding: 0.1em 0 0; text-align: center; overflow: hidden; }
[data-element="counts"] caption { caption-side: top; text-align: left; color: var(--chalk2); }
[data-element="axis"] { display: flex; justify-content: space-between; gap: 0.5em; font-size: 0.85em; margin: 0.1em 0 0; }
[data-element="axis"] > span { color: var(--chalk2); }
[data-element="axis"] a:only-child { margin: 0 auto; }
[data-element="quartiles"] { display: flex; flex-wrap: wrap; gap: 0.1em 0.7em; font-size: 0.82em; }
[data-key]::before { content: ""; display: inline-block; width: 0.25em; height: 0.9em; margin-right: 0.3em; vertical-align: -0.1em; }
[data-key="median"]::before { background: var(--chalk); }
[data-key="delta"]::before { width: 0.4em; height: 1.2em; vertical-align: -0.25em; background: var(--mint); }
[data-key="zero"]::before { width: 0.15em; height: 1.2em; vertical-align: -0.25em; background: var(--line2); }
rect.column { fill: var(--violet); }
rect.whisker { fill: var(--violet); }
rect.cap { fill: var(--violet); }
rect.box { fill: var(--violet); fill-opacity: 0.35; stroke: var(--violet); }
rect.median { fill: var(--chalk); }
rect.delta { fill: var(--mint); }
rect.zero { fill: var(--line2); }
rect.whisker, rect.cap, rect.median, rect.delta, rect.zero { stroke: none; }
[data-element="dots"] { display: grid; grid-template-columns: fit-content(9.5em) minmax(3em, 1fr); align-items: center; gap: 0.1em 0.5em; }
[data-dot] { display: contents; }
[data-dot] > span { font-size: 0.8em; line-height: 1.2; overflow-wrap: anywhere; color: var(--chalk2); }
[data-dot] svg { height: 0.8em; background: var(--board2); }
[data-dot] rect { stroke: none; }
rect.between { fill: var(--line2); }
rect.favours-control { fill: var(--pen); }
rect.favours-candidate { fill: var(--orange); }
[data-element="dot-ends"] { grid-column: 2; display: flex; justify-content: space-between; font-size: 0.85em; margin: 0 0 0.1em; }
[data-element="dot-ends"] a:only-child { margin: 0 auto; }
[data-element="dot-key"] { display: flex; gap: 1em; font-size: 0.9em; }
[data-element="dot-order"] { font-size: 0.85em; color: var(--chalk2); }
[data-key="control"]::before { background: var(--pen); }
[data-key="candidate"]::before { width: 0.35em; height: 0.45em; vertical-align: 0.1em; background: var(--orange); }
section[data-part="decision"] { margin: 0.4em 0 0.8em; padding: 0.1em 0.6em; border-left: 3px solid var(--line2); }
section[data-linked], section[data-recorded] { border-left-color: var(--focus); }
[data-applies] { font-size: 0.8em; font-weight: normal; padding: 0 0.5em; border-radius: 1em; color: var(--cardink); background: var(--card); }
[data-applies="no"] { color: inherit; background: transparent; border: 1px solid var(--coral); }
[data-element="question"] { color: var(--chalk2); }
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
  assert.ok(ofTheControls("button.open:hover:not(:disabled) { background: var(--card); }"));
});

// "`open` refuses any path under that Attempt's folder" (D-143, correction 1): an Attempt no Assessment cites, and the same path once one does.
for (const cited of [false, true]) {
  test(`the open message of a path under the folder of an Attempt ${cited ? "an Assessment cites opens it" : "that no Assessment cites opens nothing and gives the notice"}: status-success with a per_item path planted under that folder`, async (t) => {
    const read = keptObject("status-success");
    const [attempt] = read.attempts;
    const planted = `attempts/${attempt.attempt_id}/predictions.csv`;
    read.assessments[0].per_item_ref.path = planted;
    if (!cited) attempt.observation_set_id = "c53337e9-d255-423d-a851-414278d5c3f0";
    else read.assessments[0].observation_set_id = attempt.observation_set_id;
    await openedOn(t, [planted], () => read);
    const documents = panelOf().documents.length;
    panelOf().send({ message: OPEN, kind: "assessment", index: 0, ref: contract.open_refs[0] });
    await settled();
    assert.equal(stub.callsOf("showTextDocument").length, cited ? 1 : 0, "what was asked of the editor");
    if (!cited) assert.ok(partsOf(lastDocument()).between.includes(NOT_OPENED) && panelOf().documents.length === documents + 1, "the notice of a file not opened");
  });
}
