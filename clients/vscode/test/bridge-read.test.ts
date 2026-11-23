import { test } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, readStudy, type Outcome } from "../src/bridge";
import { kept } from "./kept";
import { exit, recorder, type Answer } from "./recorder";

const ROOT = "/checkout";
const STUDY = "/work/runs/bike";
const STATUS = kept("status-success.out");
const NOT_FOUND = kept("status-not-found.out");

test("a read starts uv with the eight arguments, in the checkout root, with 30 s and 16 MiB and no shell key", async (t) => {
  const calls = recorder(t, exit(0, STATUS));
  await readStudy(ROOT, STUDY);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].program, "uv");
  assert.deepEqual(calls[0].args, ["run", "--no-sync", "python", "-m", "hypotrail", "status", `--study=${STUDY}`, "--json"]);
  assert.equal(calls[0].options.cwd, ROOT);
  assert.equal(calls[0].options.timeout, 30000);
  assert.equal(calls[0].options.maxBuffer, 16777216);
  assert.equal("shell" in calls[0].options, false);
});

test("the checkout root is two folders above the extension's folder", () => {
  const extension = "/home/owner/hypotrail/clients/vscode";
  assert.equal(checkoutRoot(extension), path.resolve(extension, "..", ".."));
});

test("the program, the arguments and the limits of a read are those of contract.json", async (t) => {
  const calls = recorder(t, exit(0, STATUS));
  await readStudy(ROOT, STUDY);
  assert.equal(calls[0].program, contract.program);
  const read = contract.read_arguments.map((argument) => argument.replace("{path}", STUDY));
  assert.deepEqual(calls[0].args, [...contract.first_arguments, ...read]);
  assert.equal(calls[0].options.timeout, contract.read_timeout_ms);
  assert.equal(calls[0].options.maxBuffer, contract.max_buffer_bytes);
});

const status = JSON.parse(STATUS);
const withUnknownKeys = { ...status, a_key_the_client_does_not_know: 1, decisions: [{ decision_id: "d-1", applies: true, a_key_in_an_entry: "x" }] };
const notFound = JSON.parse(NOT_FOUND);
const stderrLine = `${notFound.error.code} [${notFound.error.stage}]: ${notFound.error.message}\n`;

type Expected = { outcome: Outcome["outcome"]; cause?: string; object?: unknown; error?: unknown; exit_code?: number | null };

const MATRIX: [string, Answer, Expected][] = [
  ["output past the limit, also killed", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true, signal: "SIGTERM" }, stdout: '{"ok": tr' }, { outcome: "no_answer", cause: "too_large" }],
  ["killed by the time limit", { error: { code: null, killed: true, signal: "SIGTERM" } }, { outcome: "no_answer", cause: "timeout" }],
  ["the program was not found", { error: { code: "ENOENT", errno: -2, syscall: "spawn uv", path: "uv" } }, { outcome: "no_answer", cause: "not_started" }],
  ["a signal the time limit did not send, empty stdout", { error: { code: null, killed: false, signal: "SIGKILL" }, stdout: "" }, { outcome: "no_answer", cause: "inconsistent" }],
  ["exit 0, empty stdout", exit(0, ""), { outcome: "no_answer", cause: "no_json" }],
  ["exit 1, empty stdout", exit(1, ""), { outcome: "no_answer", cause: "no_json" }],
  ["exit 0, stdout not JSON", exit(0, "Study: bike\n"), { outcome: "no_answer", cause: "no_json" }],
  ["exit 0, a JSON array", exit(0, "[1, 2]"), { outcome: "no_answer", cause: "no_json" }],
  ["exit 0, ok true, empty stderr", exit(0, STATUS), { outcome: "success", object: status }],
  ["exit 0, ok true, text on stderr", exit(0, STATUS, "COMPARISON_SINGLE_FEATURE_BEATS [compare]: a warning\n"), { outcome: "success", object: status }],
  ["exit 0, ok true, unknown keys", exit(0, JSON.stringify(withUnknownKeys)), { outcome: "success", object: withUnknownKeys }],
  ["exit 2, STUDY_NOT_FOUND", exit(2, NOT_FOUND, stderrLine), { outcome: "refusal", error: notFound.error }],
  ["exit 2, ok false, an error that is not an object of two strings", exit(2, JSON.stringify({ ok: false, error: "STUDY_NOT_FOUND" })), { outcome: "refusal", exit_code: 2, error: "STUDY_NOT_FOUND" }],
  ["exit 0, ok false", exit(0, NOT_FOUND), { outcome: "no_answer", cause: "inconsistent", exit_code: 0, object: notFound }],
  ["exit 6, ok true", exit(6, STATUS), { outcome: "no_answer", cause: "inconsistent", exit_code: 6, object: status }],
];

for (const [name, answer, expected] of MATRIX) {
  test(`a read gives back ${expected.outcome}${expected.cause ? ` (${expected.cause})` : ""}: ${name}`, async (t) => {
    recorder(t, answer);
    const outcome = (await readStudy(ROOT, STUDY)) as Record<string, unknown>;
    assert.equal(outcome.outcome, expected.outcome);
    if (expected.cause !== undefined) assert.equal(outcome.cause, expected.cause);
    if (expected.object !== undefined) assert.deepEqual(outcome.object, expected.object);
    if (expected.exit_code !== undefined) assert.equal(outcome.exit_code, expected.exit_code);
    if (typeof expected.error === "object" && expected.error !== null) {
      const error = outcome.error as Record<string, unknown>;
      assert.equal(error.code, notFound.error.code);
      assert.equal(error.message, notFound.error.message);
    }
    if (expected.error !== undefined) assert.deepEqual(outcome.error, expected.error);
  });
}

test("a success keeps write_sequence and every key the CLI printed, a key the client does not know included", async (t) => {
  recorder(t, exit(0, JSON.stringify(withUnknownKeys)));
  const outcome = await readStudy(ROOT, STUDY);
  assert.equal(outcome.outcome, "success");
  const object = (outcome as { object: Record<string, unknown> }).object;
  assert.equal(object.write_sequence, status.write_sequence);
  assert.equal(object.a_key_the_client_does_not_know, 1);
  assert.equal((object.decisions as Record<string, unknown>[])[0].a_key_in_an_entry, "x");
});

const PATHS = ["/work/a study", '/work/a "quoted" study', "/work/a;b", "/work/a$(touch b)", "/work/a\nb", "-x/study"];

for (const study of PATHS) {
  test(`the Study path ${JSON.stringify(study)} reaches the CLI inside the one argument --study=, unchanged`, async (t) => {
    const calls = recorder(t, exit(0, STATUS));
    await readStudy(ROOT, study);
    const given = calls[0].args.filter((argument) => argument.startsWith("--study="));
    assert.equal(given.length, 1);
    assert.equal(given[0], `--study=${study}`);
    assert.equal(calls[0].args.includes(study), false);
  });
}

test("a second read starts the CLI again and gives back what it printed the second time", async (t) => {
  const second = { ...status, write_sequence: status.write_sequence + 2 };
  const calls = recorder(t, exit(0, STATUS), exit(0, JSON.stringify(second)));
  await readStudy(ROOT, STUDY);
  const outcome = await readStudy(ROOT, STUDY);
  assert.equal(calls.length, 2);
  assert.deepEqual(outcome, { outcome: "success", object: second });
});
