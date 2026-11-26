// The panel as a screen for deciding: the controls take the theme's colours, a call in flight locks them, each pending decision's
// choices form one group named by its question and stand under the evidence, the pending decisions are told apart, a recorded
// Decision says its outcome first, and the demonstration's kept states as headless Chrome draws them.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, opened, startChrome, type Evaluate } from "./chrome";
import * as fs from "node:fs";
import * as path from "node:path";
import { DEMONSTRATION, JOURNEY, KEPT } from "./kept";
import { KEPT_FIGURES, KEPT_READS, documentFor, elementOf, elementsOf, heldRecorder, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, workspace, FIGURES_FAILED } from "./panel-harness";
import { BELOW_AA, THEMES, themed } from "./themes";

type Entry = Record<string, any>;

const [, RECORD, SEND_AGAIN] = contract.messages;
const TIMEOUT = { error: { code: null, killed: true, signal: "SIGTERM" } };
const words = (html: string | undefined): string => partsOf(html ?? "").between.split(/\s+/).filter(Boolean).join(" ");
const PHRASES = new Map(contract.applies_phrases.map((entry) => [entry.slice(0, entry.indexOf("=")), entry.slice(entry.indexOf("=") + 1)] as [string, string]));

// Each rule of a style, as its selector and its declarations.
const rulesOf = (style: string): [string, string][] => [...style.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => [match[1].trim(), match[2]]);
const declares = (body: string, property: string, value: RegExp): boolean =>
  body.split(";").some((declaration) => declaration.includes(":") && declaration.slice(0, declaration.indexOf(":")).trim() === property && value.test(declaration.slice(declaration.indexOf(":") + 1).trim()));
// A variable of the palettes, which hold the theme's colours: a name of their own, never one of VS Code's.
const THEME = /^var\(--(?!vscode-)[a-z0-9-]+\)$/;

async function styleOf(t: TestContext): Promise<string> {
  return partsOf((await documentFor(t, success(keptObject("status-success")))).document).style;
}

// The rules a control's colours, border and focus take from the palettes, by what each one sets.
const CONTROL_RULES: [string, (rules: [string, string][]) => boolean][] = [
  ["button takes its background from --slate", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "background", /^var\(--slate\)$/))],
  ["button takes its colour from --btnfg", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "color", /^var\(--btnfg\)$/))],
  ["a hovered button takes --pen", (rules) => rules.some(([s, b]) => /button[^,{]*:hover/.test(s) && declares(b, "background", /^var\(--pen\)$/))],
  ["a disabled button takes its colours from the palettes", (rules) => rules.some(([s, b]) => /button[^,{]*:disabled/.test(s) && declares(b, "background", THEME) && declares(b, "color", THEME))],
  ["button takes a border from --chalk2, which stands out from the palette's ground", (rules) => rules.some(([s, b]) => /(^|,\s*)button\s*(,|$)/.test(s) && declares(b, "border", /var\(--chalk2\)/))],
  [":focus-visible has an outline of 1px solid --focus", (rules) => rules.some(([s, b]) => /:focus-visible/.test(s) && declares(b, "outline", /^1px solid var\(--focus\)$/))],
  ["a radio input takes its accent-color from the palettes", (rules) => rules.some(([s, b]) => /input\[type="radio"\]/.test(s) && declares(b, "accent-color", THEME))],
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
  const muted = rulesOf(await styleOf(t)).filter(([, b]) => declares(b, "color", /^var\(--chalk2\)$/) && declares(b, "font-size", /^0\.9em$/));
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
      assert.ok(!/<li>[^]*?<input/.test(fieldset), "no option is a list item");
    });
  });

  test(`D-148's order: the delta's element, the coverage element, the frame line, the warnings, the line of the limits, the fieldset, then the closed fold of the charts, then the Comparison's paths and its limitations: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    for (const part of elementsOf(document, '<section data-part="pending">')) {
      const comparison = elementOf(part, '<div data-part="comparison"')!;
      const at = (opening: string) => comparison.indexOf(opening);
      // A withheld delta draws no chart and no figure, and has no fold.
      const withheld = object.comparisons.find((each: Entry) => comparison.includes(each.comparison_id)).delta.value === null;
      const order = [at('<p data-element="delta">'), at('<p data-element="coverage">'), at('<p data-element="frame">'), at('<div data-part="warnings"'), at('<p data-element="limits">'), at("<fieldset "), ...(withheld ? [] : [at('<details data-element="charts">')])];
      const rest = Math.min(...[at("Output path"), at('<div data-part="limitations"')].filter((place) => place >= 0));
      assert.ok(order.every((place) => place >= 0), `${order}`);
      assert.equal(at('<details data-element="charts">') >= 0, !withheld, "a fold of the charts unless the delta is withheld");
      assert.deepEqual([...order, rest], [...order, rest].sort((a, b) => a - b), `${order} then ${rest}`);
      assert.ok(!/<details data-element="charts" open/.test(comparison), "the fold of the charts is closed");
      for (const chart of ['<div data-chart="delta">', "<div data-figures>"]) if (at(chart) >= 0) assert.ok(at(chart) > at('<details data-element="charts">'), `${chart} in the fold`);
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
  assert.ok(rulesOf(partsOf(document).style).some(([s, b]) => /(^|,\s*)hr\s*(,|$)/.test(s) && /border-top\s*:[^;]*var\(--(?!vscode-)[a-z0-9-]+\)/.test(b)));
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
const RULE = "Not counted again: an entry that repeats a message above.";
const linkTo = (html: string): [string, string][] => [...html.matchAll(/<a href="#([^"]*)"[^>]*>([^<]*)<\/a>/g)].map((match) => [match[1], match[2]]);

for (const name of PENDING_READS) {
  test(`in the step of the Decisions, the heading of the pending decisions is followed by their count, in a link to the Study's part: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const after = document.slice(document.indexOf("<h4>Pending decisions</h4>") + "<h4>Pending decisions</h4>".length).trimStart();
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

  test(`directly above each fieldset, a line names how many warnings and how many limitations that are no warning's message its Comparison holds, each count a link to its list, and states that rule: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    elementsOf(document, '<section data-part="pending">').forEach((part, index) => {
      const comparison = object.comparisons.find((each: Entry) => each.comparison_id === object.pending_decisions[index].comparison_id);
      const before = part.slice(0, part.indexOf("<fieldset ")).trimEnd();
      const line = before.slice(before.lastIndexOf("<p "));
      // "Now counts and lists only the limitations that are no warning's message, and states that rule." (D-151, answer 8)
      const messages = comparison.warnings.map((warning: Entry) => warning.message);
      const counted = comparison.limitations.filter((limitation: string) => !messages.includes(limitation));
      assert.equal(words(line), `${WARNINGS} ${comparison.warnings.length} ${LIMITATIONS} ${counted.length} ${RULE}`, line);
      const [warnings, limitations] = linkTo(line).map(([target]) => elementWithId(document, target) ?? "");
      assert.ok(warnings.includes(`<h4>${WARNINGS}</h4>`) && elementsOf(warnings, "<li>").length === comparison.warnings.length, warnings);
      assert.ok(limitations.includes(`<h4>${LIMITATIONS}</h4>`) && elementsOf(limitations, "<li data-text>").length === counted.length, limitations);
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

test("with no Decision and no Declared deviation, the heading Decisions in its step and the form of the step of the Declared deviations are each followed by None.: status-success", async (t) => {
  const object = keptObject("status-success");
  assert.equal(object.decisions.length + object.declared_deviations.length, 0);
  const { document } = await documentFor(t, success(object));
  const decisions = document.slice(document.indexOf("<h4>Decisions</h4>") + "<h4>Decisions</h4>".length).trimStart();
  assert.ok(decisions.startsWith(`<p>${NONE}</p>`), `Decisions: ${decisions.slice(0, 60)}`);
  const form = elementOf(elementOf(document, '<details data-step="deviations">')!, '<div data-element="form">')!;
  assert.ok(form.replace('<div data-element="form">', "").trimStart().startsWith(`<p>${NONE}</p>`), `Declared deviations: ${form.slice(0, 80)}`);
});

test("with a Decision and a Declared deviation, neither heading is followed by None.: status-deviation with status-decided's Decision", async (t) => {
  const object = keptObject("status-deviation");
  object.decisions = keptObject("status-decided").decisions;
  assert.ok(object.declared_deviations.length > 0);
  const { document } = await documentFor(t, success(object));
  assert.ok(!document.includes(`<p>${NONE}</p>`));
});

// --- The demonstration's kept states as headless Chrome draws them ----------------------------------------------------------------

// Each kept state of the demonstration, drawn at 420 and 900 px in the four themes. In the first screen, 420 by 700 px: on a state
// with a Pending decision, the question and the first evidence number within the bounds of guard_bounds; on a state whose only
// Decision is its latest, that Decision with the phrase of its applies. Two parts are expected to fail on the panel as it stands, each
// under a mark of its own, and an unmarked test fails once its mark no longer holds.
const DEMONSTRATION_READS = KEPT_READS.filter((name) => name.startsWith(DEMONSTRATION));
const SCREEN = { width: 420, height: 700 };
const BOUNDS = Object.fromEntries(contract.guard_bounds.map((entry) => [entry.split("=")[0], Number(entry.split("=")[1])]));
// The mark of Record out of the first screen on a state with a Pending decision: it follows the evidence and the figures.
const RECORD_OUT_OF_SCREEN: string | undefined = undefined;
// The mark of the latest Decision out of the first screen on final: the proxy Decision follows the whole part of the first.
// Now draws the latest Decision in its first screen, under rule 4 as under rule 3: no state is expected to fail.
const LATEST_OUT_OF_SCREEN: string | undefined = undefined;

type Box = { top: number; bottom: number; width: number; height: number; visible: boolean } | null;
const BOX = (selector: string): string =>
  `(() => { const found = document.querySelector(${JSON.stringify(selector)}); if (!found) return null; const box = found.getBoundingClientRect(); return { top: box.top + scrollY, bottom: box.bottom + scrollY, width: box.width, height: box.height, visible: found.checkVisibility() }; })()`;
// An element inside a closed fold keeps a box in Chrome but is not drawn: `checkVisibility` tells them apart.
const drawnAt = (box: Box): boolean => box !== null && box.width > 0 && box.height > 0 && box.visible;
const inScreen = (box: Box): boolean => drawnAt(box) && box!.top >= 0 && box!.bottom <= SCREEN.height;

async function demonstrationDocument(t: TestContext, name: string): Promise<string> {
  if (name.startsWith(JOURNEY)) {
    const state = name.slice(JOURNEY.length, -".status".length);
    const figures = fs.existsSync(path.join(KEPT, "journey", `${state}.figures.out`)) ? [success(keptObject(`${JOURNEY}${state}.figures`))] : [];
    return (await documentFor(t, success(keptObject(name)), ...figures)).document;
  }
  return (await documentFor(t, success(keptObject(name)), success(keptObject(KEPT_FIGURES[name])))).document;
}

// The kept pending states whose first screen is checked: the demonstration's, and the journey's 04, 09 and 11 and status-several-pending
// (chadlis/hypotrail#253).
const FIRST_SCREEN_READS = [
  ...DEMONSTRATION_READS.filter((read) => keptObject(read).pending_decisions.length > 0),
  ...["04-pending", "09-new-compare", "11-study-changed"].map((state) => `${JOURNEY}${state}.status`),
  "status-several-pending",
];

// The browser, or a skip when it is missing or does not start.
async function chromeOrSkip(t: TestContext, what: string): Promise<string | undefined> {
  if (!hasChrome(t, what)) return undefined;
  const address = await startChrome(t);
  if (address === undefined) t.skip(`${what} is skipped: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
  return address;
}

// The document of a kept state in the first screen, in a theme.
async function firstScreen(t: TestContext, address: string, document: string, theme: string): Promise<Evaluate> {
  const evaluate = await opened(t, address, document, SCREEN.width, SCREEN.height);
  await evaluate(themed(theme));
  return evaluate;
}

// "`guard_bounds` guards that the question a person must answer sits near the top; in the redesign, Now's question line is that question"
// (the drive's answer on chadlis/hypotrail#252, D-133).
const QUESTION_DRAWN = '[data-element="now-question"]';
const EVIDENCE_DRAWN = 'section[data-part="now"] [data-element="delta"] a[data-kind="delta"]';
const RECORD_DRAWN = `section[data-part="now"] button[data-message="${RECORD}"]`;
const CHOICES_DRAWN = 'section[data-part="now"] fieldset';
// "2. the words box, as a closed "Add your words" above Record" (D-151, answer 5): its summary is drawn, the box itself is folded.
const WORDS_DRAWN = 'section[data-part="now"] details[data-element="add-words"] > summary';
const WORDS_FOLDED = 'section[data-part="now"] details[data-element="add-words"]:not([open])';
// The line of Now that holds the latest Decision, its option and the phrase of its applies: under rule 4 the line of the latest Decision,
// under rule 3 the line of the Decision next_step names.
const latestHeading = (object: Entry): string =>
  `section[data-part="now"] ${object.next_step.kind === "look_again" ? '[data-element="look-again"]' : '[data-element="latest-decision"]'}`;

for (const name of DEMONSTRATION_READS) {
  test(`in each of the four themes at 420 and 900 px, every text of the kept state stands at AA contrast against what it is drawn on: ${name}`, { timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the drawings of the demonstration's kept states");
    if (address === undefined) return;
    const document = await demonstrationDocument(t, name);
    for (const theme of Object.keys(THEMES)) {
      for (const width of [420, 900]) {
        const evaluate = await opened(t, address, document, width, SCREEN.height);
        await evaluate(themed(theme));
        assert.equal(await evaluate("innerWidth"), width);
        assert.deepEqual(await evaluate(BELOW_AA), [], `${theme} at ${width} px`);
      }
    }
  });
}

// "every text of the kept states 04, 09, 10, 17 and 33 stands at AA contrast against what it is drawn on; the `verify-panel` sheet covers
// the rest" (chadlis/hypotrail#252): the states of the journey, each with its figures read where one is kept.
const JOURNEY_CONTRAST = ["04-pending", "09-new-compare", "10-proxy", "17-interrupted", "33-chinook-assessed"];

for (const state of JOURNEY_CONTRAST) {
  test(`in each of the four themes at 420 and 900 px, every text of the journey's kept state stands at AA contrast against what it is drawn on: ${state}`, { timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the drawings of the journey's kept states");
    if (address === undefined) return;
    const answers = [success(keptObject(`${JOURNEY}${state}.status`))];
    if (fs.existsSync(path.join(KEPT, "journey", `${state}.figures.out`))) answers.push(success(keptObject(`${JOURNEY}${state}.figures`)));
    const { document } = await documentFor(t, ...answers);
    for (const theme of Object.keys(THEMES)) {
      for (const width of [420, 900]) {
        const evaluate = await opened(t, address, document, width, SCREEN.height);
        await evaluate(themed(theme));
        assert.equal(await evaluate("innerWidth"), width);
        assert.deepEqual(await evaluate(BELOW_AA), [], `${theme} at ${width} px`);
      }
    }
  });
}

for (const name of FIRST_SCREEN_READS) {
  test(`in the first screen at 420 px in each theme, the question and the first evidence number of the kept state stand within the bounds of guard_bounds: ${name}`, { timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
    if (address === undefined) return;
    const document = await demonstrationDocument(t, name);
    for (const theme of Object.keys(THEMES)) {
      const evaluate = await firstScreen(t, address, document, theme);
      const [question, evidence]: Box[] = [await evaluate(BOX(QUESTION_DRAWN)), await evaluate(BOX(EVIDENCE_DRAWN))];
      assert.ok(drawnAt(question) && question!.top <= BOUNDS.question, `${theme}: the question at ${JSON.stringify(question)}`);
      assert.ok(drawnAt(evidence) && evidence!.top <= BOUNDS.evidence, `${theme}: the first evidence number at ${JSON.stringify(evidence)}`);
    }
  });

  test(`in the first screen at 420 px in each theme, the choices' fieldset, the closed fold of the box of words and the whole of Record of the kept state are drawn: ${name}`, { todo: RECORD_OUT_OF_SCREEN, timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
    if (address === undefined) return;
    const document = await demonstrationDocument(t, name);
    for (const theme of Object.keys(THEMES)) {
      const evaluate = await firstScreen(t, address, document, theme);
      const [choices, words, record]: Box[] = [await evaluate(BOX(CHOICES_DRAWN)), await evaluate(BOX(WORDS_DRAWN)), await evaluate(BOX(RECORD_DRAWN))];
      assert.ok(inScreen(choices), `${theme}: the choices at ${JSON.stringify(choices)}, the first screen ${SCREEN.height} px high`);
      assert.ok(inScreen(words) && (await evaluate(`document.querySelector(${JSON.stringify(WORDS_FOLDED)}) !== null`)), `${theme}: the closed fold of the box of words at ${JSON.stringify(words)}`);
      assert.ok(drawnAt(record) && record!.bottom <= SCREEN.height, `${theme}: the bottom of Record at ${JSON.stringify(record)}, the first screen ${SCREEN.height} px high`);
    }
  });

  test(`the mark of Record below the first screen stands only while, in one theme at least, Record of the kept state is drawn out of it: ${name}`, { timeout: 120000 }, async (t) => {
    if (RECORD_OUT_OF_SCREEN === undefined) return;
    const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
    if (address === undefined) return;
    const document = await demonstrationDocument(t, name);
    const out: string[] = [];
    for (const theme of Object.keys(THEMES)) {
      const record: Box = await (await firstScreen(t, address, document, theme))(BOX(RECORD_DRAWN));
      assert.ok(drawnAt(record), `${theme}: Record is not drawn`);
      if (!inScreen(record)) out.push(theme);
    }
    assert.ok(out.length > 0, `Record is in the first screen in each of the four themes: remove the mark RECORD_OUT_OF_SCREEN, so that its test is no longer expected to fail`);
  });
}

for (const name of DEMONSTRATION_READS.filter((read) => keptObject(read).pending_decisions.length === 0 && keptObject(read).decisions.length === 1)) {
  test(`in the first screen at 420 px in each theme, Now draws the latest Decision of the kept state with the phrase of its applies: ${name}`, { timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
    if (address === undefined) return;
    const object = keptObject(name);
    const document = await demonstrationDocument(t, name);
    for (const theme of Object.keys(THEMES)) {
      const evaluate = await firstScreen(t, address, document, theme);
      const heading: Box = await evaluate(BOX(latestHeading(object)));
      assert.ok(inScreen(heading), `${theme}: the latest Decision at ${JSON.stringify(heading)}`);
      const line: string = await evaluate(`document.querySelector(${JSON.stringify(latestHeading(object))}).textContent`);
      assert.ok(line.includes(object.decisions[0].option) && line.includes(PHRASES.get(String(object.decisions[0].applies))!), line);
    }
  });
}

for (const name of DEMONSTRATION_READS.filter((read) => keptObject(read).decisions.length > 1)) {
  test(`in the first screen at 420 px in each theme, Now draws the latest Decision of the kept state: ${name}`, { todo: LATEST_OUT_OF_SCREEN, timeout: 120000 }, async (t) => {
    const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
    if (address === undefined) return;
    const document = await demonstrationDocument(t, name);
    for (const theme of Object.keys(THEMES)) {
      const heading: Box = await (await firstScreen(t, address, document, theme))(BOX(latestHeading(keptObject(name))));
      assert.ok(inScreen(heading), `${theme}: the latest Decision at ${JSON.stringify(heading)}, the first screen ${SCREEN.height} px high`);
    }
  });
}

test("the mark of the latest Decision below the first screen stands only while, in one theme at least, the latest Decision of final is drawn out of it", { timeout: 120000 }, async (t) => {
  if (LATEST_OUT_OF_SCREEN === undefined) return;
  const address = await chromeOrSkip(t, "the first screen of the demonstration's kept states");
  if (address === undefined) return;
  const name = `${DEMONSTRATION}final.status`;
  const document = await demonstrationDocument(t, name);
  const out: string[] = [];
  for (const theme of Object.keys(THEMES)) {
    const heading: Box = await (await firstScreen(t, address, document, theme))(BOX(latestHeading(keptObject(name))));
    assert.ok(heading !== null, `${theme}: the document of final holds no latest Decision`);
    if (!inScreen(heading)) out.push(theme);
  }
  assert.ok(out.length > 0, `the latest Decision of final is in the first screen in each of the four themes: remove the mark LATEST_OUT_OF_SCREEN, so that its test is no longer expected to fail`);
});
