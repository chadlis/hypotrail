// The panel's charts: bars the extension builds as text of the document, from the numbers of the object read and no other.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { barLength, scaleTop } from "../src/charts";
import { JOURNEY } from "./kept";
import { KEPT_FIGURES, KEPT_READS, documentFor, elementOf, elementsOf, keptObject, markedTexts, partsOf, profileAt, success } from "./panel-harness";

type Entry = Record<string, any>;

const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");
const widthsOf = (html: string): number[] => [...html.matchAll(/<rect [^>]*\swidth="([^"]*)"/g)].map((match) => Number(match[1]));
const classOf = (tag: string): string | undefined => /\sclass="([^"]*)"/.exec(tag)?.[1];
const rectsOf = (html: string): string[] => partsOf(html).tags.filter((tag) => tag.startsWith("<rect"));
// Whether a tag of the document opens a chart of `kind`; the style names the same attribute in its selectors.
const drawn = (document: string, kind: string): boolean => partsOf(document).tags.some((tag) => tag.includes(`data-chart="${kind}"`));

// A number written by another route than the client's, to find a value in a document.
function written(value: number | null): string {
  if (value === null) return "no value";
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

async function documentOf(t: TestContext, object: Entry): Promise<string> {
  return (await documentFor(t, success(object))).document;
}

// What every chart is.
test("the length of a bar is its value over the top of its scale, from zero, clamped from 0 to 100", () => {
  for (const [value, top, length] of [
    [0, 10, 0],
    [10, 10, 100],
    [5, 10, 50],
    [2.5, 10, 25],
    [20, 10, 100],
    [-5, 10, 0],
    [null, 10, 0],
  ] as const) {
    assert.equal(barLength(value, top), length, `${value} over ${top}`);
  }
});

test("the top of a scale is the largest value, or 1 when no value is above zero", () => {
  assert.equal(scaleTop([3, 7.5, null, -2]), 7.5);
  assert.equal(scaleTop([0, -4, null]), 1);
  assert.equal(scaleTop([]), 1);
});

// Each kept read alone, its figures call failed, then each kept read with its kept figures read, whose documents hold the figures.
const SVG_DOCUMENTS: [string, (t: TestContext) => Promise<string>][] = [
  ...KEPT_READS.map((name): [string, (t: TestContext) => Promise<string>] => [name, (t) => documentOf(t, keptObject(name))]),
  ...Object.keys(KEPT_FIGURES).map((name): [string, (t: TestContext) => Promise<string>] => [
    `${name} with ${KEPT_FIGURES[name]}`,
    async (t) => (await documentFor(t, success(keptObject(name)), success(keptObject(KEPT_FIGURES[name])))).document,
  ]),
  // "Every `svg` of the step holds only `rect` elements, no text and no colour or style attribute." (chadlis/hypotrail#262): the
  // step drawn from the kept profile read, beside the kept Bike read, and its band and target over time open in Now at state 01.
  ["status-success with figures-success and profile-bike", async (t) => profileDocument(t, "status-success")],
  [`${JOURNEY}01-init.status with profile-bike`, async (t) => profileDocument(t, `${JOURNEY}01-init.status`)],
];

async function profileDocument(t: TestContext, name: string): Promise<string> {
  const object = keptObject(name);
  const figures = KEPT_FIGURES[name] === undefined ? [] : [success(keptObject(KEPT_FIGURES[name]))];
  const { document } = await documentFor(t, success(object), ...figures, profileAt(object.write_sequence));
  const step = elementOf(document, '<details data-part="profile"')!;
  assert.ok(step && elementsOf(step, "<svg ").length >= 4, "the step draws its figures");
  return document;
}

for (const [name, documentOfName] of SVG_DOCUMENTS) {
  test(`each svg holds rect elements only, carries aria-hidden and no xmlns, holds no text, and no tag holds a colour or style attribute: ${name}`, async (t) => {
    const document = await documentOfName(t);
    const svgs = elementsOf(document, "<svg ");
    for (const svg of svgs) {
      const { tags, between } = partsOf(svg);
      assert.match(tags[0], /\saria-hidden="true"/);
      assert.ok(!/xmlns/.test(tags[0]), tags[0]);
      assert.deepEqual(tags.slice(1, -1).filter((tag) => !/^<rect\s[^>]*>$|^<\/rect>$/.test(tag)), []);
      assert.equal(between.trim(), "");
    }
    assert.deepEqual(partsOf(document).tags.filter((tag) => /\s(fill|stroke|color|style)=/.test(tag)), []);
  });
}

for (const name of KEPT_READS) {
  test(`each chart holds, for each bar, its name, a label, a coverage key or a feature of a single-feature check, one svg and one link or the word of no_value: ${name}`, async (t) => {
    const object = keptObject(name);
    const document = await documentOf(t, object);
    const coverageKeys = object.comparisons.flatMap((comparison: Entry) => Object.keys(comparison.coverage));
    // The single-feature chart names each feature as the Candidate's single-feature check records it.
    const features = object.assessments.flatMap((assessment: Entry) => (assessment.single_feature_check?.computed ?? []).map((entry: Entry) => entry.feature));
    for (const chart of elementsOf(document, "<div data-chart=").concat(elementsOf(document, "<li data-chart="))) {
      const bars = elementsOf(chart, "<div data-bar>");
      assert.ok(bars.length > 0, chart);
      for (const bar of bars) {
        const name = partsOf(elementOf(bar, "<span>")!).between.trim();
        assert.ok(contract.labels.includes(name) || coverageKeys.includes(name) || features.includes(name), name);
        const svgs = elementsOf(bar, "<svg ").length;
        const links = (bar.match(/<a /g) ?? []).length;
        assert.ok(links >= 1, bar);
        assert.equal(svgs, words(bar).includes(contract.no_value) ? 0 : 1, bar);
      }
    }
  });
}

test("the script of the document builds and changes no chart, the document of the Data profile included", async (t) => {
  const { script } = partsOf(await profileDocument(t, "status-success"));
  for (const name of ["svg", "rect", "createElement", "setAttribute"]) assert.ok(!script.includes(name), name);
});

// Chart 1: Control against Candidate, for the Metric the delta names; the delta's value stands in the delta's element above it.
const chartOne = (part: string): string | undefined => elementOf(part, '<div data-chart="delta">');
const pendingParts = (document: string): string[] => elementsOf(document, '<section data-part="pending">');

for (const [name, values] of [
  ["status-success", (object: Entry) => [object.assessments[0].metrics[0].value, object.assessments[1].metrics[0].value]],
  ["status-chinook-pending", (object: Entry) => [object.comparisons[0].delta.control, object.comparisons[0].delta.candidate]],
] as const) {
  test(`chart 1 shows two bars, named Control and Candidate, with their values and nothing else: ${name}`, async (t) => {
    const object = keptObject(name);
    const chart = chartOne(pendingParts(await documentOf(t, object))[0])!;
    assert.ok(chart, "chart 1");
    assert.equal(rectsOf(chart).length, 2);
    const [control, candidate] = values(object);
    assert.equal(words(chart), `Control ${written(control)} Candidate ${written(candidate)}`);
  });

  test(`chart 1 gives the larger bar to the larger value once the Control's value is doubled in the test: ${name}`, async (t) => {
    const object = keptObject(name);
    if (name === "status-success") object.assessments[0].metrics[0].value *= 2;
    else object.comparisons[0].delta.control = 2;
    const [control, candidate] = widthsOf(chartOne(pendingParts(await documentOf(t, object))[0])!);
    assert.equal(control, 100);
    assert.ok(candidate < control, `${candidate} < ${control}`);
  });
}

for (const name of ["status-chinook-withheld", "status-bike-withheld"]) {
  test(`chart 1 is not drawn for a Comparison whose delta is withheld: ${name}`, async (t) => {
    const document = await documentOf(t, keptObject(name));
    assert.equal(drawn(document, "delta"), false);
  });
}

test("chart 1 is not drawn when neither the delta record nor the Assessments hold the delta's Metric", async (t) => {
  const object = keptObject("status-success");
  object.comparisons[0].delta.metric = "zq_absent_metric";
  assert.equal(drawn(await documentOf(t, object), "delta"), false);
});

// The definition of the delta's sign, the core's sentence.
for (const name of KEPT_READS) {
  test(`each Comparison's part shows the delta's definition as a marked text outside the delta's element, a replaced text followed: ${name}`, async (t) => {
    const object = keptObject(name);
    for (const comparison of object.comparisons) comparison.delta.definition = `zq-definition of ${comparison.comparison_id}`;
    const document = await documentOf(t, object);
    for (const part of elementsOf(document, '<div data-part="comparison"')) {
      const comparison = object.comparisons.find((each: Entry) => part.includes(each.comparison_id));
      if (comparison === undefined) continue;
      assert.ok(markedTexts(part).includes(comparison.delta.definition), comparison.comparison_id);
      assert.ok(!elementOf(part, '<p data-element="delta">')!.includes("zq-definition"));
    }
  });
}

// Chart 2: the coverage, one stacked bar per role.
test("chart 2 on status-chinook-withheld: the Candidate's scored part is half the Control's, the two parts of a bar carry two classes the style sets", async (t) => {
  const object = keptObject("status-chinook-withheld");
  const document = await documentOf(t, object);
  const chart = elementOf(pendingParts(document)[0], '<div data-chart="coverage">')!;
  assert.ok(chart, "chart 2");
  const bars = elementsOf(chart, "<div data-bar>");
  assert.deepEqual(bars.map((bar) => partsOf(elementOf(bar, "<span>")!).between.trim()), ["Control", "Candidate"]);
  const [control, candidate] = bars.map((bar) => rectsOf(bar));
  assert.equal(control.length, 2);
  assert.equal(candidate.length, 2);
  assert.equal(widthsOf(candidate[0])[0] * 2, widthsOf(control[0])[0]);
  for (const rects of [control, candidate]) assert.notEqual(classOf(rects[0]), classOf(rects[1]));
  assert.match(words(bars[0]), /control_scored 4 expected 4/);
  assert.match(words(bars[1]), /candidate_scored 2 expected 4/);
  const { style } = partsOf(document);
  const rest = classOf(candidate[1])!;
  assert.match(style, new RegExp(`rect\\.${rest}\\s*\\{[^}]*fill:\\s*transparent;[^}]*stroke:\\s*var\\(--(?!vscode-)[a-z0-9-]+\\)`));
  assert.match(style, new RegExp(`rect\\.${classOf(candidate[0])}\\s*\\{[^}]*fill:\\s*var\\(--(?!vscode-)[a-z0-9-]+\\)`));
});

test("chart 2 is not drawn on a read whose coverage holds no expected", async (t) => {
  const object = keptObject("status-chinook-withheld");
  delete object.comparisons[0].coverage.expected;
  assert.equal(drawn(await documentOf(t, object), "coverage"), false);
});

// Chart 3: each Metric of a line of a Decision's evidence, its cited against its latest value.
const linesOf = (document: string): string[] => elementsOf(document, '<li data-part="line">');

for (const name of ["status-result-changed", "status-rescored", "status-repeated"]) {
  test(`chart 3 shows, for each Metric of each line, the cited and the latest value as two bars on one scale: ${name}`, async (t) => {
    const object = keptObject(name);
    const document = await documentOf(t, object);
    const lines = linesOf(document);
    const all = object.decisions.flatMap((decision: Entry) => decision.evidence_change?.lines ?? []);
    assert.equal(lines.length, all.length);
    all.forEach((line: Entry, index: number) => {
      const charts = elementsOf(lines[index], '<li data-chart="evidence">');
      assert.equal(charts.length, line.metrics.length);
      line.metrics.forEach((metric: Entry, at: number) => {
        assert.equal(rectsOf(charts[at]).length, 2);
        assert.equal(words(charts[at]), `Metric ${metric.id} Cited value ${written(metric.cited)} Latest value ${written(metric.latest)}`);
      });
    });
  });

  test(`chart 3 draws the cited bar half the latest one once the latest is set to twice the cited in the test: ${name}`, async (t) => {
    const object = keptObject(name);
    const metric = object.decisions[0].evidence_change.lines[0].metrics[0];
    metric.latest = metric.cited * 2;
    const [cited, latest] = widthsOf(elementOf(linesOf(await documentOf(t, object))[0], '<li data-chart="evidence">')!);
    assert.equal(latest, 100);
    assert.equal(cited, 50);
  });
}

test("chart 3 with one latest set to null: the word of no_value and one bar only", async (t) => {
  const object = keptObject("status-result-changed");
  object.decisions[0].evidence_change.lines[0].metrics[0].latest = null;
  const chart = elementOf(linesOf(await documentOf(t, object))[0], '<li data-chart="evidence">')!;
  assert.equal(rectsOf(chart).length, 1);
  assert.match(words(chart), /Latest value no value$/);
});
