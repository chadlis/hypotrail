// The three language-model tools Copilot chat calls: a read of the Study, with no side effect, the write of a Decision, and
// the run tool, which starts one command of its contract (`run-tool.contract.md`) and may write records, never an act.
// Each starts its processes through the bridge and holds nothing between calls. The read takes the Study the walk finds,
// or the folder given as `study` when the walk finds it; the write and the run tool take only the folder given as
// `study`, when the walk finds it. Otherwise they refuse and start nothing.
import * as vscode from "vscode";
import * as path from "node:path";
import contract from "../contract.json";
import { checkoutRoot, missingInputs, newRequestId, readStudy, recordDecision, runCommand, type Outcome } from "./bridge";
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
  words?: unknown;
  question_id?: unknown;
  option_id?: unknown;
  by?: unknown;
};

// The channel the tool declares for the words it is given: Copilot relays them from the chat. The tool has no input for it.
const CHANNEL = "chat_relayed";

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

// The refusal of a call that names no Study when the walk finds none.
function noStudy(tool: string): string {
  return `${contract.no_study_message} ${NOTHING_STARTED} Ask the user to open the folder that holds the Study in this workspace, then call ${tool} again.`;
}

// The Study a call of `tool` takes, or the text of its refusal. A given folder is compared, once resolved, with the
// folders the walk finds; a folder that is not absolute is never one of them. Its branches for an absent `study` serve
// only the read, because the write refuses an absent `study` before it calls this. The read keeps the narrower meaning
// of an absent `study` on purpose: there a `study` given as "" or null is a folder given, and is refused as not found.
async function studyOf(given: unknown, tool: string): Promise<{ study: string } | { refusal: string }> {
  const found = await findStudies(workspaceFolders());
  if (given !== undefined) {
    const folder = typeof given === "string" && path.isAbsolute(given) ? path.resolve(given) : undefined;
    if (folder !== undefined && found.includes(folder)) return { study: folder };
    return { refusal: `The folder ${json(given)} is not one of the Hypotrail Studies found in this workspace: study must be the absolute path of one of them. ${NOTHING_STARTED} Call ${tool} again with study set to one of the Studies found: ${json(found)}.` };
  }
  if (found.length === 1) return { study: found[0] };
  if (found.length === 0) return { refusal: noStudy(tool) };
  return { refusal: `This workspace holds several Hypotrail Studies. ${NOTHING_STARTED} Call ${tool} again with study set to the absolute path of one of the Studies found: ${json(found)}.` };
}

// The write's refusal of a call with no `study`, whatever else its input lacks. It covers any `study` that is not a
// non-empty string.
async function noStudyGiven(): Promise<string> {
  const found = await findStudies(workspaceFolders());
  if (found.length === 0) return noStudy(DECIDE);
  return `${DECIDE} needs study, the absolute path of the folder of the Study to write to. ${NOTHING_STARTED} Call ${DECIDE} again with study set to one of the Studies found: ${json(found)}.`;
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

// A Decision whose author is proxy names the rule it was chosen by; the CLI itself does not require a source. It holds no
// words either: the words are the user's, on a Decision whose author is human.
function proxyRefusal(input: DecideInput): string | undefined {
  if (input.author !== "proxy") return undefined;
  if (sourceOf(input) === undefined) {
    return `Nothing was sent to the CLI: a Decision whose author is proxy needs a source, which names the rule it was chosen by. Call ${DECIDE} again with source set to that rule.`;
  }
  if (input.words === undefined) return undefined;
  return `Nothing was sent to the CLI: words are the user's own messages, recorded on a Decision whose author is human; a Decision whose author is proxy holds none. Call ${DECIDE} again without words, and put your own wording in source.`;
}

// What the write refuses before any start, in its confirmation and in its invocation alike, in this order: an absent
// `study`, which is any `study` that is not a non-empty string, the bridge's own checks of the inputs Copilot gives, a
// proxy Decision with no source, and a `study` that the walk does not find. Otherwise the Study it would write to.
async function checked(input: DecideInput): Promise<{ study: string } | { refusal: string }> {
  if (typeof input.study !== "string" || input.study === "") return { refusal: await noStudyGiven() };
  const missing = missingInputs({ ...input, source: sourceOf(input), channel: undefined }).filter((field) => field !== "request_id");
  if (missing.length > 0) return { refusal: notSent(DECIDE, missing) };
  const refusal = proxyRefusal(input);
  return refusal === undefined ? studyOf(input.study, DECIDE) : { refusal };
}

// Who the record names as the one who made the choice, by its author.
const DECIDER: Record<string, string> = {
  human: "the record names you, the user, as the one who made this choice",
  proxy: "the record names Copilot as the one who made this choice, by applying a stated rule",
};

// The lines of the words, when they are given: each text as a JSON string on its own line, in order, the label when given,
// and what the record says of them.
function wordsLines(input: DecideInput): string[] {
  if (input.words === undefined) return [];
  return [
    "Words, each as Copilot relays it:",
    ...(input.words as string[]).map(json),
    ...(input.by === undefined ? [] : [`By: ${json(input.by)}`]),
    "These words are recorded as relayed by Copilot (channel chat_relayed); they are not checked against the chat.",
  ];
}

// The confirmation's text: what will be recorded and where, each text as a JSON string so that a quote or a line
// break stays on its line, then what each button does. The Write sequence read is not shown.
function confirmation(study: string, input: DecideInput): string {
  const cited = (input.cited_ids as string[]).map(json).join(", ");
  const source = sourceOf(input);
  const decider = typeof input.author === "string" && Object.hasOwn(DECIDER, input.author) ? ` (${DECIDER[input.author]})` : "";
  return [
    `Study folder: ${json(study)}`,
    `Question: ${json(input.question)}`,
    `Option: ${json(input.option)}`,
    `Author: ${json(input.author)}${decider}`,
    `Source: ${source === undefined ? "none" : json(source)}`,
    `Cited ids: ${cited}`,
    ...wordsLines(input),
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
    return { confirmationMessages: { title: "Record this Decision in the Hypotrail Study?", message: confirmation(resolved.study, options.input) } };
  },
  // Runs the checks and the walk again, whether or not a confirmation came first: a `study` the walk no longer finds
  // starts nothing.
  async invoke(options) {
    const input = options.input;
    const resolved = await checked(input);
    if ("refusal" in resolved) return answer(resolved.refusal);
    const source = sourceOf(input);
    const outcome = await recordDecision(ROOT, resolved.study, {
      question: input.question as string,
      option: input.option as string,
      author: input.author as string,
      source: source as string | undefined,
      question_id: input.question_id as string | undefined,
      option_id: input.option_id as string | undefined,
      words: input.words as string[] | undefined,
      channel: input.words === undefined ? undefined : CHANNEL,
      by: input.by as string | undefined,
      cited_ids: input.cited_ids as string[],
      request_id: newRequestId(),
      read_sequence: input.read_sequence as number,
    });
    return answer(writeAnswer(resolved.study, outcome));
  },
};


// --- The run tool ---------------------------------------------------------------------------------------------------------------

const RUN = "hypotrail_run";

type RunInput = { study?: unknown; command?: unknown; arguments?: unknown; read_sequence?: unknown };

// The commands of the contract, each with the options the chat gives it and whether the Write sequence read is passed.
export const RUN_COMMANDS = [
  { command: "run", track: "ml", options: ["--config", "--partition", "--request-id", "--retry-of"], read_sequence: true },
  { command: "run", track: "agent", options: ["--mode", "--config", "--request-id", "--retry-of"], read_sequence: true },
  { command: "assess", track: null, options: ["--observations", "--scorer", "--references"], read_sequence: true },
  { command: "compare", track: null, options: ["--control", "--candidate", "--factor"], read_sequence: true },
  { command: "profile", track: null, options: [], read_sequence: false },
  { command: "report", track: null, options: ["--out"], read_sequence: true },
];

// The refusal codes of each rule, in the order the rules are checked.
export const RUN_REFUSALS = [
  ["STUDY_NOT_FOUND"],
  ["COMMAND_NOT_ALLOWED"],
  ["IMPORT_REFUSED"],
  ["ARGUMENTS_NOT_VALID"],
  ["LIVE_MODE_REFUSED"],
  ["PUBLIC_CHECK_REFUSED"],
  ["ARGUMENTS_NOT_VALID"],
  ["ARGUMENTS_NOT_VALID", "OPTION_NOT_ALLOWED"],
  ["OPTION_REPEATED"],
  ["READ_SEQUENCE_MISSING"],
  ["STATUS_UNREADABLE"],
  ["PUBLIC_CHECK_REFUSED"],
];

const COMMANDS = ["run", "import", "assess", "compare", "profile", "report"];
// The options that only the Mode llm_live of `run agent` takes, and the one Mode the tool passes.
const LIVE_ONLY = ["--partition", "--repeats", "--model", "--cases", "--episode-cost-limit-usd", "--price-list"];
const FIXTURE = "scripted_fixture";
// The commands whose touched Attempts are read from `status --json` before they start.
const READ_FIRST = ["assess", "compare", "report"];

type Refusal = { code: string; reason: string };
type Built = { args: string[] } | { refusal: Refusal };

// An argument with its case, white space, "-" and "_" taken away, as the two scans read it.
const bare = (text: string): string => text.toLowerCase().replace(/[\s_-]/g, "");
const nameOf = (argument: string): string => (argument.includes("=") ? argument.slice(0, argument.indexOf("=")) : argument);
const refused = (code: string, reason: string): { refusal: Refusal } => ({ refusal: { code, reason } });

// The options as given, each with its value: read in their order, the first that fails gives its code, and a repeat is refused after.
function parsed(list: string[], allowed: string[]): { options: [string, string][] } | { refusal: Refusal } {
  const options: [string, string][] = [];
  for (let index = 0; index < list.length; index += 1) {
    const argument = list[index];
    if (!argument.startsWith("-")) return refused("ARGUMENTS_NOT_VALID", `${json(argument)} stands where no value is taken.`);
    const name = nameOf(argument);
    if (!allowed.includes(name)) return refused("OPTION_NOT_ALLOWED", `${json(name)} is not an option this command takes from the chat: ${json(allowed)}.`);
    const value = argument.includes("=") ? argument.slice(name.length + 1) : list[(index += 1)];
    if (value === undefined || (!argument.includes("=") && value.startsWith("--"))) return refused("ARGUMENTS_NOT_VALID", `${json(name)} has no value.`);
    options.push([name, value]);
  }
  const repeated = options.find(([name], index) => options.findIndex(([other]) => other === name) !== index);
  if (repeated) return refused("OPTION_REPEATED", `${json(repeated[0])} is given more than once.`);
  return { options };
}

// The values given to --mode, in either form, whatever else the arguments hold.
const modes = (list: string[]): string[] =>
  list.flatMap((argument, index) => (argument === "--mode" ? [list[index + 1] ?? ""] : argument.startsWith("--mode=") ? [argument.slice("--mode=".length)] : []));

// The checks of the contract that need no read, in its order, and the arguments the command would be started with.
function built(study: string, input: RunInput): Built {
  const command = input.command;
  if (typeof command !== "string" || !COMMANDS.includes(command)) {
    return refused("COMMAND_NOT_ALLOWED", `${json(command)} is not a command of this tool: ${json(COMMANDS)}. decide and deviation record acts, which the chat only prepares and relays.`);
  }
  if (command === "import") return refused("IMPORT_REFUSED", "an Import is run by a person through the CLI: no read gives the Partition of its population before it is recorded.");
  const list = input.arguments;
  if (!Array.isArray(list) || !list.every((argument) => typeof argument === "string")) return refused("ARGUMENTS_NOT_VALID", "arguments must be a list of strings.");
  const agent = command === "run" && list[0] === "agent";
  const row = RUN_COMMANDS.find((each) => each.command === command && (each.track === null || each.track === list[0]));
  const names = (row?.options ?? []) as string[];
  for (const argument of list as string[]) {
    const name = nameOf(argument.trim()).toLowerCase();
    const live = agent && argument.startsWith("-") && !names.includes(nameOf(argument)) && LIVE_ONLY.some((option) => option.startsWith(name));
    if (bare(argument).includes("llmlive") || live) return refused("LIVE_MODE_REFUSED", `${json(argument)} asks for a paid live run (llm_live), which this tool never starts.`);
  }
  if (agent && modes(list as string[]).some((mode) => mode !== FIXTURE)) return refused("LIVE_MODE_REFUSED", `the only Mode this tool starts is ${FIXTURE}.`);
  if (list.some((argument) => bare(argument).includes("publiccheck"))) return refused("PUBLIC_CHECK_REFUSED", "a public_check read is the held-out pass, where the chat has no place.");
  if (row === undefined) return refused("ARGUMENTS_NOT_VALID", `run takes the Track ml or agent first, not ${json(list[0])}.`);
  const options = parsed(row.track === null ? list : list.slice(1), names);
  if ("refusal" in options) return options;
  const sequence = input.read_sequence;
  const valid = typeof sequence === "number" && Number.isInteger(sequence) && sequence >= 0;
  if (row.read_sequence && !valid) return refused("READ_SEQUENCE_MISSING", "read_sequence, the write_sequence of the Study as last read, must be an integer of 0 or more.");
  return {
    args: [
      command,
      ...(row.track === null ? [] : [row.track]),
      `--study=${study}`,
      ...options.options.map(([name, value]) => `${name}=${value}`),
      ...(row.read_sequence ? [`--read-sequence=${sequence}`] : []),
      "--json",
    ],
  };
}

const id = (value: unknown): string => (typeof value === "string" ? value.trim().toLowerCase() : "");
const valueOf = (args: string[], name: string): string => id(args.find((argument) => argument.startsWith(`${name}=`))?.slice(name.length + 1));

// The Attempts on public_check that the built command would touch, as the Study's read gives them.
function publicTouched(args: string[], read: Record<string, unknown>): string[] {
  const attempts = (Array.isArray(read.attempts) ? read.attempts : []) as Record<string, unknown>[];
  const assessments = (Array.isArray(read.assessments) ? read.assessments : []) as Record<string, unknown>[];
  const sets =
    args[0] === "assess"
      ? [valueOf(args, "--observations")]
      : args[0] === "compare"
        ? assessments.filter((each) => [valueOf(args, "--control"), valueOf(args, "--candidate")].includes(id(each.assessment_id))).map((each) => id(each.observation_set_id))
        : undefined;
  return attempts
    .filter((each) => each.partition === "public_check" && (sets === undefined || sets.includes(id(each.observation_set_id))))
    .map((each) => String(each.attempt_id));
}

// Every check of the contract, in its order: the Study, the input, and for assess, compare and report a read of the Study. Otherwise
// the arguments the command is started with.
async function runChecked(input: RunInput): Promise<{ study: string; args: string[] } | { refusal: Refusal }> {
  const resolved = typeof input.study === "string" && input.study !== "" ? await studyOf(input.study, RUN) : { refusal: await noStudyGivenTo(RUN) };
  if ("refusal" in resolved) return refused("STUDY_NOT_FOUND", resolved.refusal);
  const result = built(resolved.study, input);
  if ("refusal" in result) return result;
  if (!READ_FIRST.includes(result.args[0])) return { study: resolved.study, args: result.args };
  const read = await readStudy(ROOT, resolved.study);
  if (read.outcome !== "success") return refused("STATUS_UNREADABLE", `the read of the Study did not succeed (${read.outcome}), so what the command would touch is not known.`);
  const touched = publicTouched(result.args, read.object);
  if (touched.length > 0) return refused("PUBLIC_CHECK_REFUSED", `the command would touch Attempts on public_check, the held-out pass, where the chat has no place: ${json(touched)}.`);
  return { study: resolved.study, args: result.args };
}

async function noStudyGivenTo(tool: string): Promise<string> {
  const found = await findStudies(workspaceFolders());
  if (found.length === 0) return noStudy(tool);
  return `${tool} needs study, the absolute path of the folder of the Study. Call ${tool} again with study set to one of the Studies found: ${json(found)}.`;
}

const refusalText = (refusal: Refusal): string => `Refused (${refusal.code}): ${refusal.reason} ${NOTHING_STARTED}`;

function runAnswer(args: string[], outcome: Outcome): string {
  const line = json(args);
  switch (outcome.outcome) {
    case "success":
      return `The CLI ran ${line}. It printed:\n${json(outcome.object)}`;
    case "refusal":
      return `The CLI refused ${line}, with exit code ${outcome.exit_code}. This tool does not start it again. ${READ_AGAIN} Its error, as printed:\n${json(outcome.error)}`;
    case "no_answer":
      return `The CLI gave no usable answer to ${line} (${outcome.cause}): ${contract.write_no_answer_words}. The command may have written, and this tool does not start it again. ${READ_AGAIN} What the bridge holds of the call:\n${json(outcome)}`;
    case "client_refusal":
      return notSent(RUN, outcome.missing);
  }
}

export const runTool: vscode.LanguageModelTool<RunInput> = {
  // Runs the checks, with the read of the Study they may need, and starts no command. A refusal is thrown, so that no confirmation is
  // asked for a command that would not start.
  async prepareInvocation(options) {
    const checked = await runChecked(options.input);
    if ("refusal" in checked) throw new Error(refusalText(checked.refusal));
    const message = [
      `Study folder: ${json(checked.study)}`,
      "Arguments, each as one string:",
      ...checked.args.map(json),
      "",
      "Continue: the CLI runs this command, which may write records to the Study and advance its Write sequence.",
      "Cancel: nothing is run.",
    ].join("\n");
    return { confirmationMessages: { title: "Run this command on the Hypotrail Study?", message } };
  },
  // Runs the checks again, whether or not a confirmation came first, then starts the command once.
  async invoke(options) {
    const checked = await runChecked(options.input);
    if ("refusal" in checked) return answer(refusalText(checked.refusal));
    return answer(runAnswer(checked.args, await runCommand(ROOT, checked.args)));
  },
};
