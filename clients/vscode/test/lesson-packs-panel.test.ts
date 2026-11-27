import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { bodyOf } from "../src/content";
import { documentFor, elementOf, keptObject, partsOf, runCommand, settle, success, workspace } from "./panel-harness";
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

test("the Comparison lesson links only to an existing aggregate development figure", () => {
  const object = keptObject("journey.04-pending.status");
  const figures = keptObject("journey.04-pending.figures");
  const pack = { ...packRead, write_sequence: object.write_sequence };
  const view = { study: "bike", reading: false, object, figures, lesson: pack };
  const document = bodyOf(view);
  const link = /<a data-pack-figure href="(#lesson-figure-\d+)">/.exec(document);
  assert.ok(link);
  assert.ok(document.includes(`id="${link[1].slice(1)}"`));
  assert.doesNotMatch(bodyOf({ ...view, figures: undefined }), /data-pack-figure/);
  const unknown = { ...object, attempts: object.attempts.map((attempt: object) => ({ ...attempt, partition: null })) };
  assert.doesNotMatch(bodyOf({ ...view, object: unknown }), /data-pack-figure/);
});

test("a legacy lesson read with no configured pack still draws the pack status", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study, lesson: withoutPack });
  const [section] = foldsNamed(document, "Stations and lessons");
  assert.ok(section);
  assert.match(words(section), /Lesson packs: none/);
});

test("a Study panel with an unavailable lesson read still shows the pack availability", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study });
  const [section] = foldsNamed(document, "Stations and lessons");
  assert.ok(section);
  assert.match(words(section), /Lesson packs: availability unknown/);
  assert.doesNotMatch(words(section), /Lesson packs: none/);
});

test("the method link chooses Now when the Study holds older development figures", () => {
  const object = keptObject("journey.09-new-compare.status");
  const figures = keptObject("journey.09-new-compare.figures");
  const pack = { ...packRead, write_sequence: object.write_sequence };
  const document = bodyOf({ study: "bike", reading: false, object, figures, lesson: pack });
  const link = /<a data-pack-figure href="#(lesson-figure-[0-9]+)">/.exec(document);
  assert.ok(link);
  const now = elementOf(document, '<section data-part="now" id="now">');
  assert.ok(now?.includes(`id="${link[1]}"`));
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
  const calls = recorder(
    t,
    lesson(success({ ok: true, track: packRead.track, cards: [], packs: [manifest], stations: [station, evaluator], lessons: [method] })),
    lesson(success({ ok: true, track: "tool_using_agent", cards: [], packs: [], stations: [], lessons: [] })),
  );
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
  assert.equal(calls.length, 0);
  const opened = stub.state.panels[0];
  const nonce = /<script nonce="([a-f0-9]+)">/.exec(markup)?.[1];
  assert.ok(nonce);
  opened.send({ nonce, track: "temporal_regression" });
  await settle();
  assert.ok(words(opened.webview.html).includes(method.title));
  const activeNonce = /<script nonce="([a-f0-9]+)">/.exec(opened.webview.html)?.[1];
  assert.ok(activeNonce);
  opened.send({ nonce: activeNonce, track: "tool_using_agent" });
  await settle();
  assert.match(words(opened.webview.html), /Lesson packs: none/);
  assert.deepEqual(calls.map(({ args }) => args.slice(contract.first_arguments.length)), [
    ["lesson", "--track=temporal_regression", "--json"],
    ["lesson", "--track=tool_using_agent", "--json"],
  ]);
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

const illustratedLesson = {
  ...method,
  illustration: {
    layout: "flow",
    labels: ["Set a goal & agree on a baseline", "Review the difference"],
    caption: "Use the same Protocol for the baseline & the alternative.",
  },
};
const illustratedPackRead = { ...packRead, lessons: [illustratedLesson] };

function assertIllustration(document: string): void {
  const figures = [...document.matchAll(/<figure\b[^>]*>[\s\S]*?<\/figure>/g)];
  const teachingFigure = figures.find(([figure]) => figure.includes("agree on a baseline"));
  assert.ok(teachingFigure, "the teaching illustration should be a semantic figure");
  const markup = teachingFigure[0];
  const caption = /<figcaption\b[^>]*>([\s\S]*?)<\/figcaption>/.exec(markup)?.[0];
  assert.ok(caption, "the illustration should have a text caption");
  assert.equal(words(caption), illustratedLesson.illustration.caption);
  assert.ok(markup.includes("Set a goal &amp; agree on a baseline"));
  const first = words(markup).indexOf(illustratedLesson.illustration.labels[0]);
  const second = words(markup).indexOf(illustratedLesson.illustration.labels[1]);
  assert.ok(first >= 0 && second > first, "the labels should appear in their original order");
}

test("a Study renders a v2 teaching illustration within its lesson and gives it a text equivalent", () => {
  const document = bodyOf({ study: "synthetic-study", reading: false, object: study, lesson: illustratedPackRead });
  const [section] = foldsNamed(document, "Stations and lessons");
  const [rendered] = foldsNamed(section, illustratedLesson.title);
  assert.ok(rendered);
  assertIllustration(rendered);
});

test("the selected Track renders a v2 teaching illustration before a Study exists", async (t) => {
  workspace(t, []);
  const withoutStudy = { ...illustratedPackRead, cards: [] };
  recorder(t, lesson(success(withoutStudy)));
  const showStations = stub.state.commands.get("hypotrail.showStations");
  assert.ok(showStations);
  await showStations();
  await settle();
  const panel = stub.state.panels[0];
  const nonce = /<script nonce="([a-f0-9]+)">/.exec(panel.webview.html)?.[1];
  assert.ok(nonce);
  panel.send({ nonce, track: "temporal_regression" });
  await settle();
  const [rendered] = foldsNamed(panel.webview.html, illustratedLesson.title);
  assert.ok(rendered);
  assertIllustration(rendered);
});
