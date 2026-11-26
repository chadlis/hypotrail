// The recorder: a test double that takes the place of `execFile`. It records each call (program, list of arguments,
// options) and answers with a chosen error, stdout and stderr.
//
// A profile call is answered apart from the other calls, so that the answers a test lists for the status, figures and write calls
// keep their order: with the answers marked by `profile`, in turn; with none, with the kept profile read made beside the kept status
// read the last status call was answered with, when one is kept, and otherwise with the kept refusal of a Study the profile does not
// cover, which draws nothing.
import childProcess = require("node:child_process");
import type { TestContext } from "node:test";
import contract from "../contract.json";
import { kept } from "./kept";

export type Answer = { error?: Record<string, unknown> | null; stdout?: string; stderr?: string; profile?: true };

export type RecordedCall = { program: string; args: string[]; options: Record<string, unknown> };

// An answer of a process that ended with `code`, as `execFile` gives it: a non-zero exit is an error whose `code` is the exit code.
export function exit(code: number, stdout = "", stderr = ""): Answer {
  return { error: code === 0 ? null : { code, killed: false, signal: null }, stdout, stderr };
}

// `answer` given to a profile call.
export function profile(answer: Answer): Answer {
  return { ...answer, profile: true };
}

// The kept profile read made beside each kept status read that has one, by the status read's name (tests/_client_helpers.py).
export const KEPT_PROFILES: Record<string, string> = { "status-success": "profile-bike", "status-chinook-pending": "profile-chinook" };
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
// The kept refusal of a Study the profile does not cover.
export const NO_PROFILE = "profile-chinook";

const commandOf = (args: string[]): string | undefined => args[contract.first_arguments.length];
const isProfile = (args: string[]): boolean => commandOf(args) === contract.profile_arguments[0];

// What answers the calls of one test: `next(args)` gives the answer of the next call made with `args`.
function answering(answers: Answer[]): { next: (args: string[], given?: Answer) => Answer | undefined; seen: (args: string[], answer: Answer) => void } {
  const profiles = answers.filter((answer) => answer.profile);
  const others = answers.filter((answer) => !answer.profile);
  let calls = 0;
  let profileCalls = 0;
  let status: string | undefined;
  const fallback = (): Answer => {
    const name = Object.keys(KEPT_PROFILES).find((each) => status !== undefined && kept(`${each}.out`) === status);
    return keptAnswer(name === undefined ? NO_PROFILE : KEPT_PROFILES[name]);
  };
  return {
    next: (args) => {
      if (isProfile(args)) {
        profileCalls += 1;
        return profiles.length > 0 ? profiles[Math.min(profileCalls, profiles.length) - 1] : fallback();
      }
      calls += 1;
      return others[Math.min(calls, others.length) - 1];
    },
    seen: (args, answer) => {
      if (commandOf(args) === "status") status = answer.stdout;
    },
  };
}

function reply(callback: (error: unknown, stdout: string, stderr: string) => void, answer: Answer): void {
  const error = answer.error ? Object.assign(new Error("recorded"), answer.error) : null;
  callback(error, answer.stdout ?? "", answer.stderr ?? "");
}

export function recorder(t: TestContext, ...answers: Answer[]): RecordedCall[] {
  const recorded: RecordedCall[] = [];
  const answer = answering(answers);
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    recorded.push({ program, args: [...args], options: { ...options } });
    const given = answer.next(args) ?? exit(0, "{}");
    answer.seen(args, given);
    setImmediate(() => reply(callback, given));
    return {};
  });
  return recorded;
}

// A recorder whose calls stay in flight until the test answers them, each with the answer the test gives; a profile call is answered at
// once, as the recorder above answers it when no answer is marked for it.
export function heldRecorder(t: TestContext) {
  const calls: RecordedCall[] = [];
  const waiting: { args: string[]; callback: (error: unknown, stdout: string, stderr: string) => void }[] = [];
  const answer = answering([]);
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    calls.push({ program, args: [...args], options: { ...options } });
    if (isProfile(args)) {
      const given = answer.next(args)!;
      setImmediate(() => reply(callback, given));
    } else waiting.push({ args: [...args], callback });
    return {};
  });
  return {
    calls,
    answer(given: Answer): void {
      for (const each of waiting.splice(0)) {
        answer.seen(each.args, given);
        reply(each.callback, given);
      }
    },
  };
}
