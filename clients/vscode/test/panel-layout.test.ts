// The layout of a document with a pending decision: a guard, in headless Chrome, of how far from the top the first question and
// the first evidence number stand at the width of `guard_bounds`, and their order in the document's text, which runs without
// Chrome and stands beside the guard.
// "C2 at 420 px: a headless measurement is a regression guard only. The owner's check in VS Code is the acceptance."
// (D-031 on chadlis/hypotrail#75, item 14.)
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { KEPT_FIGURES, KEPT_READS, documentFor, keptObject, success } from "./panel-harness";

const HEIGHT = 900;
const BOUND = Object.fromEntries(contract.guard_bounds.map((entry) => [entry.split("=")[0], Number(entry.split("=")[1])]));

const QUESTION = 'section[data-part="pending"] h3[data-text]';
const DELTA = 'section[data-part="pending"] [data-element="delta"]';

// The selector of the first evidence number: the delta's value of the first pending Comparison, or the delta's element when
// that delta is withheld.
function evidenceOf(object: Record<string, any>): string {
  const first = object.comparisons.find((each: Record<string, any>) => each.comparison_id === object.pending_decisions[0].comparison_id);
  return first.delta.value === null ? DELTA : `${DELTA} a[data-kind="delta"]`;
}

// The tops of the first question and of the first evidence number, from the top of the page, in a document shown at the
// guard's width; `innerWidth` is asserted before anything is measured.
async function measured(t: TestContext, document: string, evidence: string): Promise<{ innerWidth: number; question: number | null; evidence: number | null } | undefined> {
  const address = await startChrome(t);
  if (address === undefined) {
    t.skip(`the guard of how far from the top the first question and the first evidence number stand is skipped: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
    return undefined;
  }
  const evaluate = await opened(t, address, document, BOUND.width, HEIGHT);
  const innerWidth = await evaluate("innerWidth");
  assert.equal(innerWidth, BOUND.width, `innerWidth=${innerWidth}`);
  const top = (selector: string) => `(() => { const found = document.querySelector(${JSON.stringify(selector)}); return found ? found.getBoundingClientRect().top + scrollY : null; })()`;
  return { innerWidth, question: await evaluate(top(QUESTION)), evidence: await evaluate(top(evidence)) };
}

const guarded = (t: TestContext): boolean => hasChrome(t, "the guard of how far from the top the first question and the first evidence number stand");

test("at the width of guard_bounds, the first question and the first evidence number of status-success are within their bounds of the top", { timeout: 60000 }, async (t) => {
  if (!guarded(t)) return;
  const object = keptObject("status-success");
  // The figures read answered after the status read, so that the figures stand in the document measured.
  const { document } = await documentFor(t, success(object), success(keptObject(KEPT_FIGURES["status-success"])));
  assert.ok(document.includes("data-figures"), "the document holds the figures");
  const at = await measured(t, document, evidenceOf(object));
  if (at === undefined) return;
  assert.notEqual(at.question, null, "the first question is found");
  assert.notEqual(at.evidence, null, "the first evidence number is found");
  assert.ok(at.question! <= BOUND.question, `innerWidth=${at.innerWidth}: the first question is ${at.question} px from the top, past ${BOUND.question}`);
  assert.ok(at.evidence! <= BOUND.evidence, `innerWidth=${at.innerWidth}: the first evidence number is ${at.evidence} px from the top, past ${BOUND.evidence}`);
});

test("the guard of how far from the top the first question and the first evidence number stand finds the element it measures on status-chinook-withheld: the delta's element", { timeout: 60000 }, async (t) => {
  if (!guarded(t)) return;
  const object = keptObject("status-chinook-withheld");
  assert.equal(evidenceOf(object), DELTA);
  const { document } = await documentFor(t, success(object));
  const at = await measured(t, document, evidenceOf(object));
  if (at === undefined) return;
  assert.notEqual(at.evidence, null, `innerWidth=${at.innerWidth}: the delta's element is found`);
});

// "From the question: the Comparison, its delta" (chadlis/hypotrail#103, comment 7092994773, task 2).
for (const name of KEPT_READS.filter((read) => keptObject(read).pending_decisions?.length > 0)) {
  test(`the text of the first question comes before the delta's element of the first pending Comparison: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const question = document.indexOf("<h3 data-text>", document.indexOf('<section data-part="pending">'));
    const delta = document.indexOf('<p data-element="delta">', document.indexOf('<section data-part="pending">'));
    assert.ok(question >= 0 && delta >= 0, "both are found");
    assert.ok(question < delta, `the question at ${question}, the delta's element at ${delta}`);
  });
}

// The figures at the two widths of the review, with VS Code's font size and the side padding of its webview.
const VS_CODE_BODY = 'document.body.style.fontSize = "13px"; document.body.style.margin = "0"; document.body.style.padding = "0 20px";';

async function figuresAt(t: TestContext, width: number): Promise<{ tracks: { left: number; width: number }[]; key: number; box: number } | undefined> {
  const address = await startChrome(t);
  if (address === undefined) {
    t.skip(`the layout of the figures is not measured: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
    return undefined;
  }
  const { document } = await documentFor(t, success(keptObject("status-success")), success(keptObject(KEPT_FIGURES["status-success"])));
  const evaluate = await opened(t, address, document, width, HEIGHT);
  await evaluate(`(() => { ${VS_CODE_BODY} return true; })()`);
  return evaluate(`(() => {
    const box = (selector) => document.querySelector(selector).getBoundingClientRect();
    const tracks = [...document.querySelectorAll("[data-dot] svg")].map((svg) => ({ left: Math.round(svg.getBoundingClientRect().left), width: Math.round(svg.getBoundingClientRect().width) }));
    return { tracks, key: box('[data-element="quartiles"]').right, box: box('[data-figure="box"] svg').right };
  })()`);
}

for (const [width, columns] of [
  [420, 1],
  [900, 2],
] as const) {
  test(`at ${width} px the rows of the dots of status-success stand in ${columns} column${columns > 1 ? "s" : ""}, every track as wide as the others, and the key of the box plot ends within the box plot`, { timeout: 60000 }, async (t) => {
    if (!hasChrome(t, "the layout of the figures")) return;
    const at = await figuresAt(t, width);
    if (at === undefined) return;
    assert.equal(at.tracks.length, keptObject(KEPT_FIGURES["status-success"]).comparisons[0].paired_deltas.length);
    assert.equal(new Set(at.tracks.map((track) => track.left)).size, columns, JSON.stringify([...new Set(at.tracks.map((track) => track.left))]));
    assert.equal(new Set(at.tracks.map((track) => track.width)).size, 1, JSON.stringify([...new Set(at.tracks.map((track) => track.width))]));
    assert.ok(at.key <= at.box + 0.5, `the key ends at ${at.key} px, the box plot at ${at.box} px`);
  });
}
