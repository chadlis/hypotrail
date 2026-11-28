import assert from "node:assert/strict";
import { test } from "node:test";
import contract from "../contract.json";
import { RANKING_REVIEW, followLink, lastDocument, panelOf, partsOf, rankingReviewRead, runCommand, settle, success, withFigures, workspace } from "./panel-harness";
import { exit, recorder } from "./recorder";

const currentNonce = () => /<script nonce="([a-f0-9]+)">/.exec(lastDocument())?.[1];

test("opening a protected Study clears an earlier ordinary Study's review and Record action", async (t) => {
  const [ordinary, protectedStudy] = workspace(t, ["ranking", "protected"]);
  const refusal = exit(2, JSON.stringify({ ok: false, error: { code: "RANKING_HELD_OUT_REFUSED" } }));
  const calls = recorder(t, ...withFigures(success(rankingReviewRead(6, RANKING_REVIEW)), refusal));

  await followLink(0, ordinary);
  await settle();
  assert.match(partsOf(lastDocument()).between, /Awaiting your confirmation/);
  const previousNonce = currentNonce();

  await followLink(0, protectedStudy);
  await settle();
  const { between } = partsOf(lastDocument());
  assert.match(between, /RANKING_HELD_OUT_REFUSED/);
  assert.doesNotMatch(between, /Awaiting your confirmation|Record this Decision/);
  panelOf().send({ message: "record", review: 0, words: "Confirm.", nonce: previousNonce });
  await settle();
  assert.deepEqual(calls.map((call) => call.args[contract.first_arguments.length]), ["status", "figures", "lesson", "status"]);
});

for (const option of ["accepted", "keep_control"]) {
  test(`the panel shows the aggregate proxy verdict ${option} and Record requires the person's words`, async (t) => {
    const [study] = workspace(t, ["ranking"]);
    const review = { ...RANKING_REVIEW, option, option_id: option, unexpected: "PRIVATE_SYNTHETIC_SENTINEL" };
    const calls = recorder(t, ...withFigures(
      success(rankingReviewRead(6, review)), success({ ok: true, decision: { decision_id: "owner-recorded" } }),
      success(rankingReviewRead(8, { ...review, pending: false })),
    ));
    await runCommand();
    await settle();

    const { between, tags } = partsOf(lastDocument());
    for (const shown of [
      "Proxy Decision", "Awaiting your confirmation", option, RANKING_REVIEW.proxy_decision_id, RANKING_REVIEW.question, RANKING_REVIEW.rule, RANKING_REVIEW.source,
      "0.25", "0.125", "0.375", "1997", "3",
    ]) assert.ok(between.includes(shown), shown);
    assert.doesNotMatch(between, /PRIVATE_SYNTHETIC_SENTINEL|No decision waits for you/);
    assert.ok(tags.some((tag) => /<button .*data-review="0".* disabled>/.test(tag)));
    const wrote = () => calls.filter((call) => call.args[contract.first_arguments.length] === "decide");
    panelOf().send({ message: "record", review: 0, words: " \t\n", nonce: currentNonce() });
    await settle();
    assert.equal(wrote().length, 0);

    const words = "  I confirm the recorded verdict.\nI reviewed the aggregate.  ";
    panelOf().send({ message: "record", review: 0, words, nonce: "earlier-document" });
    await settle();
    assert.equal(wrote().length, 0);
    panelOf().send({ message: "record", review: 0, words, option: "a different option", nonce: currentNonce() });
    await settle();
    assert.equal(wrote().length, 1);
    const observed = wrote()[0].args.slice(contract.first_arguments.length);
    assert.ok(observed.some((argument) => /^--request-id=[0-9a-f-]{36}$/.test(argument)));
    assert.deepEqual(observed.filter((argument) => !argument.startsWith("--request-id=")), [
      "decide", `--study=${study}`, `--question=${RANKING_REVIEW.question}`, `--option=${option}`, "--author=human",
      `--question-id=${RANKING_REVIEW.question_id}`, `--option-id=${option}`, `--words=${words}`, "--channel=panel",
      `--artifact=${RANKING_REVIEW.artifact_id}`, "--read-sequence=6", "--json",
    ]);
    assert.match(partsOf(lastDocument()).between, /Confirmed by Record/);
    assert.doesNotMatch(partsOf(lastDocument()).between, /Awaiting your confirmation/);
    panelOf().send({ message: "record", review: 0, words, nonce: currentNonce() });
    await settle();
    assert.equal(wrote().length, 1);
  });
}
