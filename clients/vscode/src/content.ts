// What the panel shows of a Study, as HTML. Every text of the object read is escaped and stands between tags; an
// attribute holds only a literal of the client. The client computes nothing of its own: what is pending, the delta, the
// roles, whether a Decision applies, its reasons and the state of its evidence are those the object read holds.
import contract from "../contract.json";
import type { Outcome } from "./bridge";

// `decision` is the id a link of the second form names.
export type View = { reading: boolean; object?: Record<string, unknown>; failure?: Outcome; decision?: string };

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
} as const;

// The phrase of each state of `evidence_change`, by its code.
const PHRASES = new Map(contract.evidence_phrases.map((entry) => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)]));
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

const numberOf = (number: unknown): string => `<span>${written(number)}</span>`;

export function bodyOf(view: View): string {
  const parts: string[] = [];
  if (view.reading) parts.push(`<p>${label("reading")}</p>`);
  if (view.failure) parts.push(failureOf(view.failure));
  parts.push(`<button data-message="${contract.read_again_message}">${label("readAgain")}</button>`);
  if (view.object) parts.push(studyOf(view.object, view.decision));
  return parts.join("\n");
}

function failureOf(failure: Outcome): string {
  if (failure.outcome === "refusal") {
    const error = record(failure.error);
    return `<p>${value(error.code)} ${marked(error.message)}</p>`;
  }
  if (failure.outcome === "no_answer") return `<p>${label("noAnswer")} ${value(failure.cause)}</p>`;
  return "";
}

function studyOf(object: Entry, linked: string | undefined): string {
  const study = record(object.study);
  const pending = list(object.pending_decisions);
  const comparisons = list(object.comparisons);
  const assessments = list(object.assessments);
  return [
    `<h2>${label("study")}</h2>`,
    `<p>${value(study.study_id)}</p>`,
    `<p>${label("writeSequence")} ${numberOf(object.write_sequence)}</p>`,
    `<h2>${label("pending")}</h2>`,
    pending.length === 0 ? `<p>${label("noPending")}</p>` : pending.map((each) => pendingOf(each, comparisons, assessments)).join("\n"),
    `<h2>${label("decisions")}</h2>`,
    decisionsOf(list(object.decisions), linked, comparisons, assessments),
    `<h2>${label("deviations")}</h2>`,
    deviationsOf(list(object.declared_deviations)),
  ].join("\n");
}

function pendingOf(pending: Entry, comparisons: Entry[], assessments: Entry[]): string {
  const comparison = comparisons.find((each) => each.comparison_id === pending.comparison_id);
  const options = list(pending.options).map((option) => `<li>${marked(option.text)} ${marked(option.consequence)}</li>`);
  return [
    '<section data-part="pending">',
    marked(record(pending.question).text, "h3"),
    `<ul>\n${options.join("\n")}\n</ul>`,
    comparisonOf(pending.comparison_id, comparison),
    assessmentOf("control", pending.control_assessment_id, assessments),
    assessmentOf("candidate", pending.candidate_assessment_id, assessments),
    "</section>",
  ].join("\n");
}

function comparisonOf(id: unknown, comparison: Entry | undefined): string {
  const lines = ['<div data-part="comparison">', `<p>${label("comparison")} ${value(id)}</p>`];
  if (comparison) {
    const delta = record(comparison.delta);
    const coverage = Object.entries(record(comparison.coverage)).map(([key, number]) => `${value(key)} ${numberOf(number)}`);
    const shownDelta = delta.value === null ? `<span>${escaped(contract.withheld)}</span>` : numberOf(delta.value);
    lines.push(`<p data-element="delta">${label("delta")} ${shownDelta} ${value(delta.metric)} ${marked(delta.unit)}</p>`);
    lines.push(`<p data-element="coverage">${label("coverage")} ${coverage.join(" ")}</p>`);
    // "when the delta's `value` is null the Comparison's part holds no roles' element" (chadlis/hypotrail#177).
    if (delta.value !== null && ("control" in delta || "candidate" in delta)) {
      lines.push(`<p data-element="roles">${label("control")} ${numberOf(delta.control)} ${label("candidate")} ${numberOf(delta.candidate)}</p>`);
    }
    const warnings = list(comparison.warnings).map((warning) => `<li>${value(warning.code)} ${marked(warning.message)}</li>`);
    const limitations = (Array.isArray(comparison.limitations) ? comparison.limitations : []).map((limitation) => marked(limitation, "li"));
    lines.push(`<h4>${label("warnings")}</h4>`, `<ul>\n${warnings.join("\n")}\n</ul>`);
    lines.push(`<h4>${label("limitations")}</h4>`, `<ul>\n${limitations.join("\n")}\n</ul>`);
  }
  lines.push("</div>");
  return lines.join("\n");
}

function assessmentOf(role: "control" | "candidate", id: unknown, assessments: Entry[]): string {
  const assessment = assessments.find((each) => each.assessment_id === id);
  const metrics = list(assessment?.metrics).map(
    (metric) => `<li>${label("metric")} ${value(metric.id)} ${numberOf(metric.value)} ${marked(metric.unit)} ${label("status")} ${value(metric.status)}</li>`,
  );
  return [`<div data-role="${role}">`, `<h4>${label(role)}</h4>`, `<p>${label("assessment")} ${value(id)}</p>`, `<ul>\n${metrics.join("\n")}\n</ul>`, "</div>"].join("\n");
}

function decisionsOf(decisions: Entry[], linked: string | undefined, comparisons: Entry[], assessments: Entry[]): string {
  const parts = decisions.map((decision) => decisionOf(decision, decision.decision_id === linked, comparisons, assessments));
  if (linked !== undefined && !decisions.some((decision) => decision.decision_id === linked)) parts.unshift(`<p>${label("noDecision")} ${value(linked)}</p>`);
  return parts.join("\n");
}

function decisionOf(decision: Entry, linked: boolean, comparisons: Entry[], assessments: Entry[]): string {
  const cited = Array.isArray(decision.cited_ids) ? decision.cited_ids : [];
  const reasons = list(decision.reasons).map((reason) => `<li>${value(reason.reason)} ${value(reason.id)}</li>`);
  const lines = [
    `<section data-part="decision"${linked ? " data-linked" : ""}>`,
    `<h3>${value(decision.decision_id)}</h3>`,
    ...(linked ? [`<p>${label("linked")}</p>`] : []),
    `<p>${label("option")} ${marked(decision.option)}</p>`,
    `<p>${label("author")} ${value(decision.author)}</p>`,
    `<h4>${label("citedIds")}</h4>`,
    `<ul data-element="cited">\n${cited.map((id) => `<li>${value(id)}</li>`).join("\n")}\n</ul>`,
    `<p>${label("applies")} ${value(decision.applies)}</p>`,
    `<h4>${label("reasons")}</h4>`,
    `<ul data-element="reasons">\n${reasons.join("\n")}\n</ul>`,
  ];
  if (decision.evidence_change !== null && typeof decision.evidence_change === "object") lines.push(evidenceOf(record(decision.evidence_change), list(decision.reasons)));
  for (const comparison of comparisons.filter((each) => cited.includes(each.comparison_id))) {
    // The Assessments of a cited Comparison are those its `roles` name, and none without them.
    const roles = record(comparison.roles);
    lines.push(comparisonOf(comparison.comparison_id, comparison));
    if ("roles" in comparison) lines.push(assessmentOf("control", roles.control_assessment_id, assessments), assessmentOf("candidate", roles.candidate_assessment_id, assessments));
  }
  lines.push("</section>");
  return lines.join("\n");
}

const phrase = (state: unknown): string => text(PHRASES.get(String(state)) ?? state);

function evidenceOf(change: Entry, reasons: Entry[]): string {
  const beside = reasons.find((reason) => reason.reason === BESIDE_THE_STATE);
  const lines = list(change.lines).map((line) => {
    const metrics = list(line.metrics).map(
      (metric) => `<li>${label("metric")} ${value(metric.id)} ${label("citedValue")} ${numberOf(metric.cited)} ${label("latestValue")} ${numberOf(metric.latest)}</li>`,
    );
    return `<li data-part="line"><span>${phrase(line.state)}</span> ${label("changedItems")} ${numberOf(line.changed_item_count)}\n<ul>\n${metrics.join("\n")}\n</ul>\n</li>`;
  });
  return [`<p data-element="evidence"><span>${phrase(change.state)}</span>${beside ? ` ${value(beside.reason)}` : ""}</p>`, `<ul>\n${lines.join("\n")}\n</ul>`].join("\n");
}

function deviationsOf(deviations: Entry[]): string {
  const lines = deviations.map((deviation) => `<li data-part="deviation">${value(deviation.declared_deviation_id)} ${label("withdrawn")} ${value(deviation.withdrawn)}</li>`);
  return `<ul>\n${lines.join("\n")}\n</ul>`;
}
