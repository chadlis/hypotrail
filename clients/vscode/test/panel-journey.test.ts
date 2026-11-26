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
import { LITERALS, attributeValues, cspProblems, documentFor, elementOf, geometryValues, holdsTheHeadings, markedTexts, unescaped } from "./panel-harness";
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
