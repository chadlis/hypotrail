// The panel's charts and figures, built by the extension as text of the document: each bar is a name, a track drawn as one `svg`
// of `rect` elements, and its value as text; a figure is an `svg` of `rect` elements beside the numbers it is drawn from. A bar's
// length and a mark's place are the only numbers the client computes from the read's numbers; they stand only in the geometry
// attributes of a `rect`, and a `rect` takes its colour from its class.

// One bar: its name, already escaped, its value as the document writes it (a link, or the word of a null value), its value as a
// number, null when no track is drawn, and the class its `rect` takes its colour from.
export type Bar = { name: string; shown: string; value: number | null; kind: string };

// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/media/components/bars.js:21-23.
export function barLength(value: number | null, top: number): number {
  return Math.max(0, Math.min(100, ((Number(value) || 0) / top) * 100));
}

// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/media/components/bars.js:59-60.
export function scaleTop(values: (number | null)[]): number {
  return Math.max(0, ...values.map((value) => Number(value) || 0)) || 1;
}

// A length as a decimal number of at most two places, with no trailing zero.
const decimal = (length: number): string => String(Number(length.toFixed(2)));

// The track of a bar: a `rect` of its length, of the class of its kind, and, for a part of a whole, a second `rect` for the rest.
function track(kinds: string[], lengths: number[]): string {
  let x = 0;
  const rects = lengths.map((length, at) => {
    const rect = `<rect class="${kinds[at]}" x="${decimal(x)}" y="0" width="${decimal(length)}" height="8"></rect>`;
    x += length;
    return rect;
  });
  return `<svg viewbox="0 0 100 8" preserveaspectratio="none" aria-hidden="true">${rects.join("")}</svg>`;
}

// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/media/components/bars.js:81-86.
function row(name: string, body: string, shown: string): string {
  return `<div data-bar><span>${name}</span>${body}<span>${shown}</span></div>`;
}

// Bars on one scale, from zero to the largest of their values; a bar whose value is null shows its value and no track.
export function bars(list: Bar[]): string {
  const top = scaleTop(list.map((bar) => bar.value));
  return list.map((bar) => row(bar.name, typeof bar.value === "number" ? track([bar.kind], [barLength(bar.value, top)]) : "", bar.shown)).join("\n");
}

// A bar of a part of a whole: the part's length over the whole, then the rest.
export function partBar(name: string, kind: string, part: number, whole: number, shown: string): string {
  const length = barLength(part, whole > 0 ? whole : 1);
  return row(name, track([kind, "rest"], [length, 100 - length]), shown);
}

// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/media/components/histogram.js:16-21.
export function histogramTop(largest: number): number {
  if (largest <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(largest));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= largest) return step * power;
  return 10 * power;
}

// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/media/components/boxplot.js:39-41.
// The companion widens a zero range by 1, which leaves it zero near 1e308; here a zero range puts every number at the middle. Each
// number is halved before a difference is taken, so that a range from -1e308 to 1e308 stays finite.
export function axisPosition(value: number, min: number, max: number): number {
  const range = max / 2 - min / 2;
  if (!(range > 0) || !Number.isFinite(range)) return 50;
  return Math.max(0, Math.min(100, ((value / 2 - min / 2) / range) * 100));
}

const rect = (kind: string, x: number, y: number, width: number, height: number): string =>
  `<rect class="${kind}" x="${decimal(x)}" y="${decimal(y)}" width="${decimal(width)}" height="${decimal(height)}"></rect>`;

// A histogram: one column per bin, in the bins' order across the width, each as tall as its count over the axis top.
export function histogram(counts: number[]): string {
  const top = histogramTop(Math.max(0, ...counts));
  const step = 100 / counts.length;
  const gap = step * 0.12;
  const columns = counts.map((count, at) => rect("column", at * step + gap / 2, 100 - barLength(count, top), step - gap, barLength(count, top)));
  return `<svg viewbox="0 0 100 100" preserveaspectratio="none" aria-hidden="true">${columns.join("")}</svg>`;
}

// The five numbers of a box plot, in their order.
export type Five = [min: number, q1: number, median: number, q3: number, max: number];

// A box plot on one axis from the minimum to the maximum: a whisker from the minimum to the first quartile and one from the third
// quartile to the maximum, each ended by a cap, the box between the quartiles, the median across it, and the delta's mark when
// there is a delta, which runs past the box above and below it. A mark narrower than the track stays inside it.
export function boxPlot([min, q1, median, q3, max]: Five, delta: number | null): string {
  const at = (value: number): number => axisPosition(value, min, max);
  const across = (kind: string, from: number, to: number, y: number, height: number): string => rect(kind, at(from), y, at(to) - at(from), height);
  const mark = (kind: string, value: number, width: number, y: number, height: number): string =>
    rect(kind, Math.max(0, Math.min(100 - width, at(value) - width / 2)), y, width, height);
  const marks = [
    across("whisker", min, q1, 6.5, 1),
    across("whisker", q3, max, 6.5, 1),
    mark("cap", min, 0.5, 4.5, 5),
    mark("cap", max, 0.5, 4.5, 5),
    across("box", q1, q3, 3, 8),
    mark("median", median, 0.6, 3, 8),
    delta === null ? "" : mark("delta", delta, 0.8, 0, 14),
  ];
  return `<svg viewbox="0 0 100 14" preserveaspectratio="none" aria-hidden="true">${marks.join("")}</svg>`;
}

// One dot of the Control and one of the Candidate per Item or Case: its id, already escaped, and its two values.
export type Dot = { id: string; control: number; candidate: number };

// The dots of a Comparison, one row per Item or Case, on one scale from the smallest to the largest of all their values. In a row,
// the Control's mark is a tall narrow bar and the Candidate's a shorter one across its middle, both of one width, so that a mark
// stays inside the track as the others do; a thin bar joins the two.
export function dots(list: Dot[], [min, max]: [number, number]): string {
  const width = 1.4;
  const at = (value: number): number => Math.max(0, Math.min(100 - width, axisPosition(value, min, max) - width / 2));
  return list
    .map(({ id, control, candidate }) => {
      const [from, to] = [at(control), at(candidate)].sort((a, b) => a - b);
      const marks = [rect("between", from + width / 2, 4.5, to - from, 1), rect("control", at(control), 0, width, 10), rect("candidate", at(candidate), 2.5, width, 5)];
      return `<div data-dot><span data-text>${id}</span><svg viewbox="0 0 100 10" preserveaspectratio="none" aria-hidden="true">${marks.join("")}</svg></div>`;
    })
    .join("\n");
}
