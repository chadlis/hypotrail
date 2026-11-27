// The run tool driven as Copilot calls it, against the real CLI: `tests/test_run_tool_end_to_end.py` starts this script once per case of the
// corpus, with `node out/test/run-tool-e2e.js`, and without the tests' hook, which answers every `execFile` as a program not found. It
// reads one JSON object on stdin, `folder` (the workspace folder that holds the Studies) and `input` (the tool's input), activates the
// extension on the `vscode` stub, calls the tool's `prepareInvocation` then `invoke`, as VS Code does, and prints one JSON object: `text`,
// what the tool gave back, and `calls`, the argument list of each process the bridge started, after the first arguments. Each process is
// the real one: `execFile` is only watched.
import Module = require("node:module");
import childProcess = require("node:child_process");
import * as fs from "node:fs";
import * as path from "node:path";
import type * as Extension from "../src/extension";
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

type Given = { folder: string; input: Record<string, unknown> };

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
  const [registered] = stub.state.tools.filter((each) => each.name === "hypotrail_run");
  let text: string;
  try {
    await registered.tool.prepareInvocation!({ input: given.input }, {});
    const result = await registered.tool.invoke({ input: given.input, toolInvocationToken: undefined }, {});
    text = result.content.map((part) => (part as { value: string }).value).join("");
  } catch (error) {
    text = (error as Error).message;
  }
  process.stdout.write(JSON.stringify({ text, calls }));
}

void main();
