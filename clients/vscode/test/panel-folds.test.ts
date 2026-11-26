// The links into folds, in headless Chrome: a number link whose target stands inside a closed fold opens the folds that hold it and moves
// the view to it, on the kept read of state 05 of the journey (chadlis/hypotrail#257).
import { test } from "node:test";
import assert from "node:assert/strict";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { JOURNEY } from "./kept";
import { documentFor, keptObject, success } from "./panel-harness";

test("a number link of the band whose target stands in a closed step opens that step and moves the view to the target: state 05", { timeout: 60000 }, async (t) => {
  if (!hasChrome(t, "the links into folds")) return;
  const address = await startChrome(t);
  if (address === undefined) return t.skip(`Chrome at ${CHROME} did not start within ${START_MS} ms`);
  const { document } = await documentFor(t, success(keptObject(`${JOURNEY}05-decided.status`)));
  const evaluate = await opened(t, address, document, 420, 700);
  const link = `document.querySelector('p[data-element="band"] a[data-kind="write_sequence"]')`;
  const target = `document.getElementById(${link}.getAttribute("href").slice(1))`;
  assert.equal(await evaluate(`${target}.closest("details").open`), false, "the target stands in a closed fold");
  assert.equal(await evaluate(`${target}.checkVisibility()`), false, "and is not drawn");
  await evaluate(`${link}.click()`);
  assert.equal(await evaluate(`${target}.closest("details").open`), true, "the fold is open");
  assert.equal(await evaluate(`${target}.checkVisibility()`), true, "the target is drawn");
  const top: number = await evaluate(`${target}.getBoundingClientRect().top`);
  assert.ok(top > -1 && top < 700, `the view moved to the target, now at ${top} px`);
});
