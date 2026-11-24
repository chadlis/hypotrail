// The figures of a Comparison's paired deltas: a histogram of the bins and a box plot of the five numbers the figures read gives,
// drawn by the extension as text of the document, in the Comparison's part after its limitations.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { axisPosition, histogramTop } from "../src/charts";
import { KEPT_FIGURES, documentFor, elementOf, elementsOf, keptObject, partsOf, success } from "./panel-harness";
import { exit } from "./recorder";

type Entry = Record<string, any>;

const FAILED = "Figures unavailable. Read again.";
const UNAVAILABLE = "No figure for this Comparison.";
// The reasons an entry may hold, but `delta_withheld`, which keeps the word of a withheld delta alone.
const OTHER_REASONS = ["artifact_missing", "artifact_integrity", "artifact_malformed", "value_not_finite"];
const FIVE = ["min", "q1", "median", "q3", "max"];
// How far a place may stand from the one the test computes: two decimals, and the sum of two of them.
const NEAR = 0.011;

// A number written by another route than the client's, to find a value in a document.
function written(value: number): string {
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

const count = (html: string, text: string): number => html.split(text).length - 1;

// The document of `object` with the figures read `figures` answered after it.
async function drawn(t: TestContext, object: Entry, figures: Entry): Promise<string> {
  return (await documentFor(t, success(object), success(figures))).document;
}

// The full part of each Comparison of a document, with the Comparison of the status read it shows and its entry of the figures read.
function comparisonsOf(document: string, object: Entry, figures: Entry): { part: string; comparison: Entry; entry: Entry }[] {
  return elementsOf(document, '<div data-part="comparison"').map((part) => {
    const comparison = object.comparisons.find((each: Entry) => part.includes(`<span>${each.comparison_id}</span>`));
    return { part, comparison, entry: figures.comparisons.find((each: Entry) => each.comparison_id === comparison.comparison_id) };
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

const histogramOf = (part: string): string | undefined => elementOf(part, '<div data-figure="histogram">');
const boxOf = (part: string): string | undefined => elementOf(part, '<div data-figure="box">');
const ofKind = (rects: Rect[], kind: string): Rect[] => rects.filter((rect) => rect.kind === kind);
const height = (count: number, top: number): number => Number(((count / top) * 100).toFixed(2));

// The kept status reads whose kept figures read holds an entry with figures.
const DRAWN = Object.keys(KEPT_FIGURES).filter((name) => keptObject(KEPT_FIGURES[name]).comparisons.some((entry: Entry) => entry.unavailable === null));

test("the kept figures reads hold entries with figures on both Tracks, and status-chinook-spread holds a spread", () => {
  assert.deepEqual(DRAWN.sort(), ["status-chinook-pending", "status-chinook-spread", "status-public-check", "status-several-pending", "status-success"]);
  assert.ok(keptObject("figures-chinook-spread").comparisons[0].histogram.length > 1);
});

// The histogram.
test("the axis top of a histogram is the first of 1, 2, 2.5, 5 and 10 times a power of ten at or above the largest count, and 1 with no count above zero", () => {
  for (const [largest, top] of [
    [0, 1],
    [1, 1],
    [3, 5],
    [4, 5],
    [7, 10],
    [12, 20],
    [22, 25],
    [37, 50],
    [182, 200],
    [250, 250],
    [251, 500],
    [1000, 1000],
  ]) {
    assert.equal(histogramTop(largest), top, `${largest}`);
  }
});

for (const name of Object.keys(KEPT_FIGURES)) {
  test(`each entry with figures draws one histogram, one column per bin in the bins' order, each column's height its count over the axis top: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      const histograms = elementsOf(part, '<div data-figure="histogram">');
      if (entry.unavailable !== null) {
        assert.equal(histograms.length, 0, entry.comparison_id);
        continue;
      }
      assert.equal(histograms.length, 1, entry.comparison_id);
      const columns = ofKind(rectsOf(histograms[0]), "column");
      const top = histogramTop(Math.max(...entry.histogram.map((bin: Entry) => bin.count)));
      assert.equal(columns.length, entry.histogram.length);
      entry.histogram.forEach((bin: Entry, at: number) => {
        assert.equal(columns[at].height, height(bin.count, top), `bin ${at}`);
        if (at > 0) assert.ok(columns[at].x > columns[at - 1].x, `bin ${at} stands after bin ${at - 1}`);
      });
    }
  });
}

test("a count changed in the test is followed by its column, and the others are drawn over the new axis top: status-success", async (t) => {
  const object = keptObject("status-success");
  const figures = keptObject("figures-success");
  const bins = figures.comparisons[0].histogram;
  bins[0].count = 150;
  const columns = ofKind(rectsOf(histogramOf(comparisonsOf(await drawn(t, object, figures), object, figures)[0].part)!), "column");
  assert.equal(columns[0].height, 75);
  bins.forEach((bin: Entry, at: number) => assert.equal(columns[at].height, height(bin.count, 200), `bin ${at}`));
});

test("one bin whose low equals its high is one column: status-chinook-pending", async (t) => {
  const object = keptObject("status-chinook-pending");
  const figures = keptObject("figures-chinook-pending");
  const [bin] = figures.comparisons[0].histogram;
  assert.equal(bin.low, bin.high);
  const columns = ofKind(rectsOf(histogramOf(comparisonsOf(await drawn(t, object, figures), object, figures)[0].part)!), "column");
  assert.equal(columns.length, 1);
  assert.equal(columns[0].height, 80);
});

// The box plot.
const place = (value: number, quartiles: Entry): number => ((value - quartiles.min) / (quartiles.max - quartiles.min)) * 100;

// The places of a box plot's marks on its axis: each whisker's ends, the box's edges and the median's middle.
function placesOf(box: string): Record<string, number> {
  const rects = rectsOf(box);
  const [low, high] = ofKind(rects, "whisker");
  const [inner] = ofKind(rects, "box");
  const [median] = ofKind(rects, "median");
  assert.ok(low && high && inner && median, box);
  return { min: low.x, q1: inner.x, median: median.x + median.width / 2, q3: inner.x + inner.width, max: high.x + high.width, lowEnd: low.x + low.width, highStart: high.x };
}

for (const name of DRAWN) {
  test(`each entry with figures draws one box plot: the whiskers from the minimum to the first quartile and from the third to the maximum, the box between the quartiles, the median inside it: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const boxes = elementsOf(part, '<div data-figure="box">');
      assert.equal(boxes.length, 1, entry.comparison_id);
      const places = placesOf(boxes[0]);
      const median = ofKind(rectsOf(boxes[0]), "median")[0];
      for (const [mark, at] of Object.entries(places)) assert.ok(Number.isFinite(at), `${mark} at ${at}`);
      const quartiles = entry.quartiles;
      assert.ok(FIVE.every((key, at) => at === 0 || places[key] >= places[FIVE[at - 1]] - NEAR), JSON.stringify(places));
      if (quartiles.max === quartiles.min) continue;
      for (const key of ["min", "q1", "q3", "max"]) assert.ok(Math.abs(places[key] - place(quartiles[key], quartiles)) <= NEAR, `${key}: ${places[key]} against ${place(quartiles[key], quartiles)}`);
      assert.ok(Math.abs(places.lowEnd - places.q1) <= NEAR && Math.abs(places.highStart - places.q3) <= NEAR, JSON.stringify(places));
      assert.ok(Math.abs(places.median - place(quartiles.median, quartiles)) <= median.width / 2 + NEAR, `median at ${places.median}`);
    }
  });
}

for (const key of ["q1", "q3"]) {
  test(`a ${key} changed in the test moves its edge of the box: status-success`, async (t) => {
    const object = keptObject("status-success");
    const figures = keptObject("figures-success");
    const quartiles = figures.comparisons[0].quartiles;
    const before = placesOf(boxOf(comparisonsOf(await drawn(t, object, figures), object, figures)[0].part)!)[key];
    quartiles[key] = key === "q1" ? (quartiles.min + quartiles.q1) / 2 : (quartiles.q3 + quartiles.max) / 2;
    const after = placesOf(boxOf(comparisonsOf(await drawn(t, object, figures), object, figures)[0].part)!)[key];
    assert.ok(Math.abs(after - place(quartiles[key], quartiles)) <= NEAR, `${key} at ${after}`);
    assert.ok(Math.abs(after - before) > 1, `${before} to ${after}`);
  });
}

// Five equal numbers, as `chinook_pending_study` gives them (four Cases, all 0.0), and as a Comparison whose paired deltas are all
// equal near 1e308 would: `1e308 + 1` is `1e308`, so the range is zero there too.
for (const [label, value] of [
  ["the kept output of chinook_pending_study", 0],
  ["its five numbers and its one bin set to 1e308 in the test", 1e308],
] as const) {
  test(`with five equal numbers the box, the median and the whiskers stand at one place, one finite number: ${label}`, async (t) => {
    const object = keptObject("status-chinook-pending");
    const figures = keptObject("figures-chinook-pending");
    const entry = figures.comparisons[0];
    for (const key of FIVE) entry.quartiles[key] = value;
    entry.histogram = [{ low: value, high: value, count: 4 }];
    const box = boxOf(comparisonsOf(await drawn(t, object, figures), object, figures)[0].part)!;
    const places = Object.values(placesOf(box)).map((at) => Number(at.toFixed(2)));
    assert.ok(places.every(Number.isFinite), JSON.stringify(places));
    assert.equal(new Set(places).size, 1, JSON.stringify(places));
  });
}

test("the place of a number on the axis of a box plot is its share of the range, and the middle when the range is zero", () => {
  assert.equal(axisPosition(5, 0, 10), 50);
  assert.equal(axisPosition(0, 0, 10), 0);
  assert.equal(axisPosition(10, 0, 10), 100);
  assert.equal(axisPosition(-1, -4, 0), 75);
  for (const value of [0, 1e308, -1e308]) assert.equal(axisPosition(value, value, value), 50);
});

// What a figure may be in the document.
for (const name of DRAWN) {
  test(`each mark of a figure takes its colour from a class whose rule names a theme variable of VS Code: ${name}`, async (t) => {
    const document = await drawn(t, keptObject(name), keptObject(KEPT_FIGURES[name]));
    const { style } = partsOf(document);
    const marks = elementsOf(document, "<div data-figures>").flatMap((figures) => rectsOf(figures));
    assert.ok(marks.length > 0);
    for (const kind of new Set(marks.map((mark) => mark.kind))) {
      assert.match(style, new RegExp(`rect\\.${kind}\\s*\\{[^}]*fill:\\s*var\\(--vscode-[a-zA-Z0-9-]+\\)`), kind);
    }
  });
}

// The numbers of a figure.
const numbersOf = (entry: Entry): Set<string> =>
  new Set([...entry.histogram.flatMap((bin: Entry) => [bin.low, bin.high, bin.count]), ...FIVE.map((key) => entry.quartiles[key])].map(written));

for (const name of DRAWN) {
  test(`each number a figure prints is a number of its entry's histogram or quartiles, written as every number is, in a link to the part of its Comparison: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    const document = await drawn(t, object, figures);
    for (const { part, comparison, entry } of comparisonsOf(document, object, figures)) {
      if (entry.unavailable !== null) continue;
      const shown = elementOf(part, "<div data-figures>")!;
      const links = [...shown.matchAll(/<a href="#comparison-(\d+)" data-kind="([a-z_]+)">([^<]*)<\/a>/g)];
      assert.ok(links.length >= entry.histogram.length + FIVE.length, `${links.length} links`);
      for (const [, index, kind, text] of links) {
        assert.ok(numbersOf(entry).has(text), `${text} is a number of the entry of ${entry.comparison_id}`);
        assert.equal(object.comparisons[Number(index)].comparison_id, comparison.comparison_id, `${kind} ${text}`);
      }
      const between = partsOf(shown.replace(/<a [^>]*>[^<]*<\/a>/g, "")).between;
      assert.doesNotMatch(between, /\d/, between);
    }
  });
}

// A withheld delta, an entry with no figures, and a failed figures call.
for (const name of ["status-bike-withheld", "status-chinook-withheld"]) {
  for (const [way, answer] of [
    ["a figures read that succeeds", () => success(keptObject(KEPT_FIGURES[name]))],
    ["a failed figures call", () => exit(0, "not JSON")],
  ] as const) {
    test(`a Comparison whose delta is withheld draws no figure and shows neither label, with ${way}: ${name}`, async (t) => {
      const object = keptObject(name);
      const { document } = await documentFor(t, success(object), answer());
      const parts = elementsOf(document, '<div data-part="comparison"');
      assert.ok(parts.length > 0);
      for (const part of parts) {
        assert.equal(elementOf(part, "<div data-figures>"), undefined, part);
        assert.equal(count(part, FAILED) + count(part, UNAVAILABLE), 0, part);
      }
      assert.ok(!partsOf(document).tags.some((tag) => tag.includes("data-figure")), "no figure in the document");
    });
  }
}

for (const reason of OTHER_REASONS) {
  test(`an entry whose unavailable is ${reason} draws no figure, and its Comparison's part shows the label once, after its limitations: status-success`, async (t) => {
    const object = keptObject("status-success");
    const figures = keptObject("figures-success");
    Object.assign(figures.comparisons[0], { unavailable: reason, paired_deltas: null, histogram: null, quartiles: null });
    const [{ part }] = comparisonsOf(await drawn(t, object, figures), object, figures);
    assert.ok(!partsOf(part).tags.some((tag) => tag.includes("data-figure")), part);
    assert.equal(count(part, UNAVAILABLE), 1);
    assert.equal(count(part, FAILED), 0);
    assert.ok(part.indexOf(UNAVAILABLE) > part.indexOf('<div data-part="limitations"'), part);
  });
}

// Where the figures stand.
for (const name of DRAWN) {
  test(`each Comparison's figures stand after the element of its limitations, in document order: ${name}`, async (t) => {
    const object = keptObject(name);
    const figures = keptObject(KEPT_FIGURES[name]);
    for (const { part, entry } of comparisonsOf(await drawn(t, object, figures), object, figures)) {
      if (entry.unavailable !== null) continue;
      const limitations = part.indexOf('<div data-part="limitations"');
      assert.ok(limitations >= 0 && part.indexOf("<div data-figures>") > limitations, entry.comparison_id);
    }
  });
}

test("the labels of the figures are entries of contract.json", () => {
  for (const label of [FAILED, UNAVAILABLE]) assert.ok(contract.labels.includes(label), label);
});
