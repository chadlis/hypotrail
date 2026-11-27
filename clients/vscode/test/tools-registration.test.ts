import { test } from "node:test";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { activate } from "../src/extension";
import { MANIFEST } from "./tools-harness";
import * as stub from "./vscode-stub";

test("activation registers each tool the manifest contributes once, under its name, and keeps each registration among the subscriptions", () => {
  stub.reset();
  const context = { subscriptions: [] as unknown[], extensionPath: "/home/owner/hypotrail/clients/vscode" };
  activate(context as never);
  const contributed: string[] = MANIFEST.contributes.languageModelTools.map((entry: { name: string }) => entry.name);
  const registered = stub.callsOf("registerTool").map((call) => call.args[0] as string);
  assert.equal(contributed.length, 2);
  for (const name of contributed) assert.equal(registered.filter((each) => each === name).length, 1, name);
  for (const name of registered) assert.ok(contributed.includes(name), name);
  assert.equal(stub.state.tools.length, 2);
  for (const each of stub.state.tools) assert.ok(context.subscriptions.includes(each.disposable), each.name);
});

// The SHA-256 of the manifest's entry of the write tool, as JSON, on main at 01f53b2: the read tool reads `lesson`, and the write tool
// is not changed.
const DECIDE_ENTRY_ON_MAIN = "2509bf82536d2c0084819a8894d4e0c4b8c90601c782c7da6e4b1d8d0e6260c9";

test("the manifest's entry of hypotrail_decide is byte-identical to the one on main", () => {
  const entry = MANIFEST.contributes.languageModelTools.find((each: { name: string }) => each.name === "hypotrail_decide");
  assert.equal(createHash("sha256").update(JSON.stringify(entry)).digest("hex"), DECIDE_ENTRY_ON_MAIN);
});
