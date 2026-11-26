import { test } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { kept } from "./kept";
import {
  KEPT_FIGURES,
  elementOf,
  elementsOf,
  partsOf,
  followLink,
  heldRecorder,
  keptObject,
  lastDocument,
  panelOf,
  runCommand,
  samePath,
  settle,
  success,
  workspace,
} from "./panel-harness";
import { exit, recorder, type Answer, type RecordedCall } from "./recorder";

const FAILED = contract.labels[contract.labels.indexOf("Figures unavailable. Read again.")];
const PAIRED = contract.labels[contract.labels.indexOf("Paired deltas")];
// The heading of the paired deltas and the label of a failed figures call under it.
const FAILED_BLOCK = new RegExp(`\\n<h4>${PAIRED} \\(<span data-text>[^<]*</span>\\)</h4>\\n<p data-element="figures-failed">[^\\n]*</p>`, "g");
const READ_AGAIN = { message: contract.messages[0] };
const RECORD = contract.messages[1];
const REFUSED = exit(2, kept("figures-not-found.out"));
const NO_ANSWER = exit(0, "not JSON");

const commandsOf = (calls: RecordedCall[]): string[] => calls.map((call) => call.args[call.args.indexOf("hypotrail") + 1]);
const status = (name: string): Answer => success(keptObject(name));
const figures = (name: string): Answer => success(keptObject(KEPT_FIGURES[name]));
const count = (document: string, text: string): number => document.split(text).length - 1;
// A document with its nonce and its heading's path replaced, so that two documents of two workspaces compare.
const comparable = (document: string): string => samePath(document).replace(/[a-f0-9]{32}/g, "NONCE");

// The document the command opens on one Study, its status read and its figures call answered in turn.
async function opened(t: Parameters<typeof workspace>[0], ...answers: Answer[]): Promise<{ document: string; calls: RecordedCall[] }> {
  workspace(t, ["bike"]);
  const calls = recorder(t, ...answers);
  await runCommand();
  await settle();
  return { document: lastDocument(), calls };
}

function busy(document: string): boolean {
  const buttons = document.match(/<button[^>]*>/g) ?? [];
  return document.includes('<main id="study" aria-busy="true">') && buttons.length > 0 && buttons.every((button) => / disabled[\s>]/.test(button));
}

const idle = (document: string): boolean => !document.includes("aria-busy") && document.includes(`<button data-message="${contract.messages[0]}">`);

// After each status read.
type Way = [string, (study: string) => Promise<void>, Answer[], string[]];
const WAYS: Way[] = [
  ["the command", () => runCommand(), [status("status-success"), figures("status-success")], ["status", "figures", "profile"]],
  ["a link of the first form", (study) => followLink(0, study), [status("status-success"), figures("status-success")], ["status", "figures", "profile"]],
  ["a link of the second form", (study) => followLink(1, study), [status("status-success"), figures("status-success")], ["status", "figures", "profile"]],
  [
    "Read again",
    async () => {
      await runCommand();
      await settle();
      panelOf().send(READ_AGAIN);
    },
    [status("status-success"), figures("status-success")],
    ["status", "figures", "profile", "status", "figures", "profile"],
  ],
  [
    "an answered write",
    async () => {
      await runCommand();
      await settle();
      panelOf().send({ message: RECORD, pending: 0, option: 0 });
    },
    [status("status-success"), figures("status-success"), exit(0, kept("decide-success.out")), status("status-decided"), figures("status-success")],
    ["status", "figures", "profile", "decide", "status", "figures", "profile"],
  ],
];

for (const [way, open, answers, commands] of WAYS) {
  test(`the panel makes the figures call after each status read that succeeds, and at no other time: ${way}`, async (t) => {
    const [study] = workspace(t, ["bike"]);
    const calls = recorder(t, ...answers);
    await open(study);
    await settle();
    assert.deepEqual(commandsOf(calls), commands);
  });
}

for (const [outcome, answer] of [
  ["refusal", exit(2, kept("status-not-found.out"))],
  ["no_answer", NO_ANSWER],
] as [string, Answer][]) {
  test(`after a status read that gives back ${outcome}, the panel makes no figures call and the document is out of flight at once`, async (t) => {
    const { document, calls } = await opened(t, answer);
    assert.deepEqual(commandsOf(calls), ["status"]);
    assert.ok(!document.includes("aria-busy"), document);
    assert.deepEqual((document.match(/<button[^>]*>/g) ?? []).filter((button) => button.includes(" disabled")), []);
  });
}

// The parts of the Comparisons a document shows whole, each with whether its delta is withheld.
function comparisonParts(document: string): { part: string; withheld: boolean }[] {
  return elementsOf(document, '<div data-part="comparison"').map((part) => ({
    part,
    withheld: (elementsOf(part, '<p data-element="delta">')[0] ?? "").includes(`<span>${contract.withheld}</span>`),
  }));
}

// The label stands once in each part whose delta is not withheld, under the heading of its paired deltas, after its delta: in a pending
// part, in the fold of the charts after its choices; in another part, before its warnings. It stands in no part whose delta is withheld.
function labelPlaces(document: string): void {
  const parts = comparisonParts(document);
  assert.ok(parts.length > 0);
  for (const { part, withheld } of parts) {
    if (withheld) {
      assert.equal(count(part, FAILED), 0, part);
      continue;
    }
    assert.equal(count(part, FAILED), 1, part);
    const at = part.indexOf(FAILED);
    assert.ok(at > part.indexOf('<p data-element="delta">'), part);
    if (part.includes("<fieldset ")) assert.ok(at > part.indexOf("</fieldset>") && (elementOf(part, '<details data-element="charts">') ?? "").includes(FAILED), "in the fold of the charts, after the choices");
    else assert.ok(at < part.indexOf('<div data-part="warnings"'), "before the warnings");
    assert.ok(part.lastIndexOf(`<h4>${PAIRED}`, at) > part.indexOf('<p data-element="delta">'), "the heading of the paired deltas stands above the label");
  }
  assert.equal(count(document, FAILED), parts.filter((each) => !each.withheld).length);
}

for (const name of ["status-success", "status-several-pending", "status-bike-withheld", "status-chinook-withheld"]) {
  test(`with a failed figures call, the label stands once in each Comparison part whose delta is not withheld, under the heading of its paired deltas, in the fold of the charts after the choices of a pending part: ${name}`, async (t) => {
    const { document } = await opened(t, status(name), REFUSED);
    labelPlaces(document);
  });
}

test("with a failed figures call, the label follows the word of a failure, as a link to the top of the document where Read again stands, in an element styled as the panel's failures", async (t) => {
  const object = keptObject("status-success");
  const { document } = await opened(t, status("status-success"), REFUSED);
  const [line] = elementsOf(document, '<p data-element="figures-failed">');
  const failedWord = contract.labels[contract.labels.indexOf("Failed:")];
  assert.equal(line, `<p data-element="figures-failed">${failedWord} <a href="#study">${FAILED}</a></p>`);
  assert.ok(new RegExp(`<h4>${PAIRED} \\(<span data-text>${object.comparisons[0].delta.unit}</span>\\)</h4>\\n${line}`).test(document), "under the heading of the paired deltas");
  const main = elementOf(document, '<main id="study"')!;
  assert.ok(elementOf(main, '<div data-element="controls">')!.includes(`<button data-message="${contract.messages[0]}">`), "Read again stands in the element the link names");
  const { style } = partsOf(document);
  for (const rule of [/\[data-element="failure"\][^{]*\[data-element="figures-failed"\][^{]*\{[^}]*border-left:/, /\[data-element="failure"\], \[data-element="figures-failed"\] \{ border-left-color: var\(--red\)/]) {
    assert.match(style, rule);
  }
});

for (const name of Object.keys(KEPT_FIGURES)) {
  test(`with the figures read of the same Study and a matching write_sequence, the document holds no label: ${name}`, async (t) => {
    const { document } = await opened(t, status(name), figures(name));
    assert.equal(count(document, FAILED), 0);
  });

  test(`a figures read whose write_sequence differs is a failed figures call: the label as placed, and no number of its object: ${name}`, async (t) => {
    const object = keptObject(KEPT_FIGURES[name]);
    object.write_sequence += 1;
    const mismatched = (await opened(t, status(name), success(object))).document;
    const failed = (await opened(t, status(name), REFUSED)).document;
    if (comparisonParts(failed).some((each) => !each.withheld)) labelPlaces(mismatched);
    assert.equal(comparable(mismatched), comparable(failed));
  });
}

// An object that is not usable.
const usable = keptObject("figures-success");
const NOT_USABLE: [string, unknown][] = [
  ["the status object itself", keptObject("status-success")],
  ["one entry removed", { ...usable, comparisons: usable.comparisons.slice(1) }],
  ...["comparison_id", "unavailable", "paired_deltas", "histogram", "quartiles"].map((key): [string, unknown] => [
    `the key ${key} removed from an entry`,
    { ...usable, comparisons: usable.comparisons.map((entry: Record<string, unknown>) => Object.fromEntries(Object.entries(entry).filter(([name]) => name !== key))) },
  ]),
  ["no comparisons", Object.fromEntries(Object.entries(usable).filter(([name]) => name !== "comparisons"))],
];

for (const [name, object] of NOT_USABLE) {
  test(`a figures call that answers an object that is not usable is a failed figures call: ${name}`, async (t) => {
    const answers = name === "the status object itself" ? [status("status-success")] : [status("status-success"), success(object)];
    const { document, calls } = await opened(t, ...answers);
    assert.deepEqual(commandsOf(calls), ["status", "figures", "profile"]);
    labelPlaces(document);
    const failed = (await opened(t, status("status-success"), REFUSED)).document;
    assert.equal(comparable(document), comparable(failed));
  });
}

for (const [outcome, answer] of [
  ["refusal", REFUSED],
  ["no_answer", NO_ANSWER],
] as [string, Answer][]) {
  test(`a figures call that gives back ${outcome} leaves the status content and the decision, with the label`, async (t) => {
    const { document } = await opened(t, status("status-success"), answer);
    labelPlaces(document);
    const usableDocument = (await opened(t, status("status-success"), figures("status-success"))).document;
    // The figures the usable read draws stand where the label stands, and its dots at the end of the part.
    const withoutFigures = ["<div data-figures>", '<div data-figure="dots"'].reduce(
      (rest, opening) => elementsOf(rest, opening).reduce((left, shown) => left.replace(`\n${shown}`, ""), rest),
      usableDocument,
    );
    assert.equal(comparable(document).replace(FAILED_BLOCK, ""), comparable(withoutFigures));
  });
}

test("after a figures read that succeeded, a failed figures call of the following Read again drops it: the label stands and nothing of the earlier object", async (t) => {
  const [study] = workspace(t, ["bike"]);
  recorder(t, status("status-success"), figures("status-success"), status("status-success"), REFUSED);
  await followLink(0, study);
  await settle();
  assert.equal(count(lastDocument(), FAILED), 0);
  panelOf().send(READ_AGAIN);
  await settle();
  const document = lastDocument();
  labelPlaces(document);
  const failed = (await opened(t, status("status-success"), REFUSED)).document;
  assert.equal(comparable(document), comparable(failed));
});

// In flight: each document assigned while the status read or the figures call that follows it is in flight.
type HeldWay = [string, (study: string, answer: (answer: Answer) => Promise<void>) => Promise<void>];
const HELD_WAYS: HeldWay[] = [
  ["the command", async () => runCommand()],
  ["a link of the first form", async (study) => followLink(0, study)],
  ["a link of the second form", async (study) => followLink(1, study)],
  [
    "Read again",
    async (_, answer) => {
      await runCommand();
      await answer(status("status-success"));
      await answer(figures("status-success"));
      panelOf().send(READ_AGAIN);
    },
  ],
  [
    "an answered write",
    async (_, answer) => {
      await runCommand();
      await answer(status("status-success"));
      await answer(figures("status-success"));
      panelOf().send({ message: RECORD, pending: 0, option: 0 });
      await settle();
      await answer(exit(0, kept("decide-success.out")));
    },
  ],
];

for (const [way, open] of HELD_WAYS) {
  test(`while the status read or the figures call that follows it is in flight, the panel is in flight, and no document is assigned between their answers: ${way}`, async (t) => {
    const [study] = workspace(t, ["bike"]);
    const held = heldRecorder(t);
    const answer = async (given: Answer): Promise<void> => {
      held.answer(given);
      await settle();
    };
    await open(study, answer);
    await settle();
    assert.equal(commandsOf(held.calls).at(-1), "status");
    const statusDocuments = panelOf().documents.length;
    assert.ok(busy(lastDocument()), lastDocument());
    await answer(status("status-success"));
    assert.equal(commandsOf(held.calls).at(-1), "figures");
    assert.equal(panelOf().documents.length, statusDocuments);
    assert.ok(busy(lastDocument()), lastDocument());
    const calls = held.calls.length;
    panelOf().send(READ_AGAIN);
    await settle();
    assert.equal(held.calls.length, calls, "a message received while the figures call is in flight is dropped");
    await answer(figures("status-success"));
    assert.equal(panelOf().documents.length, statusDocuments + 1);
    assert.ok(idle(lastDocument()), lastDocument());
  });
}
