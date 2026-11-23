// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client.
import contract from "../contract.json";
import type { Outcome } from "./bridge";

export type View = { reading: boolean; object?: Record<string, unknown>; failure?: Outcome };

// The panel's own words, by their place in `labels` of contract.json.
const LABEL = { reading: 0, readAgain: 1 } as const;

const label = (name: keyof typeof LABEL): string => escaped(contract.labels[LABEL[name]]);

export function escaped(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function bodyOf(view: View): string {
  const parts: string[] = [];
  if (view.reading) parts.push(`<p>${label("reading")}</p>`);
  parts.push(`<button data-message="${contract.read_again_message}">${label("readAgain")}</button>`);
  return parts.join("\n");
}
