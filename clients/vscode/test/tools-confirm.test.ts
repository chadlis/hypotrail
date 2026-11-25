import { test } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import { recorder } from "./recorder";
import { invoke, keptAnswer, toolOf, workspace, WRITE_TOOL } from "./tools-harness";

// A Write sequence read that appears in no other input, so that the message can be searched for it.
const READ_SEQUENCE = 48151623;
const CITED = ["c53337e9-d255-423d-a851-414278d5c3f0", "817d7c96-0d5e-4a2b-9c55-1f0e3a6b7d21"];

type Accepted = { name: string; names: string[]; given?: (root: string) => string; source?: string; author: string };

const ACCEPTED: Accepted[] = [
  { name: "study absent, one Study found, author proxy and a source", names: ["only"], author: "proxy", source: "the rule: keep the lower MAE" },
  { name: "study given, two Studies found, author human and no source", names: ["a", "b"], given: (root) => path.join(root, "b"), author: "human" },
];

for (const each of ACCEPTED) {
  test(`with ${each.name}, the confirmation is a plain string of what will be recorded and where, and invoke writes to the folder it shows`, async (t) => {
    const { root } = workspace(t, each.names);
    const calls = recorder(t, keptAnswer("decide-success"));
    const input = {
      question: "Which Configuration do we keep after this Comparison?",
      option: "Keep the Candidate",
      author: each.author,
      cited_ids: CITED,
      read_sequence: READ_SEQUENCE,
      ...(each.source === undefined ? {} : { source: each.source }),
      ...(each.given ? { study: each.given(root) } : {}),
    };
    const prepared = (await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {})) as { confirmationMessages: { title: string; message: unknown } };
    assert.equal(calls.length, 0);
    const message = prepared.confirmationMessages.message;
    assert.equal(typeof message, "string");
    const text = message as string;
    for (const value of [input.question, input.option, `Author: "${input.author}"`, ...CITED]) assert.ok(text.includes(value), value);
    assert.ok(text.includes(each.source === undefined ? "Source: none" : each.source), text);
    assert.equal(text.includes(String(READ_SEQUENCE)), false);
    await invoke(WRITE_TOOL, input);
    assert.equal(calls.length, 1);
    const study = calls[0].args.find((argument) => argument.startsWith("--study="))!.slice("--study=".length);
    assert.ok(text.includes(study), text);
  });
}

const REFUSED: { name: string; names: string[]; given?: (root: string) => string }[] = [
  { name: "study absent and no Study found", names: [] },
  { name: "study absent and two Studies found", names: ["a", "b"] },
  { name: "study given as a folder the walk does not find", names: ["a", "b"], given: (root) => path.join(root, "c") },
];

for (const each of REFUSED) {
  test(`with ${each.name}, the confirmation is not given: prepareInvocation refuses, naming the Studies found, with no start`, async (t) => {
    const { root, studies } = workspace(t, each.names);
    const calls = recorder(t, keptAnswer("decide-success"));
    const input = { question: "q", option: "o", author: "human", cited_ids: CITED, read_sequence: 0, ...(each.given ? { study: each.given(root) } : {}) };
    let prepared: unknown = "nothing";
    await assert.rejects(
      (async () => {
        prepared = await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {});
      })(),
      (error: Error) => {
        assert.match(error.message, /Nothing was started\./);
        for (const study of studies) assert.ok(error.message.includes(study), study);
        return true;
      },
    );
    assert.equal(prepared, "nothing");
    assert.equal(calls.length, 0);
  });
}

test("with author proxy and no source, prepareInvocation refuses, naming source, with no start", async (t) => {
  workspace(t, ["only"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "proxy", cited_ids: CITED, read_sequence: 0 };
  await assert.rejects(toolOf(WRITE_TOOL).prepareInvocation!({ input }, {}) as Promise<unknown>, (error: Error) => {
    assert.match(error.message, /(?<![\w-])source(?![\w-])/);
    return true;
  });
  assert.equal(calls.length, 0);
});
