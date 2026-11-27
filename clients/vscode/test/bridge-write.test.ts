import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import * as bridge from "../src/bridge";
import { newRequestId, readStudy, recordDecision, type DecisionInput } from "../src/bridge";
import { kept } from "./kept";
import { exit, recorder, type Answer } from "./recorder";

const ROOT = "/checkout";
const STUDY = "/work/runs/bike";
const FIRST = ["run", "--no-sync", "python", "-m", "hypotrail"];

type ArgumentList = { name: string; study: string; decision: DecisionInput; arguments: string[] };
const LISTS: ArgumentList[] = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "test", "decide-arguments.json"), "utf8"));

function keptAnswer(name: string): Answer {
  return exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
}

const DECISION: DecisionInput = LISTS[1].decision;

for (const list of [...LISTS.slice(0, 2), ...LISTS.slice(3)]) {
  test(`a Decision with ${list.name} starts decide with the whole list of arguments, 120 s and no shell key`, async (t) => {
    const calls = recorder(t, keptAnswer("decide-success"));
    await recordDecision(ROOT, list.study, list.decision);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].program, "uv");
    assert.deepEqual(calls[0].args, [...FIRST, ...list.arguments]);
    assert.equal(calls[0].options.cwd, ROOT);
    assert.equal(calls[0].options.timeout, 120000);
    assert.equal(calls[0].options.maxBuffer, 16777216);
    assert.equal("shell" in calls[0].options, false);
  });
}

test("a success of decide gives back the CLI's object, decision and replayed included", async (t) => {
  recorder(t, keptAnswer("decide-success"));
  const outcome = await recordDecision(ROOT, STUDY, DECISION);
  const printed = JSON.parse(kept("decide-success.out"));
  assert.equal(outcome.outcome, "success");
  const object = (outcome as { object: Record<string, unknown> }).object;
  assert.deepEqual(Object.keys(object).sort(), Object.keys(printed).sort());
  for (const key of Object.keys(printed)) assert.deepEqual(object[key], printed[key], key);
});

// Each export of the bridge, marked true when calling it starts a process.
const EXPORTS: Record<string, boolean> = { checkoutRoot: false, readStudy: true, readFigures: true, readProfile: true, readLesson: true, recordDecision: true, newRequestId: false, missingInputs: false };

test("the bridge's exports are the test's list, both ways, and its starters start only the commands of contract.json", async (t) => {
  assert.deepEqual(Object.keys(bridge).sort(), Object.keys(EXPORTS).sort());
  const calls = recorder(t, exit(0, kept("status-success.out")));
  const exported = bridge as unknown as Record<string, (...args: unknown[]) => unknown>;
  for (const [name, starts] of Object.entries(EXPORTS)) {
    const before = calls.length;
    await exported[name](ROOT, STUDY, DECISION);
    assert.equal(calls.length - before, starts ? 1 : 0, name);
  }
  const commands = new Set(calls.map((call) => call.args[call.args.indexOf("hypotrail") + 1]));
  assert.deepEqual([...commands].sort(), [...contract.reads, ...contract.writes].sort());
});

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

test("newRequestId gives a new UUID at each call", () => {
  const first = newRequestId();
  const second = newRequestId();
  assert.match(first, UUID);
  assert.match(second, UUID);
  assert.notEqual(first, second);
});

test("a write that gets no answer is not repeated by the bridge", async (t) => {
  const calls = recorder(t, { error: { code: null, killed: true, signal: "SIGTERM" } });
  const outcome = await recordDecision(ROOT, STUDY, DECISION);
  assert.equal(outcome.outcome, "no_answer");
  assert.equal(calls.length, 1);
});

test("a repeat with the same id reaches the CLI with the same --request-id and gives back replayed as the CLI says", async (t) => {
  const calls = recorder(t, keptAnswer("decide-success"), keptAnswer("decide-replay"));
  const decision = { ...DECISION, request_id: "panel-1", read_sequence: 12 };
  await recordDecision(ROOT, STUDY, decision);
  const repeat = await recordDecision(ROOT, STUDY, decision);
  assert.equal(calls.length, 2);
  const ids = calls.map((call) => call.args.filter((argument) => argument.startsWith("--request-id=")));
  assert.deepEqual(ids, [["--request-id=panel-1"], ["--request-id=panel-1"]]);
  assert.equal(repeat.outcome, "success");
  assert.equal((repeat as { object: Record<string, unknown> }).object.replayed, true);
});

const FIELDS = ["question", "option", "author", "cited_ids", "source", "request_id", "read_sequence"];

const REFUSED: [string, Record<string, unknown>, string[]][] = [
  ["question undefined", { question: undefined }, ["question"]],
  ["question empty", { question: "" }, ["question"]],
  ["question a number", { question: 1 }, ["question"]],
  ["option undefined", { option: undefined }, ["option"]],
  ["option empty", { option: "" }, ["option"]],
  ["author undefined", { author: undefined }, ["author"]],
  ["author a number", { author: 1 }, ["author"]],
  ["cited_ids undefined", { cited_ids: undefined }, ["cited_ids"]],
  ["cited_ids a string", { cited_ids: "817d7c96" }, ["cited_ids"]],
  ["cited_ids holds an empty string", { cited_ids: ["a", ""] }, ["cited_ids"]],
  ["cited_ids holds undefined", { cited_ids: ["a", undefined] }, ["cited_ids"]],
  ["source null", { source: null }, ["source"]],
  ["source a number", { source: 1 }, ["source"]],
  ["request_id undefined", { request_id: undefined }, ["request_id"]],
  ["request_id empty", { request_id: "" }, ["request_id"]],
  ["request_id a number", { request_id: 42 }, ["request_id"]],
  ["read_sequence undefined", { read_sequence: undefined }, ["read_sequence"]],
  ["read_sequence -1", { read_sequence: -1 }, ["read_sequence"]],
  ["read_sequence 1.5", { read_sequence: 1.5 }, ["read_sequence"]],
  ["read_sequence the string 12", { read_sequence: "12" }, ["read_sequence"]],
  ["read_sequence NaN", { read_sequence: NaN }, ["read_sequence"]],
  ["read_sequence 2 to the power 53", { read_sequence: 2 ** 53 }, ["read_sequence"]],
  ["all seven", { question: "", option: undefined, author: 1, cited_ids: "a", source: null, request_id: "", read_sequence: -1 }, FIELDS],
];

for (const [name, change, missing] of REFUSED) {
  test(`a write whose ${name} starts no process and is a client_refusal`, async (t) => {
    const calls = recorder(t, keptAnswer("decide-success"));
    const outcome = await recordDecision(ROOT, STUDY, { ...DECISION, source: "a source", ...change } as unknown as DecisionInput);
    assert.equal(calls.length, 0);
    assert.deepEqual(outcome, { outcome: "client_refusal", missing });
  });
}

test("the fields of a client_refusal are those of contract.json, in its order", async (t) => {
  recorder(t);
  const none = { question: 0, option: 0, author: 0, cited_ids: 0, source: 0, question_id: 0, option_id: 0, words: 0, channel: 0, by: 0, request_id: 0, read_sequence: "x" };
  assert.deepEqual(await recordDecision(ROOT, STUDY, none as unknown as DecisionInput), { outcome: "client_refusal", missing: contract.client_refusal_fields });
});

test("a write with no id after a write that had one is still a client_refusal: the bridge holds no id", async (t) => {
  const calls = recorder(t, keptAnswer("decide-success"));
  await recordDecision(ROOT, STUDY, { ...DECISION, request_id: "panel-1" });
  const { request_id, ...withoutId } = { ...DECISION, request_id: "panel-1" };
  void request_id;
  assert.deepEqual(await recordDecision(ROOT, STUDY, withoutId as DecisionInput), { outcome: "client_refusal", missing: ["request_id"] });
  assert.equal(calls.length, 1);
});

const STARTED: [string, Record<string, unknown>, Answer | undefined, (args: string[], outcome: Record<string, unknown>) => void][] = [
  ["the question one space", { question: " " }, undefined, (args) => assert.ok(args.includes("--question= "))],
  ["the author nobody", { author: "nobody" }, keptAnswer("decide-invalid-arguments"), (_, outcome) => assert.equal(outcome.outcome, "refusal")],
  ["an empty list of cited ids", { cited_ids: [] }, keptAnswer("decide-invalid-arguments"), (args, outcome) => {
    assert.equal(args.some((argument) => argument.startsWith("--artifact")), false);
    assert.equal(outcome.outcome, "refusal");
  }],
  ["no source", { source: undefined }, undefined, (args) => assert.equal(args.some((argument) => argument.startsWith("--source")), false)],
  ["the source empty", { source: "" }, undefined, (args) => assert.ok(args.includes("--source="))],
  ["the id a and the Write sequence 0", { request_id: "a", read_sequence: 0 }, undefined, (args) => {
    assert.ok(args.includes("--request-id=a"));
    assert.ok(args.includes("--read-sequence=0"));
  }],
];

for (const [name, change, answer, check] of STARTED) {
  test(`a write with ${name} starts one process`, async (t) => {
    const calls = recorder(t, answer ?? keptAnswer("decide-success"));
    const outcome = await recordDecision(ROOT, STUDY, { ...DECISION, ...change } as DecisionInput);
    assert.equal(calls.length, 1);
    check(calls[0].args, outcome as unknown as Record<string, unknown>);
  });
}

test("the Write sequence a write passes is the one the caller read", async (t) => {
  const status = JSON.parse(kept("status-success.out"));
  assert.equal(status.write_sequence, 12);
  const calls = recorder(t, exit(0, kept("status-success.out")), keptAnswer("decide-success"));
  const read = await readStudy(ROOT, STUDY);
  const writeSequence = (read as unknown as { object: { write_sequence: number } }).object.write_sequence;
  await recordDecision(ROOT, STUDY, { ...DECISION, read_sequence: writeSequence });
  assert.equal(calls.length, 2);
  assert.ok(calls[1].args.includes("--read-sequence=12"));
});

const REFUSALS = ["decide-study-changed", "decide-write-sequence-ahead", "decide-request-conflict", "decide-invalid-arguments", "decide-study-not-found"];

for (const name of REFUSALS) {
  test(`the refusal ${name} is given back as the CLI printed it`, async (t) => {
    recorder(t, keptAnswer(name));
    const outcome = await recordDecision(ROOT, STUDY, DECISION);
    const printed = JSON.parse(kept(`${name}.out`)).error;
    assert.equal(outcome.outcome, "refusal");
    const error = (outcome as { error: Record<string, unknown> }).error;
    assert.equal(error.code, printed.code);
    assert.equal(error.message, printed.message);
    assert.deepEqual(Object.keys(error).sort(), Object.keys(printed).sort());
    for (const key of Object.keys(printed)) assert.deepEqual(error[key], printed[key], key);
  });
}

const NO_ANSWERS: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true, signal: "SIGTERM" } }],
  ["no_json", exit(0, "")],
  ["inconsistent", exit(0, kept("decide-study-changed.out"))],
];

for (const [cause, answer] of NO_ANSWERS) {
  test(`a write with no answer (${cause}) is worded outcome unknown, and a read is not`, async (t) => {
    recorder(t, answer, answer);
    const write = await recordDecision(ROOT, STUDY, DECISION);
    const read = await readStudy(ROOT, STUDY);
    assert.equal(write.outcome, "no_answer");
    assert.equal((write as { cause: string }).cause, cause);
    assert.ok(JSON.stringify(write).includes("outcome unknown"));
    assert.equal(contract.write_no_answer_words, "outcome unknown");
    assert.equal(read.outcome, "no_answer");
    assert.equal(JSON.stringify(read).includes("outcome unknown"), false);
  });
}

const TEXTS = ["a b", 'a "b"', "a;b", "a$(b)", "a\nb", "-x", "--study"];

for (const field of ["question", "option", "source"] as const) {
  for (const text of TEXTS) {
    test(`the ${field} ${JSON.stringify(text)} reaches the CLI inside its one argument, unchanged`, async (t) => {
      const calls = recorder(t, keptAnswer("decide-success"));
      await recordDecision(ROOT, STUDY, { ...DECISION, [field]: text });
      assert.equal(calls.length, 1);
      const given = calls[0].args.filter((argument) => argument.startsWith(`--${field}=`));
      assert.deepEqual(given, [`--${field}=${text}`]);
    });
  }
}

test("the options decide is given are those of contract.json, in its order, the optional one only when given", async (t) => {
  const calls = recorder(t, keptAnswer("decide-success"), keptAnswer("decide-success"), keptAnswer("decide-success"));
  await recordDecision(ROOT, STUDY, LISTS[0].decision);
  await recordDecision(ROOT, STUDY, LISTS[1].decision);
  await recordDecision(ROOT, STUDY, { ...LISTS[3].decision, source: "the owner, in chat" });
  const names = (args: string[]) => [...new Set(args.slice(FIRST.length + 1).map((argument) => argument.split("=")[0]))];
  const without = (absent: string[]) => contract.decide_options.filter((option) => !absent.includes(option));
  assert.deepEqual(names(calls[0].args), without(contract.decide_optional_options.filter((option) => option !== "--source")));
  assert.deepEqual(names(calls[1].args), without(contract.decide_optional_options));
  assert.deepEqual(names(calls[2].args), contract.decide_options);
  assert.equal(calls[0].args[FIRST.length], contract.writes[0]);
  assert.equal(calls[0].options.timeout, contract.write_timeout_ms);
});

// Each input of the words, the ids and the label that the bridge refuses, with the field the refusal names: no process starts.
const LIMIT = contract.words_limit_characters;
const WORDS_REFUSED: [string, Partial<Record<keyof DecisionInput, unknown>>, string][] = [
  ["words that is a text, not a list", { words: "keep it" }, "words"],
  ["words that is an empty list", { words: [] }, "words"],
  ["words that holds an empty text", { words: ["keep it", ""] }, "words"],
  ["words that holds a number", { words: ["keep it", 3] }, "words"],
  [`words of ${LIMIT + 1} characters in total, in two texts`, { words: ["a".repeat(LIMIT), "b"] }, "words"],
  [`words of ${LIMIT + 1} characters in total, counted as code points`, { words: ["\u00e9".repeat(LIMIT - 1), "\u{1F600}\u{1F600}"] }, "words"],
  ["a question_id that is not a text", { question_id: 1 }, "question_id"],
  ["an option_id that is not a text", { option_id: ["keep_control"] }, "option_id"],
  ["a channel that is not a text", { channel: true }, "channel"],
  ["a by that is not a text", { by: { name: "owner" } }, "by"],
];

for (const [name, change, field] of WORDS_REFUSED) {
  test(`${name} is a client_refusal that names ${field}, and no process starts`, async (t) => {
    const calls = recorder(t, keptAnswer("decide-success"));
    const outcome = await recordDecision(ROOT, STUDY, { ...LISTS[3].decision, ...change } as DecisionInput);
    assert.deepEqual(outcome, { outcome: "client_refusal", missing: [field] });
    assert.equal(calls.length, 0);
  });
}

test(`words of exactly ${LIMIT} characters in total start decide, with one --words= per text`, async (t) => {
  const calls = recorder(t, keptAnswer("decide-success"));
  const words = ["\u00e9".repeat(LIMIT - 2), "\u{1F600}\u{1F600}"];
  await recordDecision(ROOT, STUDY, { ...LISTS[3].decision, words });
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].args.filter((argument) => argument.startsWith("--words=")), words.map((text) => `--words=${text}`));
});
