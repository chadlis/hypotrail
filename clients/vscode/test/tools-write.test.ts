import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { kept } from "./kept";
import { recorder } from "./recorder";
import { FIRST, invoke, jsonAfterFirstLine, keptAnswer, NO_ANSWERS, workspace, WRITE_INPUT, WRITE_TOOL } from "./tools-harness";

type ArgumentList = { name: string; study: string; decision: Record<string, unknown>; arguments: string[] };
const LISTS: ArgumentList[] = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "test", "decide-arguments.json"), "utf8"));
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// A list of arguments with the values of --study= and --request-id= put aside.
const apart = (args: string[]) => args.map((argument) => argument.replace(/^(--study=|--request-id=).*$/s, "$1"));

for (const list of LISTS) {
  test(`the write tool given the decision of the kept list with ${list.name} starts decide with that list, the Study found and a new request id`, async (t) => {
    const { studies } = workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer("decide-success"));
    const { request_id, ...input } = list.decision;
    void request_id;
    const text = await invoke(WRITE_TOOL, input);
    assert.equal(calls.length, 1);
    const args = calls[0].args;
    assert.equal(args[FIRST.length], "decide");
    assert.deepEqual(apart(args), apart([...FIRST, ...list.arguments]));
    assert.deepEqual(args.filter((argument) => argument.startsWith("--study=")), [`--study=${studies[0]}`]);
    const ids = args.filter((argument) => argument.startsWith("--request-id="));
    assert.equal(ids.length, 1);
    assert.match(ids[0].slice("--request-id=".length), UUID);
    assert.deepEqual(jsonAfterFirstLine(text), JSON.parse(kept("decide-success.out")));
  });
}

// Each case: what is changed in the accepted inputs, and the field the refusal names, or undefined when the write starts.
const AUTHOR_CASES: [string, Record<string, unknown>, string | undefined][] = [
  ["author proxy and no source", { author: "proxy", source: undefined }, "source"],
  ["author proxy and an empty source", { author: "proxy", source: "" }, "source"],
  ["author human and no source", { author: "human", source: undefined }, undefined],
  ["no question", { question: undefined }, "question"],
  ["no option", { option: undefined }, "option"],
  ["no cited_ids", { cited_ids: undefined }, "cited_ids"],
  ["no read_sequence", { read_sequence: undefined }, "read_sequence"],
];

for (const [name, change, named] of AUTHOR_CASES) {
  test(`the write tool with ${name} ${named ? `starts nothing and names ${named}` : "starts decide once, with no --source"}`, async (t) => {
    workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer("decide-success"));
    const text = await invoke(WRITE_TOOL, { ...WRITE_INPUT, ...change });
    if (named) {
      assert.equal(calls.length, 0);
      assert.match(text, new RegExp(`(?<![\\w-])${named}(?![\\w-])`));
    } else {
      assert.equal(calls.length, 1);
      assert.ok(calls[0].args.includes(`--author=${change.author}`));
      assert.equal(calls[0].args.some((argument) => argument.startsWith("--source")), false);
    }
  });
}

test("the write tool passes author proxy and its source as given", async (t) => {
  workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  await invoke(WRITE_TOOL, { ...WRITE_INPUT, author: "proxy", source: "the rule: keep the lower MAE" });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].args.includes("--author=proxy"));
  assert.ok(calls[0].args.includes("--source=the rule: keep the lower MAE"));
});

test("two invocations of the write tool with the same inputs start decide with two different request ids", async (t) => {
  workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer("decide-success"), keptAnswer("decide-success"));
  await invoke(WRITE_TOOL, WRITE_INPUT);
  await invoke(WRITE_TOOL, WRITE_INPUT);
  const ids = calls.map((call) => call.args.filter((argument) => argument.startsWith("--request-id=")));
  assert.equal(ids.length, 2);
  for (const each of ids) assert.match(each[0].slice("--request-id=".length), UUID);
  assert.notEqual(ids[0][0], ids[1][0]);
});

const REFUSALS = ["decide-study-changed", "decide-write-sequence-ahead", "decide-request-conflict", "decide-invalid-arguments", "decide-study-not-found"];

for (const name of REFUSALS) {
  test(`the write tool gives the refusal ${name} with its error object as printed, from one start`, async (t) => {
    workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer(name), keptAnswer("decide-success"));
    const text = await invoke(WRITE_TOOL, WRITE_INPUT);
    assert.equal(calls.length, 1);
    const printed = JSON.parse(kept(`${name}.out`)).error;
    assert.deepEqual(jsonAfterFirstLine(text), printed);
    if (printed.code === "STUDY_CHANGED") assert.deepEqual(jsonAfterFirstLine(text).details.writes_since, printed.details.writes_since);
  });
}

for (const [cause, answer] of NO_ANSWERS) {
  test(`the write tool gives a write with no answer (${cause}) as ${contract.write_no_answer_words}, from one start`, async (t) => {
    workspace(t, ["bike"]);
    const calls = recorder(t, answer, keptAnswer("decide-success"));
    const text = await invoke(WRITE_TOOL, WRITE_INPUT);
    assert.equal(calls.length, 1);
    assert.ok(text.includes(contract.write_no_answer_words), text);
    assert.ok(text.includes(cause), text);
  });
}
