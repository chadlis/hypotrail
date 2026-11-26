import { test } from "node:test";
import assert from "node:assert/strict";
import { KEPT_READS, documentFor, elementOf, elementsOf, keptObject, markedTexts, partsOf, success } from "./panel-harness";

const KEPT_ID = "00000000-0000-4000-8000-000000000001";

// The Study's id and Write sequence, and how a number is written.
for (const name of KEPT_READS) {
  test(`the document shows the Study's id whole and its Write sequence as the object holds it: ${name}`, async (t) => {
    const object = keptObject(name);
    const { between } = partsOf((await documentFor(t, success(object))).document);
    assert.ok(between.includes(object.study.study_id), object.study.study_id);
    assert.ok(new RegExp(`(^|\\s)${object.write_sequence}(\\s|$)`).test(between), String(object.write_sequence));
  });
}

test("on a read whose Study id and Write sequence are changed, the document shows the changed values and not the kept id", async (t) => {
  const object = keptObject("status-success");
  assert.equal(object.study.study_id, KEPT_ID);
  object.study.study_id = "6a1f3c2e-9b7d-4e85-a0c4-d2f81b937e56";
  object.write_sequence = 9876543;
  const { between } = partsOf((await documentFor(t, success(object))).document);
  assert.ok(between.includes("6a1f3c2e-9b7d-4e85-a0c4-d2f81b937e56"));
  assert.ok(between.includes("9876543"));
  assert.ok(!between.includes(KEPT_ID));
});

test("a delta that is not an integer is written with six significant digits and no sign: 173.939 on status-success", async (t) => {
  const object = keptObject("status-success");
  assert.equal(object.comparisons[0].delta.value, 173.93948298447322);
  const { between } = partsOf((await documentFor(t, success(object))).document);
  assert.ok(between.includes("173.939"), between);
  assert.ok(!between.includes("173.9394"));
  assert.ok(!between.includes("+173.939"));
});

test("a Metric value of 0.5 is written 0.5 and not 0.500000", async (t) => {
  const object = keptObject("status-success");
  object.assessments[0].metrics[0].value = 0.5;
  const { between } = partsOf((await documentFor(t, success(object))).document);
  assert.ok(/(^|\s)0\.5(\s|$)/.test(between), between);
  assert.ok(!between.includes("0.500000"));
});

// A number written by another route than the client's, to find a value in a document.
function written(value: number | null): string {
  if (value === null) return "no value";
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

const QUESTION = "Which Configuration do we keep after this Comparison?";
// Now's sentence under rule 4: "No pending decision." goes (D-161 item 2, #75 comment 7196684358), and Now says "No decision waits for
// you." (the first addendum to D-161, #75 comment 7197277304).
const NO_PENDING = "No decision waits for you.";

// Each pending decision, its question, and each option with its consequence.
for (const name of KEPT_READS) {
  test(`each option shows its text and its consequence, each whole in a marked element: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const marked = markedTexts(document);
    const { between } = partsOf(document);
    for (const pending of object.pending_decisions) {
      assert.ok(marked.includes(pending.question.text), pending.question.text);
      for (const option of pending.options) {
        for (const text of [option.text, option.consequence]) {
          assert.ok(marked.includes(text), text);
          assert.ok(between.includes(text), text);
        }
      }
    }
  });
}

test("on a read whose question, options and consequences are replaced, the document shows the replaced texts, whole", async (t) => {
  const object = keptObject("status-success");
  const pending = object.pending_decisions[0];
  pending.question.text = "zq-planted question 7 & <its> \"words\"";
  pending.options.forEach((option: Record<string, string>, index: number) => {
    option.text = `zq-planted option ${index} 'quoted'`;
    option.consequence = `zq-planted consequence ${index}: a > b & c < d`;
  });
  const marked = markedTexts((await documentFor(t, success(object))).document);
  assert.ok(marked.includes(pending.question.text));
  for (const option of pending.options) {
    assert.ok(marked.includes(option.text), option.text);
    assert.ok(marked.includes(option.consequence), option.consequence);
  }
});

test("the pending decisions stand in the order of pending_decisions: status-several-pending", async (t) => {
  const object = keptObject("status-several-pending");
  assert.ok(object.pending_decisions.length > 1);
  const parts = elementsOf((await documentFor(t, success(object))).document, '<section data-part="pending">');
  assert.equal(parts.length, object.pending_decisions.length);
  object.pending_decisions.forEach((pending: Record<string, string>, index: number) => assert.ok(parts[index].includes(pending.comparison_id), pending.comparison_id));
});

const NOTHING_PENDING: [string, () => Record<string, any>][] = [
  ["status-decided", () => keptObject("status-decided")],
  [
    "status-success with pending_decisions emptied and its Comparison cited by no Decision",
    () => {
      const object = keptObject("status-success");
      object.pending_decisions = [];
      assert.deepEqual(object.decisions, []);
      return object;
    },
  ],
];

for (const [name, make] of NOTHING_PENDING) {
  test(`with no pending decision the document shows the sentence and no question, and computes nothing pending: ${name}`, async (t) => {
    const object = make();
    const { document } = await documentFor(t, success(object));
    const { between } = partsOf(document);
    assert.ok(between.includes(NO_PENDING));
    // A recorded Decision's part shows its own question; the pending question is read outside those parts.
    assert.ok(!partsOf(document.replace(/<section data-part="decision"[\s\S]*?<\/section>/g, "")).between.includes(QUESTION));
    assert.deepEqual(elementsOf(document, '<section data-part="pending">'), []);
  });
}

test("a Comparison that is not pending and that no Decision cites has its part in the step of the Comparisons of the Study so far, and nowhere else", async (t) => {
  const object = keptObject("status-success");
  object.pending_decisions = [];
  const { document } = await documentFor(t, success(object));
  const step = elementOf(document, '<details data-step="comparisons">')!;
  for (const comparison of object.comparisons) {
    assert.ok(step.includes(comparison.comparison_id), comparison.comparison_id);
    assert.equal(document.split(comparison.comparison_id).length - 1, step.split(comparison.comparison_id).length - 1, "nowhere else");
  }
});

// The Comparison, its delta, and the two Assessments under their roles.
for (const name of KEPT_READS) {
  test(`each pending decision shows both Assessments, under their roles, with every entry of their metrics: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const parts = elementsOf(document, '<section data-part="pending">');
    object.pending_decisions.forEach((pending: Record<string, string>, index: number) => {
      for (const [role, key] of [["control", "control_assessment_id"], ["candidate", "candidate_assessment_id"]]) {
        const part = elementOf(parts[index], `<div data-role="${role}">`)!;
        assert.ok(part, role);
        const assessment = object.assessments.find((each: Record<string, string>) => each.assessment_id === pending[key]);
        assert.ok(partsOf(part).between.includes(assessment.assessment_id), assessment.assessment_id);
        // An Assessment has one part in a document; a later reference shows its id as a link to that part.
        const shown = elementsOf(document, '<div data-part="assessment"').find((each) => partsOf(each).between.includes(assessment.assessment_id))!;
        const { between } = partsOf(shown);
        for (const metric of assessment.metrics) {
          for (const text of [metric.id, written(metric.value), metric.unit, metric.status]) assert.ok(between.includes(text), `${role} ${text}`);
        }
      }
    });
  });
}

test("the Assessment shown as the Control is the read's control_assessment_id, when the two ids are exchanged", async (t) => {
  const object = keptObject("status-success");
  const pending = object.pending_decisions[0];
  [pending.control_assessment_id, pending.candidate_assessment_id] = [pending.candidate_assessment_id, pending.control_assessment_id];
  const part = elementsOf((await documentFor(t, success(object))).document, '<section data-part="pending">')[0];
  assert.ok(elementOf(part, '<div data-role="control">')!.includes(pending.control_assessment_id));
  assert.ok(elementOf(part, '<div data-role="candidate">')!.includes(pending.candidate_assessment_id));
  assert.ok(!elementOf(part, '<div data-role="control">')!.includes(pending.candidate_assessment_id));
});

for (const name of KEPT_READS) {
  test(`the delta's element holds the Comparison's own delta value, not a difference of the two Metric values: ${name}`, async (t) => {
    const object = keptObject(name);
    for (const comparison of object.comparisons) if (comparison.delta.value !== null) comparison.delta.value = 12.5;
    const { document } = await documentFor(t, success(object));
    const parts = elementsOf(document, '<section data-part="pending">');
    assert.equal(parts.length, object.pending_decisions.length);
    for (const part of parts) {
      const comparison = object.comparisons.find((each: Record<string, any>) => part.includes(each.comparison_id));
      if (comparison.delta.value === null) continue; // a withheld delta has no value of its own to change
      const delta = elementOf(part, '<p data-element="delta">')!;
      const { between } = partsOf(delta);
      assert.ok(/(^|\s)12\.5(\s|$)/.test(between), delta);
      const kept = keptObject(name);
      const pending = kept.pending_decisions.find((each: Record<string, string>) => each.comparison_id === comparison.comparison_id);
      const metricOf = (id: string) => kept.assessments.find((each: Record<string, string>) => each.assessment_id === id).metrics.find((metric: Record<string, string>) => metric.id === comparison.delta.metric);
      const [control, candidate] = [metricOf(pending.control_assessment_id), metricOf(pending.candidate_assessment_id)];
      const difference = control && candidate ? candidate.value - control.value : comparison.delta.candidate - comparison.delta.control;
      assert.ok(!new RegExp(`(^|\\s)${written(difference).replace(".", "\\.")}(\\s|$)`).test(between), `${written(difference)} in ${delta}`);
      assert.ok(between.includes(comparison.delta.metric) && between.includes(comparison.delta.unit));
    }
  });
}

test("a null Metric value is shown as no value, with that Metric's id, unit and status", async (t) => {
  const object = keptObject("status-success");
  const pending = object.pending_decisions[0];
  const assessment = object.assessments.find((each: Record<string, string>) => each.assessment_id === pending.control_assessment_id);
  assessment.metrics[0].value = null;
  const part = elementsOf((await documentFor(t, success(object))).document, '<section data-part="pending">')[0];
  const metric = partsOf(elementOf(elementOf(part, '<div data-role="control">')!, "<li>")!).between;
  for (const text of ["no value", assessment.metrics[0].id, assessment.metrics[0].unit, assessment.metrics[0].status]) assert.ok(metric.includes(text), `${text} in ${metric}`);
});

test("status-chinook-pending: control and candidate stand under their roles in the roles' element, first in the fold of the charts after the coverage element", async (t) => {
  const object = keptObject("status-chinook-pending");
  const { document } = await documentFor(t, success(object));
  const parts = elementsOf(document, '<section data-part="pending">');
  object.pending_decisions.forEach((pending: Record<string, string>, index: number) => {
    const delta = object.comparisons.find((each: Record<string, any>) => each.comparison_id === pending.comparison_id).delta;
    const coverage = elementOf(parts[index], '<p data-element="coverage">')!;
    const roles = elementOf(parts[index], '<p data-element="roles">')!;
    assert.ok(coverage && roles);
    const fold = elementOf(parts[index], '<details data-element="charts">')!;
    assert.ok(parts[index].indexOf(coverage) < parts[index].indexOf(fold) && fold.includes(roles), "the roles' element stands in the fold of the charts, after the coverage element");
    const between = partsOf(roles).between;
    assert.match(between, new RegExp(`Control\\s+${written(delta.control).replace(".", "\\.")}(\\s|$)`));
    assert.match(between, new RegExp(`Candidate\\s+${written(delta.candidate).replace(".", "\\.")}(\\s|$)`));
  });
});

test("status-chinook-pending with control set to null beside a delta that has a value: no value under that role", async (t) => {
  const object = keptObject("status-chinook-pending");
  object.comparisons[0].delta.control = null;
  assert.notEqual(object.comparisons[0].delta.value, null);
  const roles = elementOf(elementsOf((await documentFor(t, success(object))).document, '<section data-part="pending">')[0], '<p data-element="roles">')!;
  assert.match(partsOf(roles).between, /Control\s+no value(\s|$)/);
});

// The limits the Comparison records, and the Declared deviations.
const WARNINGS = "Warnings of the Comparison";
const LIMITATIONS = "Limitations of the Comparison";

for (const name of KEPT_READS) {
  test(`each Comparison shown holds both headings, each warning's code and message and each limitation, marked, a pending one only those that are no warning's message: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const parts = elementsOf(document, '<div data-part="comparison"');
    const ids = object.comparisons.map((comparison: Record<string, string>) => comparison.comparison_id);
    const cited = object.decisions.flatMap((decision: Record<string, string[]>) => decision.cited_ids.filter((id) => ids.includes(id)));
    assert.equal(parts.length, object.pending_decisions.length + cited.length);
    for (const part of parts) {
      const comparison = object.comparisons.find((each: Record<string, string>) => part.includes(each.comparison_id));
      const { between } = partsOf(part);
      assert.ok(between.includes(WARNINGS) && between.includes(LIMITATIONS));
      const warnings = elementOf(part, '<div data-part="warnings"')!;
      const limitations = elementOf(part, '<div data-part="limitations"')!;
      for (const warning of comparison.warnings) {
        assert.ok(partsOf(warnings).between.includes(warning.code), warning.code);
        assert.ok(markedTexts(warnings).includes(warning.message), warning.message);
      }
      // "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
      const messages = comparison.warnings.map((warning: Record<string, string>) => warning.message);
      const pending = part.includes("<fieldset ");
      assert.deepEqual(markedTexts(limitations), pending ? comparison.limitations.filter((each: string) => !messages.includes(each)) : comparison.limitations);
    }
  });
}

test("status-deviation: each Declared deviation shows its id, its text, the mark of a declared one while it is not withdrawn, and withdrawn with the value the object holds", async (t) => {
  const object = keptObject("status-deviation");
  const { document } = await documentFor(t, success(object));
  for (const deviation of object.declared_deviations) {
    const line = partsOf(elementsOf(document, "<li data-part=\"deviation\">").find((each) => each.includes(deviation.declared_deviation_id))!).between;
    const mark = deviation.withdrawn ? "" : "\u2016\\s+declared\\s+";
    assert.match(line, new RegExp(`${deviation.declared_deviation_id}\\s+${deviation.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+${mark}withdrawn\\s+${deviation.withdrawn}(\\s|$)`));
  }
});
