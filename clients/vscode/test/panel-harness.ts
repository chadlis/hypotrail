// What the tests of the panel's read and content share: a workspace of Studies, the extension activated on the stub,
// an opening by the command or a link, and the parts of a document that the tests read.
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

// The root of every workspace holds a digit, a space and markup, so that each document shows such a path in its heading.
export function workspace(t: TestContext, names: string[]): string[] {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-read 7 <b>-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const panel of stub.state.panels) if (!panel.disposed) panel.dispose();
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

export async function followLink(form: number, study: string, decision = "c53337e9-d255-423d-a851-414278d5c3f0"): Promise<void> {
  const link = contract.link_forms[form].replace("{path}", study).replace("{uuid}", decision);
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

// The kept status reads, the nine states the demonstration kept last, in the order it went through them: seven of the second Bike
// Study, then two of the copy of the kept Chinook Campaign.
export const KEPT_READS = [
  "status-success",
  "status-chinook-pending",
  "status-several-pending",
  "status-decided",
  "status-deviation",
  "status-rescored",
  "status-result-changed",
  "status-repeated",
  "status-chinook-decided",
  "status-chinook-withheld",
  "status-bike-withheld",
  "status-public-check",
  "status-chinook-spread",
  "demonstration.after-compare.status",
  "demonstration.after-decide.status",
  "demonstration.after-6.1.status",
  "demonstration.after-6.2.status",
  "demonstration.before-the-refused-write.status",
  "demonstration.after-the-terminal-wrote.status",
  "demonstration.final.status",
  "demonstration.chinook-campaign-pending.status",
  "demonstration.chinook-campaign-decided.status",
];

// The kept figures read made beside each kept status read that has one, by the status read's name.
export const KEPT_FIGURES: Record<string, string> = {
  "status-success": "figures-success",
  "status-several-pending": "figures-several-pending",
  "status-bike-withheld": "figures-bike-withheld",
  "status-chinook-pending": "figures-chinook-pending",
  "status-chinook-withheld": "figures-chinook-withheld",
  "status-public-check": "figures-public-check",
  "status-chinook-spread": "figures-chinook-spread",
  "demonstration.after-compare.status": "demonstration.after-compare.figures",
  "demonstration.after-decide.status": "demonstration.after-decide.figures",
  "demonstration.after-6.1.status": "demonstration.after-6.1.figures",
  "demonstration.after-6.2.status": "demonstration.after-6.2.figures",
  "demonstration.before-the-refused-write.status": "demonstration.before-the-refused-write.figures",
  "demonstration.after-the-terminal-wrote.status": "demonstration.after-the-terminal-wrote.figures",
  "demonstration.final.status": "demonstration.final.figures",
  "demonstration.chinook-campaign-pending.status": "demonstration.chinook-campaign-pending.figures",
  "demonstration.chinook-campaign-decided.status": "demonstration.chinook-campaign-decided.figures",
};

export function keptObject(name: string): Record<string, any> {
  return JSON.parse(kept(`${name}.out`));
}

export function success(object: unknown): Answer {
  return exit(0, JSON.stringify(object));
}

// The answer of a figures call that fails, which leaves the document of its status read with the label of a failed figures call.
export const FIGURES_FAILED: Answer = exit(0, "not JSON");

// `answers` with the answer of a figures call after each answer of a status read that succeeds (exit 0 and an object with
// `pending_decisions`), since the panel makes the figures call after each such read: a test that queues the answers of a status read
// and of the write after it keeps them in step.
export function withFigures(...answers: Answer[]): Answer[] {
  const status = (answer: Answer): boolean => {
    try {
      return !answer.error && "pending_decisions" in JSON.parse(answer.stdout ?? "");
    } catch {
      return false;
    }
  };
  return answers.flatMap((answer) => (status(answer) ? [answer, FIGURES_FAILED] : [answer]));
}

// The document the panel shows once the command opened it on one Study and its calls were answered with `answers` in turn: the
// status read, then the figures call, which takes the last answer again when it is the only one.
export async function documentFor(t: TestContext, ...answers: Answer[]): Promise<{ document: string; calls: RecordedCall[] }> {
  workspace(t, ["bike"]);
  const calls = recorder(t, ...answers);
  await runCommand();
  await settle();
  return { document: lastDocument(), calls };
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

export function unescaped(text: string): string {
  return text.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ENTITIES[entity]);
}

// A document read in three parts: the texts of the one `script` and the one `style` element set apart, then
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

// What makes a document break the policy, by patterns, with no parser. The patterns of an attribute read the tags of
// the document, not the text between them, and a remote address is looked for in the tags and in the texts of the
// script and of the style.
export function cspProblems(document: string): string[] {
  const problems: string[] = [];
  const policies = [...document.matchAll(/http-equiv="Content-Security-Policy" content="([^"]*)"/g)];
  if (policies.length !== 1) return [`${policies.length} policies`];
  const nonce = /script-src 'nonce-([^']*)'/.exec(policies[0][1])?.[1] ?? "";
  if (!/^[A-Za-z0-9]+$/.test(nonce)) problems.push(`the nonce ${nonce}`);
  const expected = contract.csp_directives.map((directive) => directive.replace("{nonce}", nonce)).join("; ");
  if (policies[0][1] !== expected) problems.push(`the policy ${policies[0][1]}`);
  for (const element of ["script", "style"]) {
    const opened = document.split(`<${element} `).length - 1;
    const withNonce = document.split(`<${element} nonce="${nonce}"`).length - 1;
    if (opened !== 1 || withNonce !== 1 || document.split(`<${element}>`).length > 1) problems.push(`${element}: ${opened} opened, ${withNonce} with the nonce`);
  }
  const { script, style, tags } = partsOf(document);
  if (tags.some((tag) => /\sstyle=/i.test(tag))) problems.push("a style attribute");
  if (tags.some((tag) => /\son[a-z]+\s*=/i.test(tag))) problems.push("an inline event handler");
  if ([...tags, script, style].some((part) => /https?:\/\//i.test(part))) problems.push("a remote address");
  if (/<\/script/i.test(script)) problems.push("the script's text holds </script");
  return problems;
}

// The texts of the client's sources and of contract.json, where an attribute value of a document is looked for.
export const LITERALS = [
  ...fs.readdirSync(path.join(__dirname, "..", "..", "src")).map((name) => fs.readFileSync(path.join(__dirname, "..", "..", "src", name), "utf8")),
  fs.readFileSync(path.join(__dirname, "..", "..", "contract.json"), "utf8"),
].join("\n");

// The SVG attributes that hold a bar's length and place, a number the client computes from the read's numbers.
export const GEOMETRY = ["x", "y", "width", "height"];

// Each attribute of the tags of a document, outside the policy, as its name and its value.
function attributesOf(document: string): [string, string][] {
  return partsOf(document)
    .tags.filter((tag) => !tag.includes("Content-Security-Policy"))
    .flatMap((tag) => [...tag.matchAll(/\s([a-z-]+)="([^"]*)"/g)].map((match): [string, string] => [match[1], match[2]]));
}

// The value of each attribute of the tags of a document, outside the policy, the nonce and the four geometry attributes.
export function attributeValues(document: string): string[] {
  return attributesOf(document)
    .filter(([name]) => !GEOMETRY.includes(name))
    .map(([, value]) => value)
    .filter((value) => !/^[a-f0-9]{32}$/.test(value));
}

// The value of each geometry attribute of the tags of a document.
export function geometryValues(document: string): string[] {
  return attributesOf(document)
    .filter(([name]) => GEOMETRY.includes(name))
    .map(([, value]) => value);
}

// A document with the text of its heading, the path the panel was opened with, replaced by a fixed text, so that two documents
// built in two workspaces can be compared.
export function samePath(document: string): string {
  return document.replace(/<h1 data-text>[^<]*<\/h1>/, "<h1 data-text>PATH</h1>");
}
