// The two language-model tools Copilot chat calls: a read of the Study, with no side effect, and the write of a Decision.
// Each starts at most one process, through the bridge. The read holds nothing between calls; the write holds, from its
// confirmation to its invocation, the Study folder the confirmation showed. Both take the Study the walk finds, or the
// folder given as `study` when the walk finds it; otherwise they refuse and start nothing.
import * as vscode from "vscode";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, missingInputs, newRequestId, readStudy, recordDecision, type Outcome } from "./bridge";
import { findStudies, workspaceFolders } from "./studies";

type ReadInput = { study?: unknown };

type DecideInput = {
  question?: unknown;
  option?: unknown;
  author?: unknown;
  cited_ids?: unknown;
  source?: unknown;
  read_sequence?: unknown;
  study?: unknown;
};

// The checkout that holds this extension: its compiled sources sit in `out/src/` of the extension's folder.
const ROOT = checkoutRoot(path.resolve(__dirname, "..", ".."));

const READ = "hypotrail_read_study";
const DECIDE = "hypotrail_decide";
const NOTHING_STARTED = "Nothing was started.";
const READ_AGAIN = `Read the Study again with ${READ} before any other write.`;

const json = (value: unknown): string => JSON.stringify(value) ?? "null";

function answer(text: string): vscode.LanguageModelToolResult {
  return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
}

// The Study a call of `tool` takes, or the text of its refusal. A given folder is compared, once resolved, with the
// folders the walk finds; a folder that is not absolute is never one of them.
async function studyOf(given: unknown, tool: string): Promise<{ study: string } | { refusal: string }> {
  const found = await findStudies(workspaceFolders());
  if (given !== undefined) {
    const folder = typeof given === "string" && path.isAbsolute(given) ? path.resolve(given) : undefined;
    if (folder !== undefined && found.includes(folder)) return { study: folder };
    return { refusal: `The folder ${json(given)} is not one of the Hypotrail Studies found in this workspace: study must be the absolute path of one of them. ${NOTHING_STARTED} Call ${tool} again with study set to one of the Studies found: ${json(found)}.` };
  }
  if (found.length === 1) return { study: found[0] };
  if (found.length === 0) return { refusal: `${contract.no_study_message} ${NOTHING_STARTED} Ask the user to open the folder that holds the Study in this workspace, then call ${tool} again.` };
  return { refusal: `This workspace holds several Hypotrail Studies. ${NOTHING_STARTED} Call ${tool} again with study set to the absolute path of one of the Studies found: ${json(found)}.` };
}

// The request id is made by the extension, so a refusal never names it.
function notSent(tool: string, missing: string[]): string {
  const given = missing.filter((field) => field !== "request_id");
  return `Nothing was sent to the CLI: these inputs are missing or not valid: ${given.join(", ")}. Call ${tool} again with them corrected.`;
}

// What the read gives back: the object the CLI printed, whole, or what the bridge says of a call that did not succeed.
function readAnswer(study: string, outcome: Outcome): string {
  switch (outcome.outcome) {
    case "success":
      return `The Study ${json(study)}, as the CLI's read printed it:\n${json(outcome.object)}`;
    case "refusal":
      return `The CLI refused to read the Study ${json(study)}, with exit code ${outcome.exit_code}. Correct what its error names, then call ${READ} again. Its error, as printed:\n${json(outcome.error)}`;
    case "no_answer":
      return `The CLI gave no usable answer to the read of the Study ${json(study)} (${outcome.cause}). Call ${READ} again to read it. What the bridge holds of the call:\n${json(outcome)}`;
    case "client_refusal":
      return notSent(READ, outcome.missing);
  }
}

function writeAnswer(study: string, outcome: Outcome): string {
  switch (outcome.outcome) {
    case "success":
      return `The Decision was recorded in the Study ${json(study)}. The CLI printed:\n${json(outcome.object)}`;
    case "refusal":
      return `The CLI refused the Decision, with exit code ${outcome.exit_code}. This tool does not send it again. ${READ_AGAIN} Its error, as printed:\n${json(outcome.error)}`;
    case "no_answer":
      return `The CLI gave no usable answer to the Decision (${outcome.cause}): ${contract.write_no_answer_words}. The Decision may have been recorded, and this tool does not send it again. ${READ_AGAIN} It shows whether the Study holds the Decision. What the bridge holds of the call:\n${json(outcome)}`;
    case "client_refusal":
      return notSent(DECIDE, outcome.missing);
  }
}

// A source that is empty or holds only white space is no source: it shows as none and is not passed.
function sourceOf(input: DecideInput): unknown {
  return typeof input.source === "string" && input.source.trim() === "" ? undefined : input.source;
}

// A Decision whose author is proxy names the rule it was chosen by; the CLI itself does not require a source.
function proxyRefusal(input: DecideInput): string | undefined {
  if (input.author !== "proxy" || sourceOf(input) !== undefined) return undefined;
  return `Nothing was sent to the CLI: a Decision whose author is proxy needs a source, which names the rule it was chosen by. Call ${DECIDE} again with source set to that rule.`;
}

// What the write refuses before any start, in its confirmation and in its invocation alike: the bridge's own checks
// of the inputs Copilot gives, a proxy Decision with no source, and a call that takes no single Study. Otherwise the
// Study it would write to.
async function checked(input: DecideInput): Promise<{ study: string } | { refusal: string }> {
  const missing = missingInputs({ ...input, source: sourceOf(input) }).filter((field) => field !== "request_id");
  if (missing.length > 0) return { refusal: notSent(DECIDE, missing) };
  const refusal = proxyRefusal(input);
  return refusal === undefined ? studyOf(input.study, DECIDE) : { refusal };
}

// The Study folder each confirmation showed, by the inputs it was shown for; the invocation of those inputs takes it.
const shown = new Map<string, string>();

const keyOf = (input: DecideInput): string => JSON.stringify(input, Object.keys(input).sort());

// Who the record names as the one who made the choice, by its author.
const DECIDER: Record<string, string> = {
  human: "the record names you, the user, as the one who made this choice",
  proxy: "the record names Copilot as the one who made this choice, by applying a stated rule",
};

// The confirmation's text: what will be recorded and where, each text as a JSON string so that a quote or a line
// break stays on its line, then what each button does. The Write sequence read is not shown.
function confirmation(study: string, input: DecideInput): string {
  const cited = (input.cited_ids as string[]).map(json).join(", ");
  const source = sourceOf(input);
  const decider = typeof input.author === "string" && Object.hasOwn(DECIDER, input.author) ? ` (${DECIDER[input.author]})` : "";
  const optional = input.author === "human" ? ' (with author "human", a source may be given, and it is optional)' : "";
  return [
    `Study folder: ${json(study)}`,
    `Question: ${json(input.question)}`,
    `Option: ${json(input.option)}`,
    `Author: ${json(input.author)}${decider}`,
    `Source: ${source === undefined ? "none" : json(source)}${optional}`,
    `Cited ids: ${cited}`,
    "",
    "Continue: the Decision is recorded in the Study, and it is not withdrawn. It can still be refused if the Study was written to since Copilot read it.",
    "Cancel: nothing is recorded.",
  ].join("\n");
}

export const readTool: vscode.LanguageModelTool<ReadInput> = {
  async invoke(options) {
    const resolved = await studyOf(options.input.study, READ);
    if ("refusal" in resolved) return answer(resolved.refusal);
    return answer(readAnswer(resolved.study, await readStudy(ROOT, resolved.study)));
  },
};

export const decideTool: vscode.LanguageModelTool<DecideInput> = {
  // Runs the checks and the walk and nothing else: it starts no process and writes nothing. A refusal is thrown, so
  // that no confirmation is asked for a Decision that would not be sent.
  async prepareInvocation(options) {
    const resolved = await checked(options.input);
    if ("refusal" in resolved) throw new Error(resolved.refusal);
    shown.set(keyOf(options.input), resolved.study);
    return { confirmationMessages: { title: "Record this Decision in the Hypotrail Study?", message: confirmation(resolved.study, options.input) } };
  },
  // Writes only to the folder the confirmation showed for these inputs: the walk is run again, and a Study it now
  // takes that is not that folder, or no folder shown, starts nothing.
  async invoke(options) {
    const input = options.input;
    const key = keyOf(input);
    const folder = shown.get(key);
    shown.delete(key);
    const resolved = await checked(input);
    if ("refusal" in resolved) return answer(resolved.refusal);
    if (folder !== resolved.study) return answer(unshown(folder, resolved.study));
    const source = sourceOf(input);
    const outcome = await recordDecision(ROOT, folder, {
      question: input.question as string,
      option: input.option as string,
      author: input.author as string,
      source: source as string | undefined,
      cited_ids: input.cited_ids as string[],
      request_id: newRequestId(),
      read_sequence: input.read_sequence as number,
    });
    return answer(writeAnswer(folder, outcome));
  },
};

function unshown(folder: string | undefined, study: string): string {
  const what = folder === undefined ? "No confirmation showed a Study folder for this Decision" : `The confirmation showed the Study folder ${json(folder)}, and the call now takes ${json(study)}`;
  return `${what}. ${NOTHING_STARTED} Call ${DECIDE} again, so that the user confirms the Decision with the folder it goes to.`;
}
