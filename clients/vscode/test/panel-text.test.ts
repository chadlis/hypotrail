import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { KEPT_READS, cspProblems, documentFor, elementOf, keptObject, partsOf, success } from "./panel-harness";

const CLIENT = path.join(__dirname, "..", "..");
const LITERALS = [
  ...fs.readdirSync(path.join(CLIENT, "src")).map((name) => fs.readFileSync(path.join(CLIENT, "src", name), "utf8")),
  fs.readFileSync(path.join(CLIENT, "contract.json"), "utf8"),
].join("\n");

const sameNonce = (document: string): string => document.replace(/nonce-[A-Za-z0-9]+/g, "nonce-N").replace(/nonce="[A-Za-z0-9]+"/g, 'nonce="N"');

// A key the client does not know.
const PLACES: [string, (object: Record<string, any>) => Record<string, any> | undefined][] = [
  ["the top level", (object) => object],
  ["an entry of pending_decisions", (object) => object.pending_decisions[0]],
  ["an entry of comparisons", (object) => object.comparisons[0]],
  ["an entry of assessments", (object) => object.assessments[0]],
  ["an entry of declared_deviations", (object) => object.declared_deviations[0]],
];

for (const name of ["status-success", "status-deviation"]) {
  for (const [place, at] of PLACES) {
    const target = at(keptObject(name));
    if (target === undefined) continue;
    test(`a key the client does not know, added at ${place}, gives the same document: ${name}`, async (t) => {
      const plain = (await documentFor(t, success(keptObject(name)))).document;
      const object = keptObject(name);
      at(object)!.zq_unknown_key = { text: "zq-unknown value", number: 4242 };
      const added = (await documentFor(t, success(object))).document;
      assert.equal(sameNonce(added), sameNonce(plain));
    });
  }
}

test("a key added inside coverage is shown in the coverage element, with its value", async (t) => {
  const object = keptObject("status-success");
  object.comparisons[0].coverage.zq_added = 4242;
  const coverage = partsOf(elementOf((await documentFor(t, success(object))).document, '<p data-element="coverage">')!).between;
  assert.match(coverage, /zq_added\s+4242(\s|$)/);
});

// No text of the object read stands in an attribute, and none becomes markup.
const PLANT = (token: string) => `<script>alert(1)</script><b onclick="go()" style="color: red">https://example.com/${token}</b>`;

// The text paths the document shows, but the ids it uses to find a record.
function planted(): { object: Record<string, any>; texts: string[] } {
  const object = keptObject("status-deviation");
  const texts: string[] = [];
  const plant = () => {
    const text = PLANT(`zq-token-${texts.length}`);
    texts.push(text);
    return text;
  };
  object.study.study_id = plant();
  for (const pending of object.pending_decisions) {
    pending.question.text = plant();
    for (const option of pending.options) [option.text, option.consequence] = [plant(), plant()];
  }
  for (const comparison of object.comparisons) {
    comparison.delta.metric = plant();
    comparison.delta.unit = plant();
    for (const warning of comparison.warnings) [warning.code, warning.message] = [plant(), plant()];
    comparison.limitations = comparison.limitations.map(plant);
  }
  for (const assessment of object.assessments) for (const metric of assessment.metrics) [metric.id, metric.unit, metric.status] = [plant(), plant(), plant()];
  for (const deviation of object.declared_deviations) deviation.declared_deviation_id = plant();
  return { object, texts };
}

function attributeValues(document: string): string[] {
  return partsOf(document)
    .tags.filter((tag) => !tag.includes("Content-Security-Policy"))
    .flatMap((tag) => [...tag.matchAll(/\s[a-z-]+="([^"]*)"/g)].map((match) => match[1]))
    .filter((value) => !/^[a-f0-9]{32}$/.test(value));
}

for (const name of [...KEPT_READS, "the planted read"]) {
  test(`every attribute value is a literal of the client, and none holds a text of the object read: ${name}`, async (t) => {
    const object = name === "the planted read" ? planted().object : keptObject(name);
    const { document } = await documentFor(t, success(object));
    for (const value of attributeValues(document)) assert.ok(LITERALS.includes(value.replace(/\d+$/, "")), value);
    assert.ok(!attributeValues(document).some((value) => value.includes("zq-token")));
  });
}

test("a text of the object read that holds markup stays text: no problem of the document test, each planted text between tags", async (t) => {
  const { object, texts } = planted();
  assert.ok(texts.length > 20);
  const { document } = await documentFor(t, success(object));
  assert.deepEqual(cspProblems(document), []);
  const { between } = partsOf(document);
  for (const text of texts) assert.ok(between.includes(text), text);
});
