import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import * as bridge from "../src/bridge";
import { HANDLERS } from "../src/panel";
import { kept } from "./kept";
import { elementOf, followLink, heldRecorder, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, workspace } from "./panel-harness";
import { exit, recorder, type Answer, type RecordedCall } from "./recorder";
import * as stub from "./vscode-stub";

type Entry = Record<string, any>;

const [READ_AGAIN, RECORD, REPEAT] = contract.messages;
const RECORDED = "The Decision was recorded.";
const RECORDING = "Recording the Decision.";
const MISSING = "Nothing was sent. Missing:";
const NOTICE = '<div data-element="notice">';
const UUID_SHAPE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;

// The pairs of kept reads of a Decision: the read before it, then the read after it.
const PAIRS: [string, string][] = [
  ["status-success", "status-decided"],
  ["status-chinook-pending", "status-chinook-decided"],
];
const FIXTURE_READS = PAIRS.flat();
const KEPT_WRITES = ["decide-success", "decide-replay", "decide-study-changed", "decide-write-sequence-ahead", "decide-request-conflict", "decide-invalid-arguments", "decide-study-not-found"];
const REFUSED_WRITES = KEPT_WRITES.filter((name) => JSON.parse(kept(`${name}.out`)).ok === false);
const NOT_FOUND = exit(Number(kept("status-not-found.exit")), kept("status-not-found.out"), kept("status-not-found.err"));

// The answers of a call that got no usable answer, one for each cause of contract.json.
const NO_ANSWERS: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true } }],
  ["no_json", exit(0, "Decision recorded\n")],
  ["inconsistent", exit(0, kept("decide-study-changed.out"))],
];

function keptAnswer(name: string): Answer {
  return exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
}

// Each request id the panel asks the bridge for, in order.
function madeIds(t: TestContext): string[] {
  const made: string[] = [];
  const make = bridge.newRequestId;
  t.mock.method(bridge, "newRequestId", () => {
    const id = make();
    made.push(id);
    return id;
  });
  return made;
}

const decideCalls = (calls: RecordedCall[]): RecordedCall[] => calls.filter((call) => call.args.includes("decide"));
const commandsOf = (calls: RecordedCall[]): string[] => calls.map((call) => call.args[contract.first_arguments.length]);
const valueOf = (call: RecordedCall, option: string): string | undefined => call.args.find((argument) => argument.startsWith(`${option}=`))?.slice(option.length + 1);
const record = (pending: number, option: number): void => panelOf().send({ message: RECORD, pending, option });
const send = (message: string): void => panelOf().send({ message });
const notice = (document: string): string => partsOf(elementOf(document, NOTICE) ?? "").between;
const controls = (document: string): string[] => [...document.matchAll(/data-message="([^"]*)"/g)].map((match) => match[1]);

// The list of arguments the panel passes to `decide` for one option of one pending decision.
function expectedArguments(study: string, pending: Entry, option: Entry, requestId: string, sequence: number): string[] {
  return [
    ...contract.first_arguments,
    "decide",
    `--study=${study}`,
    `--question=${pending.question.text}`,
    `--option=${option.text}`,
    `--author=${contract.decide_author}`,
    `--artifact=${pending.comparison_id}`,
    `--request-id=${requestId}`,
    `--read-sequence=${sequence}`,
    "--json",
  ];
}

// The panel opened by the command on one Study, its first read answered with `object`.
async function opened(t: TestContext, object: Entry, ...after: Answer[]): Promise<{ study: string; calls: RecordedCall[]; made: string[] }> {
  const [study] = workspace(t, ["bike"]);
  const made = madeIds(t);
  const calls = recorder(t, success(object), ...after);
  await runCommand();
  await settle();
  return { study, calls, made };
}

test("the handlers of the panel's messages are the entries of messages of contract.json, both ways", () => {
  assert.deepEqual(Object.keys(HANDLERS).sort(), [...contract.messages].sort());
});

// Two actions record a Decision through decide.
for (const name of FIXTURE_READS) {
  const object = keptObject(name);
  object.pending_decisions.forEach((pending: Entry, p: number) => {
    pending.options.forEach((option: Entry, o: number) => {
      test(`the second action on option ${o} of pending decision ${p} starts decide once, with the arguments of that option, one cited id and no source: ${name}`, async (t) => {
        const { study, calls, made } = await opened(t, object, keptAnswer("decide-success"), success(object));
        record(p, o);
        await settle();
        const decides = decideCalls(calls);
        assert.equal(decides.length, 1);
        assert.equal(made.length, 1);
        assert.deepEqual(decides[0].args, expectedArguments(study, pending, option, made[0], object.write_sequence));
        assert.equal(decides[0].args.filter((argument) => argument.startsWith("--artifact=")).length, 1);
        assert.equal(decides[0].args.filter((argument) => argument.startsWith("--source=")).length, 0);
      });
    });
  });
}

for (const [message, case_] of [
  [{ message: RECORD, pending: 0 }, "a message of the second action with no option index"],
  [{ message: RECORD, pending: 0, option: 3 }, "a message of the second action with an option index the read does not hold"],
] as const) {
  test(`${case_} starts no decide call`, async (t) => {
    const { calls } = await opened(t, keptObject("status-success"), keptAnswer("decide-success"));
    panelOf().send(message);
    await settle();
    assert.deepEqual(decideCalls(calls), []);
  });
}

for (const name of FIXTURE_READS.filter((each) => keptObject(each).pending_decisions.length > 0)) {
  test(`the document as built holds a radio input for each option, none selected, and each control of the second action disabled: ${name}`, async (t) => {
    const object = keptObject(name);
    await opened(t, object);
    const { tags } = partsOf(lastDocument());
    const radios = tags.filter((tag) => tag.startsWith("<input "));
    const options = object.pending_decisions.reduce((count: number, pending: Entry) => count + pending.options.length, 0);
    assert.equal(radios.length, options);
    assert.ok(radios.every((tag) => / type="radio"/.test(tag) && !/\schecked(\s|>|=)/.test(tag)), radios.join("\n"));
    assert.ok(!/<form[\s>]/.test(lastDocument()));
    const records = tags.filter((tag) => tag.includes(`data-message="${RECORD}"`));
    assert.equal(records.length, object.pending_decisions.length);
    assert.ok(records.every((tag) => /\sdisabled(\s|>)/.test(tag)), records.join("\n"));
  });
}

{
  const changed = keptObject("status-success");
  changed.pending_decisions[0].question.text = "-zq the replaced question";
  changed.pending_decisions[0].options.forEach((option: Entry, o: number) => (option.text = `--zq replaced option ${o}`));
  changed.pending_decisions[0].options.forEach((option: Entry, o: number) => {
    test(`the question and option passed are the texts of the read, as replaced in the test: option ${o}`, async (t) => {
      const { calls } = await opened(t, changed, keptAnswer("decide-success"));
      record(0, o);
      await settle();
      const [decide] = decideCalls(calls);
      assert.equal(valueOf(decide, "--question"), "-zq the replaced question");
      assert.equal(valueOf(decide, "--option"), `--zq replaced option ${o}`);
    });
  });
}

// The Write sequence passed is the one read.
for (const [name, sequence] of [
  ["status-success", undefined],
  ["status-success with another write_sequence", 4242],
] as const) {
  test(`the read sequence passed is the write_sequence of the read the document was made from: ${name}`, async (t) => {
    const object = keptObject("status-success");
    if (sequence !== undefined) object.write_sequence = sequence;
    const { calls } = await opened(t, object, keptAnswer("decide-success"));
    record(0, 0);
    await settle();
    assert.equal(valueOf(decideCalls(calls)[0], "--read-sequence"), String(object.write_sequence));
  });
}

// After a write the CLI answered.
for (const name of KEPT_WRITES) {
  test(`after a write answered by ${name}, one status call follows the one decide call, and no second decide`, async (t) => {
    const { calls } = await opened(t, keptObject("status-success"), keptAnswer(name), success(keptObject("status-decided")));
    record(0, 0);
    await settle();
    await settle();
    assert.deepEqual(commandsOf(calls), ["status", "decide", "status"]);
  });
}

for (const [before, after] of PAIRS) {
  test(`after a success, the document shows the Decision of the read that follows with its applies, and no question: ${before} then ${after}`, async (t) => {
    const read = keptObject(after);
    await opened(t, keptObject(before), keptAnswer("decide-success"), success(read));
    record(0, 0);
    await settle();
    const document = lastDocument();
    const decision = read.decisions[read.decisions.length - 1];
    assert.ok(partsOf(document).between.includes(decision.decision_id), "the decision_id of the read that follows");
    const part = elementOf(document, '<section data-part="decision"')!;
    assert.match(partsOf(part).between, new RegExp(`applies\\s+${decision.applies}(\\s|$)`));
    assert.ok(!markedTexts(document).includes(keptObject(before).pending_decisions[0].question.text));
  });
}

test("after a success, a read whose Decision does not apply and whose pending_decisions still names the Comparison shows applies false and the question", async (t) => {
  const read = keptObject("status-decided");
  const comparison = read.comparisons[0];
  assert.deepEqual(read.decisions[0].cited_ids, [comparison.comparison_id]);
  read.decisions[0].applies = false;
  read.pending_decisions = keptObject("status-success").pending_decisions.map((pending: Entry) => ({
    ...pending,
    comparison_id: comparison.comparison_id,
    control_assessment_id: comparison.roles.control_assessment_id,
    candidate_assessment_id: comparison.roles.candidate_assessment_id,
  }));
  await opened(t, keptObject("status-success"), keptAnswer("decide-success"), success(read));
  record(0, 0);
  await settle();
  const document = lastDocument();
  assert.match(partsOf(elementOf(document, '<section data-part="decision"')!).between, /applies\s+false(\s|$)/);
  assert.ok(markedTexts(document).includes(read.pending_decisions[0].question.text));
});

for (const name of REFUSED_WRITES) {
  test(`after a refusal, the notice holds the code and the message of the CLI's object unchanged, before the first question: ${name}`, async (t) => {
    const error = JSON.parse(kept(`${name}.out`)).error;
    await opened(t, keptObject("status-success"), keptAnswer(name), success(keptObject("status-success")));
    record(0, 0);
    await settle();
    const document = lastDocument();
    const element = elementOf(document, NOTICE);
    assert.ok(element, "a notice");
    assert.ok(partsOf(element).between.includes(error.code), error.code);
    assert.ok(markedTexts(element).includes(error.message), error.message);
    const question = keptObject("status-success").pending_decisions[0].question.text;
    assert.ok(document.indexOf(NOTICE) < document.indexOf(question));
  });
}

test("after a refusal whose following read fails, the document holds the code of the write's refusal and the code of the read's", async (t) => {
  await opened(t, keptObject("status-success"), keptAnswer("decide-study-changed"), NOT_FOUND);
  record(0, 0);
  await settle();
  const { between } = partsOf(lastDocument());
  assert.ok(between.includes(JSON.parse(kept("decide-study-changed.out")).error.code));
  assert.ok(between.includes(JSON.parse(kept("status-not-found.out")).error.code));
});

for (const [outcome, write] of [
  ["success", "decide-success"],
  ["refusal", "decide-study-changed"],
] as const) {
  test(`the write after a write answered by a ${outcome} carries a new request id`, async (t) => {
    const { calls } = await opened(t, keptObject("status-success"), keptAnswer(write), success(keptObject("status-success")), keptAnswer("decide-success"));
    record(0, 0);
    await settle();
    record(0, 1);
    await settle();
    const ids = decideCalls(calls).map((call) => valueOf(call, "--request-id"));
    assert.equal(ids.length, 2);
    assert.notEqual(ids[1], ids[0]);
  });
}

// A success whose following read fails.
const NEW_ID = "1234abcd-0000-4000-8000-00000000beef";

function successWith(name: string, id: string): Answer {
  const object = JSON.parse(kept(`${name}.out`));
  object.decision.decision_id = id;
  return exit(0, JSON.stringify(object));
}

for (const write of ["decide-success", "decide-replay"]) {
  for (const [failure, answer] of [
    ["refusal", NOT_FOUND],
    ["no_answer", exit(0, "not JSON")],
  ] as const) {
    test(`after ${write} and a read that ends in ${failure}, the document holds the line, the id of the answer, the failure and Read again, and no control that records`, async (t) => {
      await opened(t, keptObject("status-success"), successWith(write, NEW_ID), answer);
      record(0, 0);
      await settle();
      const document = lastDocument();
      const { between } = partsOf(document);
      assert.match(notice(document), new RegExp(`${RECORDED.replace(".", "\\.")}\\s+${NEW_ID}(\\s|$)`));
      assert.ok(between.includes(failure === "refusal" ? "STUDY_NOT_FOUND" : "No answer from the CLI:"));
      assert.deepEqual(controls(document), [READ_AGAIN]);
      assert.ok(!/<input[\s>]/.test(document));
      assert.deepEqual([...document.matchAll(UUID_SHAPE)].map((match) => match[0]), [NEW_ID]);
    });
  }
}

test("the documents after decide-success and after decide-replay are equal once the nonce and the decision_id are fixed texts", async (t) => {
  const documents: string[] = [];
  for (const [write, id] of [
    ["decide-success", NEW_ID],
    ["decide-replay", "99999999-0000-4000-8000-000000000000"],
  ]) {
    await opened(t, keptObject("status-success"), successWith(write, id), NOT_FOUND);
    record(0, 0);
    await settle();
    documents.push(lastDocument().replace(/[0-9a-f]{32}/g, "NONCE").replace(UUID_SHAPE, "ID"));
  }
  assert.equal(documents[1], documents[0]);
});

// A write the CLI did not answer.
for (const [cause, answer] of NO_ANSWERS) {
  test(`after a write with no answer (${cause}) the notice holds the words of a write, Repeat stands beside Read again, no read follows, and only Repeat sends the same call`, async (t) => {
    const { calls } = await opened(t, keptObject("status-success"), answer, keptAnswer("decide-success"), success(keptObject("status-decided")));
    record(0, 0);
    await settle();
    const document = lastDocument();
    assert.ok(notice(document).includes(contract.write_no_answer_words));
    assert.deepEqual(controls(document).filter((name) => name !== RECORD), [READ_AGAIN, REPEAT]);
    const radios = partsOf(document).tags.filter((tag) => tag.startsWith("<input "));
    assert.ok(radios.length > 0 && radios.every((tag) => /\sdisabled(\s|>)/.test(tag)), "no option can be selected while an id is held");
    assert.deepEqual(commandsOf(calls), ["status", "decide"]);
    record(0, 1);
    await settle();
    assert.deepEqual(commandsOf(calls), ["status", "decide"]);
    send(REPEAT);
    await settle();
    const decides = decideCalls(calls);
    assert.equal(decides.length, 2);
    assert.deepEqual(decides[1].args, decides[0].args);
  });
}

test("while a request id is held, the documents of a read that succeeds and of a read that fails hold the words and Repeat, and Repeat sends the first id", async (t) => {
  const { calls } = await opened(t, keptObject("status-success"), NO_ANSWERS[1][1], success(keptObject("status-success")), NOT_FOUND, keptAnswer("decide-success"));
  record(0, 0);
  await settle();
  for (const read of ["a read that succeeds", "a read that fails"]) {
    send(READ_AGAIN);
    await settle();
    const document = lastDocument();
    assert.ok(notice(document).includes(contract.write_no_answer_words), read);
    assert.ok(controls(document).includes(REPEAT), read);
    assert.ok(partsOf(document).between.includes("Repeat"), read);
  }
  send(REPEAT);
  await settle();
  const decides = decideCalls(calls);
  assert.equal(decides.length, 2);
  assert.equal(valueOf(decides[1], "--request-id"), valueOf(decides[0], "--request-id"));
});

test("a repeat passes the read sequence of the call it repeats, after a read whose write_sequence is another", async (t) => {
  const later = keptObject("status-success");
  later.write_sequence = 4242;
  const { calls } = await opened(t, keptObject("status-success"), NO_ANSWERS[1][1], success(later), keptAnswer("decide-success"));
  record(0, 0);
  await settle();
  send(READ_AGAIN);
  await settle();
  send(REPEAT);
  await settle();
  const decides = decideCalls(calls);
  assert.equal(valueOf(decides[1], "--read-sequence"), String(keptObject("status-success").write_sequence));
});

for (const [case_, answer] of [
  ["the repeat's success", keptAnswer("decide-success")],
  ["the repeat's refusal", keptAnswer("decide-study-changed")],
] as const) {
  test(`the first write after ${case_} carries another request id`, async (t) => {
    const { calls } = await opened(t, keptObject("status-success"), NO_ANSWERS[1][1], answer, success(keptObject("status-success")), keptAnswer("decide-success"));
    record(0, 0);
    await settle();
    send(REPEAT);
    await settle();
    record(0, 1);
    await settle();
    const ids = decideCalls(calls).map((call) => valueOf(call, "--request-id"));
    assert.equal(ids.length, 3);
    assert.equal(ids[1], ids[0]);
    assert.notEqual(ids[2], ids[0]);
  });
}

test("the first write after the panel is closed and opened again carries another request id", async (t) => {
  const { calls } = await opened(t, keptObject("status-success"), NO_ANSWERS[1][1], success(keptObject("status-success")), keptAnswer("decide-success"));
  record(0, 0);
  await settle();
  panelOf().dispose();
  await runCommand();
  await settle();
  record(0, 0);
  await settle();
  const ids = decideCalls(calls).map((call) => valueOf(call, "--request-id"));
  assert.equal(ids.length, 2);
  assert.notEqual(ids[1], ids[0]);
});

test("a write the bridge refuses starts nothing, its notice names the missing inputs after the fixed text, no read follows, and the next write carries a new id", async (t) => {
  const changed = keptObject("status-success");
  changed.pending_decisions[0].question.text = "";
  const { calls, made } = await opened(t, changed, success(keptObject("status-success")), keptAnswer("decide-success"));
  record(0, 0);
  await settle();
  assert.deepEqual(commandsOf(calls), ["status"]);
  const document = lastDocument();
  assert.match(notice(document), new RegExp(`${MISSING}\\s+question(\\s|$)`));
  assert.ok(!controls(document).includes(REPEAT));
  send(READ_AGAIN);
  await settle();
  record(0, 0);
  await settle();
  const decides = decideCalls(calls);
  assert.equal(decides.length, 1);
  assert.equal(made.length, 2);
  assert.equal(valueOf(decides[0], "--request-id"), made[1]);
  assert.notEqual(made[1], made[0]);
});

test("two messages of the second action before the answer give one decide call, and the document assigned meanwhile holds the line of a write in flight", async (t) => {
  workspace(t, ["bike"]);
  const { calls, answer } = heldRecorder(t);
  await runCommand();
  answer(success(keptObject("status-success")));
  await settle();
  record(0, 0);
  record(0, 1);
  await settle();
  assert.deepEqual(commandsOf(calls), ["status", "decide"]);
  assert.ok(notice(lastDocument()).includes(RECORDING));
  assert.ok(!/<input [^>]*data-option(?![^>]*\sdisabled)[^>]*>/.test(lastDocument()), "no radio input can be selected");
});

// An opening while a write is in flight or a request id is held.
const OPENINGS: [string, (other: string) => Promise<void>][] = [
  ["the command", () => runCommand()],
  ...contract.link_forms.map((_, form): [string, (other: string) => Promise<void>] => [`a link of form ${form + 1} on another Study`, (other) => followLink(form, other)]),
];

for (const [way, open] of OPENINGS) {
  test(`an opening by ${way} while a write is in flight reveals the panel and changes nothing else`, async (t) => {
    const [, other] = workspace(t, ["a", "b"]);
    const { calls, answer } = heldRecorder(t);
    await runCommand();
    answer(success(keptObject("status-success")));
    await settle();
    record(0, 0);
    await settle();
    const before = { calls: calls.length, documents: [...panelOf().documents], reveals: panelOf().reveals };
    await open(other);
    await settle();
    assert.equal(calls.length, before.calls);
    assert.deepEqual(panelOf().documents, before.documents);
    assert.equal(panelOf().reveals, before.reveals + 1);
  });

  test(`an opening by ${way} while a request id is held reveals the panel and changes nothing else, and Repeat sends the held call`, async (t) => {
    const [other] = workspace(t, ["a", "b"]);
    stub.state.pick = (items) => items[1];
    const calls = recorder(t, success(keptObject("status-success")), NO_ANSWERS[1][1], keptAnswer("decide-success"), success(keptObject("status-decided")));
    await runCommand();
    await settle();
    stub.state.pick = (items) => items[0];
    record(0, 0);
    await settle();
    const before = { calls: calls.length, document: lastDocument(), reveals: panelOf().reveals };
    await open(other);
    await settle();
    assert.equal(calls.length, before.calls);
    assert.equal(lastDocument(), before.document);
    assert.equal(panelOf().reveals, before.reveals + 1);
    send(REPEAT);
    await settle();
    const decides = decideCalls(calls);
    assert.equal(decides.length, 2);
    assert.deepEqual(decides[1].args, decides[0].args);
  });
}

test("while a repeat is in flight the request id is still held: the document holds the line of a write in flight, the words and Repeat", async (t) => {
  workspace(t, ["bike"]);
  const { calls, answer } = heldRecorder(t);
  await runCommand();
  answer(success(keptObject("status-success")));
  await settle();
  record(0, 0);
  answer(NO_ANSWERS[1][1]);
  await settle();
  send(REPEAT);
  await settle();
  assert.deepEqual(commandsOf(calls), ["status", "decide", "decide"]);
  const document = lastDocument();
  assert.ok(notice(document).includes(RECORDING));
  assert.ok(notice(document).includes(contract.write_no_answer_words));
  assert.ok(controls(document).includes(REPEAT));
});
