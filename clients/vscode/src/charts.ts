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

// A mark one `width` wide whose middle stands at `at` on a track from 0 to 100, kept inside the track.
const centred = (at: number, width: number): number => Math.max(0, Math.min(100 - width, at - width / 2));

// The zero mark of a figure whose axis runs from `low` to `high`, across its whole height, or none when zero is off the axis.
function zeroMark(low: number, high: number, height: number): string {
  return low <= 0 && 0 <= high ? rect("zero", centred(axisPosition(0, low, high), 0.4), 0, 0.4, height) : "";
}

// A histogram: one column per bin, in the bins' order across the width, each as tall as its count over the axis top, and the zero
// mark of the axis from `low` to `high`.
export function histogram(counts: number[], [low, high]: [number, number]): string {
  const top = histogramTop(Math.max(0, ...counts));
  const step = 100 / counts.length;
  const gap = step * 0.12;
  const columns = counts.map((count, at) => rect("column", at * step + gap / 2, 100 - barLength(count, top), step - gap, barLength(count, top)));
  return `<svg viewbox="0 0 100 100" preserveaspectratio="none" aria-hidden="true">${columns.join("")}${zeroMark(low, high, 100)}</svg>`;
}

// The five numbers of a box plot, in their order.
export type Five = [min: number, q1: number, median: number, q3: number, max: number];

// A box plot on one axis from the minimum to the maximum: a whisker from the minimum to the first quartile and one from the third
// quartile to the maximum, each ended by a cap, the box between the quartiles, the median across it, the delta's mark when there is
// a delta, which runs past the box above and below it and is wider than the median, and the zero mark across the whole height.
export function boxPlot([min, q1, median, q3, max]: Five, delta: number | null): string {
  const at = (value: number): number => axisPosition(value, min, max);
  const across = (kind: string, from: number, to: number, y: number, height: number): string => rect(kind, at(from), y, at(to) - at(from), height);
  const mark = (kind: string, value: number, width: number, y: number, height: number): string => rect(kind, centred(at(value), width), y, width, height);
  const marks = [
    across("whisker", min, q1, 6.5, 1),
    across("whisker", q3, max, 6.5, 1),
    mark("cap", min, 0.5, 4.5, 5),
    mark("cap", max, 0.5, 4.5, 5),
    across("box", q1, q3, 4, 6),
    mark("median", median, 0.6, 4, 6),
    delta === null ? "" : mark("delta", delta, 1.2, 0, 14),
    zeroMark(min, max, 14),
  ];
  return `<svg viewbox="0 0 100 14" preserveaspectratio="none" aria-hidden="true">${marks.join("")}</svg>`;
}

// One dot of the Control and one of the Candidate per Item or Case: its id, already escaped, its two values, and the class of the bar
// that joins them: `favours-control` or `favours-candidate` for the side it favours, or `between` when the two values are equal.
export type Dot = { id: string; control: number; candidate: number; joint: string };

// The dots of a Comparison, one row per Item or Case, on one scale from the smallest to the largest of all their values. In a row,
// the Control's mark is a tall narrow bar and the Candidate's a shorter one across its middle, both of one width, so that a mark
// stays inside the track as the others do; a thin bar of the row's `joint` class joins the two.
export function dots(list: Dot[], [min, max]: [number, number], valueAttrs: string): string {
  const width = 1.4;
  const at = (value: number): number => centred(axisPosition(value, min, max), width);
  return list
    .map(({ id, control, candidate, joint }) => {
      const [from, to] = [at(control), at(candidate)].sort((a, b) => a - b);
      const marks = [rect(joint, from + width / 2, 4.5, to - from, 1), rect("control", at(control), 0, width, 10), rect("candidate", at(candidate), 2.5, width, 5)];
      return `<div data-dot><span data-text>${id}</span><svg viewbox="0 0 100 10" preserveaspectratio="none" aria-hidden="true"${valueAttrs}>${marks.join("")}</svg></div>`;
    })
    .join("\n");
}

// --- the figures of the data profile ---------------------------------------------------------------------------------------------

const svgOf = (width: number, height: number, rects: string[]): string =>
  `<svg viewbox="0 0 ${width} ${height}" preserveaspectratio="none" aria-hidden="true">${rects.join("")}</svg>`;

// A day as a number of days, from a date of the form YYYY-MM-DD.
export const dayOf = (date: string): number => Date.parse(`${date}T00:00:00Z`) / 86400000;

// One span of the band: its first and last day, and the class its `rect` takes its colour from.
export type Span = { first: number; last: number; kind: string };

// The target over time under the Partition band: the days run across the width from the band's first day to its last, each day with a
// value a column as tall as its value over the largest, and under them one `rect` per span of the band.
export function timeline(band: Span[], days: [day: number, value: number][]): string {
  if (band.length === 0) return svgOf(100, 40, []);
  const first = Math.min(...band.map((span) => span.first));
  const width = 100 / (Math.max(...band.map((span) => span.last)) - first + 1);
  const top = scaleTop(days.map(([, value]) => value));
  const spans = band.map((span) => rect(span.kind, (span.first - first) * width, 36, (span.last - span.first + 1) * width, 4));
  const columns = days.map(([day, value]) => rect("day", (day - first) * width, 34 - (barLength(value, top) * 34) / 100, width, (barLength(value, top) * 34) / 100));
  return svgOf(100, 40, [...spans, ...columns]);
}

// One column per count, side by side, each as tall as its count over the largest.
export function columns(counts: number[]): string {
  const top = scaleTop(counts);
  const step = 100 / Math.max(1, counts.length);
  return svgOf(100, 30, counts.map((count, at) => rect("column", at * step + step * 0.06, 30 - (barLength(count, top) * 30) / 100, step * 0.88, (barLength(count, top) * 30) / 100)));
}

// One cell of the matrix: its row and column in the clustering order, the size of its mark from 0 to 1, and its class.
export type Cell = { row: number; column: number; size: number; kind: string };

// The matrix: a grid of `size` by `size` places, each cell a square mark in its place, as wide as its size of the place.
export function matrix(size: number, cells: Cell[]): string {
  const place = 100 / Math.max(1, size);
  const marks = cells.map(({ row, column, size: part, kind }) => {
    const side = place * Math.max(0.15, Math.min(1, part)) * 0.92;
    return rect(kind, column * place + (place - side) / 2, row * place + (place - side) / 2, side, side);
  });
  return svgOf(100, 100, marks);
}

// The points of a feature against the target, each a small square on axes from the smallest to the largest of each.
export function scatter(points: [x: number, y: number][]): string {
  if (points.length === 0) return svgOf(100, 50, []);
  const [xs, ys] = [points.map(([x]) => x), points.map(([, y]) => y)];
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const side = 1.2;
  return svgOf(100, 50, points.map(([x, y]) => rect("point", centred(axisPosition(x, x0, x1), side), (centred(100 - axisPosition(y, y0, y1), side * 2) * 50) / 100, side, side)));
}

// One box per value, side by side, on one axis from the smallest of their minima to the largest of their maxima: a whisker from the
// minimum to the maximum, the box between the quartiles and the median across it; a value with no five numbers has no box.
export function boxes(fives: (Five | null)[]): string {
  const known = fives.filter((five): five is Five => five !== null);
  if (known.length === 0) return svgOf(100, 50, []);
  const [low, high] = [Math.min(...known.map((five) => five[0])), Math.max(...known.map((five) => five[4]))];
  const y = (value: number): number => ((100 - axisPosition(value, low, high)) * 50) / 100;
  const step = 100 / fives.length;
  const marks = fives.flatMap((five, at) => {
    if (five === null) return [];
    const [min, q1, median, q3, max] = five;
    const x = at * step;
    return [rect("whisker", x + step / 2 - 0.3, y(max), 0.6, y(min) - y(max)), rect("box", x + step * 0.2, y(q3), step * 0.6, y(q1) - y(q3)), rect("median", x + step * 0.2, Math.max(0, y(median) - 0.4), step * 0.6, 0.8)];
  });
  return svgOf(100, 50, marks);
}
