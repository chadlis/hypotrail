import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { bodyOf } from "../src/content";
import { JOURNEY, kept } from "./kept";
import { KEPT_FIGURES, KEPT_READS, S2_INTERVAL, documentFor, profileAt, elementOf, elementsOf, followLink, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, workspace, withFigures } from "./panel-harness";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { KEPT_LESSONS, exit, recorder, type Answer } from "./recorder";

type Entry = Record<string, any>;

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
const HEX64 = /(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])/g;
// A number written whole between two tags or two spaces; a number inside a word or an id is not one.
const NUMBER = /(?<![\w.:/-])-?\d+(?:\.\d+)?(?:e[-+]?\d+)?(?![\w.:/-])/g;
const PAIRS = new Map(contract.number_links.map((entry) => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)] as [string, string]));
const KINDS: Record<string, string> = { study: "study_id", comparison: "comparison_id", assessment: "assessment_id", decision: "decision_id", deviation: "declared_deviation_id" };
const LISTS: Record<string, string> = { comparison: "comparisons", assessment: "assessments", decision: "decisions", deviation: "declared_deviations" };

const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");

// A number written by another route than the client's, to find a value in a document.
function written(value: number | null): string {
  if (value === null) return "no value";
  if (Number.isInteger(value)) return String(value);
  const fixed = value.toPrecision(6);
  return fixed.includes("e") ? String(Number(fixed)) : fixed.replace(/\.?0+$/, "");
}

// The document with the texts of the script and of the style, and every marked element, removed.
function withoutMarked(document: string): string {
  return document
    .replace(/(<script[^>]*>)[\s\S]*?(<\/script>)/, "$1$2")
    .replace(/(<style[^>]*>)[\s\S]*?(<\/style>)/, "$1$2")
    .replace(/<([a-z0-9]+) data-text(?: data-lesson-value="[^"]*")?>[^<]*<\/\1>/g, "");
}

// Each link of the document: its href, its kind, its text and the element its href names.
type Link = { href: string; kind?: string; text: string; target?: string };

// The element whose `id` attribute is `href` without its `#`, when exactly one element holds it.
function targetOf(document: string, href: string): string | undefined {
  const openings = [...document.matchAll(/<([a-z0-9]+) [^>]*\bid="([^"]*)"[^>]*>/g)].filter((each) => `#${each[2]}` === href);
  return openings.length === 1 ? elementOf(document.slice(openings[0].index), openings[0][0]) : undefined;
}

// The links of `html`, each target found in `document`.
function linksOf(html: string, document = html): Link[] {
  return [...html.matchAll(/<a ([^>]*)>([^<]*)<\/a>/g)].map((match) => {
    const href = /href="([^"]*)"/.exec(match[1])?.[1] ?? "";
    return { href, kind: /data-kind="([^"]*)"/.exec(match[1])?.[1], text: partsOf(match[2]).between, target: targetOf(document, href) };
  });
}

// Each part of a record of `kind` in the document, in order.
function partsByKind(document: string, kind: string): string[] {
  return [...document.matchAll(new RegExp(`<([a-z0-9]+) data-part="${kind}"[^>]*>`, "g"))].map((match) => elementOf(document.slice(match.index), match[0])!);
}

const firstId = (html: string | undefined): string | undefined => partsOf(withoutMarked(html ?? "")).between.match(UUID)?.[0];

// The texts between tags that stand outside every link, the marked elements removed.
function outsideLinks(document: string): string[] {
  const texts: string[] = [];
  let inside = false;
  for (const piece of withoutMarked(document).split(/(<[^>]*>)/)) {
    if (piece.startsWith("<a ")) inside = true;
    else if (piece === "</a>") inside = false;
    else if (!piece.startsWith("<") && !inside) texts.push(partsOf(piece).between);
  }
  return texts;
}

const numbersIn = (text: string): string[] => [...text.replace(UUID, " ").replace(HEX64, " ").matchAll(NUMBER)].map((match) => match[0]);
const partKind = (element: string | undefined): string | undefined => (element ? /^<[a-z0-9]+ [^>]*data-part="([a-z]+)"/.exec(element)?.[1] : undefined);

// Every text value of the object read, at any depth.
function textsOf(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(textsOf);
  if (value && typeof value === "object") return Object.values(value).flatMap(textsOf);
  return [];
}

// What every document of the panel holds: each number is in a link of a kind of the pair list, each link names one element of the
// document, a part of the kind its pair names, and each id outside a marked text is a value of the object read.
function assertLinksAndIds(document: string, object: Entry | undefined, name: string): void {
  for (const text of outsideLinks(document)) assert.deepEqual(numbersIn(text), [], `${name}: a number outside a link in ${JSON.stringify(text)}`);
  const ids = [...document.matchAll(/\sid="([^"]*)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, `${name}: each id once`);
  for (const link of linksOf(withoutMarked(document))) {
    assert.ok(link.href.startsWith("#") && link.target, `${name}: the link ${link.href} names one element`);
    if (numbersIn(link.text).length === 0) continue;
    assert.ok(link.kind !== undefined && PAIRS.has(link.kind), `${name}: the number ${link.text} stands in a link of a kind of the pair list`);
    assert.equal(partKind(link.target), PAIRS.get(link.kind!), `${name}: the link of ${link.kind} names a part of ${PAIRS.get(link.kind!)}`);
  }
  const values = new Set(textsOf(object ?? {}));
  for (const text of outsideLinks(document).concat(linksOf(withoutMarked(document)).map((link) => link.text))) {
    for (const id of [...(text.match(UUID) ?? []), ...(text.match(HEX64) ?? [])]) assert.ok(values.has(id), `${name}: the id ${id} is a value of the object read`);
  }
  for (const [kind, key] of Object.entries(KINDS)) {
    const own = (kind === "study" ? [object!.study] : object![LISTS[kind]]).map((record: Entry) => record[key]);
    for (const part of partsByKind(document, kind)) assert.ok(own.includes(firstId(part)), `${name}: the part of a ${kind} shows the id of a ${kind} of the read first`);
  }
}

// The fixture reads whose `ok` is true, and the documents built after each kept output of `decide`.
for (const name of KEPT_READS) {
  test(`every number is in a link to the part of its record, each link names one element, and each id is the read's: ${name}`, async (t) => {
    const object = keptObject(name);
    assertLinksAndIds((await documentFor(t, success(object))).document, object, name);
  });
}

// The kept reads with their kept figures read, whose documents hold the figures and their numbers.
for (const name of Object.keys(KEPT_FIGURES)) {
  test(`every number is in a link to the part of its record, each link names one element, and each id is the read's: ${name} with ${KEPT_FIGURES[name]}`, async (t) => {
    const object = keptObject(name);
    assertLinksAndIds((await documentFor(t, success(object), success(keptObject(KEPT_FIGURES[name])))).document, object, name);
  });
}

test("status-decided with its Comparison also pending and its Decision not applying: the Comparison's part shown once, its summary in the Decision and in the step of the Comparisons, each id once, and the same links", async (t) => {
  const object = keptObject("status-decided");
  const comparison = object.comparisons[0];
  object.decisions[0].applies = false;
  object.pending_decisions = keptObject("status-success").pending_decisions.map((pending: Entry) => ({
    ...pending,
    comparison_id: comparison.comparison_id,
    control_assessment_id: comparison.roles.control_assessment_id,
    candidate_assessment_id: comparison.roles.candidate_assessment_id,
  }));
  object.next_step = { ...object.next_step, kind: "decide", ids: [comparison.comparison_id], context: [object.decisions[0].decision_id] };
  const { document } = await documentFor(t, success(object));
  assert.equal(partsByKind(document, "comparison").length, 1);
  // Its summary in the Decision, and in the step of the Comparisons.
  assert.equal(elementsOf(document, '<div data-summary="comparison">').length, 2);
  assertLinksAndIds(document, object, "status-decided changed");
});

test("status-decided with a second Decision that cites its Comparison: the Comparison's part shown once and its summary in the second Decision, each id once, and the same links", async (t) => {
  const object = keptObject("status-decided");
  object.decisions.push({ ...structuredClone(object.decisions[0]), decision_id: "3c9e7a51-8d24-4f6b-a0e3-6b1f2d9c4e87" });
  const { document } = await documentFor(t, success(object));
  assert.equal(partsByKind(document, "comparison").length, 1);
  assert.equal(elementsOf(partsByKind(document, "decision")[1], '<div data-summary="comparison">').length, 1);
  assertLinksAndIds(document, object, "status-decided with a second Decision");
});

const KEPT_WRITES = ["decide-success", "decide-replay", "decide-study-changed", "decide-write-sequence-ahead", "decide-request-conflict", "decide-invalid-arguments", "decide-study-not-found"];
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));

for (const name of KEPT_WRITES) {
  test(`after a write answered by ${name}, the document of the read that follows holds the same links and ids`, async (t) => {
    const after = keptObject(JSON.parse(kept(`${name}.out`)).ok ? "status-decided" : "status-success");
    workspace(t, ["bike"]);
    recorder(t, ...withFigures(success(keptObject("status-success")), keptAnswer(name), success(after)));
    await runCommand();
    await settle();
    panelOf().send({ message: contract.messages[1], pending: 0, option: 0 });
    await settle();
    assertLinksAndIds(lastDocument(), after, name);
  });
}

// For each pair of the list, one number of that kind of a kept read, and the id of the record whose part its link names.
const INSTANCES: Record<string, [string, (object: Entry) => [number, string]]> = {
  write_sequence: ["status-success", (o) => [o.write_sequence, o.study.study_id]],
  value: ["status-success", (o) => [o.assessments[1].metrics[0].value, o.assessments[1].assessment_id]],
  delta: ["status-success", (o) => [o.comparisons[0].delta.value, o.comparisons[0].comparison_id]],
  control: ["status-chinook-pending", (o) => [o.comparisons[0].delta.control, o.comparisons[0].comparison_id]],
  candidate: ["status-chinook-pending", (o) => [o.comparisons[0].delta.candidate, o.comparisons[0].comparison_id]],
  coverage: ["status-success", (o) => [o.comparisons[0].coverage.paired, o.comparisons[0].comparison_id]],
  cited: ["status-result-changed", (o) => [o.decisions[0].evidence_change.lines[0].metrics[0].cited, o.decisions[0].evidence_change.lines[0].assessment_id]],
  latest: ["status-result-changed", (o) => [o.decisions[0].evidence_change.lines[0].metrics[0].latest, o.decisions[0].evidence_change.lines[0].latest_assessment_id]],
  changed_item_count: ["status-result-changed", (o) => [o.decisions[0].evidence_change.lines[0].changed_item_count, o.decisions[0].evidence_change.lines[0].latest_assessment_id]],
  pending_decisions: ["status-several-pending", (o) => [o.pending_decisions.length, o.study.study_id]],
};

// For each pair whose part is a list of a Comparison's part, one number of that kind of a kept read, and the id of that Comparison.
const IN_A_COMPARISON: Record<string, [string, (object: Entry) => [number, string]]> = {
  warnings: ["status-success", (o) => [o.comparisons[0].warnings.length, o.comparisons[0].comparison_id]],
  // A pending Comparison counts only the limitations that are no warning's message.
  limitations: ["status-success", (o) => [o.comparisons[0].limitations.filter((each: string) => !o.comparisons[0].warnings.some((warning: Entry) => warning.message === each)).length, o.comparisons[0].comparison_id]],
};

// For each pair whose number a figure prints, one number of that kind of a kept figures read, and the id of the Comparison of its entry.
const IN_A_FIGURE: Record<string, [string, (figures: Entry) => [number, string]]> = {
  bin_count: ["status-success", (f) => [f.comparisons[0].histogram[2].count, f.comparisons[0].comparison_id]],
  bin_edge: ["status-success", (f) => [f.comparisons[0].histogram[0].low, f.comparisons[0].comparison_id]],
  quartile: ["status-success", (f) => [f.comparisons[0].quartiles.median, f.comparisons[0].comparison_id]],
  dot_end: ["status-success", (f) => [Math.max(...f.comparisons[0].paired_deltas.flatMap((each: Entry) => [each.control_abs_error, each.candidate_abs_error])), f.comparisons[0].comparison_id]],
};

// For each pair whose number the band prints, a kept read of the journey and the number of that kind it holds.
const IN_THE_BAND: Record<string, [string, (object: Entry) => number]> = {
  writes_since: [`${JOURNEY}04-pending.status`, (o) => o.writes_since.length],
};

// For each pair whose number the delta line prints from the Comparison's `interval`, the kept read the interval is injected into.
const IN_AN_INTERVAL: Record<string, string> = { interval: "status-success" };
// For each pair whose number a link prints toward a part of its own, the kept read of the journey that holds it and that part.
const IN_THEIR_PART: Record<string, [string, string]> = {
  to_handle: [`${JOURNEY}19-two-interrupted.status`, "tohandle"],
  revision_number: [`${JOURNEY}08-result-changed.status`, "study"],
};

for (const [kind, [name, part]] of Object.entries(IN_THEIR_PART)) {
  test(`each number of the kind ${kind} links to the one part ${part}: ${name}`, async (t) => {
    const { document } = await documentFor(t, success(keptObject(name)));
    const links = linksOf(document).filter((link) => link.kind === kind);
    assert.ok(links.length > 0, `a link of ${kind}`);
    for (const link of links) assert.equal(partKind(link.target), part, link.href);
  });
}

// For each pair whose number an Attempt's line prints, the kept read whose Attempts an Assessment cites.
const IN_AN_ATTEMPT: Record<string, string> = { item_counts: "status-success" };

for (const [kind, name] of Object.entries(IN_AN_ATTEMPT)) {
  test(`each number of the kind ${kind} of an Attempt's line links to the part of the Assessment that cites the Attempt: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const rows = partsByKind(document, "attempt");
    assert.equal(rows.length, object.attempts.length);
    object.attempts.forEach((attempt: Entry, at: number) => {
      const citing = object.assessments.find((each: Entry) => each.observation_set_id === attempt.observation_set_id);
      const links = linksOf(rows[at], document).filter((link) => link.kind === kind);
      assert.deepEqual(links.map((link) => link.text), Object.values(attempt.item_counts).map((each) => written(each as number)), `the counts of ${attempt.request_id}`);
      for (const link of links) assert.equal(firstId(link.target), citing.assessment_id, link.href);
    });
  });
}

// For each pair whose number the step of the Data profile prints, the kept status read the kept profile read is made beside.
const IN_THE_PROFILE: Record<string, string> = { profile: "status-success" };

for (const [kind, name] of Object.entries(IN_THE_PROFILE)) {
  test(`each number of the kind ${kind} links to the one part ${PAIRS.get(kind)}, and the document keeps every rule of its links: ${name} with profile-bike`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object), success(keptObject(KEPT_FIGURES[name])), profileAt(object.write_sequence));
    const links = linksOf(document).filter((link) => link.kind === kind);
    assert.ok(links.length > 0, `a link of ${kind}`);
    for (const link of links) assert.equal(partKind(link.target), PAIRS.get(kind), link.href);
    assert.equal(partsByKind(document, PAIRS.get(kind)!).length, 1);
    assertLinksAndIds(document, object, `${name} with profile-bike`);
  });
}

test("the pairs of contract.json are the kinds of number each read here, both ways", () => {
  assert.deepEqual([...PAIRS.keys()].sort(), [...Object.keys(INSTANCES), ...Object.keys(IN_A_COMPARISON), ...Object.keys(IN_A_FIGURE), ...Object.keys(IN_THE_BAND), ...Object.keys(IN_AN_INTERVAL), ...Object.keys(IN_AN_ATTEMPT), ...Object.keys(IN_THEIR_PART), ...Object.keys(IN_THE_PROFILE)].sort());
});

for (const [kind, name] of Object.entries(IN_AN_INTERVAL)) {
  test(`a number of the kind ${kind} links to the part of its Comparison, and the document keeps every rule of its links: ${name} with an injected interval`, async (t) => {
    const object = keptObject(name);
    object.comparisons[0].interval = S2_INTERVAL;
    const { document } = await documentFor(t, success(object));
    const links = linksOf(document).filter((link) => link.kind === kind);
    assert.deepEqual(links.map((link) => link.text), [S2_INTERVAL.level, S2_INTERVAL.lower, S2_INTERVAL.upper].map(written));
    for (const link of links) assert.ok(partKind(link.target) === "comparison" && firstId(link.target) === object.comparisons[0].comparison_id, link.href);
    assertLinksAndIds(document, object, `${name} with an injected interval`);
  });
}

for (const [kind, [name, instance]] of Object.entries(IN_THE_BAND)) {
  test(`a number of the kind ${kind} stands in the band and links to its one part there: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const links = linksOf(elementOf(document, '<div data-part="band">')!, document).filter((link) => link.kind === kind);
    assert.deepEqual(links.map((link) => link.text), [written(instance(object))]);
    assert.equal(partKind(links[0].target), PAIRS.get(kind));
    assert.equal(partsByKind(document, PAIRS.get(kind)!).length, 1);
  });
}

for (const [kind, [name, instance]] of Object.entries(IN_A_FIGURE)) {
  test(`a number of the kind ${kind} links to the part of the Comparison its figure is drawn for: ${name} with ${KEPT_FIGURES[name]}`, async (t) => {
    const figures = keptObject(KEPT_FIGURES[name]);
    const [number, id] = instance(figures);
    const { document } = await documentFor(t, success(keptObject(name)), success(figures));
    const links = linksOf(document).filter((link) => link.kind === kind && link.text === written(number));
    assert.ok(links.length > 0, `a link of ${kind} holding ${written(number)}`);
    for (const link of links) assert.ok(partKind(link.target) === "comparison" && firstId(link.target) === id, `${kind} ${written(number)} in the part of ${id}`);
  });
}

for (const [kind, [name, instance]] of Object.entries(IN_A_COMPARISON)) {
  test(`a number of the kind ${kind} links to its list in the part of its Comparison: ${name}`, async (t) => {
    const object = keptObject(name);
    const [number, id] = instance(object);
    const { document } = await documentFor(t, success(object));
    const links = linksOf(document).filter((link) => link.kind === kind && link.text === written(number));
    assert.ok(links.length > 0, `a link of ${kind} holding ${written(number)}`);
    const comparison = partsByKind(document, "comparison").find((part) => firstId(part) === id)!;
    for (const link of links) assert.ok(link.target && comparison.includes(link.target) && partKind(link.target) === kind, `${kind} ${written(number)} in the part of ${id}`);
  });
}

// The numbers of a line are looked for in the first line of the first Decision, where the same number may stand in another line.
const IN_A_LINE = ["cited", "latest", "changed_item_count"];

for (const [kind, [name, instance]] of Object.entries(INSTANCES)) {
  test(`a number of the kind ${kind} links to the part that shows the id of its record: ${name}`, async (t) => {
    const object = keptObject(name);
    const [number, id] = instance(object);
    const { document } = await documentFor(t, success(object));
    const scope = IN_A_LINE.includes(kind) ? partsByKind(document, "line")[0] : document;
    const links = linksOf(scope, document).filter((link) => link.kind === kind && link.text === written(number));
    assert.ok(links.length > 0, `a link of ${kind} holding ${written(number)}`);
    for (const link of links) assert.equal(firstId(link.target), id, `${kind} ${written(number)} in the part of ${id}`);
  });
}

test("status-result-changed with the latest Assessment of one line removed from assessments: that line's latest and changed_item_count link to the Decision's part", async (t) => {
  const object = keptObject("status-result-changed");
  const decision = object.decisions[0];
  const line = decision.evidence_change.lines[0];
  object.assessments = object.assessments.filter((assessment: Entry) => assessment.assessment_id !== line.latest_assessment_id);
  const { document } = await documentFor(t, success(object));
  const part = partsByKind(document, "line")[0];
  for (const [kind, number] of [["latest", line.metrics[0].latest], ["changed_item_count", line.changed_item_count]]) {
    const link = linksOf(part, document).find((each) => each.kind === kind && each.text === written(number));
    assert.ok(link, `${kind} in the line`);
    assert.equal(partKind(link.target), "decision", `${kind} targets the Decision's part`);
    assert.equal(firstId(link.target), decision.decision_id);
  }
});

// The paths of the outputs.
for (const name of KEPT_READS) {
  test(`each Assessment and Comparison part prints the paths of its outputs as marked texts, and no references path is shown: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const parts = [...partsByKind(document, "assessment"), ...partsByKind(document, "comparison")];
    for (const [list, key, refs] of [
      ["assessments", "assessment_id", ["per_item_ref"]],
      ["comparisons", "comparison_id", ["paired_deltas_ref", "population_ref"]],
    ] as const) {
      for (const record of object[list]) {
        const shown = parts.filter((part) => firstId(part) === record[key]);
        for (const part of shown) for (const ref of refs) if (record[ref]) assert.ok(markedTexts(part).includes(record[ref].path), `${ref}.path in the part of ${record[key]}`);
      }
    }
    for (const assessment of object.assessments) assert.ok(!document.includes(assessment.references_ref.path), assessment.references_ref.path);
  });
}

// Which Assessments have a part.
for (const name of ["status-result-changed", "status-several-pending"]) {
  test(`each Assessment has one part: where a shown pending decision, a cited Comparison's roles, a line or cited_ids names it, there; any other in the step of the Assessments: ${name}`, async (t) => {
    const object = keptObject(name);
    const named = new Set<string>();
    for (const pending of object.pending_decisions) named.add(pending.control_assessment_id).add(pending.candidate_assessment_id);
    for (const decision of object.decisions) {
      for (const id of decision.cited_ids) named.add(id);
      for (const comparison of object.comparisons.filter((each: Entry) => decision.cited_ids.includes(each.comparison_id))) {
        named.add(comparison.roles.control_assessment_id).add(comparison.roles.candidate_assessment_id);
      }
      for (const line of decision.evidence_change?.lines ?? []) named.add(line.assessment_id).add(line.latest_assessment_id);
    }
    const document = (await documentFor(t, success(object))).document;
    const parts = partsByKind(document, "assessment");
    const step = partsByKind(elementOf(document, '<details data-step="assessments">')!, "assessment");
    for (const assessment of object.assessments) {
      assert.equal(parts.filter((part) => firstId(part) === assessment.assessment_id).length, 1, assessment.assessment_id);
      assert.equal(step.filter((part) => firstId(part) === assessment.assessment_id).length, named.has(assessment.assessment_id) ? 0 : 1, `${assessment.assessment_id} in the step`);
    }
  });
}

// Ids.
test("status-success with the ids of the two Assessments of its Comparison exchanged: the document follows the change", async (t) => {
  const object = keptObject("status-success");
  const [first, second] = object.assessments;
  [first.assessment_id, second.assessment_id] = [second.assessment_id, first.assessment_id];
  const pending = object.pending_decisions[0];
  const { document } = await documentFor(t, success(object));
  const control = words(elementOf(document, '<div data-role="control">'));
  const holder = object.assessments.find((each: Entry) => each.assessment_id === pending.control_assessment_id);
  assert.ok(control.includes(`Assessment ${pending.control_assessment_id}`), control);
  assert.ok(control.includes(`mae ${written(holder.metrics[0].value)}`), control);
});

test("the id of a link that names no Decision of the Study stands in the element of its fixed line, and is the one id the read does not hold", async (t) => {
  const object = keptObject("status-decided");
  const missing = "0b8f2c4e-6d1a-4f3b-8e7c-5a9d2f1b3c6e";
  const [study] = workspace(t, ["bike"]);
  recorder(t, success(object));
  await followLink(1, study, missing);
  await settle();
  const values = new Set(textsOf(object));
  const unknown = [...partsOf(withoutMarked(lastDocument())).between.matchAll(UUID)].map((match) => match[0]).filter((id) => !values.has(id));
  assert.deepEqual(unknown, [missing]);
  const line = elementsOf(lastDocument(), "<p>").find((each) => each.includes(missing));
  assert.match(words(line), /^This Study holds no Decision with the id [0-9a-f-]+$/);
});

test("the decision_id of a write's answer, when the read that follows fails, stands in the element of its fixed line, and is the one id shown", async (t) => {
  const answer = JSON.parse(kept("decide-success.out"));
  answer.decision.decision_id = "1234abcd-0000-4000-8000-00000000beef";
  workspace(t, ["bike"]);
  recorder(t, ...withFigures(success(keptObject("status-success")), exit(0, JSON.stringify(answer)), exit(Number(kept("status-not-found.exit")), kept("status-not-found.out"), kept("status-not-found.err"))));
  await runCommand();
  await settle();
  panelOf().send({ message: contract.messages[1], pending: 0, option: 0 });
  await settle();
  const between = partsOf(withoutMarked(lastDocument())).between;
  assert.deepEqual([...between.matchAll(UUID)].map((match) => match[0]), [answer.decision.decision_id]);
  const line = elementsOf(lastDocument(), "<p>").find((each) => each.includes(answer.decision.decision_id));
  assert.match(words(line), /^The Decision was recorded\. [0-9a-f-]+$/);
});

// Statuses.
const OTHER: Record<string, (value: any) => any> = {
  status: (value) => (value === "scored" ? "errored" : "scored"),
  "comparability.status": (value) => (value === "compatible" ? "descriptive_only" : "compatible"),
  applies: (value) => !value,
  withdrawn: (value) => !value,
};

test("the statuses of contract.json are entries of the label list, and each is one the witness below changes", () => {
  for (const status of contract.statuses) assert.ok(contract.labels.includes(status), status);
  assert.deepEqual([...contract.statuses].sort(), Object.keys(OTHER).sort());
});

for (const name of KEPT_READS) {
  test(`each status is shown as its key and the value the read holds, each changed in the test to another value of its kind: ${name}`, async (t) => {
    const object = keptObject(name);
    for (const assessment of object.assessments) for (const metric of assessment.metrics) metric.status = OTHER.status(metric.status);
    for (const comparison of object.comparisons) comparison.comparability.status = OTHER["comparability.status"](comparison.comparability.status);
    for (const decision of object.decisions) decision.applies = OTHER.applies(decision.applies);
    for (const deviation of object.declared_deviations) deviation.withdrawn = OTHER.withdrawn(deviation.withdrawn);
    const { document } = await documentFor(t, success(object));
    const partOf = (kind: string, id: string): string | undefined => {
      const part = partsByKind(document, kind).find((each) => firstId(each) === id);
      return part === undefined ? undefined : words(part);
    };
    for (const assessment of object.assessments) {
      const part = partOf("assessment", assessment.assessment_id);
      if (part) for (const metric of assessment.metrics) assert.ok(part.includes(`status ${metric.status}`), `${metric.id} status ${metric.status} in ${part}`);
    }
    for (const comparison of object.comparisons) {
      const part = partOf("comparison", comparison.comparison_id);
      if (part) assert.ok(part.includes(`comparability.status ${comparison.comparability.status}`), `comparability.status ${comparison.comparability.status} in ${part}`);
    }
    for (const decision of object.decisions) assert.ok(String(partOf("decision", decision.decision_id)).includes(`applies ${decision.applies}`), decision.decision_id);
    for (const deviation of object.declared_deviations) assert.ok(String(partOf("deviation", deviation.declared_deviation_id)).includes(`withdrawn ${deviation.withdrawn}`), deviation.declared_deviation_id);
  });
}

// Nothing in a tag starts a command or a form, and a link moves inside the document.
for (const name of [...KEPT_READS, "status-success with command: in its question"]) {
  test(`no tag holds command: or a form, and every href starts with #: ${name}`, async (t) => {
    const object = keptObject(name === KEPT_READS.find((each) => each === name) ? name : "status-success");
    if (!KEPT_READS.includes(name)) object.pending_decisions[0].question.text = "command:hypotrail.openPanel <form action=x>";
    const { document } = await documentFor(t, success(object));
    const { tags, between } = partsOf(document);
    if (!KEPT_READS.includes(name)) assert.ok(between.includes("command:hypotrail.openPanel <form action=x>"));
    assert.deepEqual(tags.filter((tag) => /command:/i.test(tag) || /^<form[\s>]/i.test(tag)), []);
    const hrefs = tags.flatMap((tag) => [...tag.matchAll(/\shref="([^"]*)"/g)].map((match) => match[1]));
    assert.ok(hrefs.length > 0, "the document holds links");
    assert.deepEqual(hrefs.filter((href) => !href.startsWith("#")), []);
  });
}

// The keys the function that builds the document reads, at every depth.
function recording(value: unknown, path: string, read: Set<string>): unknown {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) {
    return new Proxy(value, {
      get: (target, key, receiver) => (typeof key === "string" && /^\d+$/.test(key) ? recording(target[Number(key)], `${path}[]`, read) : Reflect.get(target, key, receiver)),
    });
  }
  let enumerated = false;
  const at = (key: string) => (path === "" ? key : `${path}.${key}`);
  return new Proxy(value as Entry, {
    get: (target, key) => {
      if (typeof key !== "string" || (!Object.hasOwn(target, key) && key in Object.prototype)) return Reflect.get(target, key);
      read.add(enumerated ? at("*") : at(key));
      return recording(target[key], enumerated ? at("*") : at(key), read);
    },
    has: (target, key) => {
      if (typeof key === "string") read.add(at(key));
      return Reflect.has(target, key);
    },
    ownKeys: (target) => {
      enumerated = true;
      read.add(at("*"));
      return Reflect.ownKeys(target);
    },
  });
}

// The paths that hold others are kept only through them: `comparisons[].delta` is read on the way to `comparisons[].delta.value`.
const leaves = (paths: Set<string>): string[] => [...paths].filter((path) => ![...paths].some((other) => other.startsWith(`${path}.`) || other.startsWith(`${path}[]`))).sort();

function pathsRead(object: Entry): Set<string> {
  const read = new Set<string>();
  bodyOf({ reading: false, object: recording(object, "", read) as Entry });
  return read;
}

for (const name of KEPT_READS) {
  test(`the function that builds the document reads the top-level keys of key_paths and no other, both ways: ${name}`, () => {
    const top = new Set([...pathsRead(keptObject(name))].map((path) => path.split(/[.[]/)[0]));
    assert.deepEqual([...top].sort(), [...new Set(contract.key_paths.map((path) => path.split(/[.[]/)[0]))].sort());
  });
}

// status-success with an `interval` injected into its pending Comparison, its bounds given, then null with their reason: no kept read
// holds the key yet.
function withInterval(bounds: boolean): Entry {
  const object = keptObject("status-success");
  object.comparisons[0].interval = bounds ? S2_INTERVAL : { ...S2_INTERVAL, lower: null, upper: null, reason: "too_few_units" };
  return object;
}

test("the key paths the function reads over every kept read, over status-success with an injected interval and over two reads of the journey, are the entries of key_paths, both ways", () => {
  const read = new Set<string>();
  // And two reads of the journey made with `--since 0`, as the panel reads: state 08, under rule 3, and state 19, with two Attempts to handle.
  const journey = [`${JOURNEY}08-result-changed.status`, `${JOURNEY}19-two-interrupted.status`].map(keptObject);
  for (const object of [...KEPT_READS.map(keptObject), withInterval(true), withInterval(false), ...journey]) for (const path of pathsRead(object)) read.add(path);
  assert.deepEqual(leaves(read), [...contract.key_paths].sort());
});

// The key paths the function reads from the object of the figures read, beside the kept status read made with it.
function figuresPathsRead(name: string): Set<string> {
  const read = new Set<string>();
  bodyOf({ reading: false, object: keptObject(name), figures: recording(keptObject(KEPT_FIGURES[name]), "", read) as Entry });
  return read;
}

test("the key paths the function reads from the figures read over every kept figures read are the entries of figures_key_paths, both ways", () => {
  const read = new Set<string>();
  for (const name of Object.keys(KEPT_FIGURES)) for (const path of figuresPathsRead(name)) read.add(path);
  assert.deepEqual(leaves(read), [...contract.figures_key_paths].sort());
});

// The key paths the function reads from the object of the profile read, beside the kept status read it is made with, and beside a read
// that lists no Attempt, whose Now shows the band and the target over time: "`contract.json` gains `profile_arguments` [...] and
// `profile_key_paths` (the paths the panel draws)" (chadlis/hypotrail#262).
function profilePathsRead(object: Entry, changes: Entry = {}): Set<string> {
  const read = new Set<string>();
  const profile = { ...keptObject("profile-bike"), write_sequence: object.write_sequence, ...changes };
  bodyOf({ reading: false, object, profile: { outcome: "success", object: recording(profile, "", read) as Entry } });
  return read;
}

test("the key paths the function reads from the profile read, on the kept Bike read, on it with workload_protocol differs and on state 01, are the entries of profile_key_paths, both ways", () => {
  const read = new Set<string>();
  for (const paths of [profilePathsRead(keptObject("status-success")), profilePathsRead(keptObject("status-success"), { workload_protocol: "differs" }), profilePathsRead(keptObject(`${JOURNEY}01-init.status`))]) {
    for (const path of paths) read.add(path);
  }
  assert.deepEqual(leaves(read), [...contract.profile_key_paths].sort());
});

// The key paths the function reads from the object of the lesson read, beside the kept status read of the same state.
test("the key paths the function reads from the lesson read over every kept lesson read beside its status read are the entries of lesson_key_paths, both ways", () => {
  const read = new Set<string>();
  for (const [status, lesson] of Object.entries(KEPT_LESSONS)) {
    bodyOf({ reading: false, object: keptObject(status), lesson: recording(keptObject(lesson), "", read) as Entry });
  }
  bodyOf({
    reading: false, object: keptObject("demonstration.after-decide.status"),
    lesson: recording(keptObject("lesson.with-pack-bike"), "", read) as Entry,
  });
  assert.deepEqual(leaves(read), [...contract.lesson_key_paths].sort());
});

// "its id and its Observation set's id are plain text, never links" (D-143, correction 1): the Attempt's id stands as text only.
test("status-public-check: the document holds the attempt_id of the Attempt no Assessment assessed as plain text only, and none of its request_id and artifact paths", async (t) => {
  const object = keptObject("status-public-check");
  const [attempt] = object.attempts.filter((each: Entry) => each.request_id === "ml-public_check-seasonal_7");
  const { document } = await documentFor(t, success(object));
  for (const value of [attempt.request_id, ...attempt.artifacts.map((artifact: Entry) => artifact.path)]) assert.ok(!document.includes(value), value);
  assert.ok(partsOf(document).between.split(/\s+/).includes(attempt.attempt_id), "the attempt_id as text");
  assert.ok(!partsOf(document).tags.some((tag) => tag.includes(attempt.attempt_id)), "the attempt_id in no tag");
  assert.ok(![...document.matchAll(/<a [^>]*>([^<]*)<\/a>/g)].some((match) => match[1].includes(attempt.attempt_id)), "the attempt_id in no link");
});

// "a deep link builds the document with the target's folds open" (D-136, I3), in headless Chrome: state 16, its first Decision.
test("a link of the second form on state 16 opens the fold of the Decision it names and moves the view to it", { timeout: 60000 }, async (t) => {
  if (!hasChrome(t, "the deep link into a fold")) return;
  const address = await startChrome(t);
  if (address === undefined) return t.skip(`Chrome at ${CHROME} did not start within ${START_MS} ms`);
  const object = keptObject(`${JOURNEY}16-deviation-withdrawn.status`);
  const [study] = workspace(t, ["bike"]);
  recorder(t, ...withFigures(success(object)));
  await followLink(1, study, object.decisions[0].decision_id);
  await settle();
  const evaluate = await opened(t, address, lastDocument(), 420, 700);
  const linked = `document.querySelector("[data-linked]")`;
  assert.equal(await evaluate(`${linked}.closest("details").open`), true, "the fold of the Decision is open");
  assert.equal(await evaluate(`${linked}.checkVisibility()`), true, "the Decision is drawn");
  const top: number = await evaluate(`${linked}.getBoundingClientRect().top`);
  assert.ok(top > -1 && top < 700, `the view moved to the Decision, now at ${top} px`);
});
