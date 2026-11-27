// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client, an index, or, in a bar's geometry, a length computed from the read's numbers.
// The client computes nothing else of its own: what is pending, the delta, the roles, whether a Decision applies, its reasons
// and the state of its evidence are those the object read holds; the order of the dots and the side a dot's row favours follow the
// sign of the paired delta the figures read holds.
import contract from "../contract.json";
import type { Outcome } from "./bridge";
import { bars, boxPlot, boxes, columns, dayOf, dots, histogram, matrix, partBar, scatter, timeline, type Bar, type Cell, type Dot, type Five } from "./charts";

// `study` is the string the panel was opened with, `figures` the object of the figures read made after the status read, `profile` the
// answer of the profile call made after it, `lesson` the object of the lesson read made after it, `failure`
// the outcome of a read that failed, `written` the answer of the
// write the document follows, `unanswered` whether a write that got no answer is held, and `sent` the question, option, words and cited
// ids of the write in flight or held; `decision` is the id a link of the second form names; `unopened` says that the document follows a
// message of a control that opens whose file the panel did not open.
export type View = {
  study?: string;
  reading: boolean;
  writing?: boolean;
  object?: Record<string, unknown>;
  figures?: Record<string, unknown>;
  lesson?: Record<string, unknown>;
  failure?: Outcome;
  written?: Outcome;
  unanswered?: boolean;
  sent?: { question: unknown; option: unknown; cited_ids: unknown; words?: unknown };
  decision?: string;
  unopened?: boolean;
  profile?: Outcome;
};

// An object of the read, whatever its keys.
type Entry = Record<string, unknown>;

// The panel's own words, by their place in `labels` of contract.json.
const LABEL = {
  reading: 0,
  readAgain: 1,
  study: 2,
  writeSequence: 3,
  comparison: 4,
  delta: 5,
  coverage: 6,
  control: 7,
  candidate: 8,
  assessment: 9,
  metric: 10,
  status: 11,
  warnings: 12,
  limitations: 13,
  decisions: 14,
  deviations: 15,
  withdrawn: 16,
  noAnswer: 17,
  author: 18,
  citedIds: 19,
  applies: 20,
  reasons: 21,
  changedItems: 22,
  citedValue: 23,
  latestValue: 24,
  linked: 25,
  noDecision: 26,
  sendAgain: 27,
  record: 28,
  writing: 29,
  missing: 30,
  recordedId: 31,
  outputPath: 32,
  comparabilityStatus: 33,
  recorded: 34,
  mayHaveBeenRecorded: 35,
  notWrittenTwice: 36,
  readAgainChoose: 37,
  pendingCount: 38,
  toChoices: 39,
  sent: 40,
  failed: 41,
  figuresUnavailable: 42,
  noFigure: 43,
  pairedDeltas: 44,
  itemsPerBin: 45,
  minimum: 46,
  firstQuartile: 47,
  median: 48,
  thirdQuartile: 49,
  maximum: 50,
  shares: 51,
  casesPerBin: 52,
  itemErrors: 53,
  zero: 54,
  itemsBelow: 55,
  casesBelow: 56,
  dotOrder: 57,
  openFile: 58,
  notOpened: 59,
  openRecord: 60,
  now: 61,
  studySoFar: 62,
  tools: 63,
  since: 64,
  waiting: 65,
  consequence: 66,
  charts: 67,
  scorer: 68,
  interval: 69,
  resamplingUnit: 70,
  limitationsRule: 71,
  earlierDecision: 72,
  citedDelta: 73,
  featuresAlone: 74,
  yourWords: 75,
  addWords: 76,
  frame: 77,
  produce: 78,
  assessAndCompare: 79,
  decideAndFollow: 80,
  attempts: 81,
  attempt: 82,
  assessments: 83,
  comparisons: 84,
  countsOnceCited: 85,
  byRule: 86,
  recoverable: 87,
  declared: 88,
  source: 89,
  toHandle: 90,
  interrupted: 91,
  recoverByTerminal: 92,
  handOver: 93,
  reportByTerminal: 94,
  protocolRevision: 95,
  noEnd: 96,
  latestDecision: 97,
  seeDecision: 98,
  observationSet: 99,
  noDecisionWaits: 100,
  pendingOne: 101,
  everythingToHandle: 102,
  dataProfile: 103,
  days: 104,
  profileFailed: 105,
  profileDiffers: 106,
  targetOverTime: 107,
  distributions: 108,
  notAvailable: 109,
  associations: 110,
  flaggedAt: 111,
  againstTarget: 112,
  drawnFrom: 113,
  partition: 114,
  firstDay: 115,
  lastDay: 116,
  value: 117,
  count: 118,
  from: 119,
  to: 120,
  measure: 121,
  items: 122,
  columns: 123,
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
  profile: "#profile-",
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
const value = (content: unknown, attrs = ""): string => {
  const displayed = text(content);
  return `<span${displayed === "" ? "" : attrs}>${displayed}</span>`;
};
const marked = (content: unknown, tag = "span", attrs = ""): string => `<${tag} data-text${attrs}>${text(content)}</${tag}>`;
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
const link = (kind: string, index: number, number: unknown, part = PART_OF.get(kind)!, attrs = ""): string => `<a href="${HREF[part]}${index}" data-kind="${kind}"${attrs}>${written(number)}</a>`;
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

// The object of the lesson read when it is usable beside the status read: `ok` true and the same Write sequence. Otherwise there is
// none, and the document draws no card and no failure text.
export function usableLesson(object: Entry | undefined, lesson: Entry | undefined): Entry | undefined {
  return object !== undefined && lesson !== undefined && lesson.ok === true && lesson.write_sequence === object.write_sequence ? lesson : undefined;
}

// Mark the element that renders a lesson value. The read and path are fixed by the renderer, and every displayed entry can carry the same path.
const lessonValue = (key: string): string => key === "" ? "" : ` data-lesson-value="${key}"`;
const ATTEMPT_COUNT_KEYS = new Map([
  ["produced", "status attempts[].item_counts.produced"],
  ["failed", "status attempts[].item_counts.failed"],
  ["missing", "status attempts[].item_counts.missing"],
]);

// Cards stand after Record, and list a key path only when the page already renders its value.
export function cardsOf(lesson: Entry | undefined, body: string): string {
  const cards = list(lesson?.cards).map((card) => {
    const items = list(card.key_paths).flatMap((path) => {
      if (typeof path.read !== "string" || typeof path.path !== "string") return [];
      const key = escaped(`${path.read} ${path.path}`);
      return body.includes(` data-lesson-value="${key}"`) ? [`<li data-shows="${key}">${marked(path.path, "code")}</li>`] : [];
    });
    return ['<details data-element="card">', `<summary>${marked(card.title)}</summary>`, marked(card.text, "p"), ...(items.length === 0 ? [] : [`<ul>\n${items.join("\n")}\n</ul>`]), "</details>"].join("\n");
  });
  return cards.length === 0 ? "" : ['<div data-part="lesson">', ...cards, "</div>"].join("\n");
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
  const profile = view.object ? profileOf(view.object, view.profile, inert) : undefined;
  const study = view.object ? studyOf(view.object, view.decision, busy, view.unanswered === true, recorded, view.sent, figures && list(figures.comparisons), profile?.step ?? "") : undefined;
  parts.push(...[toHandleLineOf(view.object), nowOf(view.object, study?.now ?? "", study?.count ?? "", profile?.now ?? ""), toHandleListOf(view.object)].filter((part) => part !== ""));
  if (study && study.waiting !== "") parts.push(['<section data-part="waiting">', `<h2>${label("waiting")}</h2>`, study.waiting, "</section>"].join("\n"));
  const after = ['<section data-part="path">', `<h2>${label("studySoFar")}</h2>`, ...(study ? [study.path] : []), "</section>", toolsOf(inert)].join("\n");
  // The cards stand between the two, and name the places of either that show a value of their key paths.
  const cards = cardsOf(view.object ? usableLesson(view.object, view.lesson) : undefined, `${parts.join("\n")}\n${after}`);
  if (cards !== "") parts.push(cards);
  parts.push(after);
  return parts.join("\n");
}

// Tools, last on the page: Read again, then "Hand over" last: the `report` command as fixed text, which the panel never starts.
function toolsOf(inert: string): string {
  return [
    '<section data-part="tools">',
    `<h2>${label("tools")}</h2>`,
    `<p><button data-message="${contract.messages[0]}"${inert}>${label("readAgain")}</button></p>`,
    `<div data-element="hand-over">`,
    `<h3>${label("handOver")}</h3>`,
    `<p>${label("reportByTerminal")}</p>`,
    "</div>",
    "</section>",
  ].join("\n");
}

// The band under the path: the Write sequence of the read, and how many write-journal entries the panel's read gives after the
// Write sequence of the object it held, as a link to the place of their lines.
function bandOf(object: Entry): string[] {
  const entries = list(object.writes_since);
  const revisions = list(object.revisions);
  return [
    `<p data-element="band">${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence, undefined, lessonValue("status write_sequence"))}</p>`,
    // The lines of the entries stand in a closed fold, so that Now keeps its place in the first screen.
    [`<details data-part="since"${anchor("since", 0)}>`, `<summary>${label("since")} ${link("writes_since", 0, entries.length)}</summary>`, ...(entries.length === 0 ? [] : [`<ul>\n${entries.map((entry) => sinceLineOf(entry, entries, revisions)).join("\n")}\n</ul>`]), "</details>"].join("\n"),
  ];
}

// One line of `writes_since`: the command, the phase of the entry, the outcome of an end and what it wrote, each record by its kind and
// its id as plain text; a revision as "Protocol revision" and its number, never as the word revision before a digest; a begin that no
// end follows says so.
function sinceLineOf(entry: Entry, entries: Entry[], revisions: Entry[]): string {
  const written = list(entry.written).map((each) => {
    if (each.kind !== "revision") return `${value(each.kind)} ${value(each.id)}`;
    const revision = revisions.find((spec) => spec.revision === each.id);
    return `${label("protocolRevision")} ${revision === undefined ? escaped(contract.no_value) : link("revision_number", 0, revision.revision_number)}`;
  });
  const ended = entry.phase === "end" || entries.some((other) => other.phase === "end" && other.command === entry.command && other.request_id === entry.request_id);
  const parts = [value(entry.command), value(entry.phase), ...(entry.phase === "end" ? [value(entry.outcome)] : []), ...written, ...(ended ? [] : [`<span>${label("noEnd")}</span>`])];
  return `<li data-element="since-line">${parts.join(" ")}</li>`;
}

// "To handle": one compact line above Now when `next_step` lists Attempts to handle, with their count, as a link to the full list, which
// stands after Now with the id `tohandle-list`; each entry names the Attempt and the command that handles it, as fixed text.
function toHandleLineOf(object: Entry | undefined): string {
  const ids = Array.isArray(record(object?.next_step).to_handle) ? (record(object?.next_step).to_handle as unknown[]) : [];
  if (ids.length === 0) return "";
  return ['<section data-part="tohandle-line">', `<h2>${label("toHandle")}</h2>`, `<p>${label("interrupted")} <a href="#tohandle-list" data-kind="to_handle">${written(ids.length)}</a></p>`, "</section>"].join("\n");
}

function toHandleListOf(object: Entry | undefined): string {
  const ids = Array.isArray(record(object?.next_step).to_handle) ? (record(object?.next_step).to_handle as unknown[]) : [];
  if (ids.length === 0) return "";
  const rows = ids.map((id) => {
    const attempt = list(object?.attempts).find((each) => each.attempt_id === id);
    return `<li>${label("attempt")} ${value(id)} ${value(attempt?.technical_status, lessonValue("status attempts[].technical_status"))} ${markOf("!", "recoverable")} <span>${label("recoverByTerminal")}</span></li>`;
  });
  // The list opens on its own heading, "Everything to handle", other than the compact line's "To handle", so that no two headings of the
  // page share a text (D-161 addendum 2, #75 comment 7197719288), and above the level of the Control's and the Candidate's, so that it
  // cannot read as part of the Candidate drawn above it in Now; the section headings of the page stay the five.
  return ['<section data-part="tohandle" id="tohandle-list">', `<h3>${label("everythingToHandle")}</h3>`, `<ul>\n${rows.join("\n")}\n</ul>`, "</section>"].join("\n");
}

// Under rule 3, after the core's text: each Decision `next_step` names, its option as a link to its part, the phrase of whether it applies
// and the state of its evidence.
function lookAgainOf(object: Entry, step: Entry): string[] {
  const decisions = list(object.decisions);
  return (Array.isArray(step.ids) ? step.ids : []).flatMap((id) => {
    const index = decisions.findIndex((each) => each.decision_id === id);
    if (index < 0) return [];
    const decision = decisions[index];
    const change = record(decision.evidence_change);
    const state = "state" in change ? ` <span>${phrase(change.state)}</span>` : "";
    return [`<p data-element="look-again"><a href="${HREF.decision}${index}">${marked(decision.option, "strong", lessonValue("status decisions[].option"))}</a> ${value(APPLIES.get(String(decision.applies)), lessonValue("status decisions[].applies"))}${state}</p>`];
  });
}

// Under rule 4, after the sentence that no decision waits for the person: the latest Decision as one line (D-159), its option, its author
// with the mark of a rule's Decision, the phrase of whether it applies, and a link to its part in the step of the Decisions, which opens
// that fold.
function latestOf(object: Entry): string[] {
  const decisions = list(object.decisions);
  const index = decisions.length - 1;
  if (index < 0) return [];
  const decision = decisions[index];
  const rule = decision.author === "proxy" ? ` ${markOf("\u25c7", "byRule")}` : "";
  const applies = APPLIES.get(String(decision.applies));
  return [
    `<p data-element="latest-decision">${label("latestDecision")} ${marked(decision.option, "strong", lessonValue("status decisions[].option"))} ${label("author")} ${value(decision.author, lessonValue("status decisions[].author"))}${rule}${applies === undefined ? "" : ` <span${lessonValue("status decisions[].applies")}>${escaped(applies)}</span>`} <a href="${HREF.decision}${index}">${label("seeDecision")}</a></p>`,
  ];
}

// Now, under its heading, from the read's `next_step`: with its kind `decide`, `pending`, the whole part of the pending decision its first
// id names, whose question is Now's line; with `look_again`, its text; with no kind, the label that no decision waits for the person.
// Without an object read, Now holds nothing.
function nowOf(object: Entry | undefined, pending: string, count = "", frame = ""): string {
  const lines = [`<section data-part="now" id="now">`, `<div data-element="now-heading"><h2>${label("now")}</h2>${count === "" ? "" : ` ${count}`}</div>`];
  if (object) {
    const step = record(object.next_step);
    if (step.kind === "decide" && pending !== "") lines.push(pending);
    else if (step.kind === "look_again") lines.push(`<p data-element="now-question">${marked(step.text, "strong")}</p>`, ...lookAgainOf(object, step));
    // Rule 4: the sentence that no decision waits for the person, true whatever To handle lists (D-161 addendum, #75 comment
    // 7197277304), then the latest Decision (D-159).
    else lines.push(`<p data-element="now-question">${label("noDecisionWaits")}</p>`, ...latestOf(object));
    if (frame !== "") lines.push(frame);
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
  if (written?.outcome === "client_refusal") lines.push(`<p>${label("missing")} ${written.missing.map((entry) => value(entry)).join(" ")}</p>`);
  if (written?.outcome === "success") lines.push(recordedOf(record(written.object.decision).decision_id, view));
  return lines;
}

// A write the CLI accepted: the Decision of the read that follows, by its id, or the answer's id when that read holds none.
function recordedOf(id: unknown, view: View): string {
  const decisions = view.failure ? [] : list(view.object?.decisions);
  const index = decisions.findIndex((decision) => decision.decision_id === id);
  if (index < 0) return `<p>${label("recordedId")} ${value(id)}</p>`;
  return `<p>${label("recorded")} <a href="${HREF.decision}${index}" data-recorded>${marked(decisions[index].option, "strong", lessonValue("status decisions[].option"))}</a></p>`;
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
// other one in a closed fold whose summary is its question; and `path`, the Study so far, whose first step is `profile` when there is one.
function studyOf(object: Entry, linked: string | undefined, busy: boolean, held: boolean, recorded: unknown, sent: View["sent"], figures: Entry[] | undefined, profile = ""): { count: string; now: string; waiting: string; path: string } {
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
  const studyPart = [`<div data-part="study"${anchor("study", 0)}>`, `<p>${value(study.study_id)} ${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence, undefined, lessonValue("status write_sequence"))}</p>`, "</div>"].join("\n");
  const attempts = list(object.attempts);
  const assessments = shown.assessments;
  const comparisons = shown.comparisons;
  const decisions = list(object.decisions);
  const deviations = list(object.declared_deviations);
  // The steps of each moment, in a fixed order of kinds: the Study, its Attempts, its Assessments and Comparisons and its Decisions, which
  // the Study's own citations make the order in which each of these kinds first appears in the write journal (D-161); then, last whenever
  // present, its Declared deviations, which nothing in the core orders against the others (D-161 addendum 2, #75 comment 7197719288). A
  // step stands only when the read holds a record of its kind; the Study's always.
  // The Decisions are built before the Assessments and the Comparisons, so that a record a Decision cites keeps its part in that Decision
  // and the steps of Assess and compare show its summary or a link to it.
  const decideAndFollow = [
    ...(decisions.length === 0 ? [] : [decisionsStepOf(decisions, [`<h4>${label("decisions")}</h4>`, decisionsOf(decisions, linked, recorded, shown)].join("\n"))]),
    ...(deviations.length === 0 ? [] : [deviationsStepOf(deviations, shown)]),
  ];
  const produce = attempts.length === 0 ? [] : [attemptsStepOf(attempts, shown)];
  const assess = [...(assessments.length === 0 ? [] : [assessmentsStepOf(shown)]), ...(comparisons.length === 0 ? [] : [comparisonsStepOf(shown)])];
  // The count of pending decisions stands on Now's heading line, only when n > 0, at no cost of height, in the singular for one (D-161
  // addendum 2, #75 comment 7197719288).
  const count = pending.length === 0 ? "" : `<span data-element="count">\u00b7 ${link("pending_decisions", 0, pending.length)} ${label(pending.length === 1 ? "pendingOne" : "pendingCount")}</span>`;
  return { count, now: parts[0] ?? "", waiting: waiting.join("\n"), path: [
    momentOf("frame", [...(profile === "" ? [] : [profile]), stepOf("study", value(study.study_id), studyPart)]),
    momentOf("produce", produce),
    momentOf("assessAndCompare", assess),
    momentOf("decideAndFollow", decideAndFollow),
  ].filter((part) => part !== "").join("\n") };
}

// A moment of the Study so far: a plain heading, then its steps; nothing when it holds none.
const momentOf = (name: keyof typeof LABEL, steps: string[]): string => (steps.length === 0 ? "" : [`<h3>${label(name)}</h3>`, ...steps].join("\n"));

// A mark that restates one read fact, hidden from assistive technology, with the word it stands for after it.
const markOf = (mark: string, word: keyof typeof LABEL): string => `<span data-mark aria-hidden="true">${mark}</span> <span>${label(word)}</span>`;

// A done step: one line, its mark first when it has one, then its name and its values, which folds open to its review form, then its chart,
// and closes on its limitation; each part stands only when the step has one.
function stepOf(name: keyof typeof LABEL, values: string, form: string, chart = "", limitation = "", mark = ""): string {
  return [
    `<details data-step="${name}">`,
    `<summary>${mark === "" ? "" : `${mark} `}<span data-element="step">${label(name)}</span>${values === "" ? "" : ` ${values}`}</summary>`,
    `<div data-element="form">\n${form}\n</div>`,
    ...(chart === "" ? [] : [`<div data-element="chart">\n${chart}\n</div>`]),
    ...(limitation === "" ? [] : [`<div data-element="limitation">\n${limitation}\n</div>`]),
    "</details>",
  ].join("\n");
}

// The Attempts: each with its id, its Mode, its technical status and the mark of a recoverable one. "Its `item_counts`, and anything
// derived from its outputs, show only once an Assessment cites it" (D-136, question 1): an Attempt is cited when an Assessment holds the
// `observation_set_id` the read gives the Attempt; its counts then show, each count a link to the part of that Assessment.
function attemptsStepOf(attempts: Entry[], shown: Shown): string {
  const rows = attempts.map((attempt) => {
    const cited = attempt.observation_set_id === null || attempt.observation_set_id === undefined ? -1 : shown.assessments.findIndex((each) => each.observation_set_id === attempt.observation_set_id);
    const mark = attempt.recoverable === true ? ` ${markOf("!", "recoverable")}` : "";
    if (cited < 0) {
      // "its id and its Observation set's id are plain text, never links" (D-143, correction 1).
      const set = attempt.observation_set_id === null || attempt.observation_set_id === undefined ? "" : ` ${label("observationSet")} ${value(attempt.observation_set_id)}`;
      return `<li data-part="attempt">${label("attempt")} ${value(attempt.attempt_id)}${set} ${value(attempt.mode, lessonValue("status attempts[].mode"))} ${value(attempt.technical_status, lessonValue("status attempts[].technical_status"))}${mark} <span>${label("countsOnceCited")}</span></li>`;
    }
    const counts = Object.entries(record(attempt.item_counts)).map(([key, number]) => `${value(key)} ${link("item_counts", cited, number, undefined, lessonValue(ATTEMPT_COUNT_KEYS.get(key) ?? ""))}`);
    return `<li data-part="attempt">${label("attempt")} ${value(attempt.attempt_id)} ${value(attempt.mode, lessonValue("status attempts[].mode"))} ${value(attempt.technical_status, lessonValue("status attempts[].technical_status"))}${mark}${counts.length === 0 ? "" : ` ${counts.join(" ")}`}</li>`;
  });
  const modes = [...new Set(attempts.map((attempt) => attempt.mode))].map((entry) => value(entry, lessonValue("status attempts[].mode"))).join(" ");
  const recoverable = attempts.some((attempt) => attempt.recoverable === true) ? markOf("!", "recoverable") : "";
  return stepOf("attempts", modes, `<ul>\n${rows.join("\n")}\n</ul>`, "", "", recoverable);
}

// The Assessments: the line holds the first Metric of the latest one; each has its part where the document shows none yet, and the step
// closes on the latest one's limitations.
function assessmentsStepOf(shown: Shown): string {
  const latest = shown.assessments.length - 1;
  const metric = record(list(shown.assessments[latest].metrics)[0]);
  const line = `${value(metric.id, lessonValue("status assessments[].metrics[].id"))} ${link("value", latest, metric.value, undefined, lessonValue("status assessments[].metrics[].value"))} ${marked(metric.unit)}`;
  const form = shown.assessments.map((assessment) => assessmentOf(undefined, assessment.assessment_id, shown)).join("\n");
  const limitations = Array.isArray(shown.assessments[latest].limitations) ? shown.assessments[latest].limitations : [];
  return stepOf("assessments", line, form, "", limitations.length === 0 ? "" : `<ul>\n${limitations.map((each) => marked(each, "li")).join("\n")}\n</ul>`);
}

// The Comparisons: the line holds the delta of the latest one; each has its part, or its summary where the document shows its part already.
function comparisonsStepOf(shown: Shown): string {
  const latest = shown.comparisons.length - 1;
  const delta = record(shown.comparisons[latest].delta);
  const line = `${delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", latest, delta.value, undefined, lessonValue("status comparisons[].delta.value"))} ${value(delta.metric)} ${marked(delta.unit)}`;
  const form = shown.comparisons
    .map((comparison) => {
      const roles = record(comparison.roles);
      const ids = "roles" in comparison ? [roles.control_assessment_id, roles.candidate_assessment_id] : [];
      return shown.parts.has(comparison) ? summaryOf(comparison, shown, ids) : comparisonOf(comparison.comparison_id, shown, ids);
    })
    .join("\n");
  return stepOf("comparisons", line, form);
}

// The Decisions: the line holds the latest one's option and whether it applies, with the mark of a Decision made by a rule.
function decisionsStepOf(decisions: Entry[], form: string): string {
  const latest = decisions[decisions.length - 1];
  if (latest === undefined) return stepOf("decisions", "", form);
  const applies = APPLIES.get(String(latest.applies));
  const line = `${marked(latest.option, "strong", lessonValue("status decisions[].option"))}${applies === undefined ? "" : ` <span${lessonValue("status decisions[].applies")}>${escaped(applies)}</span>`}`;
  return stepOf("decisions", line, form, "", "", latest.author === "proxy" ? markOf("\u25c7", "byRule") : "");
}

// The Declared deviations, with the mark of a declared one where one is not withdrawn.
function deviationsStepOf(deviations: Entry[], shown: Shown): string {
  const declared = deviations.some((deviation) => deviation.withdrawn === false) ? markOf("\u2016", "declared") : "";
  return stepOf("deviations", "", deviationsOf(deviations, shown), "", "", declared);
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
  // The box of the person's own words, in a fold directly above the control that records, empty but where the write `sent` held words
  // for this decision.
  const words = asked && Array.isArray(sent.words) ? sent.words.join("") : "";
  const choices = [
    `<fieldset aria-labelledby="${question}" ${anchor("choices", index)}>`,
    ...options,
    // "2. the words box, as a closed "Add your words" above Record" (D-151, answer 5): open where it holds the words of the write `sent`.
    `<details data-element="add-words"${words === "" ? "" : " open"}><summary>${label("addWords")}</summary>`,
    `<label data-element="words">${label("yourWords")} <textarea data-words="${index}" rows="2"${inert}>${text(words)}</textarea></label>`,
    "</details>",
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
    const coverageLine = `<p data-element="coverage">${label("coverage")} ${coverage.map(([key, number]) => `${value(key)} ${link("coverage", index, number, undefined, key === "paired" ? lessonValue("status comparisons[].coverage.paired") : "")}`).join(" ")}</p>`;
    // "when the delta's `value` is null the Comparison's part holds no roles' element" (chadlis/hypotrail#177).
    const rolesLine =
      delta.value !== null && ("control" in delta || "candidate" in delta)
        ? `<p data-element="roles">${label("control")} ${link("control", index, delta.control)} ${label("candidate")} ${link("candidate", index, delta.candidate)}</p>`
        : "";
    const messages = list(comparison.warnings).map((warning) => warning.message);
    const warnings = list(comparison.warnings).map((warning) => `<li${lessonValue("status comparisons[].warnings")}>${value(warning.code)} ${marked(warning.message)}</li>`);
    const all = Array.isArray(comparison.limitations) ? comparison.limitations : [];
    // "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
    const limitations = (choices === "" ? all : all.filter((limitation) => !messages.includes(limitation))).map((limitation) => marked(limitation, "li", lessonValue("status comparisons[].limitations")));
    const listOf = (kind: "warnings" | "limitations", items: string[]): string =>
      [`<div data-part="${kind}"${first ? anchor(kind, index) : ""}>`, `<h4>${label(kind)}</h4>`, `<ul>\n${items.join("\n")}\n</ul>`, "</div>"].join("\n");
    const status = `${label("comparabilityStatus")} ${value(record(comparison.comparability).status, lessonValue("status comparisons[].comparability.status"))}`;
    const [figures, rest] = figuresOf(shown.figures, id, index, delta, first);
    const paths = [[PAIRED_DELTAS, comparison.paired_deltas_ref], [POPULATION, comparison.population_ref]].flatMap(([ref, output]) => {
      const path = record(output).path;
      return typeof path === "string" ? [`<p data-element="output">${label("outputPath")} ${opening("comparison", index, ref as string, path, shown)}</p>`] : [];
    });
    if (choices !== "") {
      lines.push(deltaOf(delta, index, comparison.interval), contextOf(context ?? [], shown), coverageLine);
      lines.push(`<p data-element="frame">${label("scorer")} ${value(scorerOf(roles[0], shown), lessonValue("status assessments[].scorer.id"))} ${status}</p>`, listOf("warnings", warnings));
      lines.push(`<p data-element="limits">${label("warnings")} ${link("warnings", index, warnings.length)} ${label("limitations")} ${link("limitations", index, limitations.length)} <span>${label("limitationsRule")}</span></p>`, choices);
      const fold = [featuresChartOf(roles, delta, shown), rolesLine, deltaChartOf(delta, index, roles, shown), figures, rest].filter((line) => line !== "");
      if (fold.length > 0) lines.push(['<details data-element="charts">', `<summary>${label("charts")}</summary>`, ...fold, "</details>"].join("\n"));
      lines.push(`<p data-element="definition">${marked(delta.definition, "span", lessonValue("status comparisons[].delta.definition"))}</p>`, coverageChartOf(coverage, index), ...paths);
      lines.push(recordFileOf("comparison", index, comparison.comparison_id, shown), listOf("limitations", limitations));
    } else {
      lines.push(deltaOf(delta, index, comparison.interval), coverageLine, rolesLine, deltaChartOf(delta, index, roles, shown), featuresChartOf(roles, delta, shown), figures);
      lines.push(`<p data-element="definition">${marked(delta.definition, "span", lessonValue("status comparisons[].delta.definition"))}</p>`, coverageChartOf(coverage, index), `<p>${status}</p>`, ...paths);
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
      const lines = [`<p data-element="context">${label("earlierDecision")} <a href="${HREF.decision}${index}">${marked(decision.option, "strong", lessonValue("status decisions[].option"))}</a> ${value(APPLIES.get(String(decision.applies)), lessonValue("status decisions[].applies"))}</p>`];
      const cited = shown.comparisons.findIndex((each) => Array.isArray(decision.cited_ids) && decision.cited_ids.includes(each.comparison_id));
      const delta = record(shown.comparisons[cited]?.delta);
      if (cited >= 0) lines.push(`<p data-element="cited-delta">${label("citedDelta")} ${delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", cited, delta.value, undefined, lessonValue("status comparisons[].delta.value"))} ${value(delta.metric)} ${marked(delta.unit)}</p>`);
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
  const marks: [number, string][] = QUARTILES.map(([key, name]) => [number(quartiles[key])!, `<span${key === "median" ? ' data-key="median"' : ""}>${label(name)} ${link("quartile", index, quartiles[key], undefined, lessonValue("figures comparisons[].quartiles"))}</span>`]);
  marks.push([number(delta.value)!, `<span data-key="delta">${label("delta")} ${link("delta", index, delta.value, undefined, lessonValue("status comparisons[].delta.value"))}</span>`]);
  if (ends[0] <= 0 && 0 <= ends[1]) marks.push([0, `<span data-key="zero">${label("zero")}</span>`]);
  // In the order of the axis; `sort` keeps the order above between equal numbers.
  marks.sort((a, b) => a[0] - b[0]);
  const few = pairs.length < FEW;
  const shownDots = dotsOf(pairs as Pair[], index, delta, agent, few, first);
  return [
    [
      "<div data-figures>",
      heading,
      `<p data-element="caption">${marked(delta.definition, "span", lessonValue("status comparisons[].delta.definition"))}</p>`,
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
    `<div data-element="dots"${lessonValue("figures comparisons[].paired_deltas")}>`,
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
    `<p data-element="definition">${marked(delta.definition, "span", lessonValue("status comparisons[].delta.definition"))}</p>`,
    deltaChartOf(delta, index, roles, shown),
    "</div>",
  ]
    .filter((line) => line !== "")
    .join("\n");
}

// The delta's element: its value as a link, or the word of a withheld delta, with its Metric and unit; then, given the Comparison's
// `interval` when the read holds one, its level and its two bounds as links to the Comparison, and its resampling unit, or, when a bound
// is null, its reason. A withheld delta holds no interval, not even its reason: the interval would show what the withheld delta hides
// (D-159).
function deltaOf(delta: Entry, index: number, given?: unknown): string {
  const shownDelta = delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", index, delta.value, undefined, lessonValue("status comparisons[].delta.value"));
  let slot = "";
  if (delta.value !== null && typeof given === "object" && given !== null) {
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
      return metric === undefined ? undefined : { shown: link("value", at, metric.value, undefined, lessonValue("status assessments[].metrics[].value")), value: number(metric.value) };
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
  const roleTarget = role === undefined ? "" : lessonValue(
    role === "control" ? "status comparisons[].roles.control_assessment_id" : "status comparisons[].roles.candidate_assessment_id",
  );
  let body = `<p>${label("assessment")} ${value(id, roleTarget)}</p>`;
  if (assessment !== undefined && shown.parts.has(assessment)) {
    body = `<p>${label("assessment")} <a href="${HREF.assessment}${index}"${roleTarget}>${text(id)}</a></p>`;
  } else if (assessment !== undefined) {
    shown.parts.add(assessment);
    const metrics = list(assessment.metrics).map(
      (metric) => `<li>${label("metric")} ${value(metric.id, lessonValue("status assessments[].metrics[].id"))} ${link("value", index, metric.value, undefined, lessonValue("status assessments[].metrics[].value"))} ${marked(metric.unit)} ${label("status")} ${value(metric.status)}</li>`,
    );
    const output = record(assessment.per_item_ref).path;
    const path = typeof output === "string" ? `<p data-element="output">${label("outputPath")} ${opening("assessment", index, PER_ITEM, output, shown)}</p>` : "";
    const own = recordFileOf("assessment", index, id, shown);
    const scorer = `<p>${label("scorer")} ${value(record(assessment.scorer).id, lessonValue("status assessments[].scorer.id"))}</p>`;
    body = [`<div data-part="assessment"${anchor("assessment", index)}>`, body, scorer, path, own, `<ul>\n${metrics.join("\n")}\n</ul>`, "</div>"].filter((line) => line !== "").join("\n");
  }
  return role === undefined ? body : [`<div data-role="${role}">`, `<h4>${label(role)}</h4>`, body, "</div>"].join("\n");
}

function decisionsOf(decisions: Entry[], linked: string | undefined, recorded: unknown, shown: Shown): string {
  const parts = decisions.map((decision, index) => decisionOf(decision, index, decision.decision_id === linked, decision.decision_id === recorded, shown));
  if (linked !== undefined && !decisions.some((decision) => decision.decision_id === linked)) parts.unshift(`<p>${label("noDecision")} ${value(linked)}</p>`);
  return parts.join("\n");
}

// A recorded Decision: what was chosen and whether it applies, its id, its question, the state of its evidence with each line of
// it and its reasons, then who recorded it, what it cites, and the Assessments of each line. `recorded` marks the Decision the
// write this document follows recorded.
function decisionOf(decision: Entry, index: number, linked: boolean, recorded: boolean, shown: Shown): string {
  const cited = Array.isArray(decision.cited_ids) ? decision.cited_ids : [];
  const reasons = list(decision.reasons).map((reason) => `<li${lessonValue("status decisions[].reasons")}>${value(reason.reason)} ${value(reason.id)}</li>`);
  const applies = APPLIES.get(String(decision.applies));
  const change = decision.evidence_change !== null && typeof decision.evidence_change === "object" ? record(decision.evidence_change) : undefined;
  const lines = [
    `<section data-part="decision"${anchor("decision", index)}${linked ? " data-linked" : ""}${recorded ? " data-recorded" : ""}>`,
    `<h3>${marked(decision.option, "strong", lessonValue("status decisions[].option"))}${applies === undefined ? "" : ` <span data-applies="${decision.applies === true ? "yes" : "no"}"${lessonValue("status decisions[].applies")}>${escaped(applies)}</span>`}</h3>`,
    ...(linked ? [`<p>${label("linked")}</p>`] : []),
    `<p>${value(decision.decision_id)}</p>`,
    recordFileOf("decision", index, decision.decision_id, shown),
    `<p data-element="question"${lessonValue("status decisions[].question")}>${marked(decision.question)}</p>`,
    ...(change ? [stateOf(change, list(decision.reasons)), linesOf(change, index, shown)] : []),
    ...(reasons.length > 0 ? [`<h4>${label("reasons")}</h4>`] : []),
    `<ul data-element="reasons">\n${reasons.join("\n")}\n</ul>`,
    `<p>${label("author")} ${value(decision.author, lessonValue("status decisions[].author"))}${decision.source === null || decision.source === undefined ? "" : ` ${label("source")} ${marked(decision.source, "span", lessonValue("status decisions[].source"))}`}</p>`,
    ...(decision.author === "proxy" ? [`<p data-element="proxy">${markOf("\u25c7", "byRule")}</p>`] : []),
    `<h4>${label("citedIds")}</h4>`,
    `<ul data-element="cited">\n${cited.map((id) => `<li>${value(id, lessonValue("status decisions[].cited_ids"))}</li>`).join("\n")}\n</ul>`,
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
  lines.push(`<p>${label("applies")} ${value(decision.applies, lessonValue("status decisions[].applies"))}</p>`);
  // The Assessments of each line stand after the cited Comparison's, so that a role's Assessment has its part under its role.
  if (change) lines.push(...list(change.lines).flatMap((line) => [assessmentOf(undefined, line.assessment_id, shown), assessmentOf(undefined, line.latest_assessment_id, shown)]));
  lines.push("</section>");
  return lines.filter((line) => line !== "").join("\n");
}

const phrase = (state: unknown): string => text(PHRASES.get(String(state)) ?? state);

// The state of a Decision's evidence, with `revision_changed` beside it when a reason.
function stateOf(change: Entry, reasons: Entry[]): string {
  const beside = reasons.find((reason) => reason.reason === BESIDE_THE_STATE);
  return `<p data-element="evidence"><span>${phrase(change.state)}</span>${beside ? ` ${value(beside.reason, lessonValue("status decisions[].reasons"))}` : ""}</p>`;
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
    const mark = deviation.withdrawn === false ? `${markOf("\u2016", "declared")} ` : "";
    return `<li data-part="deviation">${value(deviation.declared_deviation_id)} ${marked(deviation.text)} ${mark}${label("withdrawn")} ${value(deviation.withdrawn)}${file === "" ? "" : ` ${file}`}</li>`;
  });
  return `<ul>\n${lines.join("\n")}\n</ul>`;
}

// --- the data profile ------------------------------------------------------------------------------------------------------------

// The code of a refusal of a Study the profile does not cover: the document then holds nothing of the profile.
const NOT_COVERED = "UNSUPPORTED_CAPABILITY";
// The value of `workload_protocol` when the Workload as declared now no longer gives the Study's Protocol.
const DIFFERS = "differs";
// The keys of the five numbers of a profile's figures, in their order.
const FIVE = QUARTILES.map(([key]) => key);

// The object of the profile read when it is usable beside the status read: `ok` true and the same Write sequence.
export function usableProfile(object: Entry | undefined, profile: Entry | undefined): Entry | undefined {
  return object !== undefined && profile !== undefined && profile.ok === true && profile.write_sequence === object.write_sequence ? profile : undefined;
}

// A number of the profile, as a link to its step.
const linked = (number: unknown): string => link("profile", 0, number);

// The Data profile, from the answer of the profile call: `step`, the first step of the Study so far, and `now`, the band and the target
// over time, which Now shows open when the read lists no Attempt. A refusal of a Study the profile does not cover gives neither. Any other
// refusal gives a step that holds the fixed sentence of a failure with its code, and a call with no answer or a read that cannot stand
// beside the status read the sentence alone, each with Read again.
function profileOf(object: Entry, answer: Outcome | undefined, inert: string): { step: string; now: string } {
  if (answer === undefined) return { step: "", now: "" };
  const code = answer.outcome === "refusal" ? record(answer.error).code : undefined;
  if (code === NOT_COVERED) return { step: "", now: "" };
  const profile = answer.outcome === "success" ? usableProfile(object, answer.object) : undefined;
  const open = `<details data-part="profile" data-step="profile"${anchor("profile", 0)}>`;
  const name = `<span data-element="step">${label("dataProfile")}</span>`;
  if (profile === undefined) {
    const failed = `<span data-element="profile-failed">${label("profileFailed")}</span>${code === undefined ? "" : ` ${value(code)}`}`;
    return { step: [open, `<summary>${name} ${failed}</summary>`, `<div data-element="form">`, `<p><button data-message="${contract.messages[0]}"${inert}>${label("readAgain")}</button></p>`, "</div>", "</details>"].join("\n"), now: "" };
  }
  const target = targetOf(profile);
  const form = [
    ...(profile.workload_protocol === DIFFERS ? [`<p data-element="differs">${label("profileDiffers")}</p>`] : []),
    target,
    distributionsOf(profile),
    matrixOf(profile),
    againstOf(profile),
  ];
  const step = [open, `<summary>${name} · ${linked(profile.items)} ${marked(profile.partition)} ${label("days")}</summary>`, `<div data-element="form">\n${form.join("\n")}\n</div>`, "</details>"].join("\n");
  return { step, now: list(object.attempts).length === 0 ? target : "" };
}

// A closed fold of the numbers a figure is drawn from.
const numbersOf = (body: string): string => [`<details data-element="numbers">`, `<summary>${label("drawnFrom")}</summary>`, body, "</details>"].join("\n");
const table = (heads: (keyof typeof LABEL)[], rows: string[][]): string =>
  `<table data-element="profile-numbers"><tr>${heads.map((head) => `<th>${label(head)}</th>`).join("")}</tr>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</table>`;
const fiveOf = (figures: unknown): string[] => FIVE.map((key) => linked(record(record(figures).quartiles)[key] ?? null));
const fiveNumbers = (figures: unknown): Five | null => {
  const five = FIVE.map((key) => number(record(record(figures).quartiles)[key]));
  return five.includes(null) ? null : (five as Five);
};

// The band and the target over time: one column per `train` day under the band, the band's spans named in its order, then in a fold
// the spans' days and the target's five numbers; the days themselves get no table.
function targetOf(profile: Entry): string {
  const band = list(profile.band);
  const target = record(profile.target);
  const spans = band.map((span) => ({ first: dayOf(String(span.first)), last: dayOf(String(span.last)), kind: span.name === profile.partition ? "band-read" : "band" }));
  const days = list(target.series).flatMap((day): [number, number][] => (number(day.value) === null ? [] : [[dayOf(String(day.date)), number(day.value)!]]));
  const key = band.map((span) => `<span data-key="${span.name === profile.partition ? "band-read" : "band"}">${marked(span.name)}</span>`).join(" ");
  const rows = band.map((span) => [marked(span.name), marked(span.first), marked(span.last)]);
  const quartiles = QUARTILES.map(([, name], at) => `<span>${label(name)} ${fiveOf(target.figures)[at]}</span>`).join(" ");
  return [
    '<div data-figure="profile-target">',
    `<h4>${label("targetOverTime")} (${marked(target.column)}, ${marked(target.unit)})</h4>`,
    timeline(spans, days),
    `<p data-element="band-key">${key}</p>`,
    numbersOf([table(["partition", "firstDay", "lastDay"], rows), `<p data-element="quartiles">${quartiles}</p>`].join("\n")),
    "</div>",
  ].join("\n");
}

const availability = (column: Entry): string => (column.available === false ? ` <span data-element="unavailable">${label("notAvailable")}</span>` : "");

// One closed fold per profiled column: its name and kind, marked when it is not available at prediction time, then its counts or bins
// drawn as columns beside the numbers they are drawn from.
function distributionsOf(profile: Entry): string {
  const folds = list(profile.columns).map((column) => {
    const distribution = record(column.distribution);
    const counts = list(distribution.counts);
    const bins = list(distribution.histogram);
    const body =
      distribution.counts !== null && distribution.counts !== undefined
        ? [columns(counts.map((each) => number(each.count) ?? 0)), table(["value", "count"], counts.map((each) => [marked(each.value), linked(each.count)]))]
        : distribution.histogram !== null && distribution.histogram !== undefined
          ? [columns(bins.map((bin) => number(bin.count) ?? 0)), table(["from", "to", "count"], bins.map((bin) => [linked(bin.low), linked(bin.high), linked(bin.count)]))]
          : [`<p>${marked(distribution.unavailable)}</p>`];
    return ['<details data-element="distribution">', `<summary>${marked(column.name)} ${marked(column.kind)}${availability(column)}</summary>`, ...body, "</details>"].join("\n");
  });
  return ['<div data-figure="profile-distributions">', `<h4>${label("distributions")}</h4>`, ...folds, "</div>"].join("\n");
}

// The matrix of the columns in clustering order: each pair a mark in its two places, as wide as its absolute value of its place, the
// class of a flagged pair or of a pair with no value from the read; the columns in that order, each marked when it is not available at
// prediction time; the flagged pairs with their value; and in a fold every pair with its measure and value.
function matrixOf(profile: Entry): string {
  const associations = record(profile.associations);
  const order = (Array.isArray(associations.order) ? associations.order : []).map(String);
  const columnsByName = new Map(list(profile.columns).map((column) => [String(column.name), column]));
  const pairs = list(associations.pairs);
  const cells = pairs.flatMap((pair): Cell[] => {
    const [a, b] = [order.indexOf(String(pair.a)), order.indexOf(String(pair.b))];
    if (a < 0 || b < 0) return [];
    const size = number(pair.value) === null ? 1 : Math.abs(number(pair.value)!);
    const kind = number(pair.value) === null ? "no-value" : pair.flagged === true ? "flagged" : "cell";
    return [{ row: a, column: b, size, kind }, { row: b, column: a, size, kind }];
  });
  const names = order.map((name) => `<li>${marked(name)}${availability(columnsByName.get(name) ?? {})}</li>`);
  const flagged = pairs.filter((pair) => pair.flagged === true).map((pair) => `<li>${marked(pair.a)} ${marked(pair.b)} ${marked(pair.measure)} ${linked(pair.value)}</li>`);
  const rows = pairs.map((pair) => [`${marked(pair.a)} ${marked(pair.b)}`, marked(pair.measure), `${linked(pair.value)}${pair.reason === null || pair.reason === undefined ? "" : ` ${marked(pair.reason)}`}`]);
  return [
    '<div data-figure="profile-matrix">',
    `<h4>${label("associations")}</h4>`,
    matrix(order.length, cells),
    `<ol data-element="order">\n${names.join("\n")}\n</ol>`,
    `<p data-element="level">${label("flaggedAt")} ${linked(associations.level)}</p>`,
    `<ul data-element="flagged">\n${flagged.join("\n")}\n</ul>`,
    numbersOf(table(["columns", "measure", "value"], rows)),
    "</div>",
  ].join("\n");
}

// The target against each allowed feature: its name, kind, measure and value over its `train` Items; the points of a numeric feature,
// with no table; for a categorical one, a box of the target per value beside its count and five numbers in a fold.
function againstOf(profile: Entry): string {
  const entries = list(profile.against_target).map((entry) => {
    const line = `<p>${marked(entry.name)} ${marked(entry.kind)} ${marked(entry.measure)} ${linked(entry.value)} ${linked(entry.rows)} ${label("items")}${entry.reason === null || entry.reason === undefined ? "" : ` ${marked(entry.reason)}`}</p>`;
    if (entry.values === null || entry.values === undefined) {
      const points = list(entry.points).flatMap((point): [number, number][] => (number(point.feature) === null || number(point.target) === null ? [] : [[number(point.feature)!, number(point.target)!]]));
      return ['<div data-element="against">', line, scatter(points), "</div>"].join("\n");
    }
    const values = list(entry.values);
    const rows = values.map((each) => [marked(each.value), linked(each.count), ...fiveOf(each.figures)]);
    return ['<div data-element="against">', line, boxes(values.map((each) => fiveNumbers(each.figures))), numbersOf(table(["value", "count", ...QUARTILES.map(([, name]) => name)], rows)), "</div>"].join("\n");
  });
  return ['<div data-figure="profile-against">', `<h4>${label("againstTarget")}</h4>`, ...entries, "</div>"].join("\n");
}
