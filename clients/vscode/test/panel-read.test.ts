import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { kept } from "./kept";
import { followLink, heldRecorder, lastDocument, panelOf, partsOf, runCommand, settle, workspace } from "./panel-harness";
import { exit, recorder } from "./recorder";
import * as stub from "./vscode-stub";

const STATUS = kept("status-success.out");
const READING = "Reading the Study.";
const READ_AGAIN = { message: "read-again" };

function readArguments(study: string): string[] {
  return [...contract.first_arguments, ...contract.read_arguments.map((argument) => argument.replace("{path}", study))];
}

const WAYS: [string, (study: string) => Promise<void>][] = [
  ["the command", () => runCommand()],
  ["a link of the first form", (study) => followLink(0, study)],
  ["a link of the second form", (study) => followLink(1, study)],
];

for (const [way, open] of WAYS) {
  test(`an opening by ${way} reads the Study once, through status, with the string the panel was opened with`, async (t) => {
    const [study] = workspace(t, ["bike"]);
    const calls = recorder(t, exit(0, STATUS));
    await open(study);
    await settle();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].program, contract.program);
    assert.deepEqual(calls[0].args, readArguments(study));
    assert.deepEqual(calls.filter((call) => !call.args.includes("status")), []);
  });
}

test("the message of Read again on a read that succeeded starts one more status call, with the same arguments", async (t) => {
  const [study] = workspace(t, ["bike"]);
  const calls = recorder(t, exit(0, STATUS));
  await runCommand();
  await settle();
  panelOf().send(READ_AGAIN);
  await settle();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].args, readArguments(study));
  assert.deepEqual(calls[1].args, calls[0].args);
});

test("while a read is in flight the document holds the line for a read in flight, and a message of Read again starts no call", async (t) => {
  workspace(t, ["bike"]);
  const { calls, answer } = heldRecorder(t);
  await runCommand();
  assert.equal(panelOf().documents.length, 1);
  assert.ok(partsOf(panelOf().documents[0]).between.includes(READING), panelOf().documents[0]);
  panelOf().send(READ_AGAIN);
  await settle();
  assert.equal(calls.length, 1);
  answer(exit(0, STATUS));
  await settle();
  assert.equal(calls.length, 1);
  assert.ok(!partsOf(lastDocument()).between.includes(READING));
});

// The part of VD-V13 of #180 that #177's own code meets: an opening while a read is in flight.
const OPENINGS: [string, (other: string) => Promise<void>][] = [
  ["the command", () => runCommand()],
  ["a link of the first form on another Study", (other) => followLink(0, other)],
  ["a link of the second form on another Study", (other) => followLink(1, other)],
];

for (const [way, open] of OPENINGS) {
  test(`an opening by ${way} while a read is in flight reveals the panel and changes nothing else`, async (t) => {
    const [, other] = workspace(t, ["a", "b"]);
    const { calls } = heldRecorder(t);
    stub.state.pick = (items) => items[0];
    await runCommand();
    const before = [...panelOf().documents];
    const reveals = panelOf().reveals;
    await open(other);
    await settle();
    assert.equal(calls.length, 1);
    assert.deepEqual(panelOf().documents, before);
    assert.equal(panelOf().reveals, reveals + 1);
  });
}
