import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { bodyOf } from "../src/content";
import { documentFor, elementOf, partsOf, runCommand, settle, success, workspace } from "./panel-harness";
import { lesson, recorder } from "./recorder";
import { invoke } from "./tools-harness";
import * as stub from "./vscode-stub";

const study = {
  ok: true,
  study: { study_id: "synthetic-study" },
  write_sequence: 4,
  next_step: { kind: "decide", ids: ["synthetic-comparison"] },
  pending_decisions: [{
    comparison_id: "synthetic-comparison",
    question: { text: "Which configuration do you choose?" },
    options: [{ text: "Keep the control", consequence: "Continue with the existing configuration." }],
  }],
};
const card = { kind: "comparisons", title: "Read the step", text: "A card from the Track.", key_paths: [] };
const manifest = {
  id: "test-pack", version: "1.0.0", title: "Synthetic teaching pack",
  language: "en", licence: "unlicensed", valid: true, reason: null,
};
const station = {
  id: "compare_decide", title: "Compare the results", purpose: "Prepare a choice with evidence.",
  where: "panel", chat: true, has_records: true,
};
const evaluator = {
  id: "held_out", title: "Protected evaluation", purpose: "The evaluator handles this station.",
  where: "evaluator", chat: false, has_records: null,
};
const method = {
  id: "interpret-an-interval", station: station.id, track: "temporal_regression", title: "Interpret an interval",
  why_this_step: "Compare the difference with the threshold you set beforehand.",
  how_to_do_it: ["Locate both bounds."],
  how_to_read: 'Read <img src="fixture" onerror="fixture()"> as plain text.',
  pitfalls: ["Watch for a bound that leaves an inconclusive result."],
  key_paths: [{ read: "status", path: "comparisons[].interval.lower" }],
  source: "test-pack@1.0.0",
};
const packRead = {
  ok: true, track: "temporal_regression", write_sequence: study.write_sequence, cards: [card],
  packs: [manifest], stations: [station, evaluator], lessons: [method],
};
const withoutPack = { ok: true, track: packRead.track, write_sequence: study.write_sequence, cards: [card] };

const words = (markup: string): string => partsOf(markup).between.replace(/\s+/g, " ").trim();

function foldsNamed(document: string, title: string): string[] {
  const openings = [...document.matchAll(/<details\b[^>]*>\s*<summary\b[^>]*>[\s\S]*?<\/summary>/g)];
  return openings.flatMap((match) => {
    const summary = match[0].slice(match[0].indexOf("<summary"));
    if (words(summary) !== title) return [];
    const opening = match[0].slice(0, match[0].indexOf(">") + 1);
    return [elementOf(document.slice(match.index), opening)!];
  });
}

test("the Study panel puts one closed pack section after Record and Track cards", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study, lesson: packRead });
  const sections = foldsNamed(document, "Stations and lessons");
  assert.equal(sections.length, 1);
  const section = sections[0];
  assert.doesNotMatch(section.slice(0, section.indexOf(">")), /\sopen(?:\s|=|$)/);
  const record = document.indexOf(`<button data-message="${contract.messages[1]}"`);
  const trackCard = document.indexOf('<details data-element="card"');
  const pack = document.indexOf(section);
  const path = document.indexOf('<section data-part="path">');
  assert.ok(record >= 0 && record < trackCard && trackCard < pack && pack < path);
});

test("pack lessons are folded and render their four parts and source as escaped text", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study, lesson: packRead });
  const [section] = foldsNamed(document, "Stations and lessons");
  assert.ok(section);
  const [rendered] = foldsNamed(section, method.title);
  assert.ok(rendered);
  assert.doesNotMatch(rendered.slice(0, rendered.indexOf(">")), /\sopen(?:\s|=|$)/);
  for (const value of [
    manifest.title, station.purpose, evaluator.purpose, method.source, method.why_this_step,
    method.how_to_do_it[0], method.how_to_read, method.pitfalls[0],
  ]) {
    assert.ok(words(section).includes(value), value);
  }
  assert.doesNotMatch(section, /<img\b[^>]*onerror=/);
  const evaluatorMarkup = section.slice(section.indexOf(evaluator.title));
  assert.doesNotMatch(evaluatorMarkup, /<button\b|<input\b|<textarea\b/);

  const noMark = bodyOf({
    study: "synthetic-study", reading: false, object: study,
    lesson: { ...packRead, stations: [{ ...station, has_records: null }, evaluator] },
  });
  const [unknown] = foldsNamed(noMark, "Stations and lessons");
  assert.notEqual(words(unknown), words(section), "a definite record mark must differ from an unknown one");
});

test("a legacy lesson read with no configured pack still draws the pack status", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study, lesson: withoutPack });
  const [section] = foldsNamed(document, "Stations and lessons");
  assert.ok(section);
  assert.match(words(section), /Lesson packs: none/);
});

test("the lesson response adds the pack section to the existing Study panel", async (t) => {
  const { document, calls } = await documentFor(t, success(study), success({
    ok: true, write_sequence: study.write_sequence, comparisons: [],
  }), lesson(success(packRead)));
  const sections = foldsNamed(document, "Stations and lessons");
  assert.equal(sections.length, 1);
  assert.ok(words(sections[0]).includes(method.source));
  assert.equal(calls.filter((call) => call.args.some((arg) => arg === "lesson")).length, 1);
});

test("an empty workspace offers Show stations without opening a Study panel", async (t) => {
  workspace(t, []);
  await runCommand();
  await settle();
  const [notification] = stub.callsOf("showInformationMessage");
  assert.equal(notification.args[0], contract.no_study_message);
  assert.ok(notification.args.includes("Show stations"));
  assert.equal(stub.callsOf("createWebviewPanel").length, 0);
});

test("choosing Show stations opens the Track document from the empty workspace notification", async (t) => {
  workspace(t, []);
  stub.state.informationChoice = "Show stations";
  recorder(t, lesson(success({
    ok: true, track: packRead.track, cards: [], packs: [], stations: [], lessons: [],
  })));
  await runCommand();
  await settle();
  const open = stub.state.panels.filter((panel) => !panel.disposed);
  assert.equal(open.length, 1);
  const buttons = elementsNamedButton(open[0].webview.html).map(words);
  assert.ok(buttons.includes("Temporal regression"));
  assert.ok(buttons.includes("Tool-using agent"));
});

test("the stations command opens a document offering both Tracks with no Study", async (t) => {
  workspace(t, []);
  const calls = recorder(t, lesson(success({
    ok: true, track: packRead.track, cards: [], packs: [manifest], stations: [station, evaluator], lessons: [method],
  })));
  const showStations = stub.state.commands.get("hypotrail.showStations");
  assert.ok(showStations, "the stations command is registered");
  await showStations();
  await settle();
  assert.equal(stub.state.panels.length, 1);
  const documents = stub.state.panels[0].documents;
  const markup = documents[documents.length - 1];
  const buttons = elementsNamedButton(markup).map(words);
  assert.ok(buttons.includes("Temporal regression"));
  assert.ok(buttons.includes("Tool-using agent"));
  assert.ok(calls.every((call) => call.args.includes("lesson") && call.args.some((arg) => arg.startsWith("--track="))));
});

function elementsNamedButton(markup: string): string[] {
  return [...markup.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => button);
}

test("the read tool requests the selected Track pack without a Study", async (t) => {
  workspace(t, []);
  const calls = recorder(t, lesson(success({
    ok: true, track: packRead.track, cards: [], packs: [manifest], stations: [station, evaluator], lessons: [method],
  })));
  const result = await invoke("hypotrail_read_study", { track: packRead.track });
  assert.equal(calls.length, 1);
  const args = calls[0].args.slice(contract.first_arguments.length);
  assert.deepEqual(args, ["lesson", "--track=temporal_regression", "--json"]);
  assert.ok(result.includes(method.source));
  assert.ok(result.includes(method.why_this_step));
});

const guide = readFileSync(path.join(__dirname, "..", "..", "hypotrail-guide.agent.md"), "utf8");
for (const sentence of [
  "Quote a pack lesson verbatim and name its source.",
  "Name the station the person names; if they name none, ask which station they are at.",
  "Ask at most the lesson's question.",
  "At the held-out station, say only that the held-out pass runs at the evaluator and that you cannot discuss it.",
  "Before the person opens a Comparison's figures, you may ask what they expect; record nothing.",
]) {
  test(`the guide includes the required wording: ${sentence}`, () => {
    assert.ok(guide.includes(sentence));
  });
}
