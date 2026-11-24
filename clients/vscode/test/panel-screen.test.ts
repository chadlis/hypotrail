// The panel as a screen for deciding: the controls take the theme's colours, a call in flight locks them, each pending decision's
// choices form one group named by its question and stand under the evidence, the pending decisions are told apart, and a recorded
// Decision says its outcome first.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { KEPT_READS, documentFor, elementOf, elementsOf, heldRecorder, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, workspace, FIGURES_FAILED } from "./panel-harness";

type Entry = Record<string, any>;

const [, RECORD, SEND_AGAIN] = contract.messages;
const TIMEOUT = { error: { code: null, killed: true, signal: "SIGTERM" } };
const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");
const PHRASES = new Map(contract.applies_phrases.map((entry) => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)] as [string, string]));

// Each rule of a style, as its selector and its declarations.
const rulesOf = (style: string): [string, string][] => [...style.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => [match[1].trim(), match[2]]);
const declares = (body: string, property: string, value: RegExp): boolean =>
  body.split(";").some((declaration) => declaration.includes(":") && declaration.slice(0, declaration.indexOf(":")).trim() === property && value.test(declaration.slice(declaration.indexOf(":") + 1).trim()));
const THEME = /var\(--vscode-[a-zA-Z0-9-]+(?:,[^)]*\)?)?\)/;

async function styleOf(t: TestContext): Promise<string> {
  return partsOf((await documentFor(t, success(keptObject("status-success")))).document).style;
}

// The rules a control's colours, border and focus take from the theme, by what each one sets.
const CONTROL_RULES: [string, (rules: [string, string][]) => boolean][] = [
  ["button takes its background from --vscode-button-background", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "background", /^var\(--vscode-button-background\)$/))],
  ["button takes its colour from --vscode-button-foreground", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "color", /^var\(--vscode-button-foreground\)$/))],
  ["a hovered button takes --vscode-button-hoverBackground", (rules) => rules.some(([s, b]) => /button[^,{]*:hover/.test(s) && declares(b, "background", /^var\(--vscode-button-hoverBackground\)$/))],
  ["a disabled button takes its colours from theme variables", (rules) => rules.some(([s, b]) => /button[^,{]*:disabled/.test(s) && declares(b, "background", THEME) && declares(b, "color", THEME))],
  ["button takes a border from --vscode-contrastBorder", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "border", /var\(--vscode-contrastBorder\b/))],
  [":focus-visible has an outline of 1px solid --vscode-focusBorder", (rules) => rules.some(([s, b]) => /:focus-visible/.test(s) && declares(b, "outline", /^1px solid var\(--vscode-focusBorder\)$/))],
  ["a radio input takes its accent-color from a theme variable", (rules) => rules.some(([s, b]) => /input\[type="radio"\]/.test(s) && declares(b, "accent-color", THEME))],
];

for (const [rule, holds] of CONTROL_RULES) {
  test(`the style of the document holds the rule: ${rule}`, async (t) => {
    assert.ok(holds(rulesOf(await styleOf(t))), await styleOf(t));
  });
}

test("the style gives h1 the declaration overflow-wrap: anywhere", async (t) => {
  assert.ok(rulesOf(await styleOf(t)).some(([s, b]) => /(^|,\s*)h1\s*(,|$)/.test(s) && declares(b, "overflow-wrap", /^anywhere$/)));
});

test("the style mutes the first line of a Comparison's summary as it mutes the first line of its full part", async (t) => {
  const muted = rulesOf(await styleOf(t)).filter(([, b]) => declares(b, "color", /^var\(--vscode-descriptionForeground\)$/) && declares(b, "font-size", /^0\.9em$/));
  const selectors = muted.flatMap(([s]) => s.split(",").map((each) => each.trim()));
  assert.ok(selectors.includes('div[data-part="comparison"] > p:first-child'), selectors.join(" | "));
  assert.ok(selectors.includes('div[data-summary="comparison"] > p:first-child'), selectors.join(" | "));
});

// A call in flight: every control is disabled and main is busy; the document after it is not busy; a notice is a status.
const tagsOf = (document: string): string[] => partsOf(document).tags;
const mainTag = (document: string): string => tagsOf(document).find((tag) => tag.startsWith("<main"))!;

function assertBusy(document: string, busy: boolean, at: string): void {
  const buttons = tagsOf(document).filter((tag) => tag.startsWith("<button"));
  assert.ok(buttons.length > 0, `${at}: a button`);
  if (busy) assert.deepEqual(buttons.filter((tag) => !/\sdisabled(\s|>)/.test(tag)), [], `${at}: every button disabled`);
  assert.equal(/\saria-busy="true"/.test(mainTag(document)), busy, `${at}: ${mainTag(document)}`);
  if (!busy) assert.ok(!/\saria-busy=/.test(mainTag(document)), `${at}: no aria-busy`);
  const notice = tagsOf(document).find((tag) => tag.startsWith('<div data-element="notice"'));
  if (notice) assert.match(notice, /\srole="status"/, at);
}

test("while a read, a write and a second sending are in flight every button is disabled and main is busy, and not in the document that follows each", async (t) => {
  workspace(t, ["bike"]);
  const { answer } = heldRecorder(t);
  await runCommand();
  assertBusy(lastDocument(), true, "a read in flight");
  answer(success(keptObject("status-success")));
  await settle();
  answer(FIGURES_FAILED);
  await settle();
  assertBusy(lastDocument(), false, "after the read");
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  assertBusy(lastDocument(), true, "a write in flight");
  answer(TIMEOUT);
  await settle();
  assertBusy(lastDocument(), false, "after the write with no answer");
  panelOf().send({ message: SEND_AGAIN });
  assertBusy(lastDocument(), true, "a second sending in flight");
  answer(TIMEOUT);
  await settle();
  assertBusy(lastDocument(), false, "after the second sending");
});

// The choices: one group named by the question, one label per option, under the delta and its chart, before the limits.
const PENDING_READS = KEPT_READS.filter((name) => keptObject(name).pending_decisions.length > 0);
const idOf = (tag: string, name: string): string | undefined => new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1];

// The one element of the document whose `id` is `id`.
function elementWithId(document: string, id: string): string | undefined {
  const openings = [...document.matchAll(/<([a-z0-9]+) [^>]*\bid="([^"]*)"[^>]*>/g)].filter((match) => match[2] === id);
  return openings.length === 1 ? elementOf(document.slice(openings[0].index), openings[0][0]) : undefined;
}

for (const name of PENDING_READS) {
  test(`each option is one label holding one radio input, a strong and the two marked texts, inside a fieldset named by its question: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const parts = elementsOf(document, '<section data-part="pending">');
    object.pending_decisions.forEach((pending: Entry, index: number) => {
      const fieldset = elementOf(parts[index], "<fieldset ")!;
      assert.ok(fieldset, "a fieldset");
      const named = idOf(/^<fieldset [^>]*>/.exec(fieldset)![0], "aria-labelledby")!;
      assert.ok(named, "aria-labelledby");
      assert.deepEqual(markedTexts(elementWithId(document, named) ?? "").filter((text) => text === pending.question.text), [pending.question.text]);
      assert.ok(elementWithId(document, named)!.includes("<h3 data-text>"));
      const labels = elementsOf(fieldset, "<label>");
      assert.equal(labels.length, pending.options.length);
      pending.options.forEach((option: Entry, at: number) => {
        const label = labels[at];
        assert.equal(partsOf(label).tags.filter((tag) => tag.startsWith('<input type="radio"')).length, 1);
        assert.match(label, new RegExp(`<strong data-text>[^<]*</strong>`));
        assert.deepEqual(markedTexts(label), [option.text, option.consequence]);
      });
      assert.ok(!/<li>[^]*?<input/.test(parts[index]), "no option is a list item");
    });
  });

  test(`the delta's element, the coverage element, the roles' element, chart 1, the fieldset, then the Comparison's status, paths and limits: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    for (const part of elementsOf(document, '<section data-part="pending">')) {
      const comparison = elementOf(part, '<div data-part="comparison"')!;
      const at = (opening: string) => comparison.indexOf(opening);
      const order = [at('<p data-element="delta">'), at('<p data-element="coverage">'), at('<p data-element="roles">'), at('<div data-chart="delta">'), at("<fieldset ")].filter((place) => place >= 0);
      const rest = Math.min(...[at("comparability.status"), at("Output path"), at("<h4>Warnings"), at("<h4>Limitations")].filter((place) => place >= 0));
      assert.ok(order.length >= 3 && at("<fieldset ") >= 0, "the delta, the coverage and the fieldset");
      assert.deepEqual([...order, rest], [...order, rest].sort((a, b) => a - b), `${order} then ${rest}`);
    }
  });
}

test("in the part of a Comparison a Decision cites, chart 1 stands after the coverage element and before the Comparison's status, and there is no fieldset: status-decided", async (t) => {
  const { document } = await documentFor(t, success(keptObject("status-decided")));
  const comparison = elementOf(elementOf(document, '<section data-part="decision"')!, '<div data-part="comparison"')!;
  const chart = comparison.indexOf('<div data-chart="delta">');
  assert.ok(chart > comparison.indexOf('<p data-element="coverage">') && chart < comparison.indexOf("comparability.status"), comparison);
  assert.ok(!comparison.includes("<fieldset"));
});

// Several pending decisions.
test("status-several-pending: each part but the first starts with a separator, and each control that records is described by its own question", async (t) => {
  const object = keptObject("status-several-pending");
  const { document, } = await documentFor(t, success(object));
  const parts = elementsOf(document, '<section data-part="pending">');
  assert.equal(parts.length, object.pending_decisions.length);
  parts.forEach((part, index) => {
    assert.equal(/^<section data-part="pending">\s*<hr>/.test(part), index > 0, `the separator of part ${index}`);
    const control = partsOf(part).tags.find((tag) => tag.includes(`data-message="${RECORD}"`))!;
    const described = idOf(control, "aria-describedby")!;
    assert.ok(described, control);
    const question = elementWithId(document, described)!;
    assert.ok(question && part.includes(question), "the element is in the same part");
    assert.ok(question.includes(`<h3 data-text>`));
  });
  const ids = parts.map((part) => idOf(partsOf(part).tags.find((tag) => tag.includes(`data-message="${RECORD}"`))!, "aria-describedby"));
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(rulesOf(partsOf(document).style).some(([s, b]) => /(^|,\s*)hr\s*(,|$)/.test(s) && /border-top\s*:[^;]*var\(--vscode-[a-zA-Z0-9-]+\)/.test(b)));
});

// A recorded Decision: its option and whether it applies, its id, its question, the state of its evidence and its reasons, in this order.
const DECIDED_READS = KEPT_READS.filter((name) => keptObject(name).decisions.length > 0);

function assertDecisionOrder(document: string, object: Entry): void {
  const parts = elementsOf(document, '<section data-part="decision"');
  assert.equal(parts.length, object.decisions.length);
  object.decisions.forEach((decision: Entry, index: number) => {
    const part = parts[index];
    const heading = elementOf(part, "<h3>")!;
    assert.match(heading, /^<h3><strong data-text>/);
    assert.equal(words(heading), `${decision.option} ${PHRASES.get(String(decision.applies))}`);
    const places = [part.indexOf(heading), part.indexOf(decision.decision_id), part.indexOf(`<span data-text>${decision.question}</span>`)];
    if (decision.evidence_change !== null) places.push(part.indexOf('<p data-element="evidence">'));
    places.push(part.indexOf('<ul data-element="reasons">'));
    assert.ok(places.every((place) => place >= 0), `${places}`);
    assert.deepEqual(places, [...places].sort((a, b) => a - b), `${places}`);
    assert.ok(markedTexts(part).includes(decision.question));
  });
}

for (const name of DECIDED_READS) {
  test(`each Decision's part opens with its option and the phrase of its applies, then its id, its question, its evidence and its reasons: ${name}`, async (t) => {
    const object = keptObject(name);
    assertDecisionOrder((await documentFor(t, success(object))).document, object);
  });

  test(`with applies turned over and the question replaced in the test, the heading and the question follow: ${name}`, async (t) => {
    const object = keptObject(name);
    for (const decision of object.decisions) {
      decision.applies = !decision.applies;
      decision.question = `zq-replaced question of ${decision.decision_id}`;
    }
    assertDecisionOrder((await documentFor(t, success(object))).document, object);
  });
}

// The way to the choices: how many decisions are pending, a link that jumps to the first choices, what bears on the choice above it,
// and each option's radio named by the option alone.
const COUNT = "Number of pending decisions:";
const SKIP = "To the choices";
const NONE = "None.";
const WARNINGS = "Warnings of the Comparison";
const LIMITATIONS = "Limitations of the Comparison";
const linkTo = (html: string): [string, string][] => [...html.matchAll(/<a href="#([^"]*)"[^>]*>([^<]*)<\/a>/g)].map((match) => [match[1], match[2]]);

for (const name of PENDING_READS) {
  test(`the heading of the pending decisions is followed by their count, in a link to the Study's part: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const after = document.slice(document.indexOf("<h2>Pending decisions</h2>") + "<h2>Pending decisions</h2>".length).trimStart();
    const line = elementOf(after, "<p")!;
    assert.ok(after.startsWith(line), after.slice(0, 80));
    assert.equal(words(line), `${COUNT} ${object.pending_decisions.length}`);
    const [[target, count]] = linkTo(line);
    assert.equal(count, String(object.pending_decisions.length));
    assert.match(elementWithId(document, target) ?? "", /^<div data-part="study"/);
  });

  test(`the controls hold a link to the choices of the first pending decision: ${name}`, async (t) => {
    const { document } = await documentFor(t, success(keptObject(name)));
    const controls = elementOf(document, '<div data-element="controls">')!;
    const skip = linkTo(controls).filter(([, text]) => text === SKIP);
    assert.equal(skip.length, 1, controls);
    const fieldset = elementOf(elementsOf(document, '<section data-part="pending">')[0], "<fieldset ")!;
    assert.equal(elementWithId(document, skip[0][0]), fieldset);
  });

  test(`directly above each fieldset, a line names how many warnings and limitations its Comparison holds, each count a link to its list: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    elementsOf(document, '<section data-part="pending">').forEach((part, index) => {
      const comparison = object.comparisons.find((each: Entry) => each.comparison_id === object.pending_decisions[index].comparison_id);
      const before = part.slice(0, part.indexOf("<fieldset ")).trimEnd();
      const line = before.slice(before.lastIndexOf("<p "));
      assert.equal(words(line), `${WARNINGS} ${comparison.warnings.length} ${LIMITATIONS} ${comparison.limitations.length}`, line);
      const [warnings, limitations] = linkTo(line).map(([target]) => elementWithId(document, target) ?? "");
      assert.ok(warnings.includes(`<h4>${WARNINGS}</h4>`) && elementsOf(warnings, "<li>").length === comparison.warnings.length, warnings);
      assert.ok(limitations.includes(`<h4>${LIMITATIONS}</h4>`) && elementsOf(limitations, "<li data-text>").length === comparison.limitations.length, limitations);
    });
  });

  test(`each radio is named by its option's text alone and described by its consequence: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    object.pending_decisions.forEach((pending: Entry, index: number) => {
      const radios = partsOf(elementsOf(document, '<section data-part="pending">')[index]).tags.filter((tag) => tag.startsWith('<input type="radio"'));
      assert.equal(radios.length, pending.options.length);
      pending.options.forEach((option: Entry, at: number) => {
        const named = idOf(radios[at], "aria-labelledby");
        const described = idOf(radios[at], "aria-describedby");
        assert.ok(named && described, radios[at]);
        assert.deepEqual(markedTexts(elementWithId(document, named) ?? ""), [option.text]);
        assert.deepEqual(markedTexts(elementWithId(document, described) ?? ""), [option.consequence]);
      });
    });
  });
}

test("with no Decision and no Declared deviation, the headings Decisions and Declared deviations are each followed by None.: status-success", async (t) => {
  const object = keptObject("status-success");
  assert.equal(object.decisions.length + object.declared_deviations.length, 0);
  const { document } = await documentFor(t, success(object));
  for (const heading of ["Decisions", "Declared deviations"]) {
    const after = document.slice(document.indexOf(`<h2>${heading}</h2>`) + `<h2>${heading}</h2>`.length).trimStart();
    assert.ok(after.startsWith(`<p>${NONE}</p>`), `${heading}: ${after.slice(0, 60)}`);
  }
});

test("with a Decision and a Declared deviation, neither heading is followed by None.: status-deviation with status-decided's Decision", async (t) => {
  const object = keptObject("status-deviation");
  object.decisions = keptObject("status-decided").decisions;
  assert.ok(object.declared_deviations.length > 0);
  const { document } = await documentFor(t, success(object));
  assert.ok(!document.includes(`<p>${NONE}</p>`));
});
