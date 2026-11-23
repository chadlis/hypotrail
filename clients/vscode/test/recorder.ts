// The recorder: a test double that takes the place of `execFile`. It records each call (program, list of arguments,
// options) and answers with a chosen error, stdout and stderr.
import childProcess = require("node:child_process");
import type { TestContext } from "node:test";

export type Answer = { error?: Record<string, unknown> | null; stdout?: string; stderr?: string };

export type RecordedCall = { program: string; args: string[]; options: Record<string, unknown> };

// An answer of a process that ended with `code`, as `execFile` gives it: a non-zero exit is an error whose `code` is the exit code.
export function exit(code: number, stdout = "", stderr = ""): Answer {
  return { error: code === 0 ? null : { code, killed: false, signal: null }, stdout, stderr };
}

export function recorder(t: TestContext, ...answers: Answer[]): RecordedCall[] {
  const recorded: RecordedCall[] = [];
  t.mock.method(childProcess, "execFile", (program: string, args: string[], options: Record<string, unknown>, callback: (error: unknown, stdout: string, stderr: string) => void) => {
    recorded.push({ program, args: [...args], options: { ...options } });
    const answer = answers[Math.min(recorded.length, answers.length) - 1] ?? exit(0, "{}");
    const error = answer.error ? Object.assign(new Error("recorded"), answer.error) : null;
    setImmediate(() => callback(error, answer.stdout ?? "", answer.stderr ?? ""));
    return {};
  });
  return recorded;
}
