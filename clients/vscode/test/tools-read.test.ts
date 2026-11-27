import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import contract from "../contract.json";
import { kept, KEPT } from "./kept";
import { lesson, recorder } from "./recorder";
import { CHECKOUT, FIRST, invoke, jsonOfSecondLine, keptAnswer, NO_ANSWERS, READ_TOOL, workspace, WRITE_INPUT, WRITE_TOOL } from "./tools-harness";

const STATUS_READS = fs
  .readdirSync(KEPT)
  .filter((name) => name.startsWith("status-") && name.endsWith(".out"))
  .map((name) => name.slice(0, -".out".length))
  .filter((name) => JSON.parse(kept(`${name}.out`)).ok === true);

test("the kept status reads whose ok is true are found", () => {
  assert.ok(STATUS_READS.length >= 10, String(STATUS_READS.length));
});

for (const name of STATUS_READS) {
  test(`the read tool gives the object of ${name} whole, from one start of the read in the checkout root, then one start of the lesson read`, async (t) => {
    const { studies } = workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer(name));
    const text = await invoke(READ_TOOL, {});
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[1].args.slice(FIRST.length), contract.lesson_arguments.map((argument) => argument.replace("{path}", studies[0])));
    assert.deepEqual(calls[0].args, [...FIRST, ...contract.read_arguments.filter((argument) => !argument.includes("{n}")).map((argument) => argument.replace("{path}", studies[0]))]);
    assert.deepEqual(calls[0].args.slice(FIRST.length), ["status", `--study=${studies[0]}`, "--json"]);
    assert.equal(calls[0].args.includes("decide"), false);
    assert.equal(calls[0].options.cwd, CHECKOUT);
    assert.deepEqual(jsonOfSecondLine(text), JSON.parse(kept(`${name}.out`)));
  });
}

test("the read tool gives a refusal of the CLI with its error object as printed and its exit code, from one start", async (t) => {
  workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer("status-not-found"));
  const text = await invoke(READ_TOOL, {});
  assert.equal(calls.length, 1);
  assert.deepEqual(jsonOfSecondLine(text), JSON.parse(kept("status-not-found.out")).error);
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

// "The Copilot tools make no profile read." (chadlis/hypotrail#262)
test("neither Copilot tool starts the profile read: the read tool on a Bike read and the write tool with its read after it", async (t) => {
  const { studies } = workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer("status-success"), keptAnswer("decide-success"), keptAnswer("status-decided"));
  await invoke(READ_TOOL, {});
  await invoke(WRITE_TOOL, { ...WRITE_INPUT, study: studies[0] });
  assert.ok(calls.length >= 2, String(calls.length));
  assert.deepEqual(calls.map((call) => call.args[FIRST.length]).filter((command) => command === contract.profile_arguments[0]), []);
});

// "`hypotrail_read_study` returns the `lesson` object beside the state, so that the chat explains with the same text" (#283).
for (const state of ["after-compare", "after-decide"]) {
  test(`the read tool gives the object of the status read, then starts the lesson read of the same Study and gives its object whole: ${state}`, async (t) => {
    const { studies } = workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer(`demonstration.${state}.status`), lesson(keptAnswer(`lesson.${state}`)));
    const text = await invoke(READ_TOOL, {});
    assert.deepEqual(calls.map((call) => call.args.slice(FIRST.length)), [
      ["status", `--study=${studies[0]}`, "--json"],
      contract.lesson_arguments.map((argument) => argument.replace("{path}", studies[0])),
    ]);
    const lines = text.split("\n");
    assert.deepEqual(JSON.parse(lines[1]), JSON.parse(kept(`demonstration.${state}.status.out`)));
    assert.deepEqual(JSON.parse(lines[3]), JSON.parse(kept(`lesson.${state}.out`)));
  });
}

test("the read tool gives the lesson read's refusal of a Chinook Study with its error object as printed, after the status object", async (t) => {
  workspace(t, ["chinook"]);
  recorder(t, keptAnswer("status-chinook-pending"), lesson(keptAnswer("lesson.chinook-pending")));
  const lines = (await invoke(READ_TOOL, {})).split("\n");
  assert.deepEqual(JSON.parse(lines[1]), JSON.parse(kept("status-chinook-pending.out")));
  assert.deepEqual(JSON.parse(lines[3]), JSON.parse(kept("lesson.chinook-pending.out")).error);
});
