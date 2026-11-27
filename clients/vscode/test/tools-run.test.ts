import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import childProcess = require("node:child_process");
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { RUN_COMMANDS, RUN_REFUSALS } from "../src/tools";
import { CHECKOUT, FIRST, invoke, MANIFEST, toolOf, workspace } from "./tools-harness";
import type { Answer, RecordedCall } from "./recorder";
import { exit } from "./recorder";

const RUN_TOOL = "hypotrail_run";
const FOLDER = path.join(__dirname, "..", "..");
const CONTRACT = fs.readFileSync(path.join(FOLDER, "run-tool.contract.md"), "utf8");

type Case = { id: string; state: "dev" | "public_check"; input: Record<string, unknown>; expected: string; argv?: string[]; cli?: string };
const CASES: Case[] = fs
  .readFileSync(path.join(FOLDER, "test", "run-tool-corpus", "cases.jsonl"), "utf8")
  .split("\n")
  .filter((line) => line !== "")
  .map((line) => JSON.parse(line));

// The values the tests give the corpus's placeholders, beside the Study folder and the Write sequence.
const IDS: Record<string, string> = {
  OBS_SEASONAL: "0b5e0000-0000-4000-8000-000000000001",
  OBS_RIDGE: "0b5e0000-0000-4000-8000-000000000002",
  OBS_PUBLIC: "0b5e0000-0000-4000-8000-000000000003",
  A_SEASONAL: "a5e00000-0000-4000-8000-000000000001",
  A_RIDGE: "a5e00000-0000-4000-8000-000000000002",
  A_PUBLIC: "a5e00000-0000-4000-8000-000000000003",
  REFS: "references-7520d791bfe31924",
  OUT_DIR: "/work/out",
};
const WRITE_SEQUENCE = 12;
const PUBLIC_IDS = [IDS.OBS_PUBLIC, IDS.A_PUBLIC];

// The part of a `status --json` read the run tool reads: the Attempts with their Observation sets and Partitions, and the Assessments.
function statusOf(state: Case["state"]): Record<string, unknown> {
  const attempts = [
    { attempt_id: "a77e0000-0000-4000-8000-000000000001", observation_set_id: IDS.OBS_SEASONAL, partition: "dev" },
    { attempt_id: "a77e0000-0000-4000-8000-000000000002", observation_set_id: IDS.OBS_RIDGE, partition: "dev" },
    { attempt_id: "a77e0000-0000-4000-8000-000000000003", observation_set_id: null, partition: null },
  ];
  const assessments = [
    { assessment_id: IDS.A_SEASONAL, observation_set_id: IDS.OBS_SEASONAL },
    { assessment_id: IDS.A_RIDGE, observation_set_id: IDS.OBS_RIDGE },
  ];
  if (state === "public_check") {
    attempts.push({ attempt_id: "a77e0000-0000-4000-8000-000000000004", observation_set_id: IDS.OBS_PUBLIC, partition: "public_check" });
    assessments.push({ assessment_id: IDS.A_PUBLIC, observation_set_id: IDS.OBS_PUBLIC });
  }
  return { ok: true, write_sequence: WRITE_SEQUENCE, attempts, assessments };
}

function filled(value: unknown, study: string): unknown {
  if (value === "{READ_SEQUENCE}") return WRITE_SEQUENCE;
  if (typeof value === "string") {
    return value
      .replaceAll("{STUDY}", study)
      .replaceAll("{READ_SEQUENCE}", String(WRITE_SEQUENCE))
      .replaceAll("{OBS_PUBLIC_UPPER}", IDS.OBS_PUBLIC.toUpperCase())
      .replace(/\{([A-Z_]+)\}/g, (whole, name: string) => IDS[name] ?? whole);
  }
  if (Array.isArray(value)) return value.map((each) => filled(each, study));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, each]) => [key, filled(each, study)]));
  return value;
}

// A test double for `execFile` that answers a status read with the state's read and any other command with `command`.
function routed(t: TestContext, status: Answer, command: Answer = exit(0, JSON.stringify({ ok: true, written: "records" }))): RecordedCall[] {
  const recorded: RecordedCall[] = [];
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    recorded.push({ program, args: [...args], options: { ...options } });
    const answer = args[FIRST.length] === "status" ? status : command;
    const error = answer.error ? Object.assign(new Error("recorded"), answer.error) : null;
    setImmediate(() => callback(error, answer.stdout ?? "", answer.stderr ?? ""));
    return {};
  });
  return recorded;
}

const isRead = (study: string) => (call: RecordedCall) => JSON.stringify(call.args) === JSON.stringify([...FIRST, "status", `--study=${study}`, "--json"]);

// An argument with case, white space, "-" and "_" taken away: the form in which neither llm_live nor public_check may reach the CLI.
const bare = (text: string) => text.toLowerCase().replace(/[\s_-]/g, "");

// What no started command may hold, whatever the input: an act writer as its command, llm_live or public_check in any spelling, or the id of
// a public_check Observation set or Assessment.
function reachesNothingForbidden(call: RecordedCall): boolean {
  const args = call.args.slice(FIRST.length);
  if (["decide", "deviation", "import"].includes(args[0])) return false;
  if (args.some((argument) => bare(argument).includes("llmlive") || bare(argument).includes("publiccheck"))) return false;
  return !args.some((argument) => PUBLIC_IDS.some((id) => argument.toLowerCase().includes(id)));
}

async function runCase(t: TestContext, input: Record<string, unknown>, state: Case["state"]) {
  const { studies } = workspace(t, ["bike"]);
  const calls = routed(t, exit(0, JSON.stringify(statusOf(state))));
  const text = await invoke(RUN_TOOL, filled(input, studies[0]) as Record<string, unknown>);
  return { study: studies[0], calls, text, commands: calls.filter((call) => !isRead(studies[0])(call)) };
}

for (const each of CASES) {
  test(`the run tool given the corpus case ${each.id} ${each.expected === "allowed" ? "starts the command with the argument list the case gives" : `refuses it with ${each.expected} and starts no command`}`, async (t) => {
    const { study, calls, text, commands } = await runCase(t, each.input, each.state);
    if (each.expected === "allowed") {
      assert.equal(commands.length, 1, text);
      assert.equal(commands[0].program, contract.program);
      assert.deepEqual(commands[0].args, [...FIRST, ...(filled(each.argv, study) as string[])]);
      assert.equal(commands[0].options.cwd, CHECKOUT);
      assert.match(text, /"written":"records"/);
    } else {
      assert.equal(commands.length, 0, JSON.stringify(commands));
      assert.ok(text.startsWith(`Refused (${each.expected}):`), text);
      assert.ok(text.includes("Nothing was started."), text);
      const byTheRead = each.expected === "PUBLIC_CHECK_REFUSED" && !JSON.stringify(each.input.arguments).split('"').some((part) => bare(part).includes("publiccheck"));
      assert.equal(calls.length, byTheRead ? 1 : 0, JSON.stringify(calls));
    }
    assert.ok(calls.every(reachesNothingForbidden));
  });
}

// The variants of a refused case: its command and arguments in capitals, padded with spaces, each option joined to its value by "=" or
// split from it, and every argument given twice.
function variants(input: Record<string, unknown>): [string, Record<string, unknown>][] {
  const command = input.command;
  const args = input.arguments;
  const onArgs = (change: (list: string[]) => unknown[]) => (Array.isArray(args) && args.every((a) => typeof a === "string") ? change(args as string[]) : args);
  const onCommand = (change: (text: string) => string) => (typeof command === "string" ? change(command) : command);
  const joined = (list: string[]) =>
    list.flatMap((argument, index) => (argument.startsWith("--") && !argument.includes("=") && list[index + 1] !== undefined && !list[index + 1].startsWith("-") ? [`${argument}=${list[index + 1]}`] : index > 0 && list[index - 1].startsWith("--") && !list[index - 1].includes("=") && !argument.startsWith("-") ? [] : [argument]));
  const split = (list: string[]) => list.flatMap((argument) => (argument.startsWith("--") && argument.includes("=") ? [argument.slice(0, argument.indexOf("=")), argument.slice(argument.indexOf("=") + 1)] : [argument]));
  return [
    ["in capitals", { ...input, command: onCommand((text) => text.toUpperCase()), arguments: onArgs((list) => list.map((a) => a.toUpperCase())) }],
    ["padded with spaces", { ...input, command: onCommand((text) => ` ${text} `), arguments: onArgs((list) => list.map((a) => ` ${a} `)) }],
    ["with each option joined to its value", { ...input, arguments: onArgs(joined) }],
    ["with each option split from its value", { ...input, arguments: onArgs(split) }],
    ["with every argument given twice", { ...input, arguments: onArgs((list) => [...list, ...list]) }],
  ];
}

test("no variant of a refused corpus case starts a command, and no started process reaches an act writer, llm_live or a public_check read", async (t) => {
  let checked = 0;
  for (const each of CASES.filter((one) => one.expected !== "allowed")) {
    for (const [how, input] of variants(each.input)) {
      await t.test(`${each.id} ${how}`, async (inner) => {
        const { calls, commands, text } = await runCase(inner, input, each.state);
        assert.equal(commands.length, 0, `${text}\n${JSON.stringify(commands)}`);
        assert.match(text, /^Refused \([A-Z_]+\):/);
        assert.ok(calls.every(reachesNothingForbidden));
      });
      checked += 1;
    }
  }
  assert.ok(checked >= 400, String(checked));
});

test("the run tool refuses assess, compare and report with STATUS_UNREADABLE when the read of the Study does not succeed, and starts no command", async (t) => {
  for (const command of ["assess", "compare", "report"]) {
    const { studies } = workspace(t, ["bike"]);
    const calls = routed(t, exit(2, JSON.stringify({ ok: false, error: { code: "STUDY_NOT_FOUND" } })));
    const text = await invoke(RUN_TOOL, { study: studies[0], command, arguments: command === "report" ? ["--out=/work/r.html"] : [], read_sequence: 1 });
    assert.ok(text.startsWith("Refused (STATUS_UNREADABLE):"), text);
    assert.ok(calls.every(isRead(studies[0])), command);
    t.mock.restoreAll();
  }
});

test("the run tool asks VS Code to confirm the command it would start, with the Study and each argument as a JSON string, and starts nothing then", async (t) => {
  const { studies } = workspace(t, ["bike"]);
  const calls = routed(t, exit(0, JSON.stringify(statusOf("dev"))));
  const input = { study: studies[0], command: "run", arguments: ["ml", "--config", 'seasonal_7 "x"', "--partition=dev", "--request-id=r1"], read_sequence: 3 };
  const prepared = await toolOf(RUN_TOOL).prepareInvocation!({ input }, {});
  const message = (prepared as { confirmationMessages: { title: string; message: string } }).confirmationMessages;
  assert.equal(message.title, "Run this command on the Hypotrail Study?");
  for (const text of [studies[0], "run", "ml", '--config=seasonal_7 "x"', "--partition=dev", "--request-id=r1", "--read-sequence=3", "--json"]) {
    assert.ok(message.message.includes(JSON.stringify(text)), text);
  }
  assert.equal(calls.length, 0);
});

test("a command the CLI refuses or that gets no answer is reported and not started again", async (t) => {
  const input = (study: string) => ({ study, command: "profile", arguments: [] });
  {
    const { studies } = workspace(t, ["bike"]);
    const calls = routed(t, exit(0, "{}"), exit(2, JSON.stringify({ ok: false, error: { code: "STUDY_NOT_FOUND", message: "no" } })));
    const text = await invoke(RUN_TOOL, input(studies[0]));
    assert.equal(calls.length, 1);
    assert.match(text, /exit code 2/);
    assert.match(text, /"STUDY_NOT_FOUND"/);
    t.mock.restoreAll();
  }
  {
    const { studies } = workspace(t, ["bike"]);
    const calls = routed(t, exit(0, "{}"), exit(0, ""));
    const text = await invoke(RUN_TOOL, input(studies[0]));
    assert.equal(calls.length, 1);
    assert.match(text, /no_json/);
    assert.match(text, /may have written/);
  }
});

// The rows of the Markdown table under a heading of the contract, each as its cells.
function tableUnder(heading: string): string[][] {
  const section = CONTRACT.split(`## ${heading}\n`)[1].split("\n## ")[0];
  return section
    .split("\n")
    .filter((line) => line.startsWith("|"))
    .slice(2)
    .map((line) => line.slice(1, -1).split("|").map((cell) => cell.trim()));
}

const codes = (cell: string) => [...cell.matchAll(/`([^`]+)`/g)].map((found) => found[1]);

test("the tool's commands and its refusal codes, in order, are the contract's tables, and its manifest schema is the contract's", () => {
  const rows = tableUnder("The commands").map(([command, track, options, read]) => ({
    command: codes(command)[0],
    track: track === "none" ? null : codes(track)[0],
    options: options === "none" ? [] : codes(options),
    read_sequence: read === "passed",
  }));
  assert.deepEqual(RUN_COMMANDS, rows);
  assert.deepEqual(RUN_REFUSALS, tableUnder("What is refused before any command starts").map(([code]) => codes(code)));
  const schema = JSON.parse(CONTRACT.split("```json\n")[1].split("\n```")[0]);
  const entry = MANIFEST.contributes.languageModelTools.find((tool: { name: string }) => tool.name === RUN_TOOL);
  assert.deepEqual(entry.inputSchema, schema);
  assert.ok(MANIFEST.activationEvents.includes(`onLanguageModelTool:${RUN_TOOL}`));
});
