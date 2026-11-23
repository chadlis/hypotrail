import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { kept } from "./kept";
import { documentFor, followLink, heldRecorder, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, workspace } from "./panel-harness";
import { exit, recorder, type Answer } from "./recorder";
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

// VA-T7 of #177: a read that fails.
const NOT_FOUND = kept("status-not-found.out");
const UUID_SHAPE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

test("a read refused shows the code and the message of the CLI's object, unchanged, the message as a marked text", async (t) => {
  const error = JSON.parse(NOT_FOUND).error;
  const { document } = await documentFor(t, exit(2, NOT_FOUND));
  const { between } = partsOf(document);
  assert.ok(between.includes(error.code), error.code);
  assert.ok(markedTexts(document).includes(error.message), error.message);
});

const CAUSES: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true } }],
  ["no_json", exit(0, "Study: bike\n")],
  ["inconsistent", exit(0, NOT_FOUND)],
];

test("the causes of a read with no answer are those of contract.json", () => {
  assert.deepEqual(CAUSES.map(([cause]) => cause), contract.no_answer_causes);
});

for (const [cause, answer] of CAUSES) {
  test(`a read with no answer shows its cause after the fixed text, and not the words of a write: ${cause}`, async (t) => {
    const { between } = partsOf((await documentFor(t, answer)).document);
    assert.match(between, new RegExp(`No answer from the CLI:\\s+${cause}(\\s|$)`));
    assert.ok(!between.includes(contract.write_no_answer_words));
  });
}

const FAILURES: [string, Answer][] = [
  ["refusal", exit(2, NOT_FOUND)],
  ["no_answer", exit(0, "not JSON")],
];

for (const [outcome, failure] of FAILURES) {
  for (const way of ["the panel opened on another Study", "Read again on the same Study"]) {
    test(`after a read that succeeded, a ${outcome} by ${way} leaves nothing of the earlier read, and Read again`, async (t) => {
      const [, other] = workspace(t, ["a", "b"]);
      recorder(t, exit(0, STATUS), failure);
      await runCommand();
      await settle();
      assert.match(partsOf(lastDocument()).between, UUID_SHAPE);
      if (way.startsWith("the panel")) await followLink(0, other);
      else panelOf().send(READ_AGAIN);
      await settle();
      const document = lastDocument();
      assert.doesNotMatch(document, UUID_SHAPE);
      assert.deepEqual([...document.matchAll(/data-message="([^"]*)"/g)].map((match) => match[1]), [contract.read_again_message]);
      assert.ok(!/<(input|select|form)[\s>]/.test(document));
      assert.ok(partsOf(document).between.includes("Read again"));
    });
  }
}
