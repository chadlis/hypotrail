// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client. The client computes nothing of its own: what is pending, the delta, the
// roles, whether a Decision applies, its reasons and the state of its evidence are those the object read holds.
import contract from "../contract.json";
import type { Outcome } from "./bridge";

// `failure` is the outcome of a read that failed, `written` the answer of the write the document follows, and
// `unanswered` whether a write that got no answer is held; `decision` is the id a link of the second form names.
export type View = {
  reading: boolean;
  writing?: boolean;
  object?: Record<string, unknown>;
  failure?: Outcome;
  written?: Outcome;
  unanswered?: boolean;
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
  option: 20,
  author: 21,
  citedIds: 22,
  applies: 23,
  reasons: 24,
  changedItems: 25,
  citedValue: 26,
  latestValue: 27,
  linked: 28,
  noDecision: 29,
  repeat: 30,
  record: 31,
  writing: 32,
  missing: 33,
  recorded: 34,
  outputPath: 35,
  comparabilityStatus: 36,
} as const;

// An entry `name=value` of a list of contract.json, as its two texts.
const pair = (entry: string): [string, string] => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)];

// The phrase of each state of `evidence_change`, by its code.
const PHRASES = new Map(contract.evidence_phrases.map(pair));
// The kind of part each kind of number links to, by the kind of number.
const PART_OF = new Map(contract.number_links.map(pair));
// The `href` of a link to each kind of part, before the place of its record in its list of the object read; the part's `id` is the
// same text without its `#`.
const HREF: Record<string, string> = { study: "#study-", comparison: "#comparison-", assessment: "#assessment-", decision: "#decision-" };
// "It is shown beside the label." (D-077 on chadlis/hypotrail#75, Q5, of `revision_changed`)
const BESIDE_THE_STATE = "revision_changed";

const label = (name: keyof typeof LABEL): string => escaped(contract.labels[LABEL[name]]);

export function escaped(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const text = (value: unknown): string => escaped(value === undefined || value === null ? "" : String(value));
const value = (content: unknown): string => `<span>${text(content)}</span>`;
const marked = (content: unknown, tag = "span"): string => `<${tag} data-text>${text(content)}</${tag}>`;
const list = (content: unknown): Entry[] => (Array.isArray(content) ? content.filter((each) => typeof each === "object" && each !== null) : []);
const record = (content: unknown): Entry => (typeof content === "object" && content !== null && !Array.isArray(content) ? (content as Entry) : {});

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

// The lists of the object read that a document's parts are found in, and the records that already have a part in it: an
// Assessment or a Comparison has one part that links name, at the first place that shows it.
type Shown = { comparisons: Entry[]; assessments: Entry[]; parts: Set<Entry> };

export function bodyOf(view: View): string {
  const parts: string[] = [];
  const notice = noticeOf(view);
  if (notice.length > 0) parts.push(['<div data-element="notice">', ...notice, "</div>"].join("\n"));
  if (view.failure) parts.push(failureOf(view.failure));
  parts.push(`<button data-message="${contract.messages[0]}">${label("readAgain")}</button>`);
  if (view.unanswered) parts.push(`<button data-message="${contract.messages[2]}">${label("repeat")}</button>`);
  // The controls that record are inert while a call is in flight or a write that got no answer is held.
  if (view.object) parts.push(studyOf(view.object, view.decision, view.reading || view.writing === true || view.unanswered === true));
  return parts.join("\n");
}

// What the panel says of a call in flight and of its last write.
function noticeOf(view: View): string[] {
  const lines: string[] = [];
  if (view.reading) lines.push(`<p>${label("reading")}</p>`);
  if (view.writing) lines.push(`<p>${label("writing")}</p>`);
  if (view.unanswered) lines.push(`<p>${escaped(contract.write_no_answer_words)}</p>`);
  const written = view.written;
  if (written?.outcome === "refusal") lines.push(failureOf(written));
  if (written?.outcome === "client_refusal") lines.push(`<p>${label("missing")} ${written.missing.map(value).join(" ")}</p>`);
  if (written?.outcome === "success" && view.failure) lines.push(`<p>${label("recorded")} ${value(record(written.object.decision).decision_id)}</p>`);
  return lines;
}

function failureOf(failure: Outcome): string {
  if (failure.outcome === "refusal") {
    const error = record(failure.error);
    return `<p>${value(error.code)} ${marked(error.message)}</p>`;
  }
  if (failure.outcome === "no_answer") return `<p>${label("noAnswer")} ${value(failure.cause)}</p>`;
  return "";
}

function studyOf(object: Entry, linked: string | undefined, locked: boolean): string {
  const study = record(object.study);
  const pending = list(object.pending_decisions);
  const shown: Shown = { comparisons: list(object.comparisons), assessments: list(object.assessments), parts: new Set() };
  return [
    `<h2>${label("study")}</h2>`,
    `<div data-part="study"${anchor("study", 0)}>`,
    `<p>${value(study.study_id)}</p>`,
    `<p>${label("writeSequence")} ${link("write_sequence", 0, object.write_sequence)}</p>`,
    "</div>",
    `<h2>${label("pending")}</h2>`,
    pending.length === 0 ? `<p>${label("noPending")}</p>` : pending.map((each, index) => pendingOf(each, index, locked, shown)).join("\n"),
    `<h2>${label("decisions")}</h2>`,
    decisionsOf(list(object.decisions), linked, shown),
    `<h2>${label("deviations")}</h2>`,
    deviationsOf(list(object.declared_deviations)),
  ].join("\n");
}

// The question, then the Comparison it names, then the options: the first action selects an option's radio input; the
// second is the control that records, disabled until then.
function pendingOf(pending: Entry, index: number, locked: boolean, shown: Shown): string {
  const inert = locked ? " disabled" : "";
  const options = list(pending.options).map(
    (option, at) =>
      `<li><input type="radio" name="pending-${index}" data-pending="${index}" data-option="${at}"${inert}> ${marked(option.text)} ${marked(option.consequence)}</li>`,
  );
  return [
    '<section data-part="pending">',
    marked(record(pending.question).text, "h3"),
    comparisonOf(pending.comparison_id, shown),
    `<ul>\n${options.join("\n")}\n</ul>`,
    `<button data-message="${contract.messages[1]}" data-pending="${index}" disabled>${label("record")}</button>`,
    assessmentOf("control", pending.control_assessment_id, shown),
    assessmentOf("candidate", pending.candidate_assessment_id, shown),
    "</section>",
  ].join("\n");
}

function comparisonOf(id: unknown, shown: Shown): string {
  const index = shown.comparisons.findIndex((each) => each.comparison_id === id);
  const comparison = shown.comparisons[index];
  const first = comparison !== undefined && !shown.parts.has(comparison);
  if (first) shown.parts.add(comparison);
  const lines = [`<div data-part="comparison"${first ? anchor("comparison", index) : ""}>`, `<p>${label("comparison")} ${value(id)}</p>`];
  if (comparison) {
    const delta = record(comparison.delta);
    const coverage = Object.entries(record(comparison.coverage)).map(([key, number]) => `${value(key)} ${link("coverage", index, number)}`);
    const shownDelta = delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : link("delta", index, delta.value);
    lines.push(`<p data-element="delta">${label("delta")} ${shownDelta} ${value(delta.metric)} ${marked(delta.unit)}</p>`);
    lines.push(`<p data-element="coverage">${label("coverage")} ${coverage.join(" ")}</p>`);
    // "when the delta's `value` is null the Comparison's part holds no roles' element" (chadlis/hypotrail#177).
    if (delta.value !== null && ("control" in delta || "candidate" in delta)) {
      lines.push(`<p data-element="roles">${label("control")} ${link("control", index, delta.control)} ${label("candidate")} ${link("candidate", index, delta.candidate)}</p>`);
    }
    lines.push(`<p>${label("comparabilityStatus")} ${value(record(comparison.comparability).status)}</p>`);
    for (const output of [comparison.paired_deltas_ref, comparison.population_ref]) {
      const path = record(output).path;
      if (typeof path === "string") lines.push(`<p>${label("outputPath")} ${marked(path)}</p>`);
    }
    const warnings = list(comparison.warnings).map((warning) => `<li>${value(warning.code)} ${marked(warning.message)}</li>`);
    const limitations = (Array.isArray(comparison.limitations) ? comparison.limitations : []).map((limitation) => marked(limitation, "li"));
    lines.push(`<h4>${label("warnings")}</h4>`, `<ul>\n${warnings.join("\n")}\n</ul>`);
    lines.push(`<h4>${label("limitations")}</h4>`, `<ul>\n${limitations.join("\n")}\n</ul>`);
  }
  lines.push("</div>");
  return lines.join("\n");
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

function decisionsOf(decisions: Entry[], linked: string | undefined, shown: Shown): string {
  const parts = decisions.map((decision, index) => decisionOf(decision, index, decision.decision_id === linked, shown));
  if (linked !== undefined && !decisions.some((decision) => decision.decision_id === linked)) parts.unshift(`<p>${label("noDecision")} ${value(linked)}</p>`);
  return parts.join("\n");
}

function decisionOf(decision: Entry, index: number, linked: boolean, shown: Shown): string {
  const cited = Array.isArray(decision.cited_ids) ? decision.cited_ids : [];
  const reasons = list(decision.reasons).map((reason) => `<li>${value(reason.reason)} ${value(reason.id)}</li>`);
  const lines = [
    `<section data-part="decision"${anchor("decision", index)}${linked ? " data-linked" : ""}>`,
    `<h3>${value(decision.decision_id)}</h3>`,
    ...(linked ? [`<p>${label("linked")}</p>`] : []),
    `<p>${label("option")} ${marked(decision.option)}</p>`,
    `<p>${label("author")} ${value(decision.author)}</p>`,
    `<h4>${label("citedIds")}</h4>`,
    `<ul data-element="cited">\n${cited.map((id) => `<li>${value(id)}</li>`).join("\n")}\n</ul>`,
  ];
  for (const id of cited) {
    const comparison = shown.comparisons.find((each) => each.comparison_id === id);
    // The Assessments of a cited Comparison are those its `roles` name, and none without them.
    if (comparison !== undefined) {
      const roles = record(comparison.roles);
      lines.push(comparisonOf(id, shown));
      if ("roles" in comparison) lines.push(assessmentOf("control", roles.control_assessment_id, shown), assessmentOf("candidate", roles.candidate_assessment_id, shown));
    } else if (shown.assessments.some((each) => each.assessment_id === id)) {
      lines.push(assessmentOf(undefined, id, shown));
    }
  }
  lines.push(`<p>${label("applies")} ${value(decision.applies)}</p>`, `<h4>${label("reasons")}</h4>`, `<ul data-element="reasons">\n${reasons.join("\n")}\n</ul>`);
  if (decision.evidence_change !== null && typeof decision.evidence_change === "object") lines.push(evidenceOf(record(decision.evidence_change), list(decision.reasons), index, shown));
  lines.push("</section>");
  return lines.join("\n");
}

const phrase = (state: unknown): string => text(PHRASES.get(String(state)) ?? state);

// `decision` is the place of the Decision in `decisions`: a number links to that Decision's part when `assessments` holds no entry
// of its Assessment's id.
function evidenceOf(change: Entry, reasons: Entry[], decision: number, shown: Shown): string {
  const beside = reasons.find((reason) => reason.reason === BESIDE_THE_STATE);
  const to = (kind: string, id: unknown, number: unknown): string => {
    const index = shown.assessments.findIndex((each) => each.assessment_id === id);
    return index < 0 ? link(kind, decision, number, "decision") : link(kind, index, number);
  };
  const lines = list(change.lines).map((line) => {
    const metrics = list(line.metrics).map(
      (metric) =>
        `<li>${label("metric")} ${value(metric.id)} ${label("citedValue")} ${to("cited", line.assessment_id, metric.cited)} ${label("latestValue")} ${to("latest", line.latest_assessment_id, metric.latest)}</li>`,
    );
    const assessments = [assessmentOf(undefined, line.assessment_id, shown), assessmentOf(undefined, line.latest_assessment_id, shown)].join("\n");
    return `<li data-part="line"><span>${phrase(line.state)}</span> ${label("changedItems")} ${to("changed_item_count", line.latest_assessment_id, line.changed_item_count)}\n<ul>\n${metrics.join("\n")}\n</ul>\n${assessments}\n</li>`;
  });
  return [`<p data-element="evidence"><span>${phrase(change.state)}</span>${beside ? ` ${value(beside.reason)}` : ""}</p>`, `<ul>\n${lines.join("\n")}\n</ul>`].join("\n");
}

function deviationsOf(deviations: Entry[]): string {
  const lines = deviations.map((deviation) => `<li data-part="deviation">${value(deviation.declared_deviation_id)} ${label("withdrawn")} ${value(deviation.withdrawn)}</li>`);
  return `<ul>\n${lines.join("\n")}\n</ul>`;
}
