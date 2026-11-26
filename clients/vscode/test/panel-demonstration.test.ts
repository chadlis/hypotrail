// The panel walked through the demonstration: at each state the demonstration kept, the document a person would see then, read
// against the kept read it was made from; the two actions that record the Decision of task 3, in a browser and through the bridge;
// the write the Study refuses at S1; and whether every number and file name leads to its record.
// "At chosen states of the demonstration, the client's tests build the real webview document from that state's `status --json`
// and `figures --json`, and assert what a person sees and can do: the question, the delta, the options, the path to Record, and
// whether every number and file name leads to its record." (chadlis/hypotrail#218, item 4.)
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";
import contract from "../contract.json";
import * as bridge from "../src/bridge";
import { CHROME, START_MS, pageOf, startChrome } from "./chrome";
import { DEMONSTRATION, KEPT, kept } from "./kept";
import { KEPT_FIGURES, KEPT_READS, documentFor, elementOf, elementsOf, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, unescaped, workspace } from "./panel-harness";
import { exit, recorder, type Answer, type RecordedCall } from "./recorder";

type Entry = Record<string, any>;
type Seen = { document: string; read: Entry; figures: Entry };

const [, RECORD] = contract.messages;

// The kept states of the demonstration on disk: each state whose status read the folder holds.
function statesOnDisk(): string[] {
  return fs
    .readdirSync(path.join(KEPT, "demonstration"))
    .filter((name) => name.endsWith(".status.out"))
    .map((name) => name.slice(0, -".status.out".length))
    .sort();
}

const readOf = (state: string): string => `${DEMONSTRATION}${state}.status`;
const figuresOf = (state: string): string => `${DEMONSTRATION}${state}.figures`;
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
const keptJson = (name: string): Entry => JSON.parse(kept(`${name}.out`));

// A label of the panel, read from contract.json: the test fails on a text that is not one of its labels.
// The words of a Comparison's delta element as read: the delta with its Metric and unit, then, where the read holds an interval for a
// delta that is not withheld, its level, its two bounds and its resampling unit, or its reason where a bound is null.
function deltaWords(comparison: Entry): string {
  const { delta, interval } = comparison;
  const line = `${label("Delta")} ${written(delta.value)} ${delta.metric} ${delta.unit}`;
  if (delta.value === null || interval === undefined || interval === null) return line;
  if (interval.lower === null || interval.upper === null) return `${line} ${label("Interval")} ${interval.reason}`;
  return `${line} ${label("Interval")} ${written(interval.level)} ${written(interval.lower)} ${written(interval.upper)} ${label("resampling unit")} ${interval.unit}`;
}

function label(text: string): string {
  assert.ok(contract.labels.includes(text), `${text} is a label of contract.json`);
  return text;
}
const phrases = (list: string[]): Map<string, string> => new Map(list.map((entry) => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)]));
const APPLIES = phrases(contract.applies_phrases);
const EVIDENCE = phrases(contract.evidence_phrases);
const applies = (value: boolean): string => APPLIES.get(String(value))!;

// A number written by another route than the client's, to find a value in a document.
function written(value: number | null): string {
  if (value === null) return contract.no_value;
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");
// The part of a document between two of the headings of the step of the Decisions.
const under = (document: string, heading: string, next: string): string => document.slice(document.indexOf(`<h4>${label(heading)}</h4>`), document.indexOf(`<h4>${label(next)}</h4>`));
// Now, where the Pending decision the core names stands.
const nowPart = (document: string): string => elementOf(document, '<section data-part="now"') ?? "";
const questionsOf = (html: string): string[] => [...html.matchAll(/<h3 data-text>([^<]*)<\/h3>/g)].map((match) => unescaped(match[1]));
const linkTexts = (html: string, kind: string): string[] => [...html.matchAll(new RegExp(`<a [^>]*data-kind="${kind}"[^>]*>([^<]*)</a>`, "g"))].map((match) => match[1]);
const decisionParts = (document: string): string[] => elementsOf(document, '<section data-part="decision"');

// The document a person sees at a kept state: the panel opened by the command, its status call and its figures call answered with
// the two kept reads of that state.
async function seenAt(t: TestContext, state: string, read = readOf(state)): Promise<Seen> {
  const figures = read.replace(/\.status$/, ".figures");
  const { document } = await documentFor(t, keptAnswer(read), keptAnswer(figures));
  return { document, read: keptJson(read), figures: keptJson(figures) };
}

// What every document of a kept state shows: the Study id and the Write sequence of the read.
function assertStudy({ document, read }: Seen): void {
  assert.equal(words(elementOf(document, '<div data-part="study"')), `${read.study.study_id} ${label("Write sequence")} ${written(read.write_sequence)}`);
}

// No pending decision: Now holds no count of pending decisions and states that no decision waits (D-161).
function assertNoPending({ document }: Seen): void {
  const now = elementOf(document, '<section data-part="now"')!;
  assert.ok(!partsOf(now).tags.some((tag) => tag.includes('data-element="count"')), "no count of pending decisions, whatever its tag");
  assert.equal(words(elementOf(now, '<p data-element="now-question">')), label("No decision waits for you."));
}

// The one Pending decision, in Now: its question, its options with their consequences, the delta of its Comparison, the
// Metric of the Control and of the Candidate, the Comparison's warning and limitations, and its figures.
function assertPending({ document, read, figures }: Seen): Entry {
  const part = nowPart(document);
  const [pending] = read.pending_decisions;
  assert.equal(read.pending_decisions.length, 1);
  assert.deepEqual(questionsOf(part), [pending.question.text], "one question, the read's");
  assert.deepEqual(elementsOf(part, "<label>").map(markedTexts), pending.options.map((option: Entry) => [option.text, option.consequence]), "each option with its consequence");
  assert.equal(partsOf(part).tags.filter((tag) => tag.startsWith('<input type="radio"')).length, pending.options.length, "one radio input per option");
  const comparison = read.comparisons.find((each: Entry) => each.comparison_id === pending.comparison_id);
  const { delta } = comparison;
  assert.equal(words(elementOf(part, '<p data-element="delta">')), deltaWords(comparison), "the delta of the Comparison");
  for (const [role, name] of [["control", "Control"], ["candidate", "Candidate"]]) {
    const assessment = read.assessments.find((each: Entry) => each.assessment_id === pending[`${role}_assessment_id`]);
    const metric = assessment.metrics.find((each: Entry) => each.id === delta.metric);
    const shown = words(elementOf(part, `<div data-role="${role}">`));
    assert.ok(shown.startsWith(`${label(name)} ${label("Assessment")} ${assessment.assessment_id}`), shown);
    assert.ok(shown.includes(`${label("Metric")} ${metric.id} ${written(metric.value)} ${metric.unit}`), `the Metric of the ${name}: ${shown}`);
  }
  const warning = comparison.warnings.find((each: Entry) => each.code === "COMPARISON_SINGLE_FEATURE_BEATS");
  assert.ok(warning, "the read holds the warning");
  const warnings = elementOf(part, '<div data-part="warnings"')!;
  assert.ok(warnings.includes(`<h4>${label("Warnings of the Comparison")}</h4>`));
  assert.ok(elementsOf(warnings, "<li>").map(words).includes(`${warning.code} ${warning.message}`), "the message of the warning");
  const limitations = elementOf(part, '<div data-part="limitations"')!;
  assert.ok(limitations.includes(`<h4>${label("Limitations of the Comparison")}</h4>`));
  // "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
  const messages = comparison.warnings.map((each: Entry) => each.message);
  assert.deepEqual(markedTexts(limitations), comparison.limitations.filter((each: string) => !messages.includes(each)), "each limitation that is no warning's message");
  const entry = figures.comparisons.find((each: Entry) => each.comparison_id === comparison.comparison_id);
  const shownFigures = elementOf(part, "<div data-figures>") ?? "";
  assert.deepEqual(linkTexts(shownFigures, "bin_count"), entry.histogram.map((bin: Entry) => written(bin.count)), "the counts of the figures");
  assert.deepEqual(linkTexts(shownFigures, "quartile"), ["min", "q1", "median", "q3", "max"].map((key) => written(entry.quartiles[key])), "the five numbers of the figures");
  return comparison;
}

// A Decision's part: its option and the phrase of its applies, and its author.
function assertDecision(part: string, decision: Entry, appliesValue: boolean, author: string): void {
  assert.equal(decision.applies, appliesValue);
  assert.equal(words(elementOf(part, "<h3>")), `${decision.option} ${applies(appliesValue)}`, "the option and the phrase of its applies");
  // "a Decision's `source` beside its author" (D-151, answer 7)
  const source = decision.source === null ? "" : ` ${label("Source")} ${decision.source}`;
  assert.ok(elementsOf(part, "<p>").map(words).includes(`${label("Author")} ${author}${source}`), `the author ${author}${source}`);
}

// The state of a Decision's evidence and each of its two lines, one per side: the phrase, the changed Items, the cited and the latest value.
function assertEvidence(part: string, decision: Entry, state: string, changed: number): { cited: string[]; latest: string[] } {
  assert.equal(words(elementOf(part, '<p data-element="evidence">')), `${EVIDENCE.get(state)} revision_changed`, "the phrase of the evidence and the reason revision_changed");
  const lines = elementsOf(part, '<li data-part="line">');
  assert.deepEqual(decision.evidence_change.lines.map((line: Entry) => line.role), ["control", "candidate"]);
  assert.equal(lines.length, 2, "a line for each side");
  const cited: string[] = [];
  const latest: string[] = [];
  decision.evidence_change.lines.forEach((line: Entry, at: number) => {
    const [metric] = line.metrics;
    assert.ok(words(lines[at]).startsWith(`${EVIDENCE.get(state)} ${label("Changed Items")} ${changed}`), words(lines[at]));
    assert.equal(line.changed_item_count, changed);
    assert.ok(words(lines[at]).includes(`${label("Cited value")} ${written(metric.cited)} ${label("Latest value")} ${written(metric.latest)}`), words(lines[at]));
    cited.push(linkTexts(lines[at], "cited")[0]);
    latest.push(linkTexts(lines[at], "latest")[0]);
  });
  return { cited, latest };
}

// The Pending decision of the last two kept states before the proxy Decision: one question, on the Comparison of the two Assessments
// the earlier Decision's evidence names as the latest, and that Decision, which does not apply.
function assertAskedAgain(seen: Seen): void {
  const { document, read } = seen;
  assertPending(seen);
  const [earlier] = read.decisions;
  const latest = earlier.evidence_change.lines.map((line: Entry) => line.latest_assessment_id);
  const [pending] = read.pending_decisions;
  assert.deepEqual([pending.control_assessment_id, pending.candidate_assessment_id], latest, "the Comparison of the two latest Assessments");
  const part = nowPart(document);
  assert.equal(words(elementOf(part, '<div data-part="comparison"')).split(" ").slice(0, 2).join(" "), `${label("Comparison")} ${pending.comparison_id}`);
  assert.equal(decisionParts(document).length, 1, "the earlier Decision alone");
  assertDecision(decisionParts(document)[0], earlier, false, "human");
}

// The one Pending decision of the copy of the kept Chinook Campaign, in Now: its question, the delta of its Comparison, its options with their
// consequences, and the path to Record, a radio input per option and the control that records the first Pending decision. "With a
// null delta, ticket 3 shows the two per-side matrices and the unscored Episodes with their reasons, states that no delta was
// computable, and shows no delta or share figure" (D-146 on chadlis/hypotrail#75, B2): the kept Comparison has a delta, so the
// document shows it.
function assertCampaignPending({ document, read }: Seen): void {
  const part = nowPart(document);
  assert.equal(read.pending_decisions.length, 1);
  const [pending] = read.pending_decisions;
  assert.deepEqual(questionsOf(part), [pending.question.text], "one question, the read's");
  const comparison = read.comparisons.find((each: Entry) => each.comparison_id === pending.comparison_id);
  const { delta } = comparison;
  assert.notEqual(delta.value, null, "the Comparison has a delta");
  assert.equal(words(elementOf(part, '<p data-element="delta">')), deltaWords(comparison), "the delta of the Comparison");
  assert.deepEqual(elementsOf(part, "<label>").map(markedTexts), pending.options.map((option: Entry) => [option.text, option.consequence]), "each option with its consequence");
  const tags = partsOf(part).tags;
  assert.equal(tags.filter((tag) => tag.startsWith('<input type="radio"')).length, pending.options.length, "one radio input per option");
  assert.equal(tags.filter((tag) => tag.startsWith("<button") && tag.includes(`data-message="${RECORD}"`) && tag.includes('data-pending="0"')).length, 1, "the control that records");
}

// The values C5-check prints, at the key paths it prints them at (tests/test_demonstration_end_to_end.py ties them to the transcript).
const C5_PATHS = ["study.study_id", "write_sequence", "pending_decisions[*].comparison_id", "decisions[*].decision_id", "decisions[*].applies"];
function valueAt(object: unknown, keyPath: string): unknown {
  const [head, ...rest] = keyPath.split(".");
  const tail = rest.join(".");
  if (head.endsWith("[*]")) return ((object as Entry)[head.slice(0, -3)] as unknown[]).map((each) => (tail ? valueAt(each, tail) : each));
  const value = (object as Entry)[head];
  return tail ? valueAt(value, tail) : value;
}

// What a person sees at each kept state of the demonstration, by its name.
const SEES: Record<string, (seen: Seen) => void> = {
  "after-compare": (seen) => {
    assertPending(seen);
    assert.equal(elementOf(seen.document, '<details data-step="decisions">'), undefined, "no step of the Decisions, no Decision being recorded");
  },
  "after-decide": (seen) => {
    assertNoPending(seen);
    const parts = decisionParts(seen.document);
    assert.equal(parts.length, 1, "one Decision");
    const [decision] = seen.read.decisions;
    assertDecision(parts[0], decision, true, "human");
    assert.ok(words(elementOf(parts[0], '<ul data-element="cited">')).split(" ").includes(seen.read.comparisons[0].comparison_id), "the Comparison among its cited ids");
  },
  "after-6.1": (seen) => {
    const parts = decisionParts(seen.document);
    const [decision] = seen.read.decisions;
    assertDecision(parts[0], decision, false, "human");
    const { cited, latest } = assertEvidence(parts[0], decision, "evidence_rescored", 0);
    assert.deepEqual(cited, latest, "a cited value equal to the latest value");
    const recorded = seen.read.comparisons.find((each: Entry) => decision.cited_ids.includes(each.comparison_id));
    // A summary of the Comparison holds its delta without the interval, which stands in the Comparison's part.
    const summaries = elementsOf(seen.document, '<div data-summary="comparison">').map((summary) => words(elementOf(summary, '<p data-element="delta">')));
    const deltas = elementsOf(seen.document, '<p data-element="delta">').map(words);
    const inParts = [...deltas];
    for (const each of summaries) inParts.splice(inParts.indexOf(each), 1);
    assert.ok(summaries.every((each) => each === `${label("Delta")} ${written(recorded.delta.value)} ${recorded.delta.metric} ${recorded.delta.unit}`), `no summary delta but the recorded Comparison's: ${summaries.join(" | ")}`);
    assert.ok(inParts.length > 0 && inParts.every((each) => each === deltaWords(recorded)), `no delta but the recorded Comparison's: ${deltas.join(" | ")}`);
    assert.ok(linkTexts(seen.document, "delta").every((each) => each === written(recorded.delta.value)), linkTexts(seen.document, "delta").join(" | "));
  },
  "after-6.2": (seen) => {
    const [decision] = seen.read.decisions;
    const part = decisionParts(seen.document)[0];
    assertDecision(part, decision, false, "human");
    const { cited, latest } = assertEvidence(part, decision, "result_changed", 1);
    cited.forEach((each, at) => assert.notEqual(each, latest[at], "the cited and the latest value differ"));
    // C5-check.
    const [studyId, sequence, pending, ids, values] = C5_PATHS.map((keyPath) => valueAt(seen.read, keyPath)) as [string, number, string[], string[], boolean[]];
    assert.equal(words(elementOf(seen.document, '<div data-part="study"')), `${studyId} ${label("Write sequence")} ${written(sequence)}`, "the study id and the Write sequence of C5-check");
    assert.equal(words(elementOf(seen.document, '<p data-element="band">')), `${label("Write sequence")} ${written(sequence)}`, "the Write sequence of C5-check in the band");
    assert.ok(elementOf(seen.document, '<section data-part="path">')!.includes('<div data-part="study"'), "the Study id of C5-check under The Study so far");
    assert.deepEqual(elementsOf(seen.document, '<section data-part="pending">').map((each) => /<p>Comparison <span>([^<]*)<\/span><\/p>/.exec(each)?.[1]), pending, "the pending ids of C5-check");
    assert.deepEqual(decisionParts(seen.document).map((each) => [/<p><span>([^<]*)<\/span><\/p>/.exec(each)?.[1], words(elementOf(each, "<h3>")).endsWith(applies(true)) && !words(elementOf(each, "<h3>")).endsWith(applies(false))]), ids.map((id, at) => [id, values[at]]), "each Decision of C5-check with applies or does not apply");
  },
  "before-the-refused-write": assertAskedAgain,
  "after-the-terminal-wrote": assertAskedAgain,
  final: (seen) => {
    assertNoPending(seen);
    const parts = decisionParts(seen.document);
    assert.equal(parts.length, 2, "two Decisions");
    assertDecision(parts[0], seen.read.decisions[0], false, "human");
    assertDecision(parts[1], seen.read.decisions[1], true, "proxy");
    const deviations = elementsOf(seen.document, '<li data-part="deviation">');
    assert.equal(deviations.length, 1, "one Declared deviation");
    assert.ok(words(deviations[0]).startsWith(seen.read.declared_deviations[0].declared_deviation_id), "with its id");
  },
  "chinook-campaign-pending": (seen) => {
    assertCampaignPending(seen);
    const parts = decisionParts(seen.document);
    assert.equal(parts.length, 1, "the proxy Decision of the Campaign");
    assertDecision(parts[0], seen.read.decisions[0], true, "proxy");
  },
  "chinook-campaign-decided": (seen) => {
    assertNoPending(seen);
    const parts = decisionParts(seen.document);
    assert.equal(parts.length, 2, "two Decisions");
    assertDecision(parts[0], seen.read.decisions[0], true, "proxy");
    assertDecision(parts[1], seen.read.decisions[1], true, "human");
  },
};

test("the demonstration's entries of KEPT_READS are the kept states of the demonstration on disk, both ways, each with its figures read in KEPT_FIGURES", () => {
  const listed = KEPT_READS.filter((name) => name.startsWith(DEMONSTRATION));
  const onDisk = statesOnDisk();
  assert.ok(onDisk.length > 0, "the folder holds kept states");
  for (const state of [...new Set([...onDisk, ...listed.map((name) => name.slice(DEMONSTRATION.length, -".status".length))])].sort()) {
    assert.ok(onDisk.includes(state), `${state} is listed in KEPT_READS and has no status read on disk`);
    assert.ok(listed.includes(readOf(state)), `the kept state ${state} is not in KEPT_READS`);
    assert.equal(KEPT_FIGURES[readOf(state)], figuresOf(state), state);
  }
});

test("the states this file builds a document for are the kept states of the demonstration on disk, both ways", () => {
  const onDisk = statesOnDisk();
  for (const state of [...new Set([...onDisk, ...Object.keys(SEES)])].sort()) {
    assert.ok(onDisk.includes(state), `${state} has a test and no kept read on disk`);
    assert.ok(state in SEES, `the kept state ${state} has no test`);
  }
});

for (const state of Object.keys(SEES)) {
  test(`the document a person sees at the kept state shows the Study id, the Write sequence and what the demonstration shows there: ${state}`, async (t) => {
    const seen = await seenAt(t, state);
    assertStudy(seen);
    SEES[state](seen);
  });
}

// The record message of the second action on the first option of the first Pending decision.
// The message of Record on the first option of the first Pending decision, its box of words empty.
const FIRST_OPTION = { message: RECORD, pending: 0, option: 0, words: "" };

// The list of arguments of a decide call after its first arguments, with the value of --study= made `<study>`, the rule of
// tests/_client_helpers.py::replaced, and the request id set apart.
const STUDY = /^--study=.*$/s;
const REQUEST = /^--request-id=.*$/s;
const apart = (args: string[]): string[] => args.map((argument) => argument.replace(STUDY, "--study=<study>").replace(REQUEST, "--request-id="));
const decideCalls = (calls: RecordedCall[]): RecordedCall[] => calls.filter((call) => call.args[contract.first_arguments.length] === "decide");

// Each request id the panel asks the bridge for, in order.
function madeIds(t: TestContext): string[] {
  const made: string[] = [];
  const make = bridge.newRequestId;
  t.mock.method(bridge, "newRequestId", () => {
    const id = make();
    made.push(id);
    return id;
  });
  return made;
}

const argumentsOf = (name: string): string[] => JSON.parse(fs.readFileSync(path.join(KEPT, "demonstration", `${name}.args`), "utf8")).arguments;

// The panel opened on a kept state, `message` sent as the document's script sends it, and each later call answered in turn.
async function recordedOn(t: TestContext, state: string, message: Entry, ...after: Answer[]): Promise<{ calls: RecordedCall[]; made: string[] }> {
  workspace(t, ["bike"]);
  const made = madeIds(t);
  const calls = recorder(t, keptAnswer(readOf(state)), keptAnswer(figuresOf(state)), ...after);
  await runCommand();
  await settle();
  panelOf().send(message);
  for (let turn = 0; turn < 3; turn += 1) await settle();
  return { calls, made };
}

// The one decide call, compared argument by argument with the argument list the demonstration ran, but for the request id, which is
// the one the panel made.
function assertArgumentsOf(calls: RecordedCall[], made: string[], name: string, sequence: number): void {
  const decides = decideCalls(calls);
  assert.equal(decides.length, 1, "one decide call");
  assert.equal(decides[0].program, contract.program);
  assert.deepEqual(decides[0].args.slice(0, contract.first_arguments.length), contract.first_arguments);
  const ours = apart(decides[0].args.slice(contract.first_arguments.length));
  const theirs = apart(argumentsOf(name));
  for (let at = 0; at < Math.max(ours.length, theirs.length); at += 1) assert.equal(ours[at], theirs[at], `argument ${at}`);
  assert.ok(decides[0].args.includes(`--read-sequence=${sequence}`), `--read-sequence=${sequence}`);
  assert.deepEqual(decides[0].args.filter((argument) => REQUEST.test(argument)), [`--request-id=${made[0]}`], "the request id the panel made");
}

async function assertRecordedAtTaskThree(t: TestContext, message: Entry): Promise<void> {
  const answer = `${DEMONSTRATION}decide-task-3`;
  const { calls, made } = await recordedOn(t, "after-compare", message, keptAnswer(answer), keptAnswer(readOf("after-decide")), keptAnswer(figuresOf("after-decide")));
  assertArgumentsOf(calls, made, "decide-task-3", 12);
  const document = lastDocument();
  // The read that follows holds the Decision the answer names, so the panel says it was recorded by "Recorded:" and its option, in a
  // link to its part; "The Decision was recorded." stands only beside an id that read does not hold.
  const seen: Seen = { document, read: keptJson(readOf("after-decide")), figures: keptJson(figuresOf("after-decide")) };
  const [decision] = seen.read.decisions;
  assert.equal(decision.decision_id, keptJson(answer).decision.decision_id);
  const notice = elementOf(document, '<div data-element="notice"') ?? "";
  assert.equal(words(notice), `${label("Recorded:")} ${decision.option}`, "the notice says the Decision was recorded");
  assert.ok(notice.includes('<a href="#decision-0" data-recorded>'), "its option links to the Decision's part");
  assertStudy(seen);
  SEES["after-decide"](seen);
}

test("the record message on the first option of after-compare starts one decide with the argument list of task 3 but for the request id, and once answered the panel says the Decision was recorded and shows the document of after-decide", async (t) => {
  await assertRecordedAtTaskThree(t, FIRST_OPTION);
});

test("on before-the-refused-write the record message starts one decide with the argument list of S1 but for the request id, and the refusal STUDY_CHANGED is shown before the question, asked again at Write sequence 30, with no Decision added and no second decide", async (t) => {
  const refusal = `${DEMONSTRATION}decide-s1`;
  const { calls, made } = await recordedOn(t, "before-the-refused-write", FIRST_OPTION, keptAnswer(refusal), keptAnswer(readOf("after-the-terminal-wrote")), keptAnswer(figuresOf("after-the-terminal-wrote")));
  assertArgumentsOf(calls, made, "decide-s1", 28);
  const document = lastDocument();
  const { error } = keptJson(refusal);
  assert.equal(error.code, "STUDY_CHANGED");
  const notice = elementOf(document, '<div data-element="notice"') ?? "";
  assert.ok(words(notice).includes(`${error.code} ${error.message}`), `the code and the message as the CLI printed them: ${words(notice)}`);
  assert.ok(document.indexOf(notice) < document.indexOf("<h3 data-text>"), "before the first question");
  const after = keptJson(readOf("after-the-terminal-wrote"));
  assert.equal(decisionParts(document).length, keptJson(readOf("before-the-refused-write")).decisions.length, "no Decision added");
  const seen: Seen = { document, read: after, figures: keptJson(figuresOf("after-the-terminal-wrote")) };
  assert.deepEqual(questionsOf(nowPart(document)), [after.pending_decisions[0].question.text], "the question shown again");
  assert.equal(after.write_sequence, 30);
  assertStudy(seen);
  for (let turn = 0; turn < 3; turn += 1) await settle();
  assert.equal(decideCalls(calls).length, 1, "no second decide call");
});

// --- The path to Record in a browser ------------------------------------------------------------------------------------------------

// The browser for the path to Record. With `CI` set in the environment, a test that needs it fails when Chrome is missing or does not
// start; without `CI`, it is skipped, as the other tests of the client that use Chrome are.
async function browserOrFailInCi(t: TestContext, what: string): Promise<string | undefined> {
  const address = fs.existsSync(CHROME) ? await startChrome(t) : undefined;
  if (address !== undefined) return address;
  const why = `${what}: Chrome at ${CHROME} is missing, or did not start or open its debugging port within ${START_MS} ms`;
  if ((process.env.CI ?? "") !== "") assert.fail(`${why}; CI is set, so the test fails instead of being skipped`);
  t.skip(`${why}, so the test is skipped`);
  return undefined;
}

type Keys = { key: (name: "Tab" | "Space" | "Enter") => Promise<void>; type: (text: string) => Promise<void>; evaluate: (expression: string) => Promise<any> };

// `document` opened in a page of the browser at 420 by 700 px, the messages its script posts kept in `window.posted`, and its keys.
async function keyboardPage(t: TestContext, address: string, document: string): Promise<Keys> {
  const page = await pageOf(t, address);
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-keys-")), "panel.html");
  t.after(() => fs.rmSync(path.dirname(file), { recursive: true, force: true }));
  fs.writeFileSync(file, document);
  await page.send("Emulation.setDeviceMetricsOverride", { width: 420, height: 700, deviceScaleFactor: 1, mobile: false });
  await page.send("Page.enable");
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.posted = []; window.acquireVsCodeApi = () => ({ postMessage: (message) => window.posted.push(message), getState() {}, setState() {} });" });
  await page.send("Page.navigate", { url: pathToFileURL(file).href });
  while (!page.events.some((event) => event.method === "Page.loadEventFired")) await new Promise((resolve) => setTimeout(resolve, 20));
  const KEYS = { Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 }, Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32, text: " " }, Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" } };
  return {
    key: async (name) => {
      await page.send("Input.dispatchKeyEvent", { type: "keyDown", ...KEYS[name] });
      await page.send("Input.dispatchKeyEvent", { type: "keyUp", ...KEYS[name], text: undefined });
    },
    type: async (text) => {
      for (const character of text) await page.send("Input.insertText", { text: character });
    },
    evaluate: async (expression) => {
      const answer = await page.send("Runtime.evaluate", { expression, returnByValue: true });
      if (answer.exceptionDetails) throw new Error(`${expression}: ${answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text}`);
      return answer.result.value;
    },
  };
}

const RECORD_CONTROL = `document.querySelector('button[data-message="${RECORD}"][data-pending="0"]')`;
const FIRST_RADIO = "document.querySelector('input[type=\"radio\"]')";

// The document of after-compare brought by the keyboard alone from its top to a recorded choice: Tab to the first option, Space, Tab
// past the summary of each option's consequence and the fold of the box of words, which it opens to type `words` when given, to the control
// that records, Enter. Gives back the messages the document posted.
async function recordedByKeyboard(t: TestContext, address: string, words?: string): Promise<Entry[]> {
  const { document } = await seenAt(t, "after-compare");
  const page = await keyboardPage(t, address, document);
  for (let at = 0; at < 300 && !(await page.evaluate(`document.activeElement === ${FIRST_RADIO}`)); at += 1) await page.key("Tab");
  assert.ok(await page.evaluate(`document.activeElement === ${FIRST_RADIO}`), "Tab brings the focus to the first option");
  assert.equal(await page.evaluate(`${RECORD_CONTROL}.disabled`), true, "before Space, the control that records is disabled");
  await page.key("Space");
  assert.equal(await page.evaluate(`${FIRST_RADIO}.checked`), true, "Space selects the first option");
  // Each option's consequence stands in a closed fold whose summary is a stop of Tab (D-151, answer 5, step 1).
  const summaries = await page.evaluate(`${RECORD_CONTROL}.closest("fieldset").querySelectorAll('details[data-element="consequence"] > summary').length`);
  for (let at = 0; at < summaries; at += 1) {
    await page.key("Tab");
    assert.ok(await page.evaluate(`document.activeElement.matches('details[data-element="consequence"] > summary')`), `Tab ${at + 1} brings the focus to the summary of a consequence`);
  }
  await page.key("Tab");
  assert.ok(await page.evaluate(`document.activeElement.matches('details[data-element="add-words"] > summary')`), "Tab brings the focus to the closed fold of the box of words, above the control that records");
  if (words !== undefined) {
    // Enter opens the fold, Tab reaches the box, and each character is typed into it.
    await page.key("Enter");
    await page.key("Tab");
    assert.ok(await page.evaluate(`document.activeElement.matches('textarea[data-words="0"]')`), "Tab brings the focus to the box of words, once its fold is open");
    await page.type(words);
  }
  await page.key("Tab");
  assert.ok(await page.evaluate(`document.activeElement === ${RECORD_CONTROL}`), `Tab brings the focus to the control that records: ${await page.evaluate("document.activeElement.outerHTML.slice(0, 80)")}`);
  await page.key("Enter");
  return page.evaluate("window.posted");
}

test("at 420 by 700 px, the keyboard alone brings the document of after-compare from its top to a recorded choice, and it posts the record message of the first option of the first Pending decision, with its empty box of words, and no other", { timeout: 60000 }, async (t) => {
  const address = await browserOrFailInCi(t, "the path to Record in a browser");
  if (address === undefined) return;
  const posted = await recordedByKeyboard(t, address);
  assert.deepEqual(posted, [{ message: RECORD, pending: 0, option: 0, words: "" }], "the record message of contract.json with the first Pending decision, its first option and its empty box of words, and no other");
});

test("at 420 by 700 px, the keyboard alone opens the fold of the box of words, types into it and records, and the record message carries the words typed", { timeout: 60000 }, async (t) => {
  const address = await browserOrFailInCi(t, "the path to Record with words in a browser");
  if (address === undefined) return;
  const posted = await recordedByKeyboard(t, address, "keep it");
  assert.deepEqual(posted, [{ message: RECORD, pending: 0, option: 0, words: "keep it" }]);
});

test("the message the document of after-compare posts in a browser is the message the panel is given at task 3, key by key, and given to the panel it starts the decide of task 3", { timeout: 60000 }, async (t) => {
  const address = await browserOrFailInCi(t, "the message of the path to Record");
  if (address === undefined) return;
  const [captured] = await recordedByKeyboard(t, address);
  for (const key of [...new Set([...Object.keys(captured ?? {}), ...Object.keys(FIRST_OPTION)])]) assert.deepEqual(captured?.[key], (FIRST_OPTION as Entry)[key], `the key ${key}`);
  await assertRecordedAtTaskThree(t, captured);
});

// --- Blocker 11 ---------------------------------------------------------------------------------------------------------------------

// Stated limit: what "leads to its record" requires here is the least the owner's sentence states, read as the panel now meets it: a
// file name or a number leads to a control that opens a file of the Study. The requirement is the owner's own sentence:
// « Panneau, tâche 2 — BLOCAGE : noms de fichiers affichés, pas cliquables ; aucun nombre n'ouvre son enregistrement. »
// A file name opens its file, and a number opens its record. A later slice may rewrite the function that recognises a link, but not
// that requirement.
//
// The file names and the numbers of a document that do not lead to their record. A file name is a value of the read at
// `assessments[].per_item_ref.path`, `comparisons[].paired_deltas_ref.path` or `comparisons[].population_ref.path` that the document
// shows; it leads to its record when it stands in the same `data-part` element as a control that opens it. A number is an element whose
// `data-kind` is among `number_links` of contract.json; it leads to its record when it stands in a link to a part of the same document
// and the record part of that number, that part or the record part it stands in, holds a control that opens the file the number is read
// or computed from: for `bin_count`, `bin_edge`, `quartile` and `dot_end`, the Comparison's control of `paired_deltas`; for `cited`,
// `latest` and `changed_item_count` that lead to a Decision's part, that Decision's control of its own file and the control of the own file
// of each Assessment its `evidence_change` names that `record_files` and `assessments` list; for every other kind, the control of the own
// file of that record part.
// The kinds `write_sequence` and `pending_decisions` are exempt: they lead to the Study's part, and neither is read or computed from a file
// of the Study. So is `writes_since`, a count of write-journal entries as `write_sequence` is, which leads to the band's place of its lines.
const NUMBER_KINDS = new Set(contract.number_links.map((entry) => entry.slice(0, entry.indexOf("="))));
const EXEMPT = new Set(["write_sequence", "pending_decisions", "writes_since"]);
const FROM_PAIRED_DELTAS = new Set(["bin_count", "bin_edge", "quartile", "dot_end"]);
const OF_A_LINE = new Set(["cited", "latest", "changed_item_count"]);
const RECORD_PARTS = new Set(["assessment", "comparison", "decision", "deviation"]);
const [, , , OPEN] = contract.messages;
const [, PAIRED_DELTAS, , RECORD_FILE] = contract.open_refs;
// The listing and the key of a record's id of each kind of record part, and the kind of its entry of `record_files`.
const LISTED: Record<string, [string, string, string]> = {
  assessment: ["assessments", "assessment_id", "assessment"],
  comparison: ["comparisons", "comparison_id", "comparison"],
  decision: ["decisions", "decision_id", "decision"],
  deviation: ["declared_deviations", "declared_deviation_id", "declared_deviation"],
};

type Element = { start: number; end: number; tag: string; part?: string; id?: string };
type Opener = { kind?: string; index: number; ref?: string };

// The controls that open in `html`, each with the kind, the index and the ref its message names.
const openersIn = (html: string): Opener[] =>
  [...html.matchAll(/<button [^>]*>/g)]
    .map(([tag]) => tag)
    .filter((tag) => tag.includes(` data-message="${OPEN}"`))
    .map((tag) => ({ kind: /data-part-kind="([^"]*)"/.exec(tag)?.[1], index: Number(/data-index="([^"]*)"/.exec(tag)?.[1]), ref: /data-ref="([^"]*)"/.exec(tag)?.[1] }));

// The path of the file a control opens, as the read names it.
function openedPath(opener: Opener, read: Entry): unknown {
  const [listing, key, kind] = LISTED[opener.kind ?? ""] ?? [];
  const record = listing === undefined ? undefined : read[listing]?.[opener.index];
  if (record === undefined) return undefined;
  if (opener.ref === RECORD_FILE) return (read.record_files ?? []).find((entry: Entry) => entry.kind === kind && entry.id === record[key])?.path;
  return record[`${opener.ref}_ref`]?.path;
}

function unled(document: string, read: Entry): { fileNames: string[]; numbers: string[] } {
  const paths = new Set<string>([
    ...(read.assessments ?? []).map((each: Entry) => each.per_item_ref?.path),
    ...(read.comparisons ?? []).flatMap((each: Entry) => [each.paired_deltas_ref?.path, each.population_ref?.path]),
  ].filter((each) => typeof each === "string"));
  const body = document.replace(/(<script[^>]*>)[\s\S]*?(<\/script>)/, "$1$2").replace(/(<style[^>]*>)[\s\S]*?(<\/style>)/, "$1$2");
  const elements: Element[] = [...body.matchAll(/<[a-z0-9]+ [^>]*>/g)].map((match) => {
    const html = elementOf(body.slice(match.index), match[0]) ?? match[0];
    return { start: match.index, end: match.index + html.length, tag: match[0], part: /\sdata-part="([^"]*)"/.exec(match[0])?.[1], id: /\sid="([^"]*)"/.exec(match[0])?.[1] };
  });
  // The innermost element that holds `at` and for which `which` holds.
  const around = (at: number, which: (element: Element) => boolean): Element | undefined =>
    elements.filter((element) => which(element) && element.start <= at && at < element.end).sort((a, b) => a.end - a.start - (b.end - b.start))[0];
  const inside = (element: Element): string => body.slice(element.start, element.end);
  const fileNames: string[] = [];
  for (const match of body.matchAll(/<([a-z0-9]+) data-text>([^<]*)<\/\1>/g)) {
    const text = unescaped(match[2]);
    if (!paths.has(text)) continue;
    const part = around(match.index, (element) => element.part !== undefined);
    if (part === undefined || !openersIn(inside(part)).some((opener) => openedPath(opener, read) === text)) fileNames.push(text);
  }
  const numbers: string[] = [];
  for (const match of body.matchAll(/<([a-z]+) [^>]*\bdata-kind="([^"]*)"[^>]*>([^<]*)</g)) {
    const [tag, name, kind, text] = [match[0].slice(0, match[0].lastIndexOf(">") + 1), match[1], match[2], unescaped(match[3]).trim()];
    if (!NUMBER_KINDS.has(kind) || EXEMPT.has(kind)) continue;
    const href = /\shref="#([^"]*)"/.exec(tag)?.[1];
    const target = name === "a" && href !== undefined ? elements.filter((element) => element.id === href) : [];
    const part = target.length === 1 ? around(target[0].start, (element) => RECORD_PARTS.has(element.part ?? "") && element.id !== undefined) : undefined;
    const index = part === undefined ? NaN : Number(/-(\d+)$/.exec(part.id!)?.[1]);
    const openers = part === undefined ? [] : openersIn(inside(part));
    const has = (kind: string, at: number, ref: string): boolean => openers.some((opener) => opener.kind === kind && opener.index === at && opener.ref === ref);
    let led: boolean;
    if (part === undefined || Number.isNaN(index)) led = false;
    else if (FROM_PAIRED_DELTAS.has(kind)) led = part.part === "comparison" && has("comparison", index, PAIRED_DELTAS);
    else if (OF_A_LINE.has(kind) && part.part === "decision") {
      const lines: Entry[] = read.decisions?.[index]?.evidence_change?.lines ?? [];
      const named = [...new Set(lines.flatMap((line) => [line.assessment_id, line.latest_assessment_id]))];
      const listed = named.filter((id) => (read.record_files ?? []).some((entry: Entry) => entry.kind === "assessment" && entry.id === id));
      const at = listed.map((id) => (read.assessments ?? []).findIndex((each: Entry) => each.assessment_id === id)).filter((each) => each >= 0);
      led = has("decision", index, RECORD_FILE) && at.every((each) => has("assessment", each, RECORD_FILE));
    } else led = has(part.part!, index, RECORD_FILE);
    if (!led) numbers.push(`${kind} ${text}`);
  }
  return { fileNames, numbers };
}

// The document the tests of blocker 11 read at a kept state, and its read.
async function blockerDocument(t: TestContext, state: string): Promise<{ document: string; read: Entry }> {
  const { document, read } = await seenAt(t, state);
  return { document, read };
}

for (const state of Object.keys(SEES)) {
  test(`blocker 11: every file name and every number of the document of the kept state leads to its record: ${state}`, async (t) => {
    const { document, read } = await blockerDocument(t, state);
    const found = unled(document, read);
    t.diagnostic(`${found.fileNames.length} file names and ${found.numbers.length} numbers do not lead to their record`);
    assert.deepEqual(found, { fileNames: [], numbers: [] }, `${found.fileNames.length} file names and ${found.numbers.length} numbers do not lead to their record`);
  });
}

// A document of after-compare with the control beside the per-Item path of its first Assessment's part removed, and that part's control
// of its own file removed.
function planted(document: string): { document: string; index: number } {
  const part = elementOf(document, '<div data-part="assessment"')!;
  const index = Number(/id="assessment-(\d+)"/.exec(part)![1]);
  const without = part.replace(/ <button [^>]*data-ref="per_item"[^>]*>[^<]*<\/button>/, "").replace(/ <button [^>]*data-ref="record"[^>]*>[^<]*<\/button>/, "");
  return { document: document.replace(part, without), index };
}

test("the function of blocker 11 finds nothing in the document of after-compare, and finds the output path left with no control and each number whose record part has no control left in a planted one", async (t) => {
  const { document, read } = await seenAt(t, "after-compare");
  assert.deepEqual(unled(document, read), { fileNames: [], numbers: [] }, "the document follows the rules");
  const { document: changed, index } = planted(document);
  assert.notEqual(changed, document, "a control was removed");
  const found = unled(changed, read);
  assert.deepEqual(found.fileNames, [read.assessments[index].per_item_ref.path], "the output path with no control");
  const expected = [...document.matchAll(new RegExp(`<a href="#assessment-${index}" data-kind="([^"]*)">([^<]*)</a>`, "g"))].map((match) => `${match[1]} ${unescaped(match[2])}`);
  assert.ok(expected.length > 0, "numbers lead to the first Assessment's part");
  assert.deepEqual(found.numbers, expected, "each number whose record part has no control");
});
