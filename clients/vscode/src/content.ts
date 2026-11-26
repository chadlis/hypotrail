// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client, an index, or, in a bar's geometry, a length computed from the read's numbers.
// The client computes nothing else of its own: what is pending, the delta, the roles, whether a Decision applies, its reasons
// and the state of its evidence are those the object read holds; the order of the dots and the side a dot's row favours follow the
// sign of the paired delta the figures read holds.
import contract from "../contract.json";
import type { Outcome } from "./bridge";
import { bars, boxPlot, dots, histogram, partBar, type Bar, type Dot, type Five } from "./charts";

// `study` is the string the panel was opened with, `figures` the object of the figures read made after the status read, `failure`
// the outcome of a read that failed, `written` the answer of the
// write the document follows, `unanswered` whether a write that got no answer is held, and `sent` the question, option and cited
// ids of the write in flight or held; `decision` is the id a link of the second form names; `unopened` says that the document follows a
// message of a control that opens whose file the panel did not open.
export type View = {
  study?: string;
  reading: boolean;
  writing?: boolean;
  object?: Record<string, unknown>;
  figures?: Record<string, unknown>;
  failure?: Outcome;
  written?: Outcome;
  unanswered?: boolean;
  sent?: { question: unknown; option: unknown; cited_ids: unknown };
  decision?: string;
  unopened?: boolean;
};

// An object of the read, whatever its keys.
type Entry = Record<string, unknown>;

// The panel's own words, by their place in `labels` of contract.json.
const LABEL = {
  reading: 0,
  readAgain: 1,
  study: 2,
  writeSequence: 3,
  pending: 4,
  noPending: 5,
  comparison: 6,
  delta: 7,
  coverage: 8,
  control: 9,
  candidate: 10,
  assessment: 11,
  metric: 12,
  status: 13,
  warnings: 14,
  limitations: 15,
  decisions: 16,
  deviations: 17,
  withdrawn: 18,
  noAnswer: 19,
  author: 20,
  citedIds: 21,
  applies: 22,
  reasons: 23,
  changedItems: 24,
  citedValue: 25,
  latestValue: 26,
  linked: 27,
  noDecision: 28,
  sendAgain: 29,
  record: 30,
  writing: 31,
  missing: 32,
  recordedId: 33,
  outputPath: 34,
  comparabilityStatus: 35,
  recorded: 36,
  mayHaveBeenRecorded: 37,
  notWrittenTwice: 38,
  readAgainChoose: 39,
  pendingCount: 40,
  toChoices: 41,
  sent: 42,
  failed: 43,
  none: 44,
  figuresUnavailable: 45,
  noFigure: 46,
  pairedDeltas: 47,
  itemsPerBin: 48,
  minimum: 49,
  firstQuartile: 50,
  median: 51,
  thirdQuartile: 52,
  maximum: 53,
  shares: 54,
  casesPerBin: 55,
  itemErrors: 56,
  zero: 57,
  itemsBelow: 58,
  casesBelow: 59,
  dotOrder: 60,
  openFile: 61,
  notOpened: 62,
  openRecord: 63,
  now: 64,
  studySoFar: 65,
  tools: 66,
  since: 67,
  waiting: 68,
  consequence: 69,
  charts: 70,
  scorer: 71,
  interval: 72,
  resamplingUnit: 73,
  limitationsRule: 74,
  earlierDecision: 75,
  citedDelta: 76,
  featuresAlone: 77,
} as const;

// An entry `name=value` of a list of contract.json, as its two texts.
const pair = (entry: string): [string, string] => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)];

// The phrase of each state of `evidence_change`, by its code.
const PHRASES = new Map(contract.evidence_phrases.map(pair));
// The phrase of each value of a Decision's `applies`.
const APPLIES = new Map(contract.applies_phrases.map(pair));
// The kind of part each kind of number links to, by the kind of number.
const PART_OF = new Map(contract.number_links.map(pair));
// The `href` of a link to each kind of part and to the choices of a pending decision, before the place of its record in its list of
// the object read; the `id` of what it links to is the same text without its `#`.
const HREF: Record<string, string> = {
  study: "#study-",
  comparison: "#comparison-",
  assessment: "#assessment-",
  decision: "#decision-",
  warnings: "#warnings-",
  limitations: "#limitations-",
  choices: "#choices-",
  dots: "#dots-",
  since: "#since-",
};
// The `href` of the document's top, where Read again stands: the `id` of its `main` element.
const TOP = "#study";
// The `id` of the element around a pending decision's question, before the place of that decision in `pending_decisions`.
const QUESTION_ID = "question-";
// The `id` of an option's text and of its consequence, before the place of that option among all the options of the document.
const OPTION_ID = "option-";
const CONSEQUENCE_ID = "consequence-";
// The `id` of the element around a path that a control that opens is described by, before the place of that path among the paths of the
// document.
const PATH_ID = "path-";
// The message of a control that opens, the ref of each output path a record names, and the ref of a record's own file.
const OPEN = contract.messages[3];
const [PER_ITEM, PAIRED_DELTAS, POPULATION, RECORD_FILE] = contract.open_refs;
// The kind of an entry of `record_files` that names the file of a record of each kind of part, by the kind of part.
const FILE_KIND: Record<string, string> = { assessment: "assessment", comparison: "comparison", decision: "decision", deviation: "declared_deviation" };
// "It is shown beside the label." (D-077 on chadlis/hypotrail#75, Q5, of `revision_changed`)
const BESIDE_THE_STATE = "revision_changed";

// The keys every entry of the figures read holds.
const FIGURES_KEYS = ["comparison_id", "unavailable", "paired_deltas", "histogram", "quartiles"];
// The keys of the five numbers of `quartiles`, in their order, each with its label.
const QUARTILES: [string, keyof typeof LABEL][] = [
  ["min", "minimum"],
  ["q1", "firstQuartile"],
  ["median", "median"],
  ["q3", "thirdQuartile"],
  ["max", "maximum"],
];
// An element of `paired_deltas` as its id, its two sides' values and its paired delta: the absolute errors of an Item on the Regression
// Track, the shares of a Case on the Agent Track, told apart by the key of the Case's id; undefined when a value is not a finite number.
// `worse` is the paired delta signed so that it is positive where the Candidate is worse: on the Regression Track a lower error is
// better, on the Agent Track a higher share.
type Pair = Dot & { worse: number };
function pairOf(element: Entry): Pair | undefined {
  const agent = "case_id" in element;
  const [id, control, candidate, delta] = agent
    ? [element.case_id, number(element.control_share), number(element.candidate_share), number(element.delta_share)]
    : [element.row_id, number(element.control_abs_error), number(element.candidate_abs_error), number(element.delta_abs_error)];
  if (control === null || candidate === null || delta === null) return undefined;
  const worse = agent ? -delta : delta;
  return { id: text(id), control, candidate, worse, joint: worse > 0 ? "favours-control" : worse < 0 ? "favours-candidate" : "between" };
}
// Fewer pairs than this, and the dots stand first, before the histogram and the box plot.
const FEW = 10;
// The reason of an entry whose Comparison withholds its delta.
const DELTA_WITHHELD = "delta_withheld";

const label = (name: keyof typeof LABEL): string => escaped(contract.labels[LABEL[name]]);

export function escaped(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const text = (value: unknown): string => escaped(value === undefined || value === null ? "" : String(value));
const value = (content: unknown): string => `<span>${text(content)}</span>`;
const marked = (content: unknown, tag = "span"): string => `<${tag} data-text>${text(content)}</${tag}>`;
const list = (content: unknown): Entry[] => (Array.isArray(content) ? content.filter((each) => typeof each === "object" && each !== null) : []);
const record = (content: unknown): Entry => (typeof content === "object" && content !== null && !Array.isArray(content) ? (content as Entry) : {});
const number = (content: unknown): number | null => (typeof content === "number" && Number.isFinite(content) ? content : null);

// "An integer is written as the object holds it, and no sign is added. A number that is not an integer is written as
// `String(Number(value.toPrecision(6)))`: six significant digits and no trailing zero" (chadlis/hypotrail#177); a null
// number is the word of `no_value`.
export function written(number: unknown): string {
  if (number === null) return escaped(contract.no_value);
  if (typeof number !== "number") return text(number);
  return Number.isInteger(number) ? String(number) : String(Number(number.toPrecision(6)));
}

// A number as a link to the part that shows its record: `index` is that record's place in its list, and the part is the one
// `number_links` gives for `kind`, or `part` when the record is not in its list.
const link = (kind: string, index: number, number: unknown, part = PART_OF.get(kind)!): string => `<a href="${HREF[part]}${index}" data-kind="${kind}">${written(number)}</a>`;
const anchor = (part: string, index: number): string => ` id="${HREF[part].slice(1)}${index}"`;

// The lists of the object read that a document's parts are found in, the records that already have a part in it (an Assessment
// or a Comparison has one part that links name, at the first place that shows it) and how many options the document shows.
// `figures` holds the entries of the figures read, none when it cannot stand beside the status read; `inert` is the attribute of a
// control that is inert while a call is in flight, `paths` how many paths beside a control the document shows, and `files` the entries
// of `record_files`.
type Shown = { comparisons: Entry[]; assessments: Entry[]; decisions: Entry[]; parts: Set<Entry>; options: number; figures: Entry[] | undefined; inert: string; paths: number; files: Entry[] };

// The object of the figures read when it is usable beside the status read: the same Write sequence, and one entry with its five keys
// for each Comparison the status read lists. Otherwise there is none, and the figures call counts as failed.
export function usableFigures(object: Entry | undefined, figures: Entry | undefined): Entry | undefined {
  if (object === undefined || figures === undefined || figures.write_sequence !== object.write_sequence || !Array.isArray(figures.comparisons)) return undefined;
  const entries = list(figures.comparisons);
  const complete = entries.length === figures.comparisons.length && entries.every((entry) => FIGURES_KEYS.every((key) => key in entry));
  const ids = list(object.comparisons).map((comparison) => comparison.comparison_id);
  const matched = entries.length === ids.length && ids.every((id) => entries.filter((entry) => entry.comparison_id === id).length === 1);
  return complete && matched ? figures : undefined;
}

export function bodyOf(view: View): string {
  const parts: string[] = [marked(view.study, "h1")];
  // While a call is in flight every control is inert.
  const busy = view.reading || view.writing === true;
  const inert = busy ? " disabled" : "";
  const notice = noticeOf(view);
  if (notice.length > 0) parts.push(['<div data-element="notice" role="status" tabindex="-1">', ...notice, "</div>"].join("\n"));
  if (view.failure) parts.push(`<div data-element="failure">${failureOf(view.failure)}</div>`);
  const controls = [`<button data-message="${contract.messages[0]}"${inert}>${label("readAgain")}</button>`];
  if (view.unanswered) controls.push(`<button data-message="${contract.messages[2]}"${inert}>${label("sendAgain")}</button>`);
  if (list(view.object?.pending_decisions).length > 0) controls.push(`<a href="${HREF.choices}0">${label("toChoices")}</a>`);
  parts.push(['<div data-part="band">', `<div data-element="controls">${controls.join(" ")}</div>`, ...(view.object ? bandOf(view.object) : []), "</div>"].join("\n"));
  // The controls that record are inert while a call is in flight or a write that got no answer is held.
  const recorded = view.written?.outcome === "success" ? record(view.written.object.decision).decision_id : undefined;
  const figures = view.object ? usableFigures(view.object, view.figures) : undefined;
  const study = view.object ? studyOf(view.object, view.decision, busy, view.unanswered === true, recorded, view.sent, figures && list(figures.comparisons)) : undefined;
  parts.push(nowOf(view.object, study?.now ?? ""));
  if (study && study.waiting !== "") parts.push(['<section data-part="waiting">', `<h2>${label("waiting")}</h2>`, study.waiting, "</section>"].join("\n"));
  parts.push('<section data-part="path">', `<h2>${label("studySoFar")}</h2>`, ...(study ? [study.path] : []));
  parts.push("</section>", '<section data-part="tools">', `<h2>${label("tools")}</h2>`, "</section>");
  return parts.join("\n");
}

// The band under the path: the Write sequence of the read, and how many write-journal entries the panel's read gives after the
// Write sequence of the object it held, as a link to the place of their lines.
function bandOf(object: Entry): string[] {
  const since = Array.isArray(object.writes_since) ? object.writes_since.length : 0;
  return [
    `<p data-element="band">${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence)} ${label("since")} ${link("writes_since", 0, since)}</p>`,
    `<div data-part="since"${anchor("since", 0)}></div>`,
  ];
}

// Now, under its heading, from the read's `next_step`: with its kind `decide`, `pending`, the whole part of the pending decision its first
// id names, whose question is Now's line; with `look_again`, its text; with no kind, the label of no pending decision. Without an object
// read, Now holds nothing.
function nowOf(object: Entry | undefined, pending: string): string {
  const lines = [`<section data-part="now" id="now">`, `<h2>${label("now")}</h2>`];
  if (object) {
    const step = record(object.next_step);
    if (step.kind === "decide" && pending !== "") lines.push(pending);
    else if (step.kind === "look_again") lines.push(`<p data-element="now-question">${marked(step.text, "strong")}</p>`);
    else lines.push(`<p data-element="now-question">${label("noPending")}</p>`);
  }
  lines.push("</section>");
  return lines.join("\n");
}

// What the panel says of a call in flight and of its last write.
function noticeOf(view: View): string[] {
  const lines: string[] = [];
  if (view.unopened) lines.push(`<p>${label("notOpened")}</p>`);
  if (view.reading) lines.push(`<p>${label("reading")}</p>`);
  if (view.writing) lines.push(`<p>${label("writing")}</p>`);
  const written = view.written;
  if (written?.outcome === "no_answer") lines.push(`<p>${label("noAnswer")} ${value(written.cause)}</p>`);
  if (view.sent && (view.writing || view.unanswered)) lines.push(`<p>${label("sent")} ${marked(view.sent.option, "strong")}</p>`);
  if (view.unanswered) {
    lines.push(`<p data-element="unknown">${escaped(contract.write_no_answer_words)}</p>`, `<p>${label("mayHaveBeenRecorded")} ${label("notWrittenTwice")}</p>`);
  }
  if (written?.outcome === "refusal") {
    lines.push(failureOf(written));
    // "if that read fails, the document shows the write's refusal and the read's failure, both" (D-092, S19, 5, its condition).
    if (!view.failure) lines.push(`<p>${label("readAgainChoose")}</p>`);
  }
  if (written?.outcome === "client_refusal") lines.push(`<p>${label("missing")} ${written.missing.map(value).join(" ")}</p>`);
  if (written?.outcome === "success") lines.push(recordedOf(record(written.object.decision).decision_id, view));
  return lines;
}

// A write the CLI accepted: the Decision of the read that follows, by its id, or the answer's id when that read holds none.
function recordedOf(id: unknown, view: View): string {
  const decisions = view.failure ? [] : list(view.object?.decisions);
  const index = decisions.findIndex((decision) => decision.decision_id === id);
  if (index < 0) return `<p>${label("recordedId")} ${value(id)}</p>`;
  return `<p>${label("recorded")} <a href="${HREF.decision}${index}" data-recorded>${marked(decisions[index].option, "strong")}</a></p>`;
}

function failureOf(failure: Outcome): string {
  if (failure.outcome === "refusal") {
    const error = record(failure.error);
    return `<p>${label("failed")} ${value(error.code)} ${marked(error.message)}</p>`;
  }
  if (failure.outcome === "no_answer") return `<p>${label("failed")} ${label("noAnswer")} ${value(failure.cause)}</p>`;
  return "";
}

// `busy` says that a call is in flight and `held` that a write with no answer is held; `recorded` is the id of the Decision the write this
// document follows recorded, `sent` the write in flight or held.
// The parts of the object read under three headings: `now`, the first pending decision when `next_step` says one is Now; `waiting`, each
// other one in a closed fold whose summary is its question; and `path`, the Study so far.
function studyOf(object: Entry, linked: string | undefined, busy: boolean, held: boolean, recorded: unknown, sent: View["sent"], figures: Entry[] | undefined): { now: string; waiting: string; path: string } {
  const study = record(object.study);
  const pending = list(object.pending_decisions);
  const locked = busy || held;
  const shown: Shown = { comparisons: list(object.comparisons), assessments: list(object.assessments), decisions: list(object.decisions), parts: new Set(), options: 0, figures, inert: busy ? " disabled" : "", paths: 0, files: list(object.record_files) };
  const step = record(object.next_step);
  const context = Array.isArray(step.context) ? step.context : [];
  // The pending decision the first id of `next_step` names is Now, the others wait in their order; each keeps its place in
  // `pending_decisions`, which the control that records sends.
  const ids = Array.isArray(step.ids) ? step.ids : [];
  const first = Math.max(0, pending.findIndex((each) => each.comparison_id === ids[0]));
  const order = step.kind === "decide" && pending.length > 0 ? [first, ...pending.keys()].filter((at, place, all) => all.indexOf(at) === place) : [];
  const parts = order.map((at, place) => pendingOf(pending[at], at, locked, shown, sent, place === 0 ? context : undefined));
  const waiting = order.slice(1).map((at, place) => ['<details data-element="waiting">', `<summary>${marked(record(pending[at].question).text)}</summary>`, parts[place + 1], "</details>"].join("\n"));
  const count = `<p data-element="count">${label("pendingCount")} ${link("pending_decisions", 0, pending.length)}</p>`;
  return { now: parts[0] ?? "", waiting: waiting.join("\n"), path: [
    `<h3>${label("study")}</h3>`,
    `<div data-part="study"${anchor("study", 0)}>`,
    `<p>${value(study.study_id)} ${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence)}</p>`,
    "</div>",
    `<h3>${label("pending")}</h3>`,
    pending.length === 0 ? `<p>${label("noPending")}</p>` : count,
    `<h3>${label("decisions")}</h3>`,
    decisionsOf(list(object.decisions), linked, recorded, shown),
    `<h3>${label("deviations")}</h3>`,
    deviationsOf(list(object.declared_deviations), shown),
  ].join("\n") };
}

// The question, then the Comparison it names with the choices under its evidence: the first action selects an option's radio
// input, named by the option's text and described by its consequence, which stands in a closed fold; the second is the control that
// records, disabled until then. The option of the write `sent` is checked where its question is this one and its cited ids hold this
// Comparison's id. `context`, given to the decision that is Now, holds the ids of the earlier Decisions that no longer apply.
function pendingOf(pending: Entry, index: number, locked: boolean, shown: Shown, sent: View["sent"], context?: unknown[]): string {
  const inert = locked ? " disabled" : "";
  const question = `${QUESTION_ID}${index}`;
  const asked =
    sent !== undefined && sent.question === record(pending.question).text && Array.isArray(sent.cited_ids) && sent.cited_ids.includes(pending.comparison_id);
  const options = list(pending.options).map((option, at) => {
    const place = shown.options++;
    const checked = asked && sent.option === option.text ? " checked" : "";
    const input = `<input type="radio" name="pending-${index}" data-pending="${index}" data-option="${at}" aria-labelledby="${OPTION_ID}${place}" aria-describedby="${CONSEQUENCE_ID}${place}"${checked}${inert}>`;
    return `<label>${input} <span id="${OPTION_ID}${place}">${marked(option.text, "strong")}</span> <details data-element="consequence"><summary>${label("consequence")}</summary><span id="${CONSEQUENCE_ID}${place}">${marked(option.consequence, "small")}</span></details></label>`;
  });
  const choices = [
    `<fieldset aria-labelledby="${question}" ${anchor("choices", index)}>`,
    ...options,
    `<button data-message="${contract.messages[1]}" data-pending="${index}" aria-describedby="${question}" disabled>${label("record")}</button>`,
    "</fieldset>",
  ].join("\n");
  return [
    '<section data-part="pending">',
    ...(index > 0 ? ["<hr>"] : []),
    `<div id="${question}"${context ? ' data-element="now-question"' : ""}>${marked(record(pending.question).text, "h3")}</div>`,
    comparisonOf(pending.comparison_id, shown, [pending.control_assessment_id, pending.candidate_assessment_id], choices, context),
    assessmentOf("control", pending.control_assessment_id, shown),
    assessmentOf("candidate", pending.candidate_assessment_id, shown),
    "</section>",
  ].join("\n");
}

// A Comparison. Where it is pending (`choices` given), in D-148's order: its delta with its interval, the context of Now, its coverage,
// its frame line, its warnings word for word, the line that counts its warnings and the limitations that are no warning's message, the
// choices, then one closed fold of its charts and figures, then the rest of its part. Elsewhere: its delta, its coverage, its roles, chart
// 1, the single-feature chart and the figures of its paired deltas, then the rest, and last its dots when they do not stand with the figures. `roles` are the ids
// of the Assessments that stand under the Control and the Candidate, whose Metric of the delta chart 1 draws where the delta record
// carries no value of its own; `context`, the ids of the Decisions that no longer apply that Now shows.
function comparisonOf(id: unknown, shown: Shown, roles: unknown[], choices = "", context?: unknown[]): string {
  const index = shown.comparisons.findIndex((each) => each.comparison_id === id);
  const comparison = shown.comparisons[index];
  const first = comparison !== undefined && !shown.parts.has(comparison);
  if (first) shown.parts.add(comparison);
  const lines = [`<div data-part="comparison"${first ? anchor("comparison", index) : ""}>`, `<p>${label("comparison")} ${value(id)}</p>`];
  if (comparison) {
    const delta = record(comparison.delta);
    // The coverage is read once, as a list of its keys and values.
    const coverage = Object.entries(record(comparison.coverage));
    const coverageLine = `<p data-element="coverage">${label("coverage")} ${coverage.map(([key, number]) => `${value(key)} ${link("coverage", index, number)}`).join(" ")}</p>`;
    // "when the delta's `value` is null the Comparison's part holds no roles' element" (chadlis/hypotrail#177).
    const rolesLine =
      delta.value !== null && ("control" in delta || "candidate" in delta)
        ? `<p data-element="roles">${label("control")} ${link("control", index, delta.control)} ${label("candidate")} ${link("candidate", index, delta.candidate)}</p>`
        : "";
    const messages = list(comparison.warnings).map((warning) => warning.message);
    const warnings = list(comparison.warnings).map((warning) => `<li>${value(warning.code)} ${marked(warning.message)}</li>`);
    const all = Array.isArray(comparison.limitations) ? comparison.limitations : [];
    // "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
    const limitations = (choices === "" ? all : all.filter((limitation) => !messages.includes(limitation))).map((limitation) => marked(limitation, "li"));
    const listOf = (kind: "warnings" | "limitations", items: string[]): string =>
      [`<div data-part="${kind}"${first ? anchor(kind, index) : ""}>`, `<h4>${label(kind)}</h4>`, `<ul>\n${items.join("\n")}\n</ul>`, "</div>"].join("\n");
    const status = `${label("comparabilityStatus")} ${value(record(comparison.comparability).status)}`;
    const [figures, rest] = figuresOf(shown.figures, id, index, delta, first);
    const paths = [[PAIRED_DELTAS, comparison.paired_deltas_ref], [POPULATION, comparison.population_ref]].flatMap(([ref, output]) => {
      const path = record(output).path;
      return typeof path === "string" ? [`<p data-element="output">${label("outputPath")} ${opening("comparison", index, ref as string, path, shown)}</p>`] : [];
    });
    if (choices !== "") {
      lines.push(deltaOf(delta, index, comparison.interval), contextOf(context ?? [], shown), coverageLine);
      lines.push(`<p data-element="frame">${label("scorer")} ${value(scorerOf(roles[0], shown))} ${status}</p>`, listOf("warnings", warnings));
      lines.push(`<p data-element="limits">${label("warnings")} ${link("warnings", index, warnings.length)} ${label("limitations")} ${link("limitations", index, limitations.length)} <span>${label("limitationsRule")}</span></p>`, choices);
      const fold = [featuresChartOf(roles, delta, shown), rolesLine, deltaChartOf(delta, index, roles, shown), figures, rest].filter((line) => line !== "");
      if (fold.length > 0) lines.push(['<details data-element="charts">', `<summary>${label("charts")}</summary>`, ...fold, "</details>"].join("\n"));
      lines.push(`<p data-element="definition">${marked(delta.definition)}</p>`, coverageChartOf(coverage, index), ...paths);
      lines.push(recordFileOf("comparison", index, comparison.comparison_id, shown), listOf("limitations", limitations));
    } else {
      lines.push(deltaOf(delta, index), coverageLine, rolesLine, deltaChartOf(delta, index, roles, shown), featuresChartOf(roles, delta, shown), figures);
      lines.push(`<p data-element="definition">${marked(delta.definition)}</p>`, coverageChartOf(coverage, index), `<p>${status}</p>`, ...paths);
      lines.push(recordFileOf("comparison", index, comparison.comparison_id, shown), listOf("warnings", warnings), listOf("limitations", limitations), rest);
    }
  } else {
    lines.push(choices);
  }
  lines.push("</div>");
  return lines.filter((line) => line !== "").join("\n");
}

// The id of the Scorer of the Assessment of `id`, as the read lists it; undefined when the read lists none.
const scorerOf = (id: unknown, shown: Shown): unknown => record(shown.assessments.find((each) => each.assessment_id === id)?.scorer).id;

// The Decisions that no longer apply that `next_step` gives Now as context: each as one line with its option, as a link to its part, and
// the phrase of its `applies`, then the delta of the Comparison it cites, read as the read holds it, beside the delta of Now.
function contextOf(ids: unknown[], shown: Shown): string {
  return ids
    .flatMap((id) => {
      const index = shown.decisions.findIndex((each) => each.decision_id === id);
      if (index < 0) return [];
      const decision = shown.decisions[index];
      const lines = [`<p data-element="context">${label("earlierDecision")} <a href="${HREF.decision}${index}">${marked(decision.option, "strong")}</a> <span>${text(APPLIES.get(String(decision.applies)) ?? "")}</span></p>`];
      const cited = shown.comparisons.findIndex((each) => Array.isArray(decision.cited_ids) && decision.cited_ids.includes(each.comparison_id));
      const delta = record(shown.comparisons[cited]?.delta);
      if (cited >= 0) lines.push(`<p data-element="cited-delta">${label("citedDelta")} ${delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", cited, delta.value)} ${value(delta.metric)} ${marked(delta.unit)}</p>`);
      return lines;
    })
    .join("\n");
}

// The single-feature chart: the Control's and the Candidate's values of the Metric the Candidate's single-feature check computed, and
// beside them the value of each feature used alone on the same Items, as that check records it; none when it computed none.
function featuresChartOf(roles: unknown[], delta: Entry, shown: Shown): string {
  const [control, candidate] = [roles[0], roles[1]].map((id) => shown.assessments.findIndex((each) => each.assessment_id === id));
  const computed = candidate < 0 ? [] : list(record(shown.assessments[candidate].single_feature_check).computed);
  if (computed.length === 0 || control < 0) return "";
  const metric = record(computed[0].metric).id;
  const sideOf = (at: number, name: keyof typeof LABEL, kind: string): Bar | undefined => {
    const found = list(shown.assessments[at].metrics).find((each) => each.id === metric);
    return found === undefined ? undefined : { name: label(name), shown: link("value", at, found.value), value: number(found.value), kind };
  };
  const sides = [sideOf(control, "control", "control"), sideOf(candidate, "candidate", "candidate")];
  if (sides.includes(undefined)) return "";
  const features = computed.map((entry): Bar => ({ name: marked(entry.feature), shown: link("value", candidate, record(entry.metric).value), value: number(record(entry.metric).value), kind: "feature" }));
  return ['<div data-chart="features">', `<p>${label("featuresAlone")} ${value(metric)} ${marked(delta.unit)}</p>`, bars([...(sides as Bar[]), ...features]), "</div>"].join("\n");
}

// The figures of a Comparison's paired deltas from its entry of the figures read, as two texts: the first stands under chart 1, the
// second at the end of the Comparison's part. A withheld delta keeps its word alone: no figure and no label. Otherwise, under a heading
// with the delta's unit: the label of a failed figures call when there are no entries or the entry gives no reason but cannot be
// drawn, the label of an entry with no figures with its reason, or the figures: the delta's definition, a histogram of the bins with
// the count of each above its column and the ends of the axis under it, then a box plot of the five numbers on that axis with the mark
// of the Comparison's delta, a zero mark through both, and a key of the marks in the order of the axis; then the dots of its Items or
// Cases, first when there are few, otherwise at the end of the part, with a link to them where the part is the Comparison's first.
function figuresOf(entries: Entry[] | undefined, id: unknown, index: number, delta: Entry, first: boolean): [string, string] {
  if (delta.value === null) return ["", ""];
  const heading = `<h4>${label("pairedDeltas")} (${marked(delta.unit)})</h4>`;
  const failed = [heading, `<p data-element="figures-failed">${label("failed")} <a href="${TOP}">${label("figuresUnavailable")}</a></p>`].join("\n");
  if (entries === undefined) return [failed, ""];
  const entry = record(entries.find((each) => each.comparison_id === id));
  if (entry.unavailable === DELTA_WITHHELD) return ["", ""];
  if (entry.unavailable !== null) return [[heading, `<p data-element="figures-unavailable">${label("noFigure")} ${value(entry.unavailable)}</p>`].join("\n"), ""];
  const bins = list(entry.histogram);
  const counts = bins.map((bin) => number(bin.count));
  const quartiles = record(entry.quartiles);
  const five = QUARTILES.map(([key]) => number(quartiles[key]));
  const pairs = list(entry.paired_deltas).map(pairOf);
  if (bins.length === 0 || [...counts, ...five].includes(null) || pairs.length === 0 || pairs.includes(undefined)) return [failed, ""];
  const agent = "case_id" in list(entry.paired_deltas)[0];
  const ends: [number, number] = [five[0]!, five[4]!];
  const edges = bins[0].low === bins[bins.length - 1].high ? [bins[0].low] : [bins[0].low, bins[bins.length - 1].high];
  const marks: [number, string][] = QUARTILES.map(([key, name]) => [number(quartiles[key])!, `<span${key === "median" ? ' data-key="median"' : ""}>${label(name)} ${link("quartile", index, quartiles[key])}</span>`]);
  marks.push([number(delta.value)!, `<span data-key="delta">${label("delta")} ${link("delta", index, delta.value)}</span>`]);
  if (ends[0] <= 0 && 0 <= ends[1]) marks.push([0, `<span data-key="zero">${label("zero")}</span>`]);
  // In the order of the axis; `sort` keeps the order above between equal numbers.
  marks.sort((a, b) => a[0] - b[0]);
  const few = pairs.length < FEW;
  const shownDots = dotsOf(pairs as Pair[], index, delta, agent, few, first);
  return [
    [
      "<div data-figures>",
      heading,
      `<p data-element="caption">${marked(delta.definition)}</p>`,
      few ? shownDots : "",
      '<div data-figure="histogram">',
      `<table data-element="counts"><caption>${label(agent ? "casesPerBin" : "itemsPerBin")}</caption><tr>${bins.map((bin) => `<td>${link("bin_count", index, bin.count)}</td>`).join("")}</tr></table>`,
      histogram(counts as number[], ends),
      `<p data-element="axis">${edges.map((edge) => link("bin_edge", index, edge)).join(` ${marked(delta.unit)} `)}</p>`,
      "</div>",
      '<div data-figure="box">',
      boxPlot(five as Five, number(delta.value)),
      `<p data-element="quartiles">${marks.map(([, mark]) => mark).join(" ")}</p>`,
      "</div>",
      few || !first ? "" : `<p data-element="to-dots"><a href="${HREF.dots}${index}">${label(agent ? "casesBelow" : "itemsBelow")}</a></p>`,
      "</div>",
    ]
      .filter((line) => line !== "")
      .join("\n"),
    few ? "" : shownDots,
  ];
}

// The dots of a Comparison: per Item or Case, its id and the marks of its two sides on one scale, which runs from the smallest to the
// largest of their values, both printed above the rows; the rows run from the one where the Candidate is worst, as a fixed sentence
// after the key says. Their heading gives the unit only when they stand at the end of the part (`few` false), apart from the heading of
// the paired deltas; there, in the Comparison's first part, they hold the id a link names.
function dotsOf(pairs: Pair[], index: number, delta: Entry, agent: boolean, few: boolean, first: boolean): string {
  const values = pairs.flatMap((pair) => [pair.control, pair.candidate]);
  const ends: [number, number] = [values.reduce((a, b) => Math.min(a, b)), values.reduce((a, b) => Math.max(a, b))];
  // `sort` keeps the order of the read between rows of equal deltas.
  const ordered = [...pairs].sort((a, b) => b.worse - a.worse);
  const printed = `<p data-element="dot-ends">${(ends[0] === ends[1] ? [ends[0]] : ends).map((end) => link("dot_end", index, end)).join(" ")}</p>`;
  return [
    `<div data-figure="dots"${!few && first ? anchor("dots", index) : ""}>`,
    `<h4>${label(agent ? "shares" : "itemErrors")}${few ? "" : ` (${marked(delta.unit)})`}</h4>`,
    `<p data-element="dot-key"><span data-key="control">${label("control")}</span> <span data-key="candidate">${label("candidate")}</span></p>`,
    `<p data-element="dot-order">${label("dotOrder")}</p>`,
    '<div data-element="dots">',
    printed,
    dots(ordered, ends),
    "</div>",
    "</div>",
  ].join("\n");
}

// A Comparison whose full part the document already holds: its id as a link to that part, its delta, the delta's definition and
// chart 1.
function summaryOf(comparison: Entry, shown: Shown, roles: unknown[]): string {
  const index = shown.comparisons.indexOf(comparison);
  const delta = record(comparison.delta);
  return [
    '<div data-summary="comparison">',
    `<p>${label("comparison")} <a href="${HREF.comparison}${index}">${text(comparison.comparison_id)}</a></p>`,
    deltaOf(delta, index),
    `<p data-element="definition">${marked(delta.definition)}</p>`,
    deltaChartOf(delta, index, roles, shown),
    "</div>",
  ]
    .filter((line) => line !== "")
    .join("\n");
}

// The delta's element: its value as a link, or the word of a withheld delta, with its Metric and unit; then, given the Comparison's
// `interval` when the read holds one, its level and its two bounds as links to the Comparison, and its resampling unit, or, when a bound
// is null, its reason.
function deltaOf(delta: Entry, index: number, given?: unknown): string {
  const shownDelta = delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", index, delta.value);
  let slot = "";
  if (typeof given === "object" && given !== null) {
    const interval = given as Entry;
    slot =
      interval.lower === null || interval.upper === null
        ? ` <span data-element="interval">${label("interval")} ${marked(interval.reason)}</span>`
        : ` <span data-element="interval">${label("interval")} ${link("interval", index, interval.level)} ${link("interval", index, interval.lower)} ${link("interval", index, interval.upper)} ${label("resamplingUnit")} ${marked(interval.unit)}</span>`;
  }
  return `<p data-element="delta">${label("delta")} ${shownDelta} ${value(delta.metric)} ${marked(delta.unit)}${slot}</p>`;
}

// Chart 1: the Control's and the Candidate's values of the Metric the delta names, from the delta record where it carries them,
// else from each role's Assessment; with neither, or with the delta withheld, no chart.
function deltaChartOf(delta: Entry, index: number, roles: unknown[], shown: Shown): string {
  if (delta.value === null) return "";
  let control: Pick<Bar, "shown" | "value"> | undefined;
  let candidate: Pick<Bar, "shown" | "value"> | undefined;
  if ("control" in delta && "candidate" in delta) {
    control = { shown: link("control", index, delta.control), value: number(delta.control) };
    candidate = { shown: link("candidate", index, delta.candidate), value: number(delta.candidate) };
  } else {
    const metricOf = (id: unknown): Pick<Bar, "shown" | "value"> | undefined => {
      const at = shown.assessments.findIndex((each) => each.assessment_id === id);
      const metric = at < 0 ? undefined : list(shown.assessments[at].metrics).find((each) => each.id === delta.metric);
      return metric === undefined ? undefined : { shown: link("value", at, metric.value), value: number(metric.value) };
    };
    [control, candidate] = roles.map(metricOf);
  }
  if (control === undefined || candidate === undefined) return "";
  const values: Bar[] = [
    { ...control, name: label("control"), kind: "control" },
    { ...candidate, name: label("candidate"), kind: "candidate" },
  ];
  return ['<div data-chart="delta">', bars(values), "</div>"].join("\n");
}

// Chart 2: the coverage, one bar per role, its scored part over the expected whole; without those keys, no chart.
function coverageChartOf(coverage: [string, unknown][], index: number): string {
  const entry = (key: string): number | null => number(coverage.find(([name]) => name === key)?.[1]);
  const expected = entry("expected");
  const roles: [string, string, string][] = [
    ["control_scored", label("control"), "scored-control"],
    ["candidate_scored", label("candidate"), "scored-candidate"],
  ];
  if (expected === null || roles.some(([key]) => entry(key) === null)) return "";
  const rows = roles.map(([key, name, kind]) => partBar(name, kind, entry(key)!, expected, `${value(key)} ${link("coverage", index, entry(key))} ${value("expected")} ${link("coverage", index, expected)}`));
  return ['<div data-chart="coverage">', ...rows, "</div>"].join("\n");
}

// A path as a marked text, and beside it the control that opens the file it names: its message names the kind of the record's part, the
// place of the record in its listing and the ref, and the control is described by the path.
function opening(kind: string, index: number, ref: string, path: unknown, shown: Shown, name: keyof typeof LABEL = "openFile"): string {
  const id = `${PATH_ID}${shown.paths++}`;
  const control = `<button class="open" data-message="${OPEN}" data-part-kind="${kind}" data-index="${index}" data-ref="${ref}" aria-describedby="${id}"${shown.inert}>${label(name)}</button>`;
  return `<span id="${id}">${marked(path)}</span> ${control}`;
}

// The path of a record's own file, as `record_files` names it for the record of `id` of that kind of part, with the control that opens
// it; nothing when `record_files` names none.
function recordFileOf(kind: string, index: number, id: unknown, shown: Shown, tag = "p"): string {
  const path = shown.files.find((entry) => entry.kind === FILE_KIND[kind] && entry.id === id)?.path;
  return typeof path === "string" ? `<${tag} data-element="record-file">${opening(kind, index, RECORD_FILE, path, shown, "openRecord")}</${tag}>` : "";
}

// An Assessment, under its role where it has one: its part at the first place that shows it, its id as a link to that part after.
function assessmentOf(role: "control" | "candidate" | undefined, id: unknown, shown: Shown): string {
  const index = shown.assessments.findIndex((each) => each.assessment_id === id);
  const assessment = shown.assessments[index];
  let body = `<p>${label("assessment")} ${value(id)}</p>`;
  if (assessment !== undefined && shown.parts.has(assessment)) {
    body = `<p>${label("assessment")} <a href="${HREF.assessment}${index}">${text(id)}</a></p>`;
  } else if (assessment !== undefined) {
    shown.parts.add(assessment);
    const metrics = list(assessment.metrics).map(
      (metric) => `<li>${label("metric")} ${value(metric.id)} ${link("value", index, metric.value)} ${marked(metric.unit)} ${label("status")} ${value(metric.status)}</li>`,
    );
    const output = record(assessment.per_item_ref).path;
    const path = typeof output === "string" ? `<p data-element="output">${label("outputPath")} ${opening("assessment", index, PER_ITEM, output, shown)}</p>` : "";
    const own = recordFileOf("assessment", index, id, shown);
    const scorer = `<p>${label("scorer")} ${value(record(assessment.scorer).id)}</p>`;
    body = [`<div data-part="assessment"${anchor("assessment", index)}>`, body, scorer, path, own, `<ul>\n${metrics.join("\n")}\n</ul>`, "</div>"].filter((line) => line !== "").join("\n");
  }
  return role === undefined ? body : [`<div data-role="${role}">`, `<h4>${label(role)}</h4>`, body, "</div>"].join("\n");
}

function decisionsOf(decisions: Entry[], linked: string | undefined, recorded: unknown, shown: Shown): string {
  const parts = decisions.map((decision, index) => decisionOf(decision, index, decision.decision_id === linked, decision.decision_id === recorded, shown));
  if (linked !== undefined && !decisions.some((decision) => decision.decision_id === linked)) parts.unshift(`<p>${label("noDecision")} ${value(linked)}</p>`);
  return parts.length === 0 ? `<p>${label("none")}</p>` : parts.join("\n");
}

// A recorded Decision: what was chosen and whether it applies, its id, its question, the state of its evidence with each line of
// it and its reasons, then who recorded it, what it cites, and the Assessments of each line. `recorded` marks the Decision the
// write this document follows recorded.
function decisionOf(decision: Entry, index: number, linked: boolean, recorded: boolean, shown: Shown): string {
  const cited = Array.isArray(decision.cited_ids) ? decision.cited_ids : [];
  const reasons = list(decision.reasons).map((reason) => `<li>${value(reason.reason)} ${value(reason.id)}</li>`);
  const applies = APPLIES.get(String(decision.applies));
  const change = decision.evidence_change !== null && typeof decision.evidence_change === "object" ? record(decision.evidence_change) : undefined;
  const lines = [
    `<section data-part="decision"${anchor("decision", index)}${linked ? " data-linked" : ""}${recorded ? " data-recorded" : ""}>`,
    `<h3>${marked(decision.option, "strong")}${applies === undefined ? "" : ` <span data-applies="${decision.applies === true ? "yes" : "no"}">${escaped(applies)}</span>`}</h3>`,
    ...(linked ? [`<p>${label("linked")}</p>`] : []),
    `<p>${value(decision.decision_id)}</p>`,
    recordFileOf("decision", index, decision.decision_id, shown),
    `<p data-element="question">${marked(decision.question)}</p>`,
    ...(change ? [stateOf(change, list(decision.reasons)), linesOf(change, index, shown)] : []),
    ...(reasons.length > 0 ? [`<h4>${label("reasons")}</h4>`] : []),
    `<ul data-element="reasons">\n${reasons.join("\n")}\n</ul>`,
    `<p>${label("author")} ${value(decision.author)}</p>`,
    `<h4>${label("citedIds")}</h4>`,
    `<ul data-element="cited">\n${cited.map((id) => `<li>${value(id)}</li>`).join("\n")}\n</ul>`,
  ];
  for (const id of cited) {
    const comparison = shown.comparisons.find((each) => each.comparison_id === id);
    // The Assessments of a cited Comparison are those its `roles` name, and none without them.
    if (comparison !== undefined) {
      const roles = record(comparison.roles);
      const ids = "roles" in comparison ? [roles.control_assessment_id, roles.candidate_assessment_id] : [];
      if (shown.parts.has(comparison)) {
        lines.push(summaryOf(comparison, shown, ids));
        continue;
      }
      lines.push(comparisonOf(id, shown, ids));
      if ("roles" in comparison) lines.push(assessmentOf("control", roles.control_assessment_id, shown), assessmentOf("candidate", roles.candidate_assessment_id, shown));
    } else if (shown.assessments.some((each) => each.assessment_id === id)) {
      lines.push(assessmentOf(undefined, id, shown));
    }
  }
  lines.push(`<p>${label("applies")} ${value(decision.applies)}</p>`);
  // The Assessments of each line stand after the cited Comparison's, so that a role's Assessment has its part under its role.
  if (change) lines.push(...list(change.lines).flatMap((line) => [assessmentOf(undefined, line.assessment_id, shown), assessmentOf(undefined, line.latest_assessment_id, shown)]));
  lines.push("</section>");
  return lines.filter((line) => line !== "").join("\n");
}

const phrase = (state: unknown): string => text(PHRASES.get(String(state)) ?? state);

// The state of a Decision's evidence, with `revision_changed` beside it when a reason.
function stateOf(change: Entry, reasons: Entry[]): string {
  const beside = reasons.find((reason) => reason.reason === BESIDE_THE_STATE);
  return `<p data-element="evidence"><span>${phrase(change.state)}</span>${beside ? ` ${value(beside.reason)}` : ""}</p>`;
}

// Each line of a Decision's evidence, with chart 3: each Metric's cited and latest value as two bars on one scale; the line's
// Assessments are not shown here, but the file of each Assessment a line names first in the Decision is, with its control. `decision`
// is the place of the Decision in `decisions`: a number links to that Decision's part when `assessments` holds no entry of its
// Assessment's id.
function linesOf(change: Entry, decision: number, shown: Shown): string {
  const named = new Set<unknown>();
  const filesOf = (ids: unknown[]): string[] =>
    ids.filter((id) => !named.has(id) && named.add(id)).map((id) => {
      const index = shown.assessments.findIndex((each) => each.assessment_id === id);
      return index < 0 ? "" : recordFileOf("assessment", index, id, shown);
    });
  const to = (kind: string, id: unknown, number: unknown): string => {
    const index = shown.assessments.findIndex((each) => each.assessment_id === id);
    return index < 0 ? link(kind, decision, number, "decision") : link(kind, index, number);
  };
  const lines = list(change.lines).map((line) => {
    const metrics = list(line.metrics).map((metric) => {
      const chart = bars([
        { name: label("citedValue"), shown: to("cited", line.assessment_id, metric.cited), value: number(metric.cited), kind: "cited" },
        { name: label("latestValue"), shown: to("latest", line.latest_assessment_id, metric.latest), value: number(metric.latest), kind: "latest" },
      ]);
      return `<li data-chart="evidence"><p>${label("metric")} ${value(metric.id)}</p>\n${chart}</li>`;
    });
    const files = filesOf([line.assessment_id, line.latest_assessment_id]).filter((file) => file !== "");
    return `<li data-part="line"><span>${phrase(line.state)}</span> ${label("changedItems")} ${to("changed_item_count", line.latest_assessment_id, line.changed_item_count)}\n<ul>\n${metrics.join("\n")}\n</ul>${files.map((file) => `\n${file}`).join("")}\n</li>`;
  });
  return `<ul>\n${lines.join("\n")}\n</ul>`;
}

function deviationsOf(deviations: Entry[], shown: Shown): string {
  const lines = deviations.map((deviation, index) => {
    const file = recordFileOf("deviation", index, deviation.declared_deviation_id, shown, "span");
    return `<li data-part="deviation">${value(deviation.declared_deviation_id)} ${label("withdrawn")} ${value(deviation.withdrawn)}${file === "" ? "" : ` ${file}`}</li>`;
  });
  return lines.length === 0 ? `<p>${label("none")}</p>` : `<ul>\n${lines.join("\n")}\n</ul>`;
}
