// A Comparison whose main delta value is null: the word in the delta's place, no bounds and no number there, the coverage after it.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { documentFor, elementOf, elementsOf, keptObject, partsOf, success } from "./panel-harness";

type Entry = Record<string, any>;

// A value of the object read written by another route than the client's, to find it in a document.
function shown(value: unknown): string {
  if (typeof value !== "number" || Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

// The two kept reads that withhold a delta: the agent record shape (with `reason`, `control` and `candidate`) and the regression one.
const WITHHELD_READS = ["status-chinook-withheld", "status-bike-withheld"];
const NOT_IN_THE_DELTA = ["bound", "interval", "confidence", "coverage_incomplete"];

// Each pending part of the document, with the Comparison of the object read it names.
async function pendingParts(t: TestContext, object: Entry): Promise<{ document: string; parts: { part: string; comparison: Entry }[] }> {
  const { document } = await documentFor(t, success(object));
  const parts = elementsOf(document, '<section data-part="pending">').map((part, index) => ({
    part,
    comparison: object.comparisons.find((each: Entry) => each.comparison_id === object.pending_decisions[index].comparison_id),
  }));
  assert.equal(parts.length, object.pending_decisions.length);
  return { document, parts };
}

const withheldParts = (parts: { part: string; comparison: Entry }[]) => parts.filter(({ comparison }) => comparison.delta.value === null);

for (const name of WITHHELD_READS) {
  test(`the delta's element of a Comparison whose delta value is null holds the word, the delta's metric and unit, and no number: ${name}`, async (t) => {
    const { parts } = await pendingParts(t, keptObject(name));
    assert.ok(withheldParts(parts).length > 0);
    for (const { part, comparison } of withheldParts(parts)) {
      const between = partsOf(elementOf(part, '<p data-element="delta">')!).between;
      assert.match(between, /(^|\s)withheld(\s|$)/, between);
      assert.ok(between.includes(comparison.delta.metric) && between.includes(comparison.delta.unit), between);
      assert.doesNotMatch(between, /\d/, between);
    }
  });

  for (const word of NOT_IN_THE_DELTA) {
    test(`the delta's element of a Comparison whose delta value is null does not hold ${word}: ${name}`, async (t) => {
      const { parts } = await pendingParts(t, keptObject(name));
      for (const { part } of withheldParts(parts)) assert.doesNotMatch(elementOf(part, '<p data-element="delta">')!, new RegExp(word, "i"));
    });
  }
}

for (const name of ["status-success", "status-chinook-pending", "status-chinook-withheld"]) {
  test(`the coverage element directly follows the delta's element and holds each key and value of coverage: ${name}`, async (t) => {
    const { parts } = await pendingParts(t, keptObject(name));
    for (const { part, comparison } of parts) {
      const delta = elementOf(part, '<p data-element="delta">')!;
      const coverage = elementOf(part, '<p data-element="coverage">')!;
      assert.ok(part.includes(`${delta}\n${coverage}`), "the coverage element directly follows the delta's element");
      const between = partsOf(coverage).between;
      for (const [key, value] of Object.entries(comparison.coverage)) assert.match(between, new RegExp(`(^|\\s)${key}\\s+${shown(value).replace(".", "\\.")}(\\s|$)`), `${key} in ${between}`);
    }
  });
}

test("status-chinook-withheld: the word stands once for each Comparison whose main delta value is null, and no secondary delta is shown", async (t) => {
  const object = keptObject("status-chinook-withheld");
  assert.ok(object.comparisons.every((comparison: Entry) => comparison.secondary_deltas.every((delta: Entry) => delta.value === null)));
  const { document, parts } = await pendingParts(t, object);
  const count = partsOf(document).between.split(/\s+/).filter((word) => word === "withheld").length;
  assert.equal(count, withheldParts(parts).length);
});

test("status-chinook-withheld: the Comparison's part holds no roles' element", async (t) => {
  const object = keptObject("status-chinook-withheld");
  const { parts } = await pendingParts(t, object);
  assert.ok(withheldParts(parts).every(({ comparison }) => "control" in comparison.delta && "candidate" in comparison.delta));
  for (const { part } of withheldParts(parts)) assert.equal(elementOf(elementOf(part, '<div data-part="comparison">')!, '<p data-element="roles">'), undefined);
});

test("with the entry withheld of contract.json changed, the delta's element holds the changed word and not withheld: status-chinook-withheld", async (t) => {
  const loaded = contract as Record<string, unknown>;
  const kept = loaded.withheld;
  loaded.withheld = "zq-changed-word";
  t.after(() => {
    loaded.withheld = kept;
  });
  const { parts } = await pendingParts(t, keptObject("status-chinook-withheld"));
  for (const { part } of withheldParts(parts)) {
    const between = partsOf(elementOf(part, '<p data-element="delta">')!).between;
    assert.match(between, /(^|\s)zq-changed-word(\s|$)/, between);
    assert.doesNotMatch(between, /withheld/, between);
  }
});
