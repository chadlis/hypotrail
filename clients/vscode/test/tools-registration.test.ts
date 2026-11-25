import { test } from "node:test";
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
