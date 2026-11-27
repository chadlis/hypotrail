// The lesson cards in the panel: each card the lesson read gives, drawn as a closed fold after the choices and Record, and nothing of
// that read in the document when it is not usable beside the status read.
// "A card is a closed `<details>` placed after the choices and Record, in the same way the charts fold" (ADR 0007, Decision 7).
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, opened, startChrome } from "./chrome";
import { kept } from "./kept";
import { documentFor, elementOf, elementsOf, keptObject, lastDocument, panelOf, partsOf, runCommand, settle, success, unescaped, workspace } from "./panel-harness";
import { exit, heldRecorder, lesson, type Answer, UNSUPPORTED_LESSON } from "./recorder";

type Entry = Record<string, any>;

const [, RECORD] = contract.messages;
const CARD = '<details data-element="card"';
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
// Each item identifies a read and a key path, and displays the key path alone.
const itemsOf = (card: string): [string, string][] => [...card.matchAll(/<li data-shows="([^"]+)">([\s\S]*?)<\/li>/g)].map((match) => [match[1], words(match[2])]);
const words = (html: string): string => unescaped(partsOf(html).between.split(/\s+/).filter(Boolean).join(" "));
// The document with the nonce of its style and script, new for each document, and the folder of its workspace, new for each test's
// workspace, each written as one fixed text.
const fixed = (document: string): string =>
  document.replace(/nonce-[0-9a-f]+/g, "nonce-N").replace(/nonce="[0-9a-f]+"/g, 'nonce="N"').replace(/hypotrail-read 7 &lt;b&gt;-[A-Za-z0-9]+/g, "WORKSPACE");
// The document with the part that holds the cards removed.
const withoutCards = (document: string): string => {
  const [part] = elementsOf(document, '<div data-part="lesson">');
  return part === undefined ? document : document.replace(`${part}\n`, "");
};

// The two kept states of the demonstration with a kept lesson read, each with its three kept reads.
const STATES = ["after-compare", "after-decide"];
const readsOf = (state: string): Answer[] => [
  keptAnswer(`demonstration.${state}.status`),
  keptAnswer(`demonstration.${state}.figures`),
  lesson(keptAnswer(`lesson.${state}`)),
];

async function shown(t: TestContext, answers: Answer[]): Promise<string> {
  return fixed((await documentFor(t, ...answers)).document);
}

for (const state of STATES) {
  test(`each card of the kept lesson read is a closed details whose summary is its title and whose text is its text, after every Record and after Now, with no digit in it: ${state}`, async (t) => {
    const document = await shown(t, readsOf(state));
    const read = keptObject(`lesson.${state}`);
    const cards = elementsOf(document, CARD);
    assert.ok(read.cards.length > 0, "the kept read gives cards");
    assert.equal(cards.length, read.cards.length);
    cards.forEach((card, at) => {
      const opening = card.slice(0, card.indexOf(">") + 1);
      assert.ok(!/\sopen[\s>]/.test(opening), `${read.cards[at].kind}: the fold is closed`);
      const summary = card.slice(card.indexOf("<summary>"), card.indexOf("</summary>") + "</summary>".length);
      assert.equal(words(summary), read.cards[at].title);
      assert.ok(words(card).includes(read.cards[at].text), read.cards[at].kind);
      assert.doesNotMatch(words(card), /\d/, `${read.cards[at].kind}: no digit in the card`);
      const place = document.indexOf(card);
      const records = [...document.matchAll(new RegExp(`<button data-message="${RECORD}"`, "g"))].map((match) => match.index!);
      assert.ok(records.every((record) => record < place), `${read.cards[at].kind} comes after every Record`);
      assert.ok(document.indexOf("</section>", document.indexOf('<section data-part="now"')) < place, `${read.cards[at].kind} comes after Now`);
    });
  });

  test(`each item of a card names one of its key paths and an attribute that an element outside the cards holds: ${state}`, async (t) => {
    const document = await shown(t, readsOf(state));
    const cards = elementsOf(document, CARD);
    const outside = document.replace(elementsOf(document, '<div data-part="lesson">')[0], "");
    keptObject(`lesson.${state}`).cards.forEach((card: Entry, at: number) => {
      const items = itemsOf(cards[at]);
      assert.ok(items.length > 0, `${card.kind}: a key path the panel shows is named`);
      for (const [place, path] of items) {
        assert.ok(card.key_paths.some((each: Entry) => each.path === path), `${card.kind}: ${path}`);
        assert.ok(outside.includes(` data-lesson-value="${place}"`), `${card.kind}: ${place} outside the cards`);
      }
    });
  });
}

// The lesson read's object after-compare with another Write sequence than the status read's.
const otherSequence = (): Entry => ({ ...keptObject("lesson.after-compare"), write_sequence: keptObject("demonstration.after-compare.status").write_sequence + 1 });
// A refusal other than UNSUPPORTED_CAPABILITY, as the CLI prints one.
const OTHER_REFUSAL = exit(2, JSON.stringify({ ok: false, error: { code: "STUDY_NOT_FOUND", message: "no Study at this path", stage: "study", details: {} } }));
const UNUSABLE: [string, Answer][] = [
  ["another refusal", OTHER_REFUSAL],
  ["a no-answer", exit(0, "not JSON")],
  ["another write_sequence", success(otherSequence())],
];

for (const [name, answer] of UNUSABLE) {
  test(`with ${name} of the lesson read, the document holds no card and is otherwise the document of a usable read: after-compare`, async (t) => {
    const [status, figures, usable] = readsOf("after-compare");
    const document = await shown(t, [status, figures, lesson(answer)]);
    assert.deepEqual(elementsOf(document, CARD), []);
    const usableDocument = await shown(t, [status, figures, usable]);
    assert.ok(elementsOf(usableDocument, CARD).length > 0, "the usable read draws its cards");
    assert.equal(document, withoutCards(usableDocument));
  });
}

test("with UNSUPPORTED_CAPABILITY of the lesson read on a Chinook Study, the document holds no card and no failure text, and is otherwise the document of a usable read", async (t) => {
  const refusal = JSON.parse(UNSUPPORTED_LESSON);
  assert.equal(refusal.error.code, "UNSUPPORTED_CAPABILITY");
  const status = keptAnswer("status-chinook-pending");
  const figures = keptAnswer("figures-chinook-pending");
  const document = await shown(t, [status, figures, lesson(exit(2, UNSUPPORTED_LESSON))]);
  assert.deepEqual(elementsOf(document, CARD), []);
  for (const text of [refusal.error.code, refusal.error.message]) assert.ok(!unescaped(document).includes(text), text);
  const usable = { ...keptObject("lesson.after-compare"), write_sequence: keptObject("status-chinook-pending").write_sequence };
  const usableDocument = await shown(t, [status, figures, lesson(success(usable))]);
  assert.ok(elementsOf(usableDocument, CARD).length > 0, "the usable read draws its cards");
  assert.equal(document, withoutCards(usableDocument));
});

// "The value at a key path is linked or highlighted where the panel already shows it. It is never written into the card's text." (#283)
const DELTA_ATTRIBUTE = 'data-element="delta"';
const withCard = async (t: TestContext): Promise<string> => {
  const [status, figures] = readsOf("after-compare");
  const card = {
    kind: "comparisons",
    title: "Comparisons",
    text: "A card's text.",
    key_paths: [
      { read: "status", path: "comparisons[].delta.value" },
      { read: "status", path: "attempts[].request_id" },
    ],
  };
  const sequence = keptObject("demonstration.after-compare.status").write_sequence;
  return shown(t, [status, figures, lesson(success({ ok: true, write_sequence: sequence, track: "temporal_regression", cards: [card] }))]);
};

test("a card names the key path whose value the panel shows with the place of the element that shows it, nothing for a key path the panel does not show, and writes no value: after-compare", async (t) => {
  const document = await withCard(t);
  const [drawn] = elementsOf(document, CARD);
  assert.deepEqual(itemsOf(drawn), [["status comparisons[].delta.value", "comparisons[].delta.value"]]);
  assert.ok(document.includes(`<p ${DELTA_ATTRIBUTE}`), "the document shows the delta's element");
  assert.ok(!drawn.includes("attempts[].request_id"), "nothing for a key path the panel does not show");
  const value = String(keptObject("demonstration.after-compare.status").comparisons[0].delta.value);
  assert.ok(!words(drawn).includes(value.slice(0, 5)), "the delta's value is not written in the card");
});

test("in a browser, opening the card highlights only delta values including the one in Now, and closing it removes the highlight: after-compare", { timeout: 60000 }, async (t) => {
  if (!hasChrome(t, "the highlight of a card")) return;
  const address = await startChrome(t);
  if (address === undefined) return t.skip(`the highlight of a card is skipped: Chrome at ${CHROME} did not start within ${START_MS} ms`);
  const evaluate = await opened(t, address, await withCard(t), 420, 700);
  const cardExists = 'document.querySelector(\'details[data-element="card"]\') !== null';
  for (let n = 0; n < 30 && !(await evaluate(cardExists)); n += 1) await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(await evaluate(cardExists), true);
  const targets = await evaluate('document.querySelectorAll(\'[data-lesson-value="status comparisons[].delta.value"]\').length');
  const highlighted = 'JSON.stringify([...document.querySelectorAll("[data-highlighted]")].map((element) => element.getAttribute("data-kind") + " " + (element.closest(\'section[data-part="now"]\') !== null)))';
  assert.equal(await evaluate(highlighted), "[]");
  await evaluate('document.querySelector(\'details[data-element="card"]\').open = true');
  await new Promise((resolve) => setTimeout(resolve, 50));
  const open = JSON.parse(await evaluate(highlighted));
  assert.equal(open.length, targets);
  assert.ok(open.includes("delta true"));
  assert.ok(open.every((target: string) => target.startsWith("delta ")));
  await evaluate('document.querySelector(\'details[data-element="card"]\').open = false');
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(await evaluate(highlighted), "[]");
});

// "The Pending decision, its choices and Record are never held back by this read." (#283)
test("a late lesson adds its cards without replacing the Pending decision document", async (t) => {
  const [status, figures, usable] = readsOf("after-compare");
  workspace(t, ["bike"]);
  const held = heldRecorder(t, true);
  await runCommand();
  held.answer(status);
  await settle();
  held.answer(figures);
  await settle();

  const document = lastDocument();
  const before = panelOf().documents.length;
  assert.ok(!document.includes('aria-busy="true"') && document.includes(`<button data-message="${RECORD}"`), "Record is drawn and the panel is not busy");
  assert.ok(document.includes("<fieldset"), "the choices are drawn");
  assert.deepEqual(elementsOf(document, CARD), []);

  held.answer(usable);
  await settle();
  assert.equal(panelOf().documents.length, before);
  assert.equal(elementsOf(lastDocument(), CARD).length, keptObject("lesson.after-compare").cards.length);
  const [update] = panelOf().updates as { lesson: string; nonce: string }[];
  assert.equal(panelOf().updates.length, 1);
  panelOf().send({ lessonReady: "earlier-document" });
  assert.equal(panelOf().updates.length, 1);
  panelOf().send({ lessonReady: update.nonce });
  assert.deepEqual(panelOf().updates, [update, update]);

  await t.test("the browser keeps the selected option, typed words and enabled Record", { timeout: 60000 }, async (browser) => {
    if (!hasChrome(browser, "the pending form after a late lesson")) return;
    const address = await startChrome(browser);
    if (address === undefined) return browser.skip(`the pending form is skipped: Chrome at ${CHROME} did not start within ${START_MS} ms`);
    const evaluate = await opened(browser, address, document, 420, 700);
    await evaluate(`(() => {
      const option = document.querySelector('input[data-pending]');
      const words = document.querySelector('textarea[data-words]');
      words.closest("details").open = true;
      option.click();
      words.value = "A decision draft.";
      words.focus();
      window.pending = [option, words, document.querySelector('button[data-message="${RECORD}"]')];
    })()`);
    for (const nonce of ["earlier-document", update.nonce, update.nonce]) {
      await evaluate(`window.dispatchEvent(new MessageEvent("message", {data: ${JSON.stringify({ ...update, nonce })}}))`);
      assert.equal(await evaluate(`document.querySelectorAll('[data-part="lesson"]').length`), Number(nonce === update.nonce));
    }
    const keptDraft = await evaluate(`(() => {
      const [option, words, record] = window.pending;
      return option.checked && words.value === "A decision draft." && words === document.activeElement
        && !record.disabled && [option, words, record].every((control) => document.contains(control));
    })()`);
    assert.equal(keptDraft, true);
  });
});

test("a comparison delta path identifies the numeric element of every rendered entry", async (t) => {
  const status = keptObject("demonstration.after-compare.status");
  const [first] = status.comparisons;
  status.comparisons = [first, { ...first, comparison_id: "00000000-0000-4000-8000-000000000999", delta: { ...first.delta, value: 23.75 } }];
  const card = {
    kind: "comparisons",
    title: "Comparisons",
    text: "A card's text.",
    key_paths: [{ read: "status", path: "comparisons[].delta.value" }],
  };
  const answer = lesson(success({ ok: true, write_sequence: status.write_sequence, cards: [card] }));
  const document = await shown(t, [success(status), readsOf("after-compare")[1], answer]);
  const values = [...document.matchAll(/<a [^>]*data-lesson-value="status comparisons\[\]\.delta\.value"[^>]*>([^<]+)<\/a>/g)].map((match) => match[1]);
  assert.ok(values.length >= 2);
  assert.ok(values.includes("23.75"));
  for (const tag of partsOf(document).tags.filter((tag) => tag.includes('data-lesson-value="status comparisons[].delta.value"'))) {
    assert.match(tag, /^<a .*data-kind="delta"/);
  }
});

test("repeated values are marked in their summary, chart label, caption, frame and full Decision part", async (t) => {
  const before = await shown(t, readsOf("after-compare"));
  const after = await shown(t, readsOf("after-decide"));
  const slot = (document: string, prefix: string, path: string, part?: string) => {
    const scope = part === undefined ? document : elementOf(document, part)!;
    assert.ok(elementOf(scope, prefix)?.includes(`data-lesson-value="status ${path}"`), `${path} in ${prefix}`);
  };
  slot(before, "<summary>", "attempts[].mode", '<details data-step="attempts">');
  slot(before, '<span data-key="delta">', "comparisons[].delta.value");
  slot(before, '<p data-element="caption">', "comparisons[].delta.definition");
  slot(before, '<p data-element="frame">', "assessments[].scorer.id");
  slot(after, '<p data-element="latest-decision">', "decisions[].applies");
  slot(after, "<summary>", "decisions[].applies", '<details data-step="decisions">');
  const [decision] = elementsOf(after, '<section data-part="decision"');
  assert.equal((decision.match(/data-lesson-value="status decisions\[\]\.applies"/g) ?? []).length, 2);
});
