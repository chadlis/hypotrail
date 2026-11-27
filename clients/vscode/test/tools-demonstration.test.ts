// The two Copilot tools on the states the demonstration kept, on the tools harness, with no model: the read gives the read the panel
// used, and the write gives the argument list of the panel's Record at task 3 and the refusal of S1.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { DEMONSTRATION, kept } from "./kept";
import { KEPT_READS, keptObject, panelOf, runCommand, settle, workspace as panelWorkspace } from "./panel-harness";
import { recorder, type RecordedCall } from "./recorder";
import { FIRST, invoke, jsonOfSecondLine, keptAnswer, READ_TOOL, workspace, WRITE_TOOL } from "./tools-harness";

type Entry = Record<string, any>;

const readOf = (state: string): string => `${DEMONSTRATION}${state}.status`;
const STATES = KEPT_READS.filter((name) => name.startsWith(DEMONSTRATION)).map((name) => name.slice(DEMONSTRATION.length, -".status".length));

// The list of arguments of a decide call after its first arguments, with the value of --study= made `<study>`, the rule of
// tests/_client_helpers.py::replaced, and the request id set apart.
const apart = (args: string[]): string[] => args.slice(FIRST.length).map((argument) => argument.replace(/^--study=.*$/s, "--study=<study>").replace(/^--request-id=.*$/s, "--request-id="));
const decides = (calls: RecordedCall[]): RecordedCall[] => calls.filter((call) => call.args[FIRST.length] === "decide");

// What the write tool is given for the first option of the first Pending decision of a read, with the ids of the question and of the
// option, as the panel's Record sends it.
function firstOption(read: Entry, study: string): Entry {
  const [pending] = read.pending_decisions;
  return {
    question: pending.question.text,
    option: pending.options[0].text,
    author: contract.decide_author,
    question_id: pending.question.id,
    option_id: pending.options[0].id,
    cited_ids: [pending.comparison_id],
    read_sequence: read.write_sequence,
    study,
  };
}

// The argument list of the panel's Record on the first option of the first Pending decision of a kept state.
async function panelRecord(t: TestContext, state: string): Promise<string[]> {
  panelWorkspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer(readOf(state)), keptAnswer(`${DEMONSTRATION}${state}.figures`), keptAnswer(`${DEMONSTRATION}decide-task-3`));
  await runCommand();
  await settle();
  panelOf().send({ message: contract.messages[1], pending: 0, option: 0 });
  await settle();
  const [call] = decides(calls);
  return call.args;
}

for (const state of STATES) {
  test(`the read tool gives the object the panel reads at the kept state of the demonstration, whole: ${state}`, async (t) => {
    workspace(t, ["bike"]);
    const calls = recorder(t, keptAnswer(readOf(state)));
    const text = await invoke(READ_TOOL, {});
    assert.deepEqual(calls.map((call) => call.args[FIRST.length]), ["status", contract.lesson_arguments[0]]);
    assert.deepEqual(jsonOfSecondLine(text), keptObject(readOf(state)));
  });
}

test("the write tool given the first option of after-compare starts decide with the argument list of the panel's Record and of task 3, but for the request id", async (t) => {
  const record = apart(await panelRecord(t, "after-compare"));
  const { studies } = workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer(`${DEMONSTRATION}decide-task-3`));
  await invoke(WRITE_TOOL, firstOption(keptObject(readOf("after-compare")), studies[0]));
  assert.equal(decides(calls).length, 1, "one decide call");
  const ours = apart(decides(calls)[0].args);
  const demonstration = apart([...FIRST, ...JSON.parse(kept(`${DEMONSTRATION}decide-task-3.args`)).arguments]);
  for (let at = 0; at < Math.max(ours.length, record.length); at += 1) assert.equal(ours[at], record[at], `argument ${at} against the panel's Record`);
  assert.deepEqual(ours, demonstration, "the argument list of task 3");
});

test("the write tool given the first option of before-the-refused-write, answered with the refusal the demonstration kept at S1, gives the refusal STUDY_CHANGED", async (t) => {
  const { studies } = workspace(t, ["bike"]);
  const calls = recorder(t, keptAnswer(`${DEMONSTRATION}decide-s1`));
  const text = await invoke(WRITE_TOOL, firstOption(keptObject(readOf("before-the-refused-write")), studies[0]));
  assert.equal(decides(calls).length, 1, "one decide call");
  assert.ok(decides(calls)[0].args.includes("--read-sequence=28"));
  assert.equal(jsonOfSecondLine(text).code, "STUDY_CHANGED");
});
