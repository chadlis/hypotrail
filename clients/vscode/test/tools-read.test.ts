import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import contract from "../contract.json";
import { kept, KEPT } from "./kept";
import { recorder } from "./recorder";
import { CHECKOUT, FIRST, invoke, jsonAfterFirstLine, keptAnswer, NO_ANSWERS, READ_TOOL, workspace } from "./tools-harness";

const STATUS_READS = fs
  .readdirSync(KEPT)
  .filter((name) => name.startsWith("status-") && name.endsWith(".out"))
  .map((name) => name.slice(0, -".out".length))
  .filter((name) => JSON.parse(kept(`${name}.out`)).ok === true);

test("the kept status reads whose ok is true are found", () => {
  assert.ok(STATUS_READS.length >= 10, String(STATUS_READS.length));
});

for (const name of STATUS_READS) {
  test(`the read tool gives the object of ${name} whole, from one start of the read in the checkout root`, async (t) => {
    const { studies } = workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer(name));
    const text = await invoke(READ_TOOL, {});
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args, [...FIRST, ...contract.read_arguments.map((argument) => argument.replace("{path}", studies[0]))]);
    assert.equal(calls[0].args.includes("decide"), false);
    assert.equal(calls[0].options.cwd, CHECKOUT);
    assert.deepEqual(jsonAfterFirstLine(text), JSON.parse(kept(`${name}.out`)));
  });
}

test("the read tool gives a refusal of the CLI with its error object as printed and its exit code, from one start", async (t) => {
  workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer("status-not-found"));
  const text = await invoke(READ_TOOL, {});
  assert.equal(calls.length, 1);
  assert.deepEqual(jsonAfterFirstLine(text), JSON.parse(kept("status-not-found.out")).error);
  assert.ok(text.split("\n")[0].includes(`exit code ${Number(kept("status-not-found.exit"))}`), text);
});

for (const [cause, answer] of NO_ANSWERS) {
  test(`the read tool names the cause ${cause} of a read with no answer, from one start`, async (t) => {
    workspace(t, ["bike"]);
    const calls = recorder(t, answer, answer);
    const text = await invoke(READ_TOOL, {});
    assert.equal(calls.length, 1);
    assert.ok(text.includes(cause), text);
  });
}

test("the causes of the read tool's cases are those of contract.json", () => {
  assert.deepEqual(NO_ANSWERS.map(([cause]) => cause), contract.no_answer_causes);
});
