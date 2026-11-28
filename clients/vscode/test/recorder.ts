// The recorder: a test double that takes the place of `execFile`. It records each call (program, list of arguments,
// options) and answers with a chosen error, stdout and stderr.
//
// A profile call and a lesson call are each answered apart from the other calls, so that the answers a test lists for the status,
// figures and write calls keep their order: with the answers marked by `profile` or by `lesson`, in turn; with none, with the kept read
// made beside the kept status read the last status call was answered with, when one is kept, and otherwise, for a profile call, with the
// kept refusal of a Study the profile does not cover, and for a lesson call with an answer that is no JSON; neither draws anything.
import childProcess = require("node:child_process");
import type { TestContext } from "node:test";
import contract from "../contract.json";
import { kept } from "./kept";

export type Answer = { error?: Record<string, unknown> | null; stdout?: string; stderr?: string; profile?: true; lesson?: true; delay?: number };

export type RecordedCall = { program: string; args: string[]; options: Record<string, unknown> };

export function withEvaluatorEnvironment(t: TestContext): void {
  const keys = {
    GITHUB_ACTIONS: "true",
    GITHUB_WORKFLOW_REF: "chadlis/mlkit/.github/workflows/evaluator.yml@refs/heads/main",
  };
  for (const [key, value] of Object.entries(keys)) {
    const previous = process.env[key];
    process.env[key] = value;
    t.after(() => {
      if (previous === undefined) delete process.env[key];
      else process.env[key] = previous;
    });
  }
}

// An answer of a process that ended with `code`, as `execFile` gives it: a non-zero exit is an error whose `code` is the exit code.
export function exit(code: number, stdout = "", stderr = ""): Answer {
  return { error: code === 0 ? null : { code, killed: false, signal: null }, stdout, stderr };
}

// `answer` given to a profile call.
export function profile(answer: Answer): Answer {
  return { ...answer, profile: true };
}

// `answer` given to a profile call `ms` milliseconds after it starts, on the timer `setTimeout`.
export function delayedProfile(answer: Answer, ms: number): Answer {
  return { ...profile(answer), delay: ms };
}

// `answer` given to a lesson call.
export const UNSUPPORTED_LESSON = JSON.stringify({
  ok: false,
  error: { code: "UNSUPPORTED_CAPABILITY", message: "this Track serves no lesson cards", stage: "lesson", details: { command: "lesson" } },
});

export function lesson(answer: Answer): Answer {
  return { ...answer, lesson: true };
}

// The kept profile read made beside each kept status read that has one, by the status read's name (tests/_client_helpers.py).
export const KEPT_PROFILES: Record<string, string> = { "status-success": "profile-bike", "status-chinook-pending": "profile-chinook" };
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
// The kept refusal of a Study the profile does not cover.
export const NO_PROFILE = "profile-chinook";

// The kept lesson read made beside each kept status read that has one, by the status read's name (tests/_client_helpers.py,
// `lesson_outputs`): the two of the demonstration on the same Study at the same state, and the refusal of a Chinook Study.
export const KEPT_LESSONS: Record<string, string> = {
  "demonstration.after-compare.status": "lesson.after-compare",
  "demonstration.after-decide.status": "lesson.after-decide",
  "status-chinook-pending": "lesson.chinook-pending",
};
// The answer of a lesson call beside a status read of which no lesson read is kept.
export const NO_LESSON: Answer = exit(0, "not JSON");

const commandOf = (args: string[]): string | undefined => args[contract.first_arguments.length];
const isProfile = (args: string[]): boolean => commandOf(args) === contract.profile_arguments[0];
const isLesson = (args: string[]): boolean => commandOf(args) === contract.lesson_arguments[0];
const parsed = (text: string | undefined): string | undefined => {
  try {
    return JSON.stringify(JSON.parse(text ?? ""));
  } catch {
    return undefined;
  }
};

// What answers the calls of one test: `next(args)` gives the answer of the next call made with `args`, and `seen` keeps the answer of
// the last status call.
function answering(answers: Answer[]): { next: (args: string[]) => Answer | undefined; seen: (args: string[], answer: Answer) => void } {
  const profiles = answers.filter((answer) => answer.profile);
  const lessons = answers.filter((answer) => answer.lesson);
  const others = answers.filter((answer) => !answer.profile && !answer.lesson);
  let calls = 0;
  let profileCalls = 0;
  let lessonCalls = 0;
  // The stdout of the last status call: a profile read is kept beside the kept status read printed exactly so, a lesson read beside
  // the same object, however it is printed.
  let status: string | undefined;
  const keptBeside = (table: Record<string, string>, same: (out: string) => boolean): string | undefined => {
    const name = Object.keys(table).find((each) => status !== undefined && same(kept(`${each}.out`)));
    return name === undefined ? undefined : table[name];
  };
  return {
    next: (args) => {
      if (isProfile(args)) {
        profileCalls += 1;
        return profiles.length > 0 ? profiles[Math.min(profileCalls, profiles.length) - 1] : keptAnswer(keptBeside(KEPT_PROFILES, (out) => out === status) ?? NO_PROFILE);
      }
      if (isLesson(args)) {
        lessonCalls += 1;
        const beside = keptBeside(KEPT_LESSONS, (out) => parsed(out) === parsed(status));
        return lessons.length > 0 ? lessons[Math.min(lessonCalls, lessons.length) - 1] : beside === undefined ? NO_LESSON : keptAnswer(beside);
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
    if (given.delay !== undefined) setTimeout(() => reply(callback, given), given.delay);
    else setImmediate(() => reply(callback, given));
    return {};
  });
  return recorded;
}

// A recorder whose calls stay in flight until the test answers them, each with the answer the test gives; a profile call and a lesson
// call are answered at once, as the recorder above answers them when no answer is marked for them.
export function heldRecorder(t: TestContext, holdLesson = false) {
  const calls: RecordedCall[] = [];
  const waiting: { args: string[]; callback: (error: unknown, stdout: string, stderr: string) => void }[] = [];
  const answer = answering([]);
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    calls.push({ program, args: [...args], options: { ...options } });
    if (isProfile(args) || (isLesson(args) && !holdLesson)) {
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
