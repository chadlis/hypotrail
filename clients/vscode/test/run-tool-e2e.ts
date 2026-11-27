// The guide's tools driven as Copilot calls them, against the real CLI. The Python tests send the workspace's folder and the input on
// stdin. The optional tool name defaults to the run tool, and the guide test can separately simulate the person's panel Record control.
// The script activates the extension on the vscode stub and returns the response text and the arguments of calls started by the bridge,
// omitting the common prefix. Every child process is the real one: execFile is only watched.
import Module = require("node:module");
import childProcess = require("node:child_process");
import * as fs from "node:fs";
import * as path from "node:path";
import { setTimeout } from "node:timers/promises";
import contract from "../contract.json";
import type * as Extension from "../src/extension";
import type * as PanelHarness from "./panel-harness";
import type * as Stub from "./vscode-stub";

// `require("vscode")` gives the stub of this folder, as the tests' hook makes it give, and nothing else of the hook is taken.
type Resolver = (request: string, ...rest: unknown[]) => string;
const loader = Module as unknown as { _resolveFilename: Resolver };
const resolve = loader._resolveFilename;
loader._resolveFilename = function (this: unknown, request: string, ...rest: unknown[]): string {
  return request === "vscode" ? path.join(__dirname, "vscode-stub.js") : resolve.call(this, request, ...rest);
};
const stub: typeof Stub = require("./vscode-stub");
const { activate }: typeof Extension = require("../src/extension");
const { panelOf, runCommand }: typeof PanelHarness = require("./panel-harness");

type Given = { folder: string; input: Record<string, unknown>; tool?: "hypotrail_read_study" | "hypotrail_run"; panelRecord?: boolean };

async function waitForPanel(panel: Stub.StubPanel, marker: RegExp): Promise<string> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const match = marker.exec(panel.webview.html);
    if (match !== null) return match[0];
    await setTimeout(20);
  }
  throw new Error(`The panel did not show ${marker}.`);
}

// This simulates the person's Record control on the temporary Study prepared by the Python guide test.
async function recordInPanel(words: unknown): Promise<string> {
  await runCommand();
  const panel = panelOf();
  const [, record] = contract.messages;
  await waitForPanel(panel, new RegExp(`<button data-message="${record}"`));
  panel.send({ message: record, pending: 0, option: 0, words });
  return waitForPanel(panel, /<a href="[^"]+" data-recorded>/);
}

async function main(): Promise<void> {
  const given: Given = JSON.parse(fs.readFileSync(0, "utf8"));
  const calls: string[][] = [];
  const real = childProcess.execFile;
  (childProcess as { execFile: unknown }).execFile = (program: string, args: string[], ...rest: unknown[]) => {
    calls.push(args.slice(args.indexOf("hypotrail") + 1));
    return (real as (...all: unknown[]) => unknown)(program, args, ...rest);
  };
  stub.reset();
  stub.state.folders = [given.folder];
  activate({ subscriptions: [], extensionPath: "" } as never);
  let text: string;
  try {
    if (given.panelRecord) {
      text = await recordInPanel(given.input.words);
    } else {
      const tool = given.tool ?? "hypotrail_run";
      if (tool !== "hypotrail_read_study" && tool !== "hypotrail_run") throw new Error(`Tool outside the guide: ${tool}`);
      const registered = stub.state.tools.find((each) => each.name === tool)!;
      await registered.tool.prepareInvocation?.({ input: given.input }, {});
      const result = await registered.tool.invoke({ input: given.input, toolInvocationToken: undefined }, {});
      text = result.content.map((part) => (part as { value: string }).value).join("");
    }
  } catch (error) {
    text = (error as Error).message;
  }
  process.stdout.write(JSON.stringify({ text, calls }));
}

void main();
