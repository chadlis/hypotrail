// The panel over each state of the journey the panel mockups show, as `test/cli/journey/` keeps its reads (tests/_journey_states.py):
// one test per state, which builds the document from the state's status read, with its figures read where one is kept, and checks
// what holds over every document the panel builds: the policy, no text of the read in an attribute or as markup, and no letter
// left once the panel's fixed texts and the read's values are removed.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { written } from "../src/content";
import { JOURNEY, KEPT, kept } from "./kept";
import {
  FIGURES_FAILED,
  LITERALS,
  S2_INTERVAL,
  assertNowOrder,
  attributeValues,
  cspProblems,
  documentFor,
  elementOf,
  elementsOf,
  geometryValues,
  heldRecorder,
  holdsTheHeadings,
  lastDocument,
  markedTexts,
  panelOf,
  partsOf,
  runCommand,
  settle,
  success,
  unescaped,
  withFigures,
  workspace,
} from "./panel-harness";
import { exit, recorder, type Answer } from "./recorder";
import * as stub from "./vscode-stub";

const headingsOf = (document: string): string[] => [...document.matchAll(/<h2>([^<]*)<\/h2>/g)].map((match) => unescaped(match[1]));

// The kept states of the journey on disk, each by the name of its reads: `NN-name`.
const STATES = fs
  .readdirSync(path.join(KEPT, "journey"))
  .filter((name) => name.endsWith(".status.out"))
  .map((name) => name.slice(0, -".status.out".length))
  .sort();

const answerOf = (name: string): Answer => exit(Number(kept(`${JOURNEY}${name}.exit`)), kept(`${JOURNEY}${name}.out`), kept(`${JOURNEY}${name}.err`));
const hasFigures = (state: string): boolean => fs.existsSync(path.join(KEPT, "journey", `${state}.figures.out`));
const answersOf = (state: string): Answer[] => [answerOf(`${state}.status`), ...(hasFigures(state) ? [answerOf(`${state}.figures`)] : [])];

// Each value of an answer as the panel writes it: the leaves of the object its output holds, and the keys of a map the panel shows
// whole (the rule of panel-documents.test.ts).
function valuesOf(answers: Answer[]): string[] {
  const values: string[] = [];
  const walk = (value: unknown, key: string): void => {
    if (Array.isArray(value)) value.forEach((each) => walk(each, key));
    else if (value !== null && typeof value === "object") {
      for (const [name, each] of Object.entries(value)) {
        if (key === "coverage" || key === "item_counts") values.push(name);
        walk(each, name);
      }
    } else values.push(unescaped(written(value)));
  };
  for (const answer of answers) walk(JSON.parse(answer.stdout ?? ""), "");
  return values;
}

// What is left of the text between the tags of the body once the script and the marked texts are set apart and every text the
// panel may print is removed, longest first (the rule of panel-documents.test.ts).
function leftOf(document: string, answers: Answer[]): string {
  const body = document.slice(document.indexOf("<body>"), document.indexOf("</body>"));
  let left = unescaped(
    body
      .replace(/<script[^>]*>[\s\S]*?<\/script>/, "\n")
      .replace(/<([a-z0-9]+) data-text>[^<]*<\/\1>/g, "\n")
      .split(/<[^>]*>/)
      .join("\n"),
  );
  const removable = [
    ...contract.labels,
    ...contract.evidence_phrases.map((entry) => entry.slice(entry.indexOf("=") + 1)),
    ...contract.applies_phrases.map((entry) => entry.slice(entry.indexOf("=") + 1)),
    contract.no_value,
    contract.withheld,
    ...valuesOf(answers),
  ]
    .filter((text) => text.length > 0)
    .sort((a, b) => b.length - a.length);
  for (const text of removable) left = left.split(text).join("\n");
  return left;
}

test("the journey keeps the twenty-four states of tests/_journey_states.py, 00 to 19 and 30 to 33", () => {
  assert.equal(STATES.length, 24);
  assert.deepEqual(
    STATES.map((state) => state.slice(0, 2)),
    [...Array.from({ length: 20 }, (_, at) => String(at).padStart(2, "0")), "30", "31", "32", "33"],
  );
});

async function built(t: TestContext, state: string): Promise<{ document: string; answers: Answer[] }> {
  const answers = answersOf(state);
  return { document: (await documentFor(t, ...answers)).document, answers };
}

for (const state of STATES) {
  test(`the document of the journey's state ${state} keeps the policy, puts no text of the read in an attribute or as markup, and leaves no letter of its own`, async (t) => {
    const { document, answers } = await built(t, state);
    assert.deepEqual(cspProblems(document), []);
    for (const value of attributeValues(document)) assert.ok(LITERALS.includes(value.replace(/\d+$/, "")), value);
    for (const value of geometryValues(document)) assert.match(value, /^\d+(\.\d+)?$/);
    assert.deepEqual(leftOf(document, answers).match(/\p{L}+/gu) ?? [], []);
    const study = path.join(stub.state.folders[0], "bike");
    const values = valuesOf(answers);
    const [heading, ...others] = markedTexts(document);
    assert.equal(heading, study);
    for (const text of others) assert.ok(values.includes(text), text);
  });
}

for (const state of STATES) {
  test(`the section headings of the journey's state ${state} are an in-order subset of the five, with Now, The Study so far and Tools present`, async (t) => {
    const { document } = await built(t, state);
    assert.ok(holdsTheHeadings(headingsOf(document)), headingsOf(document).join(" | "));
    for (const heading of headingsOf(document)) assert.ok(contract.labels.includes(heading), heading);
  });
}

// The two states of P3-3: the band holds "Since this panel's last read" with the number of entries of `writes_since`, as a link to the
// one place of their lines.
for (const state of ["04-pending", "09-new-compare"]) {
  test(`the band of the journey's state ${state} holds the label of the panel's read since its last, with the count of writes_since as a link to the one place of their lines`, async (t) => {
    const { document, answers } = await built(t, state);
    const read = JSON.parse(answers[0].stdout ?? "");
    const band = elementOf(elementOf(document, '<div data-part="band">')!, "<summary>")!;
    const label = "Since this panel's last read";
    assert.ok(contract.labels.includes(label));
    const link = new RegExp(`${label} <a href="#([^"]*)" data-kind="writes_since">([^<]*)</a>`).exec(unescaped(band));
    assert.ok(read.writes_since.length > 0 && link, band);
    assert.equal(link![2], String(read.writes_since.length));
    assert.equal([...document.matchAll(new RegExp(` id="${link![1]}"`, "g"))].length, 1);
    assert.match(document, new RegExp(`<details data-part="since" id="${link![1]}">`));
  });
}

// The journey's states with a Pending decision, and the read of each.
const PENDING_STATES = STATES.filter((state) => {
  const read = JSON.parse(kept(`${JOURNEY}${state}.status.out`));
  return read.ok === true && read.pending_decisions.length > 0;
});
const readOf = (state: string): Record<string, any> => JSON.parse(kept(`${JOURNEY}${state}.status.out`));
const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");

for (const state of ["04-pending", "09-new-compare", "11-study-changed"]) {
  test(`Now's first Pending decision holds, in D-148's order, its question, the delta line, the coverage, the frame line, each warning, the limitations line, the choices with each consequence in a closed fold, Record, then the closed fold of the charts with the single-feature chart: ${state}`, async (t) => {
    const { document } = await built(t, state);
    assertNowOrder(document, readOf(state));
  });
}

// "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
const RULE = "Not counted again: an entry that repeats a message above.";
for (const state of PENDING_STATES) {
  test(`the limitations line of Now counts and lists only the limitations that are no warning's message and states that rule, and each warning's message stands once in Now: ${state}`, async (t) => {
    assert.ok(contract.labels.includes(RULE));
    const read = readOf(state);
    const { document } = await built(t, state);
    const now = elementOf(document, '<section data-part="now"')!;
    const comparison = read.comparisons.find((each: Record<string, any>) => each.comparison_id === read.next_step.ids[0]);
    const messages = comparison.warnings.map((warning: Record<string, any>) => warning.message);
    const counted = comparison.limitations.filter((each: string) => !messages.includes(each));
    assert.ok(comparison.limitations.some((each: string) => messages.includes(each)), "the read repeats a warning's message among its limitations");
    assert.match(words(elementOf(now, '<p data-element="limits">')), new RegExp(`Limitations of the Comparison ${counted.length} ${RULE.replace(/[.']/g, "\\$&")}$`));
    assert.deepEqual(markedTexts(elementOf(now, '<div data-part="limitations"')!), counted);
    for (const message of messages) assert.equal(markedTexts(now).filter((text) => text === message).length, 1, message);
  });
}

// "the delta line: the delta, its Metric and unit, and, when the read holds `interval`, its level, bounds and resampling unit" (#253).
for (const [name, interval, expected] of [
  ["an S2-shaped interval", S2_INTERVAL, `Interval ${S2_INTERVAL.level} ${S2_INTERVAL.lower} ${S2_INTERVAL.upper} resampling unit ${S2_INTERVAL.unit}`],
  ["an interval whose bounds are null", { ...S2_INTERVAL, lower: null, upper: null, reason: "too_few_units" }, "Interval too_few_units"],
  ["no interval key", undefined, undefined],
] as const) {
  test(`with ${name} injected into state 04, the delta line of Now shows ${expected === undefined ? "no interval" : "it"}`, async (t) => {
    const read = readOf("04-pending");
    // State 04's read holds the interval the core computed: the case without one deletes the key from this copy of the read.
    if (interval === undefined) delete read.comparisons[0].interval;
    else read.comparisons[0].interval = interval;
    const { document } = await documentFor(t, success(read));
    const line = elementOf(elementOf(document, '<section data-part="now"')!, '<p data-element="delta">')!;
    const slot = elementOf(line, '<span data-element="interval">');
    if (expected === undefined) return assert.equal(slot, undefined);
    assert.equal(words(slot), expected);
    const links = [...slot!.matchAll(/<a href="#comparison-(\d+)" data-kind="interval">/g)];
    assert.equal(links.length, interval.lower === null ? 0 : 3);
    for (const link of links) assert.equal(Number(link[1]), 0);
  });
}

// The interval line a Comparison's delta element holds where the read holds `interval`: its level, its two bounds and its unit as read,
// or its reason where a bound is null; none where the delta is withheld, whose interval would show what the withheld delta hides.
const intervalWords = (comparison: Record<string, any>): string | undefined => {
  const interval = comparison.interval;
  if (comparison.delta.value === null || interval === undefined || interval === null) return undefined;
  if (interval.lower === null || interval.upper === null) return `Interval ${interval.reason}`;
  return `Interval ${written(interval.level)} ${written(interval.lower)} ${written(interval.upper)} resampling unit ${interval.unit}`;
};

for (const state of STATES) {
  test(`each Comparison's part, in Now or in the Study so far, holds in its delta element the interval line its read gives: ${state}`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    (read.comparisons ?? []).forEach((comparison: Record<string, any>, index: number) => {
      const part = elementOf(document, `<div data-part="comparison" id="comparison-${index}"`);
      if (part === undefined) return;
      const slot = elementOf(elementOf(part, '<p data-element="delta">')!, '<span data-element="interval">');
      assert.equal(slot === undefined ? undefined : words(slot), intervalWords(comparison), comparison.comparison_id);
    });
  });
}

test("a Comparison whose delta is withheld holds no interval line in Now, not even its reason, whatever interval its read holds", async (t) => {
  for (const interval of [S2_INTERVAL, { ...S2_INTERVAL, lower: null, upper: null, reason: "too_few_units" }]) {
    const read = readOf("04-pending");
    read.comparisons[0].delta.value = null;
    read.comparisons[0].interval = interval;
    const { document } = await documentFor(t, success(read));
    const line = elementOf(elementOf(document, '<section data-part="now"')!, '<p data-element="delta">')!;
    assert.equal(elementOf(line, '<span data-element="interval">'), undefined, String(interval.reason));
  }
});

// "The reserved places are absent until their key exists." (D-151, answer 4)
for (const state of STATES) {
  test(`no element stands in the places of the rule line and of "Candidate better / worse / tied": ${state}`, async (t) => {
    const { document } = await built(t, state);
    // The two places stand under the delta of Now: the delta line holds the delta and its interval only, and nothing stands between it
    // and the coverage but the context Now shows.
    const now = elementOf(document, '<section data-part="now"') ?? "";
    for (const word of ["better", "worse", "tied", "rule"]) assert.ok(!` ${words(elementOf(now, '<p data-element="delta">'))} `.toLowerCase().includes(` ${word} `), word);
    const between = now.slice(now.indexOf("</p>", now.indexOf('<p data-element="delta">')) + 4, now.indexOf('<p data-element="coverage">'));
    if (now.includes('<p data-element="delta">')) assert.deepEqual(partsOf(between).tags.filter((tag) => tag.startsWith("<") && !tag.startsWith("</") && !/data-element="(context|cited-delta)"|^<a |^<span|^<strong/.test(tag)), []);
    assert.deepEqual(partsOf(document).tags.filter((tag) => /data-element="(rule|verdict|plan)/.test(tag)), []);
  });
}

test("on state 09 the cited Comparison's delta and the new delta both stand in Now, each as its read's number, and no number of the document is their difference", async (t) => {
  const read = readOf("09-new-compare");
  const { document } = await built(t, "09-new-compare");
  const now = elementOf(document, '<section data-part="now"')!;
  const [context] = read.next_step.context;
  const earlier = read.decisions.find((each: Record<string, any>) => each.decision_id === context);
  const cited = read.comparisons.find((each: Record<string, any>) => earlier.cited_ids.includes(each.comparison_id)).delta.value;
  const freshComparison = read.comparisons.find((each: Record<string, any>) => each.comparison_id === read.next_step.ids[0]);
  const fresh = freshComparison.delta.value;
  // The delta line also holds the new Comparison's interval as read: its level and its two bounds.
  const interval = freshComparison.interval;
  assert.ok(interval.lower !== null && interval.upper !== null, "state 09's read holds an interval with bounds");
  const intervalNumbers = [interval.level, interval.lower, interval.upper].map(written);
  const deltas = [...now.matchAll(/<a href="#comparison-\d+" data-kind="delta">([^<]*)<\/a>/g)].map((match) => match[1]);
  assert.deepEqual(deltas.slice(0, 2), [written(fresh), written(cited)], "the new delta in the delta line, then the cited one beside it");
  assert.ok(words(elementOf(now, '<p data-element="cited-delta">')).includes(written(cited)), "the cited delta in its line");
  assert.ok(words(elementOf(now, '<p data-element="context">')).includes(earlier.option), "the earlier Decision's option");
  // The two lines hold the two deltas as read, and no number of their own: no difference is printed, whatever its value.
  for (const line of ['<p data-element="delta">', '<p data-element="cited-delta">']) {
    const numbers = words(elementOf(now, line)).match(/-?\d+(\.\d+)?/g) ?? [];
    assert.deepEqual(numbers, line.includes("cited") ? [written(cited)] : [written(fresh), ...intervalNumbers], line);
  }
  if (cited !== fresh) assert.ok(!words(now).split(" ").includes(written(fresh - cited)), "the difference");
});

// --- The Study so far, in form 2 -----------------------------------------------------------------------------------------------------

// The steps of the kinds of record the read holds, in the fixed order of kinds (D-161): the Study, its Attempts, its Assessments, its
// Comparisons, its Decisions and its Declared deviations; no step for a kind with no record.
const KIND_OF_STEP: Record<string, string> = { revision: "study", attempt: "attempts", assessment: "assessments", comparison: "comparisons", decision: "decisions", declared_deviation: "deviations" };
function stepsOf(read: Record<string, any>): string[] {
  return [
    "study",
    ...(read.attempts.length > 0 ? ["attempts"] : []),
    ...(read.assessments.length > 0 ? ["assessments"] : []),
    ...(read.comparisons.length > 0 ? ["comparisons"] : []),
    ...(read.decisions.length > 0 ? ["decisions"] : []),
    ...(read.declared_deviations.length > 0 ? ["deviations"] : []),
  ];
}

// The kinds of step in the order each first appears in the write journal of a read that holds the whole journal.
function journalOrderOf(read: Record<string, any>): string[] {
  const order: string[] = [];
  for (const entry of read.writes_since) for (const each of entry.written ?? []) {
    const step = KIND_OF_STEP[each.kind];
    if (step !== undefined && !order.includes(step)) order.push(step);
  }
  return order;
}

// A read holds the whole journal when it lists one entry per write. Over the Study, its Attempts, its Assessments, its Comparisons and its
// Decisions, the steps drawn are then the kinds in the order of their first appearance in it; the Declared deviations, which nothing in
// the core orders against the others, are drawn last whenever present (D-161 addendum 2, #75 comment 7197719288).
function assertStepOrder(read: Record<string, any>, drawn: (string | undefined)[]): void {
  assert.equal(read.writes_since.length, read.write_sequence, "a read of the whole journal");
  const ordered = drawn.filter((step) => step !== "deviations");
  assert.deepEqual(ordered, journalOrderOf(read).filter((step) => step !== "deviations"), "the order of first appearance in the journal");
  if (drawn.includes("deviations")) assert.equal(drawn[drawn.length - 1], "deviations", "the Declared deviations last");
}

test("a Declared deviation the journal holds before any Comparison is still drawn last, in a copy of state 15 whose journal declares it first", async (t) => {
  const read = readOf("15-deviation");
  const at = (kind: string) => read.writes_since.findIndex((entry: Record<string, any>) => (entry.written ?? []).some((each: Record<string, any>) => each.kind === kind));
  const deviation = at("declared_deviation");
  // Its begin and end entries move before the first Comparison's begin.
  const begin = read.writes_since.findIndex((entry: Record<string, any>, index: number) => index < deviation && entry.command === read.writes_since[deviation].command && entry.request_id === read.writes_since[deviation].request_id);
  const moved = [read.writes_since[begin], read.writes_since[deviation]];
  const rest = read.writes_since.filter((_: unknown, index: number) => index !== begin && index !== deviation);
  const comparison = rest.findIndex((entry: Record<string, any>) => entry.command === "compare");
  read.writes_since = [...rest.slice(0, comparison), ...moved, ...rest.slice(comparison)];
  assert.ok(journalOrderOf(read).indexOf("deviations") < journalOrderOf(read).indexOf("comparisons"), "the copy declares the deviation before any Comparison");
  const { document } = await documentFor(t, success(read));
  const drawn = elementsOf(elementOf(document, '<section data-part="path">')!, "<details data-step=").map((step) => /^<details data-step="([a-z]+)"/.exec(step)?.[1]);
  assert.ok(drawn.includes("deviations"));
  assertStepOrder(read, drawn);
});

for (const state of STATES.filter((each) => readOf(each).ok === true)) {
  test(`the Study so far holds one closed step per kind of record present, in the order of the write journal, each running its review form, its chart and its limitation: ${state}`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    const path = elementOf(document, '<section data-part="path">')!;
    const steps = elementsOf(path, "<details data-step=");
    const drawn = steps.map((step) => /^<details data-step="([a-z]+)"/.exec(step)?.[1]);
    assert.deepEqual(drawn, stepsOf(read), "exactly the kinds present");
    assertStepOrder(read, drawn);
    for (const step of steps) {
      assert.ok(!/^<details[^>]*\sopen/.test(step), "closed");
      assert.match(step, /^<details data-step="[a-z]+">\n<summary>/, "one line first");
      const places = ['<div data-element="form">', '<div data-element="chart">', '<div data-element="limitation">'].map((opening) => step.indexOf(opening)).filter((place) => place >= 0);
      assert.ok(places[0] === step.indexOf('<div data-element="form">') && places[0] > 0, "the review form first");
      assert.deepEqual(places, [...places].sort((a, b) => a - b), "form, chart, limitation");
    }
  });
}

// B4: "Its `item_counts`, and anything derived from its outputs, show only once an Assessment cites it" (D-136, question 1); "its id and its
// Observation set's id are plain text, never links" (D-143, correction 1).
test("on state 12 the document holds no link to the Attempt no Assessment cites or its Observation set, no path under its folder and no 184, and its step reads that its counts and its record open once an Assessment cites it; on state 13 its counts show", async (t) => {
  const twelve = readOf("12-public-check-run");
  const [check] = twelve.attempts.filter((attempt: Record<string, any>) => attempt.request_id === "check");
  assert.ok(!twelve.assessments.some((assessment: Record<string, any>) => assessment.observation_set_id === check.observation_set_id));
  const { document } = await built(t, "12-public-check-run");
  for (const id of [check.attempt_id, check.observation_set_id]) assert.ok(!/<a [^>]*>[^<]*<\/a>/.test(document) || ![...document.matchAll(/<a [^>]*>([^<]*)<\/a>/g)].some((match) => match[1].includes(id)), `no link to ${id}`);
  assert.ok(!document.includes(`attempts/${check.attempt_id}/`), "no path under its folder");
  assert.ok(!partsOf(document).between.split(/\s+/).includes("184"), "no 184");
  const step = elementOf(document, '<details data-step="attempts">')!;
  assert.ok(words(step).includes("its counts and its record open once an Assessment cites it"));
  // The uncited Attempt's id and its Observation set's id stand in its row as plain text: present, and inside no link.
  const uncited = elementsOf(step, '<li data-part="attempt">').find((each) => each.includes(check.attempt_id));
  assert.ok(uncited, "the uncited Attempt's id stands in its row");
  assert.ok(words(uncited).split(" ").includes(check.attempt_id), "the Attempt's id as a word of its row");
  assert.ok(words(uncited).split(" ").includes(check.observation_set_id), "its Observation set's id as a word of its row");
  assert.ok(words(uncited).includes(`Observation set ${check.observation_set_id}`), "its Observation set's id after its label");
  assert.ok(!/<a /.test(uncited!), "no link in its row");
  const thirteen = readOf("13-exposure");
  const later = (await built(t, "13-exposure")).document;
  const row = elementsOf(elementOf(later, '<details data-step="attempts">')!, '<li data-part="attempt">').find((each) => each.includes(check.attempt_id));
  assert.ok(row && /<a [^>]*data-kind="item_counts">184<\/a>/.test(row), "its counts show once an Assessment cites it");
  assert.ok(thirteen.assessments.some((assessment: Record<string, any>) => assessment.observation_set_id === check.observation_set_id));
});

// "A proxy Decision reads "\u25c7 Decided by a rule, not by a person"" (D-151, answer 4).
const BY_RULE = "Decided by a rule, not by a person";
for (const state of ["10-proxy", "05-decided", "11-study-changed"]) {
  test(`the line and the part of each Decision of state ${state} hold the mark and the words of a rule only for a proxy Decision, and nothing stands in the place of a validation`, async (t) => {
    assert.ok(contract.labels.includes(BY_RULE));
    const read = readOf(state);
    const { document } = await built(t, state);
    const parts = elementsOf(document, '<section data-part="decision"');
    read.decisions.forEach((decision: Record<string, any>, at: number) => {
      assert.equal(words(parts[at]).includes(`\u25c7 ${BY_RULE}`), decision.author === "proxy", decision.decision_id);
    });
    const latest = read.decisions[read.decisions.length - 1];
    const line = elementOf(elementOf(document, '<details data-step="decisions">')!, "<summary>")!;
    assert.equal(words(line).includes(`\u25c7 ${BY_RULE}`), latest.author === "proxy", "the step's line");
    assert.ok(!/awaiting your validation/i.test(partsOf(document).between));
  });
}

// The marks: \u2016 a Declared deviation not withdrawn, ! a recoverable Attempt, each followed by its word.
for (const [state, mark, word, present] of [
  ["15-deviation", "\u2016", "declared", true],
  ["16-deviation-withdrawn", "\u2016", "declared", true],
  ["17-interrupted", "!", "recoverable", true],
  ["18-recovered", "!", "recoverable", false],
] as const) {
  test(`state ${state}: the mark ${mark} stands where the read says so, its word after it`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    const marks = [...document.matchAll(/<span data-mark aria-hidden="true">([^<]*)<\/span> <span>([^<]*)<\/span>/g)].filter((match) => match[1] === mark);
    assert.ok(marks.every((match) => match[2] === word), "the word follows the mark");
    if (mark === "\u2016") {
      const rows = elementsOf(document, '<li data-part="deviation">');
      read.declared_deviations.forEach((deviation: Record<string, any>, at: number) => assert.equal(rows[at].includes(`>${mark}<`), deviation.withdrawn === false, deviation.declared_deviation_id));
    } else {
      const rows = elementsOf(document, '<li data-part="attempt">');
      read.attempts.forEach((attempt: Record<string, any>, at: number) => assert.equal(rows[at].includes(`>${mark}<`), attempt.recoverable === true, attempt.request_id));
      assert.equal(marks.length > 0, present);
    }
  });
}

// --- To handle, Now under rules 3 and 4, the Since lines, Tools ------------------------------------------------------------------------

for (const [state, count] of [["17-interrupted", 1], ["19-two-interrupted", 2], ["18-recovered", 0]] as const) {
  test(`the compact line of To handle holds ${count} and the list after Now each Attempt to handle, none inside Now: ${state}`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    const line = elementOf(document, '<section data-part="tohandle-line">');
    const list = elementOf(document, '<section data-part="tohandle" id="tohandle-list">');
    assert.deepEqual(read.next_step.to_handle.length, count);
    if (count === 0) return assert.ok(line === undefined && list === undefined);
    assert.ok(document.indexOf(line!) < document.indexOf('<section data-part="now"'), "the line above Now");
    assert.equal(/<a href="#tohandle-list" data-kind="to_handle">([^<]*)<\/a>/.exec(line!)?.[1], String(count));
    const now = elementOf(document, '<section data-part="now"')!;
    assert.ok(document.indexOf(list!) > document.indexOf(now) + now.length - 1, "the list after Now, its sibling");
    for (const id of read.next_step.to_handle) {
      assert.ok(list!.includes(id), id);
      assert.ok(!now.includes(id), `${id} not inside Now`);
    }
  });
}

// The list of To handle stands under its own heading, so that it cannot read as part of the Candidate above it.
for (const state of ["17-interrupted", "19-two-interrupted"]) {
  test(`the list of To handle opens on its own heading, a label other than the compact line's, and stands outside Now and every part of Now: ${state}`, async (t) => {
    const { document } = await built(t, state);
    const list = elementOf(document, '<section data-part="tohandle" id="tohandle-list">');
    assert.ok(list, "the list is a section of its own");
    assert.ok(contract.labels.includes("Everything to handle"));
    const [, first] = /^<section[^>]*>\n(<h[1-6]>[^<]*<\/h[1-6]>)/.exec(list!) ?? [];
    assert.equal(first, "<h3>Everything to handle</h3>", "its heading first, above the level of the Candidate's, other than the compact line's");
    const now = elementOf(document, '<section data-part="now"')!;
    assert.ok(!now.includes('id="tohandle-list"'), "not inside Now");
  });
}

// The count of pending decisions stands on Now's heading line, "Now \u00b7 n pending decisions", only when n > 0, at no cost of height;
// "No pending decision." stands nowhere (D-161).
for (const state of STATES.filter((each) => readOf(each).ok === true)) {
  test(`Now's heading line holds the count of pending decisions only when there is one, and the document never says no pending decision: ${state}`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    const now = elementOf(document, '<section data-part="now"')!;
    const line = elementOf(now, '<div data-element="now-heading">');
    assert.ok(line, "Now's heading line");
    assert.ok(contract.labels.includes("pending decisions"));
    const n = read.pending_decisions.length;
    assert.ok(contract.labels.includes("pending decision"));
    assert.equal(words(line), n === 0 ? "Now" : `Now \u00b7 ${n} ${n === 1 ? "pending decision" : "pending decisions"}`);
    if (n > 0) assert.match(line!, new RegExp(`<a href="#study-0" data-kind="pending_decisions">${n}</a>`));
    assert.equal(elementsOf(document, '<span data-element="count">').length, n === 0 ? 0 : 1, "one count only");
    assert.ok(!partsOf(document).between.includes("No pending decision."));
  });
}

// Rule 4: a sentence of its own, which stays true when To handle lists Attempts, then the latest Decision (D-159).
const NO_DECISION_WAITS = "No decision waits for you.";
for (const handle of [false, true]) {
  test(`under rule 4 Now's sentence is the label that no decision waits for the person, then the latest Decision's line${handle ? ", with To handle listing an Attempt" : ""}`, async (t) => {
    assert.ok(contract.labels.includes(NO_DECISION_WAITS));
    const read = readOf("05-decided");
    assert.equal(read.next_step.kind, null);
    if (handle) read.next_step.to_handle = [read.attempts[0].attempt_id];
    const { document } = await documentFor(t, success(read));
    const now = elementOf(document, '<section data-part="now"')!;
    assert.equal(words(elementOf(now, '<p data-element="now-question">')), NO_DECISION_WAITS);
    const latest = now.indexOf('<p data-element="latest-decision">');
    assert.ok(latest > now.indexOf('<p data-element="now-question">'), "the latest Decision after the sentence");
    assert.equal(elementOf(document, '<section data-part="tohandle-line">') !== undefined, handle, "To handle has its own line");
  });
}

// "Any "Next" or "to look again" is the core's text, or absent" (#256).
for (const name of [`${JOURNEY}07-rescored.status`, `${JOURNEY}08-result-changed.status`, "status-repeated"]) {
  test(`under rule 3, Now holds the core's text and the Decision next_step names, with whether it applies and the state of its evidence: ${name}`, async (t) => {
    const read = JSON.parse(kept(`${name}.out`));
    const { document } = await documentFor(t, success(read));
    const now = elementOf(document, '<section data-part="now"')!;
    if (read.next_step.kind !== "look_again") {
      assert.equal(read.next_step.kind, null, "status-repeated: its Decision still applies");
      return assert.equal(words(elementOf(now, '<p data-element="now-question">')), NO_DECISION_WAITS);
    }
    assert.ok(markedTexts(now).includes(read.next_step.text));
    for (const id of read.next_step.ids) {
      const decision = read.decisions.find((each: Record<string, any>) => each.decision_id === id);
      assert.ok(markedTexts(elementOf(now, '<p data-element="look-again">')!).includes(decision.option), id);
    }
    assert.ok(!/\bNext\b/.test(partsOf(document).between), "no Next of the client");
  });
}

for (const state of STATES.filter((each) => readOf(each).ok === true)) {
  test(`each line of the panel's read since its last names the command and what it wrote, and a revision as Protocol revision and its number, never revision and a digest: ${state}`, async (t) => {
    const read = readOf(state);
    const { document } = await built(t, state);
    const lines = elementsOf(document, '<li data-element="since-line">');
    assert.equal(lines.length, read.writes_since.length);
    lines.forEach((line, at) => {
      const entry = read.writes_since[at];
      assert.ok(words(line).startsWith(`${entry.command} ${entry.phase}`), words(line));
      assert.doesNotMatch(words(line), /revision\s+[0-9a-f]{64}/, "no bare revision and digest");
      for (const each of entry.written ?? []) {
        if (each.kind === "revision") assert.ok(words(line).includes(`Protocol revision ${read.revisions.find((spec: Record<string, any>) => spec.revision === each.id).revision_number}`));
        else assert.ok(words(line).includes(`${each.kind} ${each.id}`));
      }
    });
    if (state === "12-public-check-run") {
      const [check] = read.attempts.filter((attempt: Record<string, any>) => attempt.request_id === "check");
      for (const line of lines) assert.ok(![...line.matchAll(/<a [^>]*>([^<]*)<\/a>/g)].some((match) => match[1].includes(check.attempt_id) || match[1].includes(check.observation_set_id)), "no link to the uncited Attempt");
    }
  });
}

test("Tools holds Read again, then Hand over last, the command report as fixed text, and no control names report", async (t) => {
  const { document } = await built(t, "04-pending");
  const tools = elementOf(document, '<section data-part="tools">')!;
  const hand = elementOf(tools, '<div data-element="hand-over">')!;
  assert.ok(tools.trimEnd().endsWith(`${hand}\n</section>`), "Hand over last");
  assert.ok(tools.indexOf(`data-message="${contract.messages[0]}"`) < tools.indexOf(hand), "Read again before it");
  assert.ok(words(hand).includes("report") && !/data-message="[^"]*report/.test(document));
});

// --- The client states, on the kept read of state 04 (D-143, correction 4) -----------------------------------------------------------

const STATE_04 = (): Answer => answerOf("04-pending.status");
const FIGURES_04 = (): Answer => answerOf("04-pending.figures");
const TIMEOUT: Answer = { error: { code: null, killed: true, signal: "SIGTERM" } };
const tagsOf = (document: string): string[] => partsOf(document).tags;
const inertControls = (document: string): string[] =>
  tagsOf(document).filter((tag) => /^<(button|textarea|input)[\s>]/.test(tag) && !/\sdisabled(\s|>)/.test(tag));

test("a read in progress on state 04: the line of a read in flight, main busy, and every control inert", async (t) => {
  workspace(t, ["bike"]);
  heldRecorder(t);
  await runCommand();
  const document = lastDocument();
  assert.ok(partsOf(elementOf(document, '<div data-element="notice"')!).between.includes("Reading the Study."));
  assert.match(tagsOf(document).find((tag) => tag.startsWith("<main"))!, /aria-busy="true"/);
  assert.deepEqual(inertControls(document), []);
});

test("a read error on state 04: the failure with the cause of no answer, Read again, and no part of an earlier read", async (t) => {
  workspace(t, ["bike"]);
  recorder(t, TIMEOUT);
  await runCommand();
  await settle();
  const document = lastDocument();
  assert.ok(words(elementOf(document, '<div data-element="failure">')).includes("timeout"));
  assert.ok(!document.includes('<section data-part="pending">'));
  assert.ok(document.includes(`data-message="${contract.messages[0]}"`));
});

test("figures unavailable on state 04: the status read stands whole, and the fold of the charts holds the label of a failed figures call", async (t) => {
  const { document } = await documentFor(t, STATE_04(), FIGURES_FAILED);
  const fold = elementOf(elementOf(document, '<section data-part="now"')!, '<details data-element="charts">')!;
  assert.ok(words(fold).includes("Figures unavailable. Read again."));
  assert.ok(elementOf(document, '<section data-part="now"')!.includes("<fieldset "), "the choices stand");
});

test("a write in flight on state 04: the line of a write in flight and the choice sent, and every control inert", async (t) => {
  workspace(t, ["bike"]);
  const { answer } = heldRecorder(t);
  await runCommand();
  answer(STATE_04());
  await settle();
  answer(FIGURES_04());
  await settle();
  panelOf().send({ message: contract.messages[1], pending: 0, option: 0, words: "" });
  const document = lastDocument();
  assert.ok(partsOf(elementOf(document, '<div data-element="notice"')!).between.includes("Recording the Decision."));
  assert.deepEqual(inertControls(document), []);
});

test("no answer, then Send again, on state 04: the words of an unknown outcome and Send again, which sends the held arguments", async (t) => {
  workspace(t, ["bike"]);
  const calls = recorder(t, ...withFigures(STATE_04(), TIMEOUT, TIMEOUT));
  await runCommand();
  await settle();
  panelOf().send({ message: contract.messages[1], pending: 0, option: 0, words: "" });
  await settle();
  const document = lastDocument();
  assert.ok(partsOf(elementOf(document, '<div data-element="notice"')!).between.includes(contract.write_no_answer_words));
  assert.ok(document.includes(`data-message="${contract.messages[2]}"`), "Send again");
  panelOf().send({ message: contract.messages[2] });
  await settle();
  const decides = calls.filter((call) => call.args.includes("decide"));
  assert.equal(decides.length, 2);
  assert.deepEqual(decides[1].args, decides[0].args, "the held arguments, the request id included");
});
