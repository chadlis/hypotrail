// What the notice says after a write: a recorded Decision confirmed with a link to it, a write with no answer and what sending
// again does, and a refusal after which the Study was read again.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { kept } from "./kept";
import { elementOf, keptObject, lastDocument, markedTexts, panelOf, partsOf, runCommand, settle, success, workspace } from "./panel-harness";
import { exit, recorder, type Answer } from "./recorder";

type Entry = Record<string, any>;

const [READ_AGAIN, RECORD] = contract.messages;
const RECORDED = "Recorded:";
const RECORDED_ID = "The Decision was recorded.";
const MAY_HAVE = "The Decision may have been recorded.";
const SEND_AGAIN_SENTENCE = "Send again: a Decision already recorded is not written twice.";
const READ_AGAIN_SENTENCE = "The Study was read again; choose again.";
const TIMEOUT: Answer = { error: { code: null, killed: true, signal: "SIGTERM" } };
const NOT_FOUND = exit(Number(kept("status-not-found.exit")), kept("status-not-found.out"), kept("status-not-found.err"));

const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
const noticeOf = (document: string): string => elementOf(document, '<div data-element="notice"') ?? "";
const words = (html: string): string => partsOf(html).between.split(/\s+/).filter(Boolean).join(" ");

function answerWith(name: string, id: string): Answer {
  const object = JSON.parse(kept(`${name}.out`));
  object.decision.decision_id = id;
  return exit(0, JSON.stringify(object));
}

// The document after the first read answered by status-success, a write answered by `write`, then `after`.
async function afterWrite(t: TestContext, write: Answer, ...after: Answer[]): Promise<string> {
  workspace(t, ["bike"]);
  recorder(t, success(keptObject("status-success")), write, ...after);
  await runCommand();
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  await settle();
  await settle();
  return lastDocument();
}

// The element whose `id` is the `href` of a link, without its `#`.
function targetOf(document: string, href: string): string | undefined {
  const opening = new RegExp(`<([a-z0-9]+) [^>]*\\bid="${href.slice(1)}"[^>]*>`).exec(document);
  return opening ? elementOf(document.slice(opening.index), opening[0]) : undefined;
}

for (const write of ["decide-success", "decide-replay"]) {
  test(`after ${write} whose id the read that follows holds, the notice holds Recorded: and the option in a link to that Decision's part`, async (t) => {
    const read = keptObject("status-decided");
    const id = read.decisions[0].decision_id;
    const document = await afterWrite(t, answerWith(write, id), success(read));
    const notice = noticeOf(document);
    assert.ok(words(notice).startsWith(`${RECORDED} ${read.decisions[0].option}`), words(notice));
    const link = /<a href="(#[^"]*)"[^>]*>(.*?)<\/a>/.exec(notice);
    assert.ok(link, notice);
    assert.deepEqual(markedTexts(link[2]), [read.decisions[0].option]);
    assert.ok(partsOf(targetOf(document, link[1]) ?? "").between.includes(id), `${link[1]} names the part of ${id}`);
    assert.ok(!words(notice).includes(RECORDED_ID));
  });

  test(`after ${write}, the option the notice shows is the read's, changed in the test`, async (t) => {
    const read = keptObject("status-decided");
    read.decisions[0].option = "zq-changed option";
    const document = await afterWrite(t, answerWith(write, read.decisions[0].decision_id), success(read));
    assert.ok(markedTexts(noticeOf(document)).includes("zq-changed option"));
  });

  test(`after ${write} whose id the read that follows does not hold, the notice holds the fixed sentence and that id, and no link`, async (t) => {
    const id = JSON.parse(kept(`${write}.out`)).decision.decision_id;
    assert.ok(!kept("status-decided.out").includes(`"decision_id": "${id}"`));
    const notice = noticeOf(await afterWrite(t, keptAnswer(write), success(keptObject("status-decided"))));
    assert.equal(words(notice), `${RECORDED_ID} ${id}`);
    assert.ok(!notice.includes("<a "));
  });
}

test("the notice can take the focus, and the script scrolls to the recorded Decision and moves the focus to the notice", async (t) => {
  const read = keptObject("status-decided");
  const document = await afterWrite(t, answerWith("decide-success", read.decisions[0].decision_id), success(read));
  assert.match(partsOf(noticeOf(document)).tags[0], /\stabindex="-1"/);
  const { script } = partsOf(document);
  for (const name of ["scrollIntoView", "focus("]) assert.ok(script.includes(name), name);
});

// A write with no answer, then a read while its id is held.
test("after a write with no answer, the document of a read that succeeds while the id is held holds the two sentences and the words, and no cause", async (t) => {
  await afterWrite(t, TIMEOUT, success(keptObject("status-success")));
  panelOf().send({ message: READ_AGAIN });
  await settle();
  const notice = words(noticeOf(lastDocument()));
  for (const text of [contract.write_no_answer_words, MAY_HAVE, SEND_AGAIN_SENTENCE]) assert.ok(notice.includes(text), `${text} in ${notice}`);
  for (const cause of contract.no_answer_causes) assert.ok(!notice.includes(cause), cause);
  assert.ok(!notice.includes("No answer from the CLI:"));
});

// A refused write, then the read that follows.
const REFUSED = ["decide-study-changed", "decide-write-sequence-ahead", "decide-request-conflict", "decide-invalid-arguments", "decide-study-not-found"];

test("the refused writes named here are the kept outputs of decide whose ok is false", () => {
  const kepts = ["decide-success", "decide-replay", ...REFUSED].filter((name) => JSON.parse(kept(`${name}.out`)).ok === false);
  assert.deepEqual(kepts, REFUSED);
});

for (const name of REFUSED) {
  test(`after a refusal and a read that succeeds, the notice holds the CLI's code and message, then the sentence that the Study was read again: ${name}`, async (t) => {
    const error = JSON.parse(kept(`${name}.out`)).error as Entry;
    const notice = noticeOf(await afterWrite(t, keptAnswer(name), success(keptObject("status-success"))));
    const text = words(notice);
    assert.ok(text.includes(error.code) && markedTexts(notice).includes(error.message));
    assert.ok(text.endsWith(READ_AGAIN_SENTENCE), text);
    assert.ok(text.indexOf(error.code) < text.indexOf(READ_AGAIN_SENTENCE));
  });
}

test("after a refusal and a read that fails, the sentence that the Study was read again is absent: decide-study-changed then status-not-found", async (t) => {
  const document = await afterWrite(t, keptAnswer("decide-study-changed"), NOT_FOUND);
  assert.ok(!partsOf(document).between.includes(READ_AGAIN_SENTENCE));
  assert.ok(partsOf(document).between.includes("STUDY_CHANGED"));
});
