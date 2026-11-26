// The "Data profile" step: the third read of the panel, `profile --json`, drawn as the first step of "The Study so far" (chadlis/hypotrail#262).
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { written } from "../src/content";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { BELOW_AA, THEMES, themed } from "./themes";
import { KEPT_FIGURES, documentFor, elementOf, elementsOf, keptObject, partsOf, samePath, success } from "./panel-harness";
import { exit, profile, type Answer } from "./recorder";

type Entry = Record<string, any>;

const STATUS = "status-success";
const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");
const label = (text: string): string => contract.labels[contract.labels.indexOf(text)];
const NOT_AVAILABLE = label("not available at prediction time");
const FAILED = label("The data profile could not be read.");
const DIFFERS = label("The Workload as declared now no longer gives this Study's Protocol; the profile is read from the Study's own data.");
const STEP = '<details data-part="profile"';

const kept = (): Entry => keptObject("profile-bike");

// The document of the kept Bike status read, its kept figures read, and the profile call answered with `answer`.
async function documentWith(t: TestContext, answer: Answer): Promise<string> {
  return (await documentFor(t, success(keptObject(STATUS)), success(keptObject(KEPT_FIGURES[STATUS])), profile(answer))).document;
}

// The `main` of a document with its heading's path fixed and the step of the Data profile left out.
const restOf = (document: string): string => {
  const main = samePath(elementOf(document, "<main ")!);
  const step = elementOf(main, STEP);
  return step === undefined ? main : main.replace(`${step}\n`, "");
};

const pathOf = (document: string): string => elementOf(document, '<section data-part="path">')!;
const profileLinks = (html: string): string[] => [...html.matchAll(/<a href="#profile-0" data-kind="profile">([^<]*)<\/a>/g)].map((match) => partsOf(match[1]).between);
const figure = (step: string, name: string): string | undefined => elementOf(step, `<div data-figure="${name}">`);

test("the kept profile read is the Bike Study's at the Write sequence of the kept status read beside it", () => {
  assert.equal(kept().ok, true);
  assert.equal(kept().write_sequence, keptObject(STATUS).write_sequence);
});

test("on the kept Bike read, The Study so far begins with the closed step Data profile, its line the count of train days, holding the four figures in order", async (t) => {
  const object = kept();
  const document = await documentWith(t, success(object));
  const path = pathOf(document);
  const step = elementOf(path, STEP)!;
  assert.ok(step, "the step");
  assert.equal(path.indexOf("<details"), path.indexOf(STEP), "the first step of the path");
  assert.ok(!/^<details[^>]*\sopen/.test(step), "closed");
  assert.equal(words(elementOf(step, "<summary>")), `Data profile · ${written(object.items)} ${object.partition} days`);
  const places = ["profile-target", "profile-distributions", "profile-matrix", "profile-against"].map((name) => step.indexOf(`<div data-figure="${name}">`));
  assert.ok(places.every((place) => place >= 0), `the four figures: ${places}`);
  assert.deepEqual(places, [...places].sort((a, b) => a - b), "in order");
  assert.ok(!step.includes(DIFFERS), "no sentence on a Workload that gives the Study's Protocol");
});

test("on the kept Bike read, each forbidden column of the matrix carries not available at prediction time, and no allowed one does", async (t) => {
  const object = kept();
  const matrix = figure(elementOf(await documentWith(t, success(object)), STEP)!, "profile-matrix")!;
  const rows = elementsOf(elementOf(matrix, '<ol data-element="order">')!, "<li>");
  assert.deepEqual(rows.map((row) => /<span data-text>([^<]*)<\/span>/.exec(row)![1]), object.associations.order);
  const available = new Map(object.columns.map((column: Entry) => [column.name, column.available]));
  assert.ok([...available.values()].includes(false) && [...available.values()].includes(true));
  rows.forEach((row, at) => assert.equal(words(row).endsWith(NOT_AVAILABLE), available.get(object.associations.order[at]) === false, row));
});

test("on the kept Bike read, each number of the step equals the value at its key path", async (t) => {
  const object = kept();
  const step = elementOf(await documentWith(t, success(object)), STEP)!;
  assert.deepEqual(profileLinks(elementOf(step, "<summary>")!), [written(object.items)]);
  const quartiles = ["min", "q1", "median", "q3", "max"];
  const target = figure(step, "profile-target")!;
  assert.deepEqual(profileLinks(target), quartiles.map((key) => written(object.target.figures.quartiles[key])));
  const columns = elementsOf(figure(step, "profile-distributions")!, '<details data-element="distribution">');
  assert.equal(columns.length, object.columns.length);
  object.columns.forEach((column: Entry, at: number) => {
    const { counts, histogram } = column.distribution;
    const expected = counts ? counts.map((each: Entry) => written(each.count)) : histogram.flatMap((bin: Entry) => [bin.low, bin.high, bin.count].map(written));
    assert.deepEqual(profileLinks(columns[at]), expected, column.name);
  });
  const matrix = figure(step, "profile-matrix")!;
  const flagged = object.associations.pairs.filter((pair: Entry) => pair.flagged);
  assert.ok(flagged.length > 0);
  assert.deepEqual(profileLinks(elementOf(matrix, '<ul data-element="flagged">')!), flagged.map((pair: Entry) => written(pair.value)));
  assert.deepEqual(profileLinks(elementOf(matrix, '<p data-element="level">')!), [written(object.associations.level)]);
  assert.deepEqual(profileLinks(elementOf(matrix, '<details data-element="numbers">')!), object.associations.pairs.map((pair: Entry) => written(pair.value)));
  const against = elementsOf(figure(step, "profile-against")!, '<div data-element="against">');
  assert.equal(against.length, object.against_target.length);
  object.against_target.forEach((entry: Entry, at: number) => {
    const values = entry.values ? entry.values.flatMap((each: Entry) => [each.count, ...quartiles.map((key) => each.figures.quartiles?.[key] ?? null)]) : [];
    assert.deepEqual(profileLinks(against[at]), [entry.value, entry.rows, ...values].map(written), entry.name);
    assert.equal(elementsOf(against[at], "<svg ").length, 1, entry.name);
    assert.equal(against[at].includes("<table"), entry.values !== null, `${entry.name}: a table for a categorical feature only`);
  });
});

test("with workload_protocol differs, the step holds the sentence of Q3 above the four figures", async (t) => {
  const step = elementOf(await documentWith(t, success({ ...kept(), workload_protocol: "differs" })), STEP)!;
  const sentence = elementOf(step, '<p data-element="differs">');
  assert.equal(words(sentence), DIFFERS);
  const places = ["profile-target", "profile-distributions", "profile-matrix", "profile-against"].map((name) => step.indexOf(`<div data-figure="${name}">`));
  assert.ok(places.every((place) => place > step.indexOf(sentence!)), `the sentence above the four figures: ${places}`);
});

test("with a refusal UNSUPPORTED_CAPABILITY the document holds no step and no failure text, and the rest is the document of a usable read", async (t) => {
  const refusal = keptObject("profile-chinook");
  assert.equal(refusal.error.code, "UNSUPPORTED_CAPABILITY");
  const usable = await documentWith(t, success(kept()));
  const refused = await documentWith(t, exit(2, JSON.stringify(refusal)));
  assert.ok(!refused.includes(STEP) && !refused.includes(FAILED));
  assert.equal(samePath(elementOf(refused, "<main ")!), restOf(usable));
});

const FAILURES: [string, Answer, string][] = [
  ["another refusal", exit(3, JSON.stringify({ ok: false, error: { code: "DATA_INTEGRITY", message: "The dataset does not match its digest." } })), `${FAILED} DATA_INTEGRITY`],
  ["a read with no answer", { error: { code: "ENOENT" } }, FAILED],
  ["a read with another write_sequence", success({ ...kept(), write_sequence: kept().write_sequence + 2 }), FAILED],
];

for (const [name, answer, line] of FAILURES) {
  test(`with ${name}, the step holds the failure sentence${line === FAILED ? " alone" : " and the refusal's code"} with Read again, and the rest is the document of a usable read`, async (t) => {
    const usable = await documentWith(t, success(kept()));
    const failed = await documentWith(t, answer);
    const step = elementOf(failed, STEP)!;
    assert.ok(step, "the step");
    assert.equal(words(elementOf(step, "<summary>")), `Data profile ${line}`);
    assert.equal(elementsOf(step, `<button data-message="${contract.messages[0]}"`).length, 1, "Read again");
    assert.equal(elementsOf(step, "<svg ").length, 0, "no figure");
    assert.equal(restOf(failed), restOf(usable));
  });
}

// "In the four themes at 420 and 900 px, the step's texts stand at AA contrast on the kept Bike read." (chadlis/hypotrail#262): with
// every fold of the step open, so that the texts inside them are drawn too.
test("in each of the four themes at 420 and 900 px, every text of the step on the kept Bike read, its folds open, stands at AA contrast", { timeout: 120000 }, async (t) => {
  if (!hasChrome(t, "the contrast of the Data profile")) return;
  const address = await startChrome(t);
  if (address === undefined) return t.skip(`Chrome at ${CHROME} did not start within ${START_MS} ms`);
  const document = await documentWith(t, success(kept()));
  const step = elementOf(document, STEP)!;
  const open = document.replace(step, step.replace(/<details /g, "<details open "));
  for (const theme of Object.keys(THEMES)) {
    for (const width of [420, 900]) {
      const evaluate = await opened(t, address, open, width, 700);
      await evaluate(themed(theme));
      assert.equal(await evaluate('document.querySelector(\'details[data-part="profile"]\').open'), true);
      assert.deepEqual(await evaluate(BELOW_AA), [], `${theme} at ${width} px`);
    }
  }
});
