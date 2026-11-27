// What the tests of the Copilot tools share: a workspace of Studies made on disk, the extension activated on the stub,
// the tools it registered, and the text of what a tool gives back.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { TestContext } from "node:test";
import { activate } from "../src/extension";
import { kept } from "./kept";
import { exit, type Answer } from "./recorder";
import * as stub from "./vscode-stub";

export const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "package.json"), "utf8"));
export const READ_TOOL = "hypotrail_read_study";
export const WRITE_TOOL = "hypotrail_decide";
// The checkout that holds the extension's folder, two folders above it, where the bridge starts the CLI.
export const CHECKOUT = path.resolve(__dirname, "..", "..", "..", "..");

// A workspace folder on disk holding one Study per name, with the extension activated on it. The Studies are given
// back by name, as the walk finds them.
export function workspace(t: TestContext, names: string[]): { root: string; studies: string[] } {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-tools-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  stub.reset();
  stub.state.folders = [root];
  activate({ subscriptions: [], extensionPath: "/home/owner/hypotrail/clients/vscode" } as never);
  const studies = names.map((name) => {
    fs.mkdirSync(path.join(root, name), { recursive: true });
    fs.writeFileSync(path.join(root, name, "study.json"), "{}");
    return path.join(root, name);
  });
  return { root, studies };
}

export function toolOf(name: string): stub.StubTool {
  const registered = stub.state.tools.filter((each) => each.name === name);
  if (registered.length !== 1) throw new Error(`${registered.length} tools registered as ${name}`);
  return registered[0].tool;
}

// Calls a tool as VS Code does: `prepareInvocation` first, when the tool has one, then `invoke`. A refusal that
// `prepareInvocation` throws ends the call before `invoke`, and its message is the text given back.
export async function invoke(name: string, input: Record<string, unknown>): Promise<string> {
  const tool = toolOf(name);
  if (tool.prepareInvocation) {
    try {
      await tool.prepareInvocation({ input }, {});
    } catch (error) {
      return (error as Error).message;
    }
  }
  const result = await tool.invoke({ input, toolInvocationToken: undefined }, {});
  return result.content.map((part) => part.value).join("");
}

// Calls a tool's `invoke` alone, with no `prepareInvocation` first: what a call gets that no confirmation came before.
export async function invokeAlone(name: string, input: Record<string, unknown>): Promise<string> {
  const result = await toolOf(name).invoke({ input, toolInvocationToken: undefined }, {});
  return result.content.map((part) => part.value).join("");
}

// The two ways a test calls the write tool, by name: as VS Code does, and by `invoke` alone.
export const CALLERS: [string, typeof invoke][] = [
  ["through prepareInvocation", invoke],
  ["by invoke alone", invokeAlone],
];

// The JSON a text gives on its second line: the object of a call, after the line that says what the call gave. The read tool's text
// gives the lesson read's object on its fourth line.
export function jsonOfSecondLine(text: string): any {
  return JSON.parse(text.split("\n")[1]);
}

// Inputs of the write tool that the bridge accepts, with no Study named: a test adds `study`.
export const WRITE_INPUT = {
  question: "Which Configuration do we keep after this Comparison?",
  option: "Keep the Control",
  author: "human",
  cited_ids: ["817d7c96-0d5e-4a2b-9c55-1f0e3a6b7d21"],
  read_sequence: 12,
};

export const FIRST = ["run", "--no-sync", "python", "-m", "hypotrail"];

// The answers of a call that got no usable answer, one per cause of `no_answer_causes`.
export const NO_ANSWERS: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true, signal: "SIGTERM" } }],
  ["no_json", exit(0, "")],
  ["inconsistent", { error: { code: null, killed: false, signal: "SIGKILL" } }],
];

export function keptAnswer(name: string): Answer {
  return exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
}
