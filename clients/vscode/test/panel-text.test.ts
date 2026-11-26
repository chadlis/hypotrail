import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { KEPT_READS, LITERALS, attributeValues, cspProblems, documentFor, elementOf, geometryValues, keptObject, partsOf, samePath, success } from "./panel-harness";

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
      assert.equal(samePath(sameNonce(added)), samePath(sameNonce(plain)));
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

// The paths of `key_paths` that hold an id or a kind the document uses to find a record or a rule of `next_step`, which no plant replaces.
const FINDING_IDS = [
  "pending_decisions[].comparison_id",
  "pending_decisions[].control_assessment_id",
  "pending_decisions[].candidate_assessment_id",
  "comparisons[].comparison_id",
  "comparisons[].roles.control_assessment_id",
  "comparisons[].roles.candidate_assessment_id",
  "assessments[].assessment_id",
  "decisions[].decision_id",
  "decisions[].cited_ids",
  "decisions[].evidence_change.lines[].assessment_id",
  "decisions[].evidence_change.lines[].latest_assessment_id",
  "record_files[].kind",
  "record_files[].id",
  "next_step.kind",
  "next_step.ids",
  "next_step.context",
  "assessments[].single_feature_check.computed[].metric.id",
  "assessments[].metrics[].id",
  "assessments[].observation_set_id",
  "attempts[].observation_set_id",
  "revisions[].revision",
];
// The kept reads that together hold a text at every other path of `key_paths` that holds one.
const PLANTED_READS = ["status-success", "status-chinook-pending", "status-deviation", "status-result-changed", "demonstration.final.status"];

// `object` with each text at a path of `key_paths` replaced by a planted text with its own token; a map shown whole is one path
// ending in `.*`, and a list of texts takes a planted text in each entry.
function planted(name: string): { object: Record<string, any>; texts: string[]; paths: Set<string>; at: string[] } {
  const object = keptObject(name);
  const texts: string[] = [];
  const paths = new Set<string>();
  const places: string[] = [];
  const plantable = (at: string) => contract.key_paths.includes(at) && !FINDING_IDS.includes(at);
  const plant = (at: string) => {
    const text = PLANT(`zq-token-${name}-${texts.length}`);
    texts.push(text);
    places.push(at);
    paths.add(at);
    return text;
  };
  const walk = (value: any, at: string): any => {
    if (typeof value === "string") return plantable(at) ? plant(at) : value;
    if (Array.isArray(value)) return value.map((each) => walk(each, typeof each === "string" ? at : `${at}[]`));
    if (value === null || typeof value !== "object") return value;
    for (const key of Object.keys(value)) value[key] = walk(value[key], contract.key_paths.includes(`${at}.*`) ? `${at}.*` : at === "" ? key : `${at}.${key}`);
    return value;
  };
  walk(object, "");
  return { object, texts, paths, at: places };
}

for (const name of [...KEPT_READS, ...PLANTED_READS.map((read) => `the planted read made from ${read}`)]) {
  test(`every attribute value is a literal of the client or an index, a geometry attribute a decimal number, and none holds a text of the object read: ${name}`, async (t) => {
    const object = KEPT_READS.includes(name) ? keptObject(name) : planted(name.split(" ").pop()!).object;
    const { document } = await documentFor(t, success(object));
    for (const value of attributeValues(document)) assert.ok(LITERALS.includes(value.replace(/\d+$/, "")), value);
    for (const value of geometryValues(document)) assert.match(value, /^\d+(\.\d+)?$/);
    assert.ok(!attributeValues(document).some((value) => value.includes("zq-token")));
  });
}

for (const name of PLANTED_READS) {
  test(`a text of the object read that holds markup stays text: no problem of the document test, a planted text between tags at each planted path: the planted read made from ${name}`, async (t) => {
    const { object, texts, at } = planted(name);
    const { document } = await documentFor(t, success(object));
    assert.deepEqual(cspProblems(document), []);
    const { between } = partsOf(document);
    // A record the panel does not show, such as an Assessment no reference names, holds planted texts that stand nowhere.
    for (const path of new Set(at)) assert.ok(texts.some((text, index) => at[index] === path && between.includes(text)), path);
  });
}

test("the planted reads hold a planted text at every path of key_paths whose value is a text, but the ids that find a record", () => {
  const covered = new Set(PLANTED_READS.flatMap((name) => [...planted(name).paths]));
  const texts = new Set<string>();
  for (const name of KEPT_READS) for (const at of planted(name).paths) texts.add(at);
  assert.deepEqual([...covered].sort(), [...texts].sort());
});

test("a planted geometry attribute that holds a text is found, and a planted attribute of another name that holds a number is found", async (t) => {
  const { document } = await documentFor(t, success(keptObject("status-success")));
  const text = document.replace("</main>", '<svg aria-hidden="true"><rect x="0" y="0" width="zq-token" height="8"></rect></svg></main>');
  assert.ok(geometryValues(text).some((value) => !/^\d+(\.\d+)?$/.test(value)));
  const number = document.replace("</main>", '<span data-zq="12.75"></span></main>');
  assert.ok(attributeValues(number).some((value) => !LITERALS.includes(value.replace(/\d+$/, ""))));
});
