// The panel's charts, built by the extension as text of the document: each bar is a name, a track drawn as one `svg` of `rect`
// elements, and its value as text. A bar's length is the one number the client computes from the read's numbers; it stands only
// in the geometry attributes of a `rect`, and a `rect` takes its colour from its class.

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
