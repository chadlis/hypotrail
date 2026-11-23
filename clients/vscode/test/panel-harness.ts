// What the tests of the panel's read and content share: a workspace of Studies, the extension activated on the stub,
// an opening by the command or a link, and the parts of a document as the tickets of L2.5 read them.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { TestContext } from "node:test";
import contract from "../contract.json";
import { activate } from "../src/extension";
import { kept } from "./kept";
import { exit, recorder, type Answer, type RecordedCall } from "./recorder";
import * as stub from "./vscode-stub";
import childProcess = require("node:child_process");

export function workspace(t: TestContext, names: string[]): string[] {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-read-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  stub.reset();
  stub.state.folders = [root];
  activate({ subscriptions: [], extensionPath: "/home/owner/hypotrail/clients/vscode" } as never);
  t.after(() => {
    for (const panel of stub.state.panels) if (!panel.disposed) panel.dispose();
  });
  return names.map((name) => {
    fs.mkdirSync(path.join(root, name), { recursive: true });
    fs.writeFileSync(path.join(root, name, "study.json"), "{}");
    return path.join(root, name);
  });
}

export async function runCommand(): Promise<void> {
  await stub.state.commands.get("hypotrail.openPanel")!();
}

export async function followLink(form: number, study: string): Promise<void> {
  const link = contract.link_forms[form].replace("{path}", study).replace("{uuid}", "c53337e9-d255-423d-a851-414278d5c3f0");
  const match = /^vscode:\/\/([^/?#]*)([^?#]*)\?(.*)$/s.exec(link)!;
  await stub.state.uriHandlers[0].handleUri({ scheme: "vscode", authority: match[1], path: match[2], query: match[3], fragment: "" });
}

// Lets the recorder's answers arrive and the panel assign the documents that follow them.
export async function settle(): Promise<void> {
  for (let turn = 0; turn < 3; turn += 1) await new Promise((resolve) => setImmediate(resolve));
}

export function panelOf() {
  const open = stub.state.panels.filter((panel) => !panel.disposed);
  if (open.length !== 1) throw new Error(`${open.length} open panels`);
  return open[0];
}

export function lastDocument(): string {
  const documents = panelOf().documents;
  return documents[documents.length - 1];
}

export const KEPT_READS = ["status-success", "status-chinook-pending", "status-several-pending", "status-decided", "status-deviation"];

export function keptObject(name: string): Record<string, any> {
  return JSON.parse(kept(`${name}.out`));
}

export function success(object: unknown): Answer {
  return exit(0, JSON.stringify(object));
}

// The document the panel shows once the command opened it on one Study and the read was answered with `answer`.
export async function documentFor(t: TestContext, answer: Answer): Promise<{ document: string; calls: RecordedCall[] }> {
  workspace(t, ["bike"]);
  const calls = recorder(t, answer);
  await runCommand();
  await settle();
  return { document: lastDocument(), calls };
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

export function unescaped(text: string): string {
  return text.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ENTITIES[entity]);
}

// A document read as VA-V0 of #177 reads it: the texts of the one `script` and the one `style` element set apart, then
// each tag a substring from `<` to the next `>`, and the text between tags the rest, with HTML escaping undone.
export function partsOf(document: string): { script: string; style: string; tags: string[]; between: string } {
  let script = "";
  let style = "";
  const rest = document
    .replace(/(<script[^>]*>)([\s\S]*?)(<\/script>)/, (_, open, text, close) => ((script = text), open + close))
    .replace(/(<style[^>]*>)([\s\S]*?)(<\/style>)/, (_, open, text, close) => ((style = text), open + close));
  const tags = rest.match(/<[^>]*>/g) ?? [];
  const between = unescaped(rest.split(/<[^>]*>/).join("\n"));
  return { script, style, tags, between };
}

// The unescaped texts of the elements that carry the marker attribute of a marked text.
export function markedTexts(document: string): string[] {
  return [...document.matchAll(/<([a-z0-9]+) data-text>([^<]*)<\/\1>/g)].map((match) => unescaped(match[2]));
}

// The HTML of the first element that opens with `opening` and closes with `</tag>`, nested elements of the same tag
// included; undefined when none opens.
export function elementOf(document: string, opening: string): string | undefined {
  const start = document.indexOf(opening);
  if (start < 0) return undefined;
  const tag = /^<([a-z0-9]+)/.exec(opening)![1];
  const pattern = new RegExp(`<${tag}[\\s>]|</${tag}>`, "g");
  pattern.lastIndex = start;
  let depth = 0;
  for (let match = pattern.exec(document); match; match = pattern.exec(document)) {
    depth += match[0].startsWith("</") ? -1 : 1;
    if (depth === 0) return document.slice(start, match.index + match[0].length);
  }
  return undefined;
}

// Every element that opens with `opening`, in order.
export function elementsOf(document: string, opening: string): string[] {
  const found: string[] = [];
  let at = 0;
  for (;;) {
    const next = document.indexOf(opening, at);
    if (next < 0) return found;
    const element = elementOf(document.slice(next), opening)!;
    found.push(element);
    at = next + element.length;
  }
}

// A recorder whose calls stay in flight until the test answers them, each with `answer`.
export function heldRecorder(t: TestContext) {
  const calls: RecordedCall[] = [];
  const waiting: ((error: unknown, stdout: string, stderr: string) => void)[] = [];
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    calls.push({ program, args: [...args], options: { ...options } });
    waiting.push(callback);
    return {};
  });
  return {
    calls,
    answer(answer: Answer): void {
      const error = answer.error ? Object.assign(new Error("recorded"), answer.error) : null;
      for (const callback of waiting.splice(0)) callback(error, answer.stdout ?? "", answer.stderr ?? "");
    },
  };
}
