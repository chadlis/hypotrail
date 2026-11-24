// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client, an index, or, in a bar's geometry, a length computed from the read's numbers.
// The client computes nothing else of its own: what is pending, the delta, the roles, whether a Decision applies, its reasons
// and the state of its evidence are those the object read holds.
import contract from "../contract.json";
import type { Outcome } from "./bridge";
import { bars, boxPlot, histogram, partBar, type Bar, type Five } from "./charts";

// `study` is the string the panel was opened with, `figures` the object of the figures read made after the status read, `failure`
// the outcome of a read that failed, `written` the answer of the
// write the document follows, `unanswered` whether a write that got no answer is held, and `sent` the question, option and cited
// ids of the write in flight or held; `decision` is the id a link of the second form names.
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
  figuresFailed: 45,
  figuresUnavailable: 46,
  pairedDeltas: 47,
  countPerBin: 48,
  minimum: 49,
  firstQuartile: 50,
  median: 51,
  thirdQuartile: 52,
  maximum: 53,
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
};
// The `id` of the element around a pending decision's question, before the place of that decision in `pending_decisions`.
const QUESTION_ID = "question-";
// The `id` of an option's text and of its consequence, before the place of that option among all the options of the document.
const OPTION_ID = "option-";
const CONSEQUENCE_ID = "consequence-";
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
// `figures` holds the entries of the figures read, none when it cannot stand beside the status read.
type Shown = { comparisons: Entry[]; assessments: Entry[]; parts: Set<Entry>; options: number; figures: Entry[] | undefined };

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
  parts.push(`<div data-element="controls">${controls.join(" ")}</div>`);
  // The controls that record are inert while a call is in flight or a write that got no answer is held.
  const recorded = view.written?.outcome === "success" ? record(view.written.object.decision).decision_id : undefined;
  if (view.object) {
    const figures = usableFigures(view.object, view.figures);
    parts.push(studyOf(view.object, view.decision, busy || view.unanswered === true, recorded, view.sent, figures && list(figures.comparisons)));
  }
  return parts.join("\n");
}

// What the panel says of a call in flight and of its last write.
function noticeOf(view: View): string[] {
  const lines: string[] = [];
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

// `recorded` is the id of the Decision the write this document follows recorded, `sent` the write in flight or held.
function studyOf(object: Entry, linked: string | undefined, locked: boolean, recorded: unknown, sent: View["sent"], figures: Entry[] | undefined): string {
  const study = record(object.study);
  const pending = list(object.pending_decisions);
  const shown: Shown = { comparisons: list(object.comparisons), assessments: list(object.assessments), parts: new Set(), options: 0, figures };
  const count = `<p data-element="count">${label("pendingCount")} ${link("pending_decisions", 0, pending.length)}</p>`;
  return [
    `<h2>${label("study")}</h2>`,
    `<div data-part="study"${anchor("study", 0)}>`,
    `<p>${value(study.study_id)} ${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence)}</p>`,
    "</div>",
    `<h2>${label("pending")}</h2>`,
    pending.length === 0 ? `<p>${label("noPending")}</p>` : [count, ...pending.map((each, index) => pendingOf(each, index, locked, shown, sent))].join("\n"),
    `<h2>${label("decisions")}</h2>`,
    decisionsOf(list(object.decisions), linked, recorded, shown),
    `<h2>${label("deviations")}</h2>`,
    deviationsOf(list(object.declared_deviations)),
  ].join("\n");
}

// The question, then the Comparison it names with the choices under its evidence: the first action selects an option's radio
// input, named by the option's text and described by its consequence; the second is the control that records, disabled until
// then. The option of the write `sent` is checked where its question is this one and its cited ids hold this Comparison's id.
function pendingOf(pending: Entry, index: number, locked: boolean, shown: Shown, sent: View["sent"]): string {
  const inert = locked ? " disabled" : "";
  const question = `${QUESTION_ID}${index}`;
  const asked =
    sent !== undefined && sent.question === record(pending.question).text && Array.isArray(sent.cited_ids) && sent.cited_ids.includes(pending.comparison_id);
  const options = list(pending.options).map((option, at) => {
    const place = shown.options++;
    const checked = asked && sent.option === option.text ? " checked" : "";
    const input = `<input type="radio" name="pending-${index}" data-pending="${index}" data-option="${at}" aria-labelledby="${OPTION_ID}${place}" aria-describedby="${CONSEQUENCE_ID}${place}"${checked}${inert}>`;
    return `<label>${input} <span id="${OPTION_ID}${place}">${marked(option.text, "strong")}</span> <span id="${CONSEQUENCE_ID}${place}">${marked(option.consequence, "small")}</span></label>`;
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
    `<div id="${question}">${marked(record(pending.question).text, "h3")}</div>`,
    comparisonOf(pending.comparison_id, shown, [pending.control_assessment_id, pending.candidate_assessment_id], choices),
    assessmentOf("control", pending.control_assessment_id, shown),
    assessmentOf("candidate", pending.candidate_assessment_id, shown),
    "</section>",
  ].join("\n");
}

// A Comparison: its delta, its coverage, its roles and chart 1, then, where it is pending, a line of how many warnings and limitations
// it holds and `choices`, then the rest, and last its figures when its delta is not withheld. `roles` are the
// ids of the Assessments that stand under the Control and the Candidate, whose Metric of the delta chart 1 draws where the delta
// record carries no value of its own.
function comparisonOf(id: unknown, shown: Shown, roles: unknown[], choices = ""): string {
  const index = shown.comparisons.findIndex((each) => each.comparison_id === id);
  const comparison = shown.comparisons[index];
  const first = comparison !== undefined && !shown.parts.has(comparison);
  if (first) shown.parts.add(comparison);
  const lines = [`<div data-part="comparison"${first ? anchor("comparison", index) : ""}>`, `<p>${label("comparison")} ${value(id)}</p>`];
  if (comparison) {
    const delta = record(comparison.delta);
    // The coverage is read once, as a list of its keys and values.
    const coverage = Object.entries(record(comparison.coverage));
    lines.push(deltaOf(delta, index));
    lines.push(`<p data-element="coverage">${label("coverage")} ${coverage.map(([key, number]) => `${value(key)} ${link("coverage", index, number)}`).join(" ")}</p>`);
    // "when the delta's `value` is null the Comparison's part holds no roles' element" (chadlis/hypotrail#177).
    if (delta.value !== null && ("control" in delta || "candidate" in delta)) {
      lines.push(`<p data-element="roles">${label("control")} ${link("control", index, delta.control)} ${label("candidate")} ${link("candidate", index, delta.candidate)}</p>`);
    }
    const warnings = list(comparison.warnings).map((warning) => `<li>${value(warning.code)} ${marked(warning.message)}</li>`);
    const limitations = (Array.isArray(comparison.limitations) ? comparison.limitations : []).map((limitation) => marked(limitation, "li"));
    lines.push(deltaChartOf(delta, index, roles, shown));
    if (choices !== "") {
      lines.push(`<p data-element="limits">${label("warnings")} ${link("warnings", index, warnings.length)} ${label("limitations")} ${link("limitations", index, limitations.length)}</p>`, choices);
    }
    lines.push(`<p data-element="definition">${marked(delta.definition)}</p>`, coverageChartOf(coverage, index));
    lines.push(`<p>${label("comparabilityStatus")} ${value(record(comparison.comparability).status)}</p>`);
    for (const output of [comparison.paired_deltas_ref, comparison.population_ref]) {
      const path = record(output).path;
      if (typeof path === "string") lines.push(`<p>${label("outputPath")} ${marked(path)}</p>`);
    }
    for (const [kind, items] of [["warnings", warnings], ["limitations", limitations]] as const) {
      lines.push(`<div data-part="${kind}"${first ? anchor(kind, index) : ""}>`, `<h4>${label(kind)}</h4>`, `<ul>\n${items.join("\n")}\n</ul>`, "</div>");
    }
    // A withheld delta keeps its word alone.
    if (delta.value !== null) lines.push(figuresOf(shown.figures, id, index, number(delta.value)));
  } else {
    lines.push(choices);
  }
  lines.push("</div>");
  return lines.filter((line) => line !== "").join("\n");
}

// The figures of a Comparison's paired deltas from its entry of the figures read: the label of a failed figures call when there are
// no entries, nothing when the entry's reason is a withheld delta, the label of an entry with no figures for any other reason, and
// otherwise a histogram of its bins with the count of each, then a box plot of its five numbers on the axis from the first bin's low
// to the last bin's high, with the mark of the Comparison's delta.
function figuresOf(entries: Entry[] | undefined, id: unknown, index: number, delta: number | null): string {
  if (entries === undefined) return `<p data-element="figures-failed">${label("figuresFailed")}</p>`;
  const entry = record(entries.find((each) => each.comparison_id === id));
  if (entry.unavailable === DELTA_WITHHELD) return "";
  const bins = list(entry.histogram);
  const counts = bins.map((bin) => number(bin.count));
  const quartiles = record(entry.quartiles);
  const five = QUARTILES.map(([key]) => number(quartiles[key]));
  if (entry.unavailable !== null || bins.length === 0 || [...counts, ...five].includes(null)) return `<p data-element="figures-unavailable">${label("figuresUnavailable")}</p>`;
  const [low, high] = [bins[0].low, bins[bins.length - 1].high];
  const edges = low === high ? [low] : [low, high];
  const named = QUARTILES.map(([key, name]) => `<span${key === "median" ? ' data-key="median"' : ""}>${label(name)} ${link("quartile", index, quartiles[key])}</span>`);
  return [
    "<div data-figures>",
    `<h4>${label("pairedDeltas")}</h4>`,
    '<div data-figure="histogram">',
    histogram(counts as number[]),
    `<table data-element="counts"><caption>${label("countPerBin")}</caption><tr>${bins.map((bin) => `<td>${link("bin_count", index, bin.count)}</td>`).join("")}</tr></table>`,
    "</div>",
    '<div data-figure="box">',
    boxPlot(five as Five, delta),
    `<p data-element="axis">${edges.map((edge) => link("bin_edge", index, edge)).join(" ")}</p>`,
    `<p data-element="quartiles">${named.join(" ")}${delta === null ? "" : ` <span data-key="delta">${label("delta")}</span>`}</p>`,
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

// The delta's element: its value as a link, or the word of a withheld delta, with its Metric and unit.
function deltaOf(delta: Entry, index: number): string {
  const shownDelta = delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", index, delta.value);
  return `<p data-element="delta">${label("delta")} ${shownDelta} ${value(delta.metric)} ${marked(delta.unit)}</p>`;
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
    const path = `<p>${label("outputPath")} ${marked(record(assessment.per_item_ref).path)}</p>`;
    body = [`<div data-part="assessment"${anchor("assessment", index)}>`, body, path, `<ul>\n${metrics.join("\n")}\n</ul>`, "</div>"].join("\n");
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
  return lines.join("\n");
}

const phrase = (state: unknown): string => text(PHRASES.get(String(state)) ?? state);

// The state of a Decision's evidence, with `revision_changed` beside it when a reason.
function stateOf(change: Entry, reasons: Entry[]): string {
  const beside = reasons.find((reason) => reason.reason === BESIDE_THE_STATE);
  return `<p data-element="evidence"><span>${phrase(change.state)}</span>${beside ? ` ${value(beside.reason)}` : ""}</p>`;
}

// Each line of a Decision's evidence, with chart 3: each Metric's cited and latest value as two bars on one scale; the line's
// Assessments are not shown here. `decision` is the
// place of the Decision in `decisions`: a number links to that Decision's part when `assessments` holds no entry of its Assessment's id.
function linesOf(change: Entry, decision: number, shown: Shown): string {
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
    return `<li data-part="line"><span>${phrase(line.state)}</span> ${label("changedItems")} ${to("changed_item_count", line.latest_assessment_id, line.changed_item_count)}\n<ul>\n${metrics.join("\n")}\n</ul>\n</li>`;
  });
  return `<ul>\n${lines.join("\n")}\n</ul>`;
}

function deviationsOf(deviations: Entry[]): string {
  const lines = deviations.map((deviation) => `<li data-part="deviation">${value(deviation.declared_deviation_id)} ${label("withdrawn")} ${value(deviation.withdrawn)}</li>`);
  return lines.length === 0 ? `<p>${label("none")}</p>` : `<ul>\n${lines.join("\n")}\n</ul>`;
}
