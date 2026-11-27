// The one module through which the client talks to the CLI. Each call starts at most one process, with `execFile` and
// a list of arguments, and gives back one of four outcomes: what the CLI printed (`success`, `refusal`), or the
// client's own account of a call that got no usable answer (`no_answer`) or that it did not start (`client_refusal`).
// The client reads only through `status`, `figures` and `profile` and writes only through `decide` (contract.json, `reads` and `writes`).
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as path from "node:path";
import contract from "../contract.json";

export type Cause = "not_started" | "timeout" | "too_large" | "no_json" | "inconsistent";

export type Outcome =
  | { outcome: "success"; object: Record<string, unknown> }
  | { outcome: "refusal"; exit_code: number; error: unknown }
  | { outcome: "no_answer"; cause: Cause; exit_code: number | null; object?: Record<string, unknown>; note?: string }
  | { outcome: "client_refusal"; missing: string[] };

type ExecError = { code?: unknown; killed?: boolean; signal?: unknown } | null;

// The checkout that holds the extension's folder (`clients/vscode/`): the CLI is run there, as the README's commands are.
export function checkoutRoot(extensionPath: string): string {
  return path.resolve(extensionPath, "..", "..");
}

// "A client reads through `status --json`, which takes no lock and writes nothing, and writes only through the documented CLI commands." (ADR 0004)
// "The panel's own read becomes `status --since <previous read's Write sequence, else 0> --json`, labelled "Since this panel's last read".
// The Copilot tool's arguments are unchanged." (D-136): given `since`, the read passes it as `--since=`; given none, it leaves that argument out.
export function readStudy(root: string, study: string, since?: number): Promise<Outcome> {
  const args = contract.read_arguments
    .filter((argument) => since !== undefined || !argument.includes("{n}"))
    .map((argument) => argument.replace("{path}", study).replace("{n}", String(since)));
  return start(root, args, contract.read_timeout_ms);
}

// The second read: the figures of the Study's Comparisons, with the read's limits. It takes no lock and writes nothing either.
export function readFigures(root: string, study: string): Promise<Outcome> {
  const args = contract.figures_arguments.map((argument) => argument.replace("{path}", study));
  return start(root, args, contract.read_timeout_ms);
}

// The third read: the data profile of the Study's `train` Items, with the read's limits.
export function readProfile(root: string, study: string): Promise<Outcome> {
  const args = contract.profile_arguments.map((argument) => argument.replace("{path}", study));
  return start(root, args, contract.read_timeout_ms);
}

function start(root: string, args: string[], timeout: number): Promise<Outcome> {
  return new Promise((resolve) => {
    execFile(contract.program, [...contract.first_arguments, ...args], { cwd: root, timeout, maxBuffer: contract.max_buffer_bytes }, (error, stdout) => {
      resolve(outcomeOf(error as ExecError, String(stdout)));
    });
  });
}

// Text on stderr decides nothing: a refusal of the argument parser prints its usage there, and a success may print a warning.
function outcomeOf(error: ExecError, stdout: string): Outcome {
  if (error) {
    if (error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") return noAnswer("too_large", null);
    if (error.killed === true) return noAnswer("timeout", null);
    if (typeof error.code === "string") return noAnswer("not_started", null);
    if (typeof error.code !== "number") return noAnswer("inconsistent", null);
  }
  const exitCode = error ? (error.code as number) : 0;
  const object = parsedObject(stdout);
  if (object === undefined) return noAnswer("no_json", exitCode);
  if (exitCode === 0 && object.ok === true) return { outcome: "success", object };
  if (exitCode !== 0 && object.ok === false) return { outcome: "refusal", exit_code: exitCode, error: object.error };
  return { outcome: "no_answer", cause: "inconsistent", exit_code: exitCode, object };
}

function noAnswer(cause: Cause, exitCode: number | null): Outcome {
  return { outcome: "no_answer", cause, exit_code: exitCode };
}

function parsedObject(stdout: string): Record<string, unknown> | undefined {
  try {
    const value: unknown = JSON.parse(stdout);
    return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

export type DecisionInput = {
  question: string;
  option: string;
  author: string;
  source?: string;
  question_id?: string;
  option_id?: string;
  words?: string[];
  channel?: string;
  by?: string;
  cited_ids: string[];
  request_id: string;
  read_sequence: number;
};

// A request id for a new write. The bridge never makes one by itself: a repeat is the caller's second call with the same id.
export function newRequestId(): string {
  return randomUUID();
}

// Records a Decision through `decide`, with the Write sequence the caller read and the caller's request id. One call
// starts at most one process, whatever its outcome: the bridge never repeats a write.
export async function recordDecision(root: string, study: string, decision: DecisionInput): Promise<Outcome> {
  const missing = missingInputs(decision as unknown as Record<string, unknown>);
  if (missing.length > 0) return { outcome: "client_refusal", missing };
  const args = [
    "decide",
    `--study=${study}`,
    `--question=${decision.question}`,
    `--option=${decision.option}`,
    `--author=${decision.author}`,
    ...(decision.source === undefined ? [] : [`--source=${decision.source}`]),
    ...(decision.question_id === undefined ? [] : [`--question-id=${decision.question_id}`]),
    ...(decision.option_id === undefined ? [] : [`--option-id=${decision.option_id}`]),
    ...(decision.words ?? []).map((text) => `--words=${text}`),
    ...(decision.channel === undefined ? [] : [`--channel=${decision.channel}`]),
    ...(decision.by === undefined ? [] : [`--by=${decision.by}`]),
    ...decision.cited_ids.map((id) => `--artifact=${id}`),
    `--request-id=${decision.request_id}`,
    `--read-sequence=${decision.read_sequence}`,
    "--json",
  ];
  const outcome = await start(root, args, contract.write_timeout_ms);
  return outcome.outcome === "no_answer" ? { ...outcome, note: contract.write_no_answer_words } : outcome;
}

const nonEmpty = (value: unknown): boolean => typeof value === "string" && value.length > 0;
const absentOrText = (value: unknown): boolean => value === undefined || typeof value === "string";
// Characters are counted as code points, as the CLI's Python counts them; the CLI and the record keep no limit.
const words = (value: unknown): boolean =>
  value === undefined ||
  (Array.isArray(value) && value.length > 0 && value.every(nonEmpty) && value.reduce((total: number, text: string) => total + [...text].length, 0) <= contract.words_limit_characters);

// The checks of the inputs, in the order of `client_refusal_fields`. What the CLI refuses itself (an empty list of cited
// ids, an unknown author, an id or a channel it does not know, words with a proxy author) is left to the CLI.
const CHECKS: Record<string, (value: unknown) => boolean> = {
  question: nonEmpty,
  option: nonEmpty,
  author: (value) => typeof value === "string",
  cited_ids: (value) => Array.isArray(value) && value.every(nonEmpty),
  source: absentOrText,
  question_id: absentOrText,
  option_id: absentOrText,
  words,
  channel: absentOrText,
  by: absentOrText,
  request_id: nonEmpty,
  read_sequence: (value) => Number.isSafeInteger(value) && (value as number) >= 0,
};

// The fields of `client_refusal_fields` that `decision` lacks or holds a value of that does not pass its check.
export function missingInputs(decision: Record<string, unknown>): string[] {
  return contract.client_refusal_fields.filter((field) => !CHECKS[field](decision[field]));
}
