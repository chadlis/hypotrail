import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { readFigures, type Outcome } from "../src/bridge";
import { kept } from "./kept";
import { PATHS } from "./paths";
import { exit, recorder, type Answer } from "./recorder";

const ROOT = "/checkout";
const STUDY = "/work/runs/bike";
const FIGURES = kept("figures-chinook-spread.out");
const NOT_FOUND = kept("figures-not-found.out");

test("a figures call starts uv with the first arguments and figures --study={path} --json, in the checkout root, with the read's limits and no shell key", async (t) => {
  const calls = recorder(t, exit(0, FIGURES));
  await readFigures(ROOT, STUDY);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].program, contract.program);
  assert.deepEqual(calls[0].args, [...contract.first_arguments, "figures", `--study=${STUDY}`, "--json"]);
  assert.deepEqual(contract.figures_arguments, ["figures", "--study={path}", "--json"]);
  assert.equal(calls[0].options.cwd, ROOT);
  assert.equal(calls[0].options.timeout, contract.read_timeout_ms);
  assert.equal(calls[0].options.maxBuffer, contract.max_buffer_bytes);
  assert.equal("shell" in calls[0].options, false);
});

for (const study of PATHS) {
  test(`the Study path ${JSON.stringify(study)} reaches the figures read inside the one argument --study=, unchanged`, async (t) => {
    const calls = recorder(t, exit(0, FIGURES));
    await readFigures(ROOT, study);
    const given = calls[0].args.filter((argument) => argument.startsWith("--study="));
    assert.deepEqual(given, [`--study=${study}`]);
    assert.equal(calls[0].args.includes(study), false);
  });
}

const figures = JSON.parse(FIGURES);
const notFound = JSON.parse(NOT_FOUND);
const withUnknownKeys = {
  ...figures,
  a_key_the_client_does_not_know: 1,
  comparisons: figures.comparisons.map((entry: Record<string, unknown>) => ({ ...entry, a_key_in_an_entry: "x" })),
};

// One answer per outcome of contract.json but client_refusal, which only a write gives, and one per cause of no_answer.
const OUTCOMES: [string, Answer, Outcome["outcome"], string?][] = [
  ["success", exit(0, FIGURES), "success"],
  ["refusal", exit(2, NOT_FOUND), "refusal"],
  ["no_answer", exit(0, "not JSON"), "no_answer", "no_json"],
];
const CAUSES: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true } }],
  ["no_json", exit(0, "Study: bike\n")],
  ["inconsistent", exit(0, NOT_FOUND)],
];

test("the figures call's answers cover the outcomes of contract.json but client_refusal and each cause of no_answer", () => {
  assert.deepEqual(OUTCOMES.map(([outcome]) => outcome), contract.outcomes.filter((outcome) => outcome !== "client_refusal"));
  assert.deepEqual(CAUSES.map(([cause]) => cause), contract.no_answer_causes);
});

for (const [name, answer, outcome] of OUTCOMES) {
  test(`a figures call gives back ${name} by the bridge's rules`, async (t) => {
    recorder(t, answer);
    const given = (await readFigures(ROOT, STUDY)) as Record<string, unknown>;
    assert.equal(given.outcome, outcome);
    if (outcome === "success") assert.deepEqual(given.object, figures);
    if (outcome === "refusal") assert.deepEqual(given.error, notFound.error);
  });
}

for (const [cause, answer] of CAUSES) {
  test(`a figures call with no answer gives back its cause: ${cause}`, async (t) => {
    recorder(t, answer);
    const given = (await readFigures(ROOT, STUDY)) as Record<string, unknown>;
    assert.equal(given.outcome, "no_answer");
    assert.equal(given.cause, cause);
  });
}

test("a figures call never gives back client_refusal, whatever the Study path", async (t) => {
  recorder(t, exit(0, FIGURES));
  for (const study of ["", ...PATHS]) assert.notEqual((await readFigures(ROOT, study)).outcome, "client_refusal");
});

test("a success of the figures call keeps write_sequence and every key the CLI printed, a key the client does not know included, at the top and in an entry", async (t) => {
  recorder(t, exit(0, JSON.stringify(withUnknownKeys)));
  const given = await readFigures(ROOT, STUDY);
  assert.equal(given.outcome, "success");
  const object = (given as { object: Record<string, unknown> }).object;
  assert.equal(object.write_sequence, figures.write_sequence);
  assert.equal(object.a_key_the_client_does_not_know, 1);
  assert.equal((object.comparisons as Record<string, unknown>[])[0].a_key_in_an_entry, "x");
  assert.deepEqual(object, withUnknownKeys);
});
