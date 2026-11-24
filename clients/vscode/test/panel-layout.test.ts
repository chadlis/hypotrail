// The layout of a document with a pending decision: a guard, in headless Chrome, of how far from the top the first question and
// the first evidence number stand at the width of `guard_bounds`, and their order in the document's text, which runs without
// Chrome and stands beside the guard.
// "C2 at 420 px: a headless measurement is a regression guard only. The owner's check in VS Code is the acceptance."
// (D-031 on chadlis/hypotrail#75, item 14.)
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { KEPT_READS, documentFor, keptObject, success } from "./panel-harness";

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
  const { document } = await documentFor(t, success(object));
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
