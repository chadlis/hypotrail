import { test } from "node:test";
import assert from "node:assert/strict";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { activate } from "../src/extension";
import { MANIFEST } from "./tools-harness";
import * as stub from "./vscode-stub";

test("activation registers each tool the manifest contributes once, under its name, and keeps each registration among the subscriptions", () => {
  stub.reset();
  const context = { subscriptions: [] as unknown[], extensionPath: "/home/owner/hypotrail/clients/vscode" };
  activate(context as never);
  const contributed: string[] = MANIFEST.contributes.languageModelTools.map((entry: { name: string }) => entry.name);
  const registered = stub.callsOf("registerTool").map((call) => call.args[0] as string);
  assert.equal(contributed.length, 3);
  for (const name of contributed) assert.equal(registered.filter((each) => each === name).length, 1, name);
  for (const name of registered) assert.ok(contributed.includes(name), name);
  assert.equal(stub.state.tools.length, 3);
  for (const each of stub.state.tools) assert.ok(context.subscriptions.includes(each.disposable), each.name);
});

// The digests, read at main 04b5806, of the write tool's code (tools.ts from `type DecideInput` to the end of `decideTool`) and of its
// manifest entry as JSON: the run tool leaves both byte for byte as they were.
const DECIDE_CODE_SHA256 = "02dfb9ecc2e07a9453e2cc9c616a56745aa1035b60ab47a46d94e4d132cc404b";
const DECIDE_ENTRY_SHA256 = "2509bf82536d2c0084819a8894d4e0c4b8c90601c782c7da6e4b1d8d0e6260c9";
const sha256 = (text: string) => crypto.createHash("sha256").update(text).digest("hex");

test("the write tool's code, its manifest entry and its registration are byte for byte those of main", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "src", "tools.ts"), "utf8");
  const from = source.indexOf("type DecideInput");
  const end = source.indexOf("\n};\n", source.indexOf("export const decideTool")) + "\n};\n".length;
  assert.ok(from >= 0 && end > from);
  // #283 changes the read tool inside this interval. Hash the original write and shared code with only that new read restored.
  const lessonRead = [
    '    const outcome = await readStudy(ROOT, resolved.study);',
    '    if (outcome.outcome !== "success") return answer(readAnswer(resolved.study, outcome));',
    '    return answer(`${readAnswer(resolved.study, outcome)}\\n${lessonAnswer(await readLesson(ROOT, resolved.study))}`);',
  ].join("\n");
  const priorRead = "    return answer(readAnswer(resolved.study, await readStudy(ROOT, resolved.study)));";
  const checked = source.slice(from, end);
  assert.equal(checked.split(lessonRead).length, 2);
  assert.equal(sha256(checked.replace(lessonRead, priorRead)), DECIDE_CODE_SHA256);
  const entry = MANIFEST.contributes.languageModelTools.find((tool: { name: string }) => tool.name === "hypotrail_decide");
  assert.equal(sha256(JSON.stringify(entry)), DECIDE_ENTRY_SHA256);
  const extension = fs.readFileSync(path.join(__dirname, "..", "..", "src", "extension.ts"), "utf8");
  assert.equal(extension.split("\n").filter((line) => line.includes("hypotrail_decide")).join("\n"), '    vscode.lm.registerTool("hypotrail_decide", decideTool),');
});
