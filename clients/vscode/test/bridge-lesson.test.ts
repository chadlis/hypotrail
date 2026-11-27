import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { readLesson, type Outcome } from "../src/bridge";
import { kept } from "./kept";
import { PATHS } from "./paths";
import { exit, lesson as answeringLesson, recorder, type Answer } from "./recorder";

// Each answer is marked for a lesson call: the recorder answers a lesson call apart from the others (recorder.ts).
const ROOT = "/checkout";
const STUDY = "/work/runs/bike";
const LESSON = kept("lesson.after-compare.out");
const UNSUPPORTED = kept("lesson.chinook-pending.out");

test("a lesson call starts uv with the first arguments and lesson --study={path} --json, in the checkout root, with the read's limits and no shell key", async (t) => {
  const calls = recorder(t, answeringLesson(exit(0, LESSON)));
  await readLesson(ROOT, STUDY);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].program, contract.program);
  assert.deepEqual(calls[0].args, [...contract.first_arguments, "lesson", `--study=${STUDY}`, "--json"]);
  assert.deepEqual(contract.lesson_arguments, ["lesson", "--study={path}", "--json"]);
  assert.equal(calls[0].options.cwd, ROOT);
  assert.equal(calls[0].options.timeout, contract.read_timeout_ms);
  assert.equal(calls[0].options.maxBuffer, contract.max_buffer_bytes);
  assert.equal("shell" in calls[0].options, false);
});

for (const study of PATHS) {
  test(`the Study path ${JSON.stringify(study)} reaches the lesson read inside the one argument --study=, unchanged`, async (t) => {
    const calls = recorder(t, answeringLesson(exit(0, LESSON)));
    await readLesson(ROOT, study);
    const given = calls[0].args.filter((argument) => argument.startsWith("--study="));
    assert.deepEqual(given, [`--study=${study}`]);
    assert.equal(calls[0].args.includes(study), false);
  });
}

const lesson = JSON.parse(LESSON);
const unsupported = JSON.parse(UNSUPPORTED);
const withUnknownKeys = {
  ...lesson,
  a_key_the_client_does_not_know: 1,
  cards: lesson.cards.map((card: Record<string, unknown>) => ({ ...card, a_key_in_an_entry: "x" })),
};

// One answer per outcome of contract.json but client_refusal, which only a write gives, and one per cause of no_answer.
const OUTCOMES: [string, Answer, Outcome["outcome"], string?][] = [
  ["success", exit(0, LESSON), "success"],
  ["refusal", exit(Number(kept("lesson.chinook-pending.exit")), UNSUPPORTED), "refusal"],
  ["no_answer", exit(0, "not JSON"), "no_answer", "no_json"],
];
const CAUSES: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true } }],
  ["no_json", exit(0, "Study: bike\n")],
  ["inconsistent", exit(0, UNSUPPORTED)],
];

test("the lesson call's answers cover the outcomes of contract.json but client_refusal and each cause of no_answer", () => {
  assert.deepEqual(OUTCOMES.map(([outcome]) => outcome), contract.outcomes.filter((outcome) => outcome !== "client_refusal"));
  assert.deepEqual(CAUSES.map(([cause]) => cause), contract.no_answer_causes);
});

for (const [name, answer, outcome] of OUTCOMES) {
  test(`a lesson call gives back ${name} by the bridge's rules`, async (t) => {
    recorder(t, answeringLesson(answer));
    const given = (await readLesson(ROOT, STUDY)) as Record<string, unknown>;
    assert.equal(given.outcome, outcome);
    if (outcome === "success") assert.deepEqual(given.object, lesson);
    if (outcome === "refusal") assert.deepEqual(given.error, unsupported.error);
  });
}

for (const [cause, answer] of CAUSES) {
  test(`a lesson call with no answer gives back its cause: ${cause}`, async (t) => {
    recorder(t, answeringLesson(answer));
    const given = (await readLesson(ROOT, STUDY)) as Record<string, unknown>;
    assert.equal(given.outcome, "no_answer");
    assert.equal(given.cause, cause);
  });
}

test("a lesson call never gives back client_refusal, whatever the Study path", async (t) => {
  recorder(t, answeringLesson(exit(0, LESSON)));
  for (const study of ["", ...PATHS]) assert.notEqual((await readLesson(ROOT, study)).outcome, "client_refusal");
});

test("a success of the lesson call keeps write_sequence and every key the CLI printed, a key the client does not know included, at the top and in an entry", async (t) => {
  recorder(t, answeringLesson(exit(0, JSON.stringify(withUnknownKeys))));
  const given = await readLesson(ROOT, STUDY);
  assert.equal(given.outcome, "success");
  const object = (given as { object: Record<string, unknown> }).object;
  assert.equal(object.write_sequence, lesson.write_sequence);
  assert.equal(object.a_key_the_client_does_not_know, 1);
  assert.equal((object.cards as Record<string, unknown>[])[0].a_key_in_an_entry, "x");
  assert.deepEqual(object, withUnknownKeys);
});
