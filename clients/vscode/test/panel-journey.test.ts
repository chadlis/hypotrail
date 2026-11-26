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
import { LITERALS, S2_INTERVAL, assertNowOrder, attributeValues, cspProblems, documentFor, elementOf, elementsOf, geometryValues, holdsTheHeadings, markedTexts, partsOf, success, unescaped } from "./panel-harness";
import { exit, type Answer } from "./recorder";
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
        if (key === "coverage") values.push(name);
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
    const band = elementOf(document, '<p data-element="band">')!;
    const label = "Since this panel's last read";
    assert.ok(contract.labels.includes(label));
    const link = new RegExp(`${label} <a href="#([^"]*)" data-kind="writes_since">([^<]*)</a>`).exec(unescaped(band));
    assert.ok(read.writes_since.length > 0 && link, band);
    assert.equal(link![2], String(read.writes_since.length));
    assert.equal([...document.matchAll(new RegExp(` id="${link![1]}"`, "g"))].length, 1);
    assert.match(document, new RegExp(`<div data-part="since" id="${link![1]}">`));
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
    if (interval !== undefined) read.comparisons[0].interval = interval;
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
  const fresh = read.comparisons.find((each: Record<string, any>) => each.comparison_id === read.next_step.ids[0]).delta.value;
  const deltas = [...now.matchAll(/<a href="#comparison-\d+" data-kind="delta">([^<]*)<\/a>/g)].map((match) => match[1]);
  assert.deepEqual(deltas.slice(0, 2), [written(fresh), written(cited)], "the new delta in the delta line, then the cited one beside it");
  assert.ok(words(elementOf(now, '<p data-element="cited-delta">')).includes(written(cited)), "the cited delta in its line");
  assert.ok(words(elementOf(now, '<p data-element="context">')).includes(earlier.option), "the earlier Decision's option");
  // The two lines hold the two deltas as read, and no number of their own: no difference is printed, whatever its value.
  for (const line of ['<p data-element="delta">', '<p data-element="cited-delta">']) {
    const numbers = words(elementOf(now, line)).match(/-?\d+(\.\d+)?/g) ?? [];
    assert.deepEqual(numbers, [line.includes("cited") ? written(cited) : written(fresh)], line);
  }
  if (cited !== fresh) assert.ok(!words(now).split(" ").includes(written(fresh - cited)), "the difference");
});
