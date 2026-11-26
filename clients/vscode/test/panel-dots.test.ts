// The dots of a Comparison: per Item or Case, the Control's and the Candidate's value of its paired deltas, each a mark on one
// scale shared by the Comparison's dots, beside the Item's or Case's id.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import { KEPT_FIGURES, documentFor, elementOf, elementsOf, keptObject, markedTexts, partsOf, success } from "./panel-harness";
import { exit } from "./recorder";
import contract from "../contract.json";

type Entry = Record<string, any>;

const FAILED = "Figures unavailable. Read again.";
const UNAVAILABLE = "No figure for this Comparison:";
const OTHER_REASONS = ["artifact_missing", "artifact_integrity", "artifact_malformed", "value_not_finite"];
// How far two places may stand apart and still be one: two decimals, and the sum of two of them.
const NEAR = 0.011;

// A number written by another route than the client's, to find a value in a document.
function written(value: number): string {
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

const count = (html: string, text: string): number => html.split(text).length - 1;

async function drawn(t: TestContext, object: Entry, figures: Entry): Promise<string> {
  return (await documentFor(t, success(object), success(figures))).document;
}

// The full part of each Comparison of a document, with its entry of the figures read.
function comparisonsOf(document: string, object: Entry, figures: Entry): { part: string; entry: Entry }[] {
  return elementsOf(document, '<div data-part="comparison"').map((part) => {
    const comparison = object.comparisons.find((each: Entry) => part.includes(`<span>${each.comparison_id}</span>`));
    return { part, entry: figures.comparisons.find((each: Entry) => each.comparison_id === comparison.comparison_id) };
  });
}

type Rect = { kind: string; x: number; y: number; width: number; height: number };

function rectsOf(html: string): Rect[] {
  return partsOf(html)
    .tags.filter((tag) => tag.startsWith("<rect"))
    .map((tag) => {
      const value = (name: string): string => new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1] ?? "";
      return { kind: value("class"), x: Number(value("x")), y: Number(value("y")), width: Number(value("width")), height: Number(value("height")) };
    });
}

// An element of `paired_deltas` as its id and its two sides' values, on either Track.
function sidesOf(element: Entry): { id: string; control: number; candidate: number } {
  return "case_id" in element
    ? { id: element.case_id, control: element.control_share, candidate: element.candidate_share }
    : { id: element.row_id, control: element.control_abs_error, candidate: element.candidate_abs_error };
}

// The element of each dot of a part, by the id it holds as a marked text.
const dotsOf = (part: string): string[] => elementsOf(part, "<div data-dot>");
const middle = (rect: Rect): number => rect.x + rect.width / 2;
const sideOf = (dot: string, side: string): Rect[] => rectsOf(dot).filter((rect) => rect.kind === side);

// The elements of an entry's paired deltas in the order of their rows: the one where the Candidate is worst first, by its paired
// delta, which is positive where the Candidate is worse on the Regression Track and where it is better on the Agent Track.
function orderOf(entry: Entry): Entry[] {
  const worse = (element: Entry): number => ("case_id" in element ? -element.delta_share : element.delta_abs_error);
  return [...entry.paired_deltas].sort((a, b) => worse(b) - worse(a));
}

// The kept status reads whose kept figures read holds an entry with figures.
const DRAWN = Object.keys(KEPT_FIGURES).filter((name) => keptObject(KEPT_FIGURES[name]).comparisons.some((entry: Entry) => entry.unavailable === null));

// Each mark of a Comparison's dots, its value beside its middle, after every assertion on its count.
function marksOf(part: string, entry: Entry): { value: number; at: number }[] {
  const dots = dotsOf(part);
  assert.equal(dots.length, entry.paired_deltas.length, `${entry.comparison_id}: one dot element per element of paired_deltas`);
  return entry.paired_deltas.flatMap((element: Entry) => {
    const sides = sidesOf(element);
    const dot = dots.find((each) => markedTexts(each)[0] === sides.id);
    assert.ok(dot, `${entry.comparison_id}: the dot of ${sides.id}`);
    return (["control", "candidate"] as const).map((side) => {
      const marks = sideOf(dot, side);
      assert.equal(marks.length, 1, `${sides.id}: one mark of the ${side}`);
      return { value: sides[side], at: middle(marks[0]) };
    });
  });
}

// The order of the marks' places follows the order of their values, on the one scale of the Comparison.
function assertOrdered(marks: { value: number; at: number }[], name: string): void {
  const sorted = [...marks].sort((a, b) => a.value - b.value);
  for (let at = 1; at < sorted.length; at += 1) {
    assert.ok(sorted[at].at >= sorted[at - 1].at - NEAR, `${name}: ${sorted[at].value} at ${sorted[at].at} stands before ${sorted[at - 1].value} at ${sorted[at - 1].at}`);
    if (sorted[at].value === sorted[at - 1].value) assert.ok(Math.abs(sorted[at].at - sorted[at - 1].at) <= NEAR, `${name}: equal values at one place`);
  }
}

for (const name of Object.keys(KEPT_FIGURES)) {
  test(`each entry with figures draws, per element of paired_deltas, one mark of the Control and one of the Candidate, placed in the order of their values on one scale: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) {
        assert.equal(dotsOf(part).length, 0, entry.comparison_id);
        continue;
      }
      const marks = marksOf(part, entry);
      for (const mark of marks) assert.ok(Number.isFinite(mark.at), `${mark.value} at ${mark.at}`);
      assertOrdered(marks, entry.comparison_id);
    }
  });
}

test("a value changed in the test to the largest of its Comparison has its mark last on the scale: status-success", async (t) => {
  const object = keptObject("status-success");
  const figures = keptObject("figures-success");
  const entry = figures.comparisons[0];
  entry.paired_deltas[90].control_abs_error = 10000;
  const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
  const marks = marksOf(part, entry);
  const moved = marks.find((mark) => mark.value === 10000)!;
  for (const mark of marks) if (mark !== moved) assert.ok(mark.at < moved.at, `${mark.value} at ${mark.at} stands before ${moved.at}`);
  assertOrdered(marks, entry.comparison_id);
});

for (const name of DRAWN) {
  test(`the Control's mark and the Candidate's differ in more than their class: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      assert.equal(dotsOf(part).length, entry.paired_deltas.length, entry.comparison_id);
      for (const dot of dotsOf(part)) {
        const [control] = sideOf(dot, "control");
        const [candidate] = sideOf(dot, "candidate");
        assert.ok(control.y !== candidate.y || control.height !== candidate.height || control.width !== candidate.width, dot);
      }
    }
  });
}

// Equal values, as `chinook_pending_study` gives them (every share 1.0), and values near 1e308, where `1e308 + 1` is `1e308`.
for (const [label, change] of [
  ["the kept output of chinook_pending_study", (_: Entry) => {}],
  ["every value set to 1e308 in the test", (element: Entry) => Object.assign(element, { control_share: 1e308, candidate_share: 1e308 })],
] as const) {
  test(`with every value equal, the marks stand at one place, one finite number: ${label}`, async (t) => {
    const object = keptObject("status-chinook-pending");
    const figures = keptObject("figures-chinook-pending");
    const entry = figures.comparisons[0];
    entry.paired_deltas.forEach(change);
    const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
    const places = marksOf(part, entry).map((mark) => Number(mark.at.toFixed(2)));
    assert.ok(places.every(Number.isFinite), JSON.stringify(places));
    assert.equal(new Set(places).size, 1, JSON.stringify(places));
  });
}

test("with values from -1e308 to 1e308, each mark's place is a finite number in the order of its value: status-chinook-spread", async (t) => {
  const object = keptObject("status-chinook-spread");
  const figures = keptObject("figures-chinook-spread");
  const entry = figures.comparisons[0];
  Object.assign(entry.paired_deltas[0], { control_share: -1e308, candidate_share: 1e308 });
  const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
  const marks = marksOf(part, entry);
  assert.ok(marks.every((mark) => Number.isFinite(mark.at)), JSON.stringify(marks));
  assertOrdered(marks, entry.comparison_id);
  assert.ok(marks[0].at < marks[1].at - 1, JSON.stringify(marks));
});

// Which Item or Case a dot is.
for (const name of DRAWN) {
  test(`each element of paired_deltas has one element of the document holding its id as a marked text and its two marks: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const dots = dotsOf(part);
      for (const element of entry.paired_deltas) {
        const { id } = sidesOf(element);
        const holding = dots.filter((dot) => markedTexts(dot).includes(id));
        assert.equal(holding.length, 1, `${entry.comparison_id}: one element holds ${id}`);
        assert.deepEqual(markedTexts(holding[0]), [id]);
        assert.equal(sideOf(holding[0], "control").length + sideOf(holding[0], "candidate").length, 2, id);
        assert.ok(!/<a[\s>]/.test(holding[0]), `${id} is not a link`);
      }
    }
  });
}

for (const [name, key] of [
  ["status-success", "row_id"],
  ["status-chinook-spread", "case_id"],
] as const) {
  test(`an id of paired_deltas replaced in the test is the id its dot shows, with its own marks: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    const entry = figures.comparisons[0];
    const element = entry.paired_deltas[1];
    element[key] = "replaced <id> & 7";
    const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
    const dot = dotsOf(part).find((each) => markedTexts(each).includes("replaced <id> & 7"));
    assert.ok(dot, part.slice(0, 200));
    assert.equal(dotsOf(part).indexOf(dot), orderOf(entry).indexOf(element));
    const marks = marksOf(part, entry);
    assert.equal(middle(sideOf(dot, "control")[0]), marks[2].at);
    assert.equal(middle(sideOf(dot, "candidate")[0]), marks[3].at);
  });
}

// The numbers of the dots: the two ends of their scale, each in a link to the part of its Comparison.
for (const name of DRAWN) {
  test(`the dots print the smallest and the largest of their values, each in a link to the part of its Comparison, and no other number: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const dots = elementOf(part, '<div data-figure="dots"')!;
      const values = entry.paired_deltas.flatMap((element: Entry) => [sidesOf(element).control, sidesOf(element).candidate]);
      const ends = [...new Set([Math.min(...values), Math.max(...values)].map(written))];
      const links = [...dots.matchAll(/<a href="#comparison-(\d+)" data-kind="([a-z_]+)">([^<]*)<\/a>/g)];
      assert.deepEqual(links.map((link) => link[3]), ends);
      const index = object.comparisons.findIndex((each: Entry) => each.comparison_id === entry.comparison_id);
      for (const link of links) assert.equal(Number(link[1]), index, link[0]);
      const between = partsOf(dots.replace(/<a [^>]*>[^<]*<\/a>/g, "").replace(/<([a-z0-9]+) data-text>[^<]*<\/\1>/g, "")).between;
      assert.doesNotMatch(between, /\d/, between);
    }
  });
}

// Where the dots stand: from ten pairs, at the end of the Comparison's part, after its limitations, with a link to them under the box
// plot that prints no number; under ten, first among the figures, before the histogram.
for (const name of DRAWN) {
  test(`each Comparison's dots stand after its limitations, linked from under its box plot by one link that prints no number, from ten pairs, and before its histogram under ten: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const at = part.indexOf('<div data-figure="dots"');
      const [histogram, box] = [part.indexOf('<div data-figure="histogram">'), part.indexOf('<div data-figure="box">')];
      assert.ok(at >= 0 && histogram >= 0 && box >= 0, entry.comparison_id);
      if (entry.paired_deltas.length < 10) {
        assert.ok(at < histogram && !part.includes('data-element="to-dots"'), `${entry.comparison_id}: ${entry.paired_deltas.length} pairs`);
        continue;
      }
      assert.ok(at > part.indexOf('<div data-part="limitations"') && at > box, `${entry.comparison_id}: ${entry.paired_deltas.length} pairs`);
      const index = object.comparisons.findIndex((each: Entry) => each.comparison_id === entry.comparison_id);
      const link = elementOf(part, '<p data-element="to-dots">')!;
      assert.ok(part.indexOf(link) > box && part.indexOf(link) < at, link);
      const below = "case_id" in entry.paired_deltas[0] ? "Cases below" : "Items below";
      assert.equal(link, `<p data-element="to-dots"><a href="#dots-${index}">${below}</a></p>`);
      assert.ok(part.includes(`<div data-figure="dots" id="dots-${index}">`), "the dots hold the id the link names");
    }
  });
}

// A withheld delta, an entry with no figures, and a failed figures call: no dot.
for (const name of ["status-bike-withheld", "status-chinook-withheld"]) {
  for (const [way, answer] of [
    ["its kept figures read", () => success(keptObject(KEPT_FIGURES[name]))],
    ["a failed figures call", () => exit(0, "not JSON")],
  ] as const) {
    test(`a Comparison whose delta is withheld draws no dot and shows no label, with ${way}: ${name}`, async (t) => {
      const { document } = await documentFor(t, success(keptObject(name)), answer());
      const parts = elementsOf(document, '<div data-part="comparison"');
      assert.ok(parts.length > 0);
      for (const part of parts) {
        assert.equal(dotsOf(part).length, 0, part);
        assert.equal(count(part, FAILED) + count(part, UNAVAILABLE), 0, part);
      }
    });
  }
}

for (const reason of [...OTHER_REASONS, "a failed figures call"]) {
  test(`with ${OTHER_REASONS.includes(reason) ? `an entry whose unavailable is ${reason}` : reason}, the Comparison's part draws no dot and shows its label once: status-success`, async (t) => {
    const object = keptObject("status-success");
    const figures = keptObject("figures-success");
    if (OTHER_REASONS.includes(reason)) Object.assign(figures.comparisons[0], { unavailable: reason, histogram: null, quartiles: null });
    const answer = OTHER_REASONS.includes(reason) ? success(figures) : exit(0, "not JSON");
    const { document } = await documentFor(t, success(object), answer);
    const [part] = elementsOf(document, '<div data-part="comparison"');
    assert.equal(dotsOf(part).length, 0, part);
    assert.ok(!part.includes('data-figure="dots"'), part);
    assert.equal(count(part, OTHER_REASONS.includes(reason) ? UNAVAILABLE : FAILED), 1);
  });
}

// The order of the rows, the side each favours, the ends of the scale above them, and what their heading names.
for (const name of DRAWN) {
  test(`the rows run from the Item or Case where the Candidate is worst, by its paired delta, and the ends of the scale stand above the first: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      assert.deepEqual(
        dotsOf(part).map((dot) => markedTexts(dot)[0]),
        orderOf(entry).map((element) => sidesOf(element).id),
      );
      const grid = elementOf(part, '<div data-element="dots">')!;
      assert.ok(grid.indexOf('<p data-element="dot-ends">') >= 0 && grid.indexOf('<p data-element="dot-ends">') < grid.indexOf("<div data-dot>"), grid.slice(0, 300));
    }
  });
}

test("a paired delta changed in the test to the largest puts its row first: status-success", async (t) => {
  const object = keptObject("status-success");
  const figures = keptObject("figures-success");
  const entry = figures.comparisons[0];
  entry.paired_deltas[120].delta_abs_error = 1e6;
  const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
  assert.equal(markedTexts(dotsOf(part)[0])[0], entry.paired_deltas[120].row_id);
});

for (const name of DRAWN) {
  test(`the bar that joins a row's two marks takes the class of the side it favours, or the class between when the two values are equal: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      for (const element of entry.paired_deltas) {
        const sides = sidesOf(element);
        const dot = dotsOf(part).find((each) => markedTexts(each)[0] === sides.id)!;
        const lower = sides.candidate < sides.control ? "candidate" : sides.control < sides.candidate ? "control" : undefined;
        // A lower absolute error wins on the Regression Track, a higher share on the Agent Track.
        const favoured = lower === undefined ? undefined : "case_id" in element ? (lower === "control" ? "candidate" : "control") : lower;
        const joints = rectsOf(dot).filter((rect) => !["control", "candidate"].includes(rect.kind)).map((rect) => rect.kind);
        assert.deepEqual(joints, [favoured === undefined ? "between" : `favours-${favoured}`], `${sides.id}: ${sides.control} against ${sides.candidate}`);
      }
    }
  });
}

test("each class of a joining bar draws in its side's colour, and the id column is as wide as its widest id up to 9.5em", async (t) => {
  const { style } = partsOf(await drawn(t, keptObject("status-success"), keptObject("figures-success")));
  for (const side of ["control", "candidate"]) {
    const colour = new RegExp(`rect\\.${side} \\{ fill: (var\\(--(?!vscode-)[a-z0-9-]+\\));`).exec(style)![1];
    assert.ok(style.includes(`rect.favours-${side} { fill: ${colour}; }`), side);
  }
  assert.match(style, /\[data-element="dots"\] \{ display: grid; grid-template-columns: fit-content\(9\.5em\) /);
});

// An entry's paired deltas cut in the test to their first nine, or each Case given twice under a new id, so that each Track has
// dots that stand first and dots that stand at the end of the part.
const firstNine = (entry: Entry): void => void entry.paired_deltas.splice(9);
const twice = (entry: Entry): void => void entry.paired_deltas.push(...entry.paired_deltas.flatMap((element: Entry) => [1, 2].map((at) => ({ ...element, case_id: `${element.case_id}-${at}` }))));

for (const [name, change, heading, unit] of [
  ["status-success", (_: Entry) => {}, "Absolute error per Item", true],
  ["status-success", firstNine, "Absolute error per Item", false],
  ["status-chinook-spread", (_: Entry) => {}, "Shares of the Control and the Candidate", false],
  ["status-chinook-spread", twice, "Shares of the Control and the Candidate", true],
] as const) {
  test(`the heading of the dots names what they plot, then its unit only when they stand at the end of the part: ${name} with ${unit ? "ten pairs or more" : "fewer than ten pairs"}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    change(figures.comparisons[0]);
    assert.equal(figures.comparisons[0].paired_deltas.length >= 10, unit);
    const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
    const dots = elementOf(part, '<div data-figure="dots"')!;
    const title = elementOf(dots, "<h4>")!;
    assert.ok(contract.labels.includes(heading), heading);
    assert.equal(title, unit ? `<h4>${heading} (<span data-text>${object.comparisons[0].delta.unit}</span>)</h4>` : `<h4>${heading}</h4>`);
  });
}

const ORDER = "Ordered from the Candidate's worst; the bar takes the colour of the better side.";

for (const name of DRAWN) {
  test(`a fixed sentence after the key of the dots says how the rows are ordered and what colour the bar takes: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    assert.ok(contract.labels.includes(ORDER));
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const dots = elementOf(part, '<div data-figure="dots"')!;
      const key = elementOf(dots, '<p data-element="dot-key">')!;
      assert.ok(dots.includes(`${key}\n<p data-element="dot-order">${ORDER.replace("'", "&#39;")}</p>\n<div data-element="dots">`), dots.slice(0, 600));
    }
  });
}
