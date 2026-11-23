import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import {
  documentFor,
  elementOf,
  elementsOf,
  followLink,
  keptObject,
  lastDocument,
  markedTexts,
  panelOf,
  partsOf,
  runCommand,
  settle,
  success,
  workspace,
} from "./panel-harness";
import { recorder } from "./recorder";
import * as stub from "./vscode-stub";

// The kept reads of #178, and the ones of them that hold a Decision.
const READS = ["status-decided", "status-rescored", "status-result-changed", "status-repeated", "status-chinook-decided", "status-success"];
const DECIDED = READS.filter((name) => keptObject(name).decisions.length > 0);
const CHANGED = DECIDED.filter((name) => keptObject(name).decisions.some((decision: Entry) => decision.evidence_change !== null));

type Entry = Record<string, any>;

const PHRASES: Record<string, string> = Object.fromEntries(contract.evidence_phrases.map((entry) => entry.split("=") as [string, string]));
const DECISION = '<section data-part="decision"';
const LINKED = "Opened from a link";
const NO_DECISION = "This Study holds no Decision with the id";

const decisionParts = (document: string): string[] => elementsOf(document, DECISION);
const between = (html: string | undefined): string => partsOf(html ?? "").between;
const words = (text: string): string => text.split(/\s+/).filter(Boolean).join(" ");

// A number written by another route than the client's, to find a value in a document.
function written(value: number | null): string {
  if (value === null) return "no value";
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

test("the phrases of contract.json name the three states the core computes, the strongest first", () => {
  assert.deepEqual(Object.keys(PHRASES), ["result_changed", "evidence_rescored", "repeated"]);
});

// Each recorded Decision, read from the Study and from nowhere else: each part in the order of decisions, with its id,
// its option whole and marked, its author and each cited id.
function assertDecisions(document: string, object: Entry): void {
  const parts = decisionParts(document);
  assert.equal(parts.length, object.decisions.length);
  const positions = object.decisions.map((decision: Entry) => document.indexOf(decision.decision_id, document.indexOf(DECISION)));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions, "the decision_id values follow the order of decisions");
  object.decisions.forEach((decision: Entry, index: number) => {
    const part = parts[index];
    assert.ok(between(part).includes(decision.decision_id), decision.decision_id);
    assert.ok(markedTexts(part).includes(decision.option), decision.option);
    assert.match(words(between(part)), new RegExp(`Author ${decision.author}( |$)`));
    const cited = words(between(elementOf(part, '<ul data-element="cited">'))).split(" ");
    decision.cited_ids.forEach((id: string, at: number) => assert.equal(cited[at], id, `the cited id ${id}, at its place in the list of cited ids`));
    assert.equal(
      cited.length,
      decision.cited_ids.length,
      `${cited.length} cited ids shown for ${decision.cited_ids.length} cited ids in the Decision`,
    );
  });
}

for (const name of DECIDED) {
  test(`each Decision stands in the order of decisions, with its id, its option whole and marked, its author and each cited id: ${name}`, async (t) => {
    const object = keptObject(name);
    assertDecisions((await documentFor(t, success(object))).document, object);
  });
}

// No kept read holds a Decision with two cited ids, since their order follows the real ids the CLI draws.
test("each Decision stands with each cited id when one of them cites two: status-result-changed with an Assessment of the read added to the first", async (t) => {
  const object = keptObject("status-result-changed");
  const added = object.assessments.find((assessment: Entry) => !object.decisions[0].cited_ids.includes(assessment.assessment_id)).assessment_id;
  object.decisions[0].cited_ids.push(added);
  assert.equal(object.decisions[0].cited_ids.length, 2);
  assertDecisions((await documentFor(t, success(object))).document, object);
});

const PLANTED_ID = "7f3e9d1c-2b4a-4c8e-9a6f-0d5b3e7c1a29";

test("a Decision on screen comes from the read alone: after the panel is closed and opened on a Study with no Decision", async (t) => {
  const decided = keptObject("status-decided");
  decided.decisions[0].decision_id = PLANTED_ID;
  const [study] = workspace(t, ["bike"]);
  recorder(t, success(decided), success(keptObject("status-success")));
  await runCommand();
  await settle();
  assert.ok(lastDocument().includes(PLANTED_ID));
  panelOf().dispose();
  await followLink(0, study);
  await settle();
  assert.equal(stub.state.panels.length, 2);
  assert.ok(!lastDocument().includes(PLANTED_ID), "the Decision of the earlier read, after the panel was closed");
});

test("a Decision on screen comes from the read alone: the panel, never closed, opened on a Study with no Decision before and after it", async (t) => {
  const decided = keptObject("status-decided");
  decided.decisions[0].decision_id = PLANTED_ID;
  const [first, second] = workspace(t, ["a", "b"]);
  recorder(t, success(keptObject("status-success")), success(decided), success(keptObject("status-success")));
  await followLink(0, first);
  await settle();
  assert.ok(!lastDocument().includes(PLANTED_ID), "no Decision before the read that holds it");
  await followLink(0, second);
  await settle();
  assert.ok(lastDocument().includes(PLANTED_ID));
  await followLink(0, first);
  await settle();
  assert.equal(stub.state.panels.length, 1);
  assert.ok(!lastDocument().includes(PLANTED_ID), "the Decision of the earlier read, the panel never closed");
});

// Whether a Decision still applies, and why not.
for (const name of DECIDED) {
  test(`beside the key applies stands the value the read holds, turned over in the test, its reasons and evidence left as they were: ${name}`, async (t) => {
    const object = keptObject(name);
    for (const decision of object.decisions) decision.applies = !decision.applies;
    const parts = decisionParts((await documentFor(t, success(object))).document);
    object.decisions.forEach((decision: Entry, index: number) => {
      assert.match(words(between(parts[index])), new RegExp(`(^| )applies ${decision.applies}( |$)`), `applies ${decision.applies}`);
    });
  });
}

for (const name of DECIDED) {
  test(`each reason of a Decision that does not apply stands in its part with its reason and its id, as they are: ${name}`, async (t) => {
    const object = keptObject(name);
    const parts = decisionParts((await documentFor(t, success(object))).document);
    object.decisions.forEach((decision: Entry, index: number) => {
      if (decision.applies) return;
      assert.ok(decision.reasons.length > 0);
      const reasons = elementsOf(elementOf(parts[index], '<ul data-element="reasons">')!, "<li>").map((each) => words(between(each)));
      for (const reason of decision.reasons) assert.ok(reasons.includes(`${reason.reason} ${reason.id}`), `${reason.reason} ${reason.id} in ${reasons}`);
    });
  });
}

// What happened to the evidence: the state of the whole, and `revision_changed` beside it.
const stateOf = (part: string): string => words(between(elementOf(part, '<p data-element="evidence">')));

for (const name of CHANGED) {
  test(`the state of the evidence shows its phrase and neither of the others, with revision_changed beside it when a reason: ${name}`, async (t) => {
    const object = keptObject(name);
    const parts = decisionParts((await documentFor(t, success(object))).document);
    object.decisions.forEach((decision: Entry, index: number) => {
      const shown = stateOf(parts[index]);
      for (const [code, phrase] of Object.entries(PHRASES)) assert.equal(shown.includes(phrase), code === decision.evidence_change.state, `${phrase} in ${shown}`);
      const revisionChanged = decision.reasons.some((reason: Entry) => reason.reason === "revision_changed");
      assert.equal(shown.includes("revision_changed"), revisionChanged, `${shown}`);
    });
  });
}

const STATES = Object.keys(PHRASES);

for (const name of ["status-result-changed", "status-rescored", "status-repeated"]) {
  test(`with the state of the whole changed in the test and its lines left, the document shows the changed state's phrase: ${name}`, async (t) => {
    const object = keptObject(name);
    const decision = object.decisions[0];
    const changed = STATES[(STATES.indexOf(decision.evidence_change.state) + 1) % STATES.length];
    decision.evidence_change.state = changed;
    const shown = stateOf(decisionParts((await documentFor(t, success(object))).document)[0]);
    assert.ok(shown.includes(PHRASES[changed]), shown);
    assert.ok(decision.evidence_change.lines.every((line: Entry) => line.state !== changed));
  });
}

test("status-decided: a Decision whose evidence_change is null shows none of the phrases", async (t) => {
  const object = keptObject("status-decided");
  assert.equal(object.decisions[0].evidence_change, null);
  const shown = between((await documentFor(t, success(object))).document);
  for (const phrase of Object.values(PHRASES)) assert.ok(!shown.includes(phrase), phrase);
});

// Each line: its phrase, its count of changed Items and both values of each Metric.
const linesOf = (part: string): string[] => elementsOf(part, '<li data-part="line">').map((line) => words(between(line)));

for (const name of CHANGED) {
  test(`each line shows its state's phrase, its count of changed Items and the cited and latest value of each Metric: ${name}`, async (t) => {
    const object = keptObject(name);
    const parts = decisionParts((await documentFor(t, success(object))).document);
    object.decisions.forEach((decision: Entry, index: number) => {
      const lines = linesOf(parts[index]);
      assert.equal(lines.length, decision.evidence_change.lines.length);
      decision.evidence_change.lines.forEach((line: Entry, at: number) => {
        assert.ok(lines[at].includes(PHRASES[line.state]), lines[at]);
        assert.ok(lines[at].includes(`Changed Items ${line.changed_item_count}`), lines[at]);
        for (const metric of line.metrics) {
          assert.ok(lines[at].includes(`${metric.id} Cited value ${written(metric.cited)} Latest value ${written(metric.latest)}`), lines[at]);
        }
      });
    });
  });
}

test("status-result-changed with one latest value set to null: no value in its place, and the cited value beside it", async (t) => {
  const object = keptObject("status-result-changed");
  const metric = object.decisions[0].evidence_change.lines[0].metrics[0];
  metric.latest = null;
  const line = linesOf(decisionParts((await documentFor(t, success(object))).document)[0])[0];
  assert.ok(line.includes(`${metric.id} Cited value ${written(metric.cited)} Latest value no value`), line);
});

for (const name of CHANGED) {
  test(`no difference of the cited and the latest value is written: ${name}`, async (t) => {
    const object = keptObject(name);
    const metric = object.decisions[0].evidence_change.lines[0].metrics[0];
    [metric.cited, metric.latest] = [1000.25, 1123.5];
    assert.ok(!JSON.stringify(object).includes("123.25"));
    const { document } = await documentFor(t, success(object));
    assert.ok(between(document).includes("1123.5"));
    assert.ok(!document.includes("123.25"), "the difference 123.25");
  });
}

// A Comparison a Decision cites: its own delta, and the two Assessments its roles name.
const citedComparisons = (object: Entry, decision: Entry): Entry[] => object.comparisons.filter((comparison: Entry) => decision.cited_ids.includes(comparison.comparison_id));

// On the kept read the delta equals the difference of the two Metric values, cited or latest; the changed read tells them apart.
const OWN_DELTA: [string, (object: Entry) => void][] = [
  ["status-result-changed", () => undefined],
  ["status-result-changed with the delta value set to 12.5", (object) => (object.comparisons[0].delta.value = 12.5)],
];

for (const [name, change] of OWN_DELTA) {
  test(`the delta's element of a Comparison a Decision cites holds that Comparison's own delta value: ${name}`, async (t) => {
    const object = keptObject("status-result-changed");
    change(object);
    const parts = decisionParts((await documentFor(t, success(object))).document);
    let found = 0;
    object.decisions.forEach((decision: Entry, index: number) => {
      for (const comparison of citedComparisons(object, decision)) {
        const part = elementOf(parts[index], '<div data-part="comparison"')!;
        assert.ok(between(part).includes(comparison.comparison_id));
        const delta = words(between(elementOf(part, '<p data-element="delta">')));
        assert.ok(delta.includes(`Delta ${written(comparison.delta.value)} ${comparison.delta.metric}`), `the own delta in ${delta}`);
        found += 1;
      }
    });
    assert.equal(found, object.comparisons.length, "each Comparison a Decision cites");
  });
}

for (const name of DECIDED) {
  test(`a Comparison a Decision cites shows the two Assessments its roles name, each under its role with every Metric: ${name}`, async (t) => {
    const object = keptObject(name);
    const parts = decisionParts((await documentFor(t, success(object))).document);
    object.decisions.forEach((decision: Entry, index: number) => {
      for (const comparison of citedComparisons(object, decision)) {
        for (const role of ["control", "candidate"]) {
          const id = comparison.roles[`${role}_assessment_id`];
          const shown = words(between(elementOf(parts[index], `<div data-role="${role}">`)));
          assert.ok(shown.includes(`Assessment ${id}`), `${role} ${id}`);
          const assessment = object.assessments.find((each: Entry) => each.assessment_id === id);
          for (const metric of assessment.metrics) assert.ok(shown.includes(`Metric ${metric.id} ${written(metric.value)} ${metric.unit} status ${metric.status}`), `${role} ${metric.id}`);
        }
      }
    });
  });
}

test("status-result-changed with roles removed from the cited Comparison: its delta, and no Assessment under a role", async (t) => {
  const object = keptObject("status-result-changed");
  const comparison = object.comparisons[0];
  assert.ok(object.decisions[0].cited_ids.includes(comparison.comparison_id));
  delete comparison.roles;
  const part = decisionParts((await documentFor(t, success(object))).document)[0];
  assert.ok(words(between(elementOf(part, '<p data-element="delta">'))).includes(`Delta ${written(comparison.delta.value)}`), "the Comparison's delta");
  assert.equal(elementOf(part, "<div data-role="), undefined, "no Assessment under a role");
});

// The Decision a deep link names.
async function linkedDocument(t: Parameters<typeof workspace>[0], object: Entry, decision: string): Promise<string> {
  const [study] = workspace(t, ["bike"]);
  recorder(t, success(object));
  await followLink(1, study, decision);
  await settle();
  return lastDocument();
}

for (const index of [0, 1]) {
  test(`a link of the second form marks its Decision with the fixed line in its part, and in no other, in the order of decisions: Decision ${index + 1} of status-result-changed`, async (t) => {
    const object = keptObject("status-result-changed");
    assert.equal(object.decisions.length, 2);
    const document = await linkedDocument(t, object, object.decisions[index].decision_id);
    const parts = decisionParts(document);
    object.decisions.forEach((decision: Entry, at: number) => {
      assert.ok(between(parts[at]).includes(decision.decision_id), `the decision_id of part ${at}, in the order of decisions`);
      assert.equal(between(parts[at]).includes(LINKED), at === index, `${LINKED} in part ${at}`);
    });
    assert.equal(between(document).split(LINKED).length, 2, `${LINKED} once in the document`);
  });
}

test("status-decided: a link of the second form whose id no Decision holds shows the Study and one line with the fixed text and that id", async (t) => {
  const object = keptObject("status-decided");
  const missing = "0b8f2c4e-6d1a-4f3b-8e7c-5a9d2f1b3c6e";
  assert.ok(new RegExp(contract.link_decision_id).test(missing));
  assert.ok(!JSON.stringify(object).includes(missing));
  const document = await linkedDocument(t, object, missing);
  const shown = between(document);
  assert.ok(shown.includes(object.study.study_id), "the Study's id");
  const lines = shown.split("\n").filter((line) => line.includes(NO_DECISION));
  assert.equal(words(between(document.split("\n").find((line) => line.includes(NO_DECISION)))), `${NO_DECISION} ${missing}`, "the line holds the fixed text and the id");
  assert.equal(lines.length, 1, "one line names the id");
  assert.deepEqual(stub.callsOf("showErrorMessage"), [], "the link is not refused");
});

// A key the client does not know, in a Decision, its evidence_change and one of its lines.
const sameNonce = (document: string): string => document.replace(/nonce-[A-Za-z0-9]+/g, "nonce-N").replace(/nonce="[A-Za-z0-9]+"/g, 'nonce="N"');

const PLACES: [string, (object: Entry) => Entry][] = [
  ["an entry of decisions", (object) => object.decisions[0]],
  ["its evidence_change", (object) => object.decisions[0].evidence_change],
  ["one entry of its lines", (object) => object.decisions[0].evidence_change.lines[0]],
];

for (const [place, at] of PLACES) {
  test(`a key the client does not know, added at ${place}, gives the same document: status-result-changed`, async (t) => {
    const plain = (await documentFor(t, success(keptObject("status-result-changed")))).document;
    const object = keptObject("status-result-changed");
    at(object).zq_unknown_key = { text: "zq-unknown value", number: 4242 };
    const added = (await documentFor(t, success(object))).document;
    assert.equal(sameNonce(added), sameNonce(plain), "the same document");
  });
}
