// The two language-model tools Copilot chat calls: a read of the Study, with no side effect, and the write of a Decision.
// Each starts at most one process, through the bridge, and holds nothing between calls. Both take the Study the walk
// finds, or the folder given as `study` when the walk finds it; otherwise they refuse and start nothing.
import * as vscode from "vscode";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, newRequestId, readStudy, recordDecision, type Outcome } from "./bridge";
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

const NOTHING_STARTED = "Nothing was started.";

const json = (value: unknown): string => JSON.stringify(value) ?? "null";

function answer(text: string): vscode.LanguageModelToolResult {
  return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
}

// The Study a call takes, or the text of its refusal. A given folder is compared, once resolved, with the folders the
// walk finds; a folder that is not absolute is never one of them.
async function studyOf(given: unknown): Promise<{ study: string } | { refusal: string }> {
  const found = await findStudies(workspaceFolders());
  if (given !== undefined) {
    const folder = typeof given === "string" && path.isAbsolute(given) ? path.resolve(given) : undefined;
    if (folder !== undefined && found.includes(folder)) return { study: folder };
    return { refusal: `The folder ${json(given)} is not one of the Hypotrail Studies found in this workspace. ${NOTHING_STARTED} The Studies found: ${json(found)}.` };
  }
  if (found.length === 1) return { study: found[0] };
  if (found.length === 0) return { refusal: `${contract.no_study_message} ${NOTHING_STARTED}` };
  return { refusal: `This workspace holds several Hypotrail Studies: give study, the folder of one of them. ${NOTHING_STARTED} The Studies found: ${json(found)}.` };
}

const notSent = (missing: string[]): string => `Nothing was sent to the CLI. Missing or not valid: ${missing.join(", ")}.`;

// What the read gives back: the object the CLI printed, whole, or what the bridge says of a call that did not succeed.
function readAnswer(study: string, outcome: Outcome): string {
  switch (outcome.outcome) {
    case "success":
      return `The Study ${json(study)}, as the CLI's read printed it:\n${json(outcome.object)}`;
    case "refusal":
      return `The CLI refused to read the Study ${json(study)}, with exit code ${outcome.exit_code}. Its error, as printed:\n${json(outcome.error)}`;
    case "no_answer":
      return `The CLI gave no usable answer to the read of the Study ${json(study)} (${outcome.cause}). What the bridge holds of the call:\n${json(outcome)}`;
    case "client_refusal":
      return notSent(outcome.missing);
  }
}

function writeAnswer(study: string, outcome: Outcome): string {
  switch (outcome.outcome) {
    case "success":
      return `The Decision was recorded in the Study ${json(study)}. The CLI printed:\n${json(outcome.object)}`;
    case "refusal":
      return `The CLI refused the Decision, with exit code ${outcome.exit_code}. This tool does not send it again. Its error, as printed:\n${json(outcome.error)}`;
    case "no_answer":
      return `The CLI gave no usable answer to the Decision (${outcome.cause}): ${contract.write_no_answer_words}. The Decision may have been recorded, and this tool does not send it again: read the Study to see whether it holds it. What the bridge holds of the call:\n${json(outcome)}`;
    case "client_refusal":
      return notSent(outcome.missing);
  }
}

// A Decision whose author is proxy names the rule it was chosen by; the CLI itself does not require a source.
function proxyRefusal(input: DecideInput): string | undefined {
  if (input.author !== "proxy" || (typeof input.source === "string" && input.source.length > 0)) return undefined;
  return "Nothing was sent to the CLI: a Decision whose author is proxy needs a source, which names the rule it was chosen by.";
}

// What `invoke` would refuse before any start, or the Study it would write to.
async function checked(input: DecideInput): Promise<{ study: string } | { refusal: string }> {
  const refusal = proxyRefusal(input);
  return refusal === undefined ? studyOf(input.study) : { refusal };
}

// The confirmation's text: what will be recorded and where, each text as a JSON string so that a quote or a line
// break stays on its line. The Write sequence read is not shown.
function confirmation(study: string, input: DecideInput): string {
  const cited = Array.isArray(input.cited_ids) ? input.cited_ids.map(json).join(", ") : json(input.cited_ids);
  return [
    `Study folder: ${json(study)}`,
    `Question: ${json(input.question)}`,
    `Option: ${json(input.option)}`,
    `Author: ${json(input.author)}`,
    `Source: ${input.source === undefined ? "none" : json(input.source)}`,
    `Cited ids: ${cited}`,
  ].join("\n");
}

export const readTool: vscode.LanguageModelTool<ReadInput> = {
  async invoke(options) {
    const resolved = await studyOf(options.input.study);
    if ("refusal" in resolved) return answer(resolved.refusal);
    return answer(readAnswer(resolved.study, await readStudy(ROOT, resolved.study)));
  },
};

export const decideTool: vscode.LanguageModelTool<DecideInput> = {
  // Runs the walk and nothing else: it starts no process and writes nothing. A refusal is thrown, so that no
  // confirmation is asked for a Decision that would not be sent.
  async prepareInvocation(options) {
    const resolved = await checked(options.input);
    if ("refusal" in resolved) throw new Error(resolved.refusal);
    return { confirmationMessages: { title: "Record this Decision in the Hypotrail Study?", message: confirmation(resolved.study, options.input) } };
  },
  async invoke(options) {
    const input = options.input;
    const resolved = await checked(input);
    if ("refusal" in resolved) return answer(resolved.refusal);
    const outcome = await recordDecision(ROOT, resolved.study, {
      question: input.question as string,
      option: input.option as string,
      author: input.author as string,
      source: input.source as string | undefined,
      cited_ids: input.cited_ids as string[],
      request_id: newRequestId(),
      read_sequence: input.read_sequence as number,
    });
    return answer(writeAnswer(resolved.study, outcome));
  },
};
