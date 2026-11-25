import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import contract from "../contract.json";
import { recorder } from "./recorder";
import { CALLERS, invoke, keptAnswer, toolOf, workspace, WRITE_TOOL } from "./tools-harness";

// A Write sequence read that appears in no other input, so that the message can be searched for it.
const READ_SEQUENCE = 48151623;
const CITED = ["c53337e9-d255-423d-a851-414278d5c3f0", "817d7c96-0d5e-4a2b-9c55-1f0e3a6b7d21"];

type Accepted = { name: string; names: string[]; given?: (root: string) => string; source?: string; author: string };

const ACCEPTED: Accepted[] = [
  { name: "study given, one Study found, author proxy and a source", names: ["only"], given: (root) => path.join(root, "only"), author: "proxy", source: "the rule: keep the lower MAE" },
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
  { name: "study absent and one Study found", names: ["only"] },
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
  const { studies } = workspace(t, ["only"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "proxy", cited_ids: CITED, read_sequence: 0, study: studies[0] };
  await assert.rejects(toolOf(WRITE_TOOL).prepareInvocation!({ input }, {}) as Promise<unknown>, (error: Error) => {
    assert.match(error.message, /(?<![\w-])source(?![\w-])/);
    return true;
  });
  assert.equal(calls.length, 0);
});

// A write with no `study` that also lacks another input: the absent `study` is what it is refused for.
const STUDY_AND_MORE_ABSENT: [string, Record<string, unknown>][] = [
  ["no study and no question", { question: undefined }],
  ["author proxy, no study and no source", { author: "proxy" }],
];

for (const [how, call] of CALLERS) {
  for (const [name, change] of STUDY_AND_MORE_ABSENT) {
    test(`the write ${how} with ${name} is refused with the list of the Studies found, with no start`, async (t) => {
      const { studies } = workspace(t, ["a", "b"]);
      const calls = recorder(t, keptAnswer("decide-success"));
      const input = { question: "q", option: "o", author: "human", cited_ids: CITED, read_sequence: 0, ...change };
      const text = await call(WRITE_TOOL, input);
      assert.equal(calls.length, 0);
      assert.ok(text.includes(JSON.stringify(studies)), text);
      assert.match(text, /Nothing was started\./);
    });
  }
}

const WHITE_SPACE = "   ";

test("with author human and a source of white space only, the confirmation shows no source and invoke passes no --source", async (t) => {
  const { studies } = workspace(t, ["only"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "human", source: WHITE_SPACE, cited_ids: CITED, read_sequence: 0, study: studies[0] };
  const prepared = (await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {})) as { confirmationMessages: { message: string } };
  const text = prepared.confirmationMessages.message;
  assert.ok(text.includes("Source: none"), text);
  await toolOf(WRITE_TOOL).invoke({ input, toolInvocationToken: undefined }, {});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.some((argument) => argument.startsWith("--source")), false, calls[0].args.join(" "));
});

for (const [how, call] of CALLERS) {
  test(`the write ${how} with author proxy and a source of white space only is refused, with no start`, async (t) => {
    const { studies } = workspace(t, ["only"]);
    const calls = recorder(t, keptAnswer("decide-success"));
    const input = { question: "q", option: "o", author: "proxy", source: WHITE_SPACE, cited_ids: CITED, read_sequence: 0, study: studies[0] };
    const text = await call(WRITE_TOOL, input);
    assert.equal(calls.length, 0);
    assert.match(text, /^Nothing was sent to the CLI: a Decision whose author is proxy needs a source/);
  });
}

// Each input that the bridge's own checks refuse, with the input that makes it so.
const NOT_VALID: [string, Record<string, unknown>][] = [
  ["no question", { question: undefined }],
  ["an empty question", { question: "" }],
  ["no option", { option: undefined }],
  ["an empty option", { option: "" }],
  ["no author", { author: undefined }],
  ["no cited_ids", { cited_ids: undefined }],
  ["cited_ids that is not a list", { cited_ids: "c53337e9-d255-423d-a851-414278d5c3f0" }],
  ["cited_ids holding an empty id", { cited_ids: [""] }],
  ["a source that is not a text", { source: 3 }],
  ["no read_sequence", { read_sequence: undefined }],
  ["a negative read_sequence", { read_sequence: -1 }],
  ["a read_sequence that is not an integer", { read_sequence: 1.5 }],
];

for (const [name, change] of NOT_VALID) {
  test(`with ${name}, prepareInvocation refuses, giving no confirmation and starting nothing`, async (t) => {
    const { studies } = workspace(t, ["only"]);
    const calls = recorder(t, keptAnswer("decide-success"));
    const input = { question: "q", option: "o", author: "human", cited_ids: CITED, read_sequence: 0, study: studies[0], ...change };
    let prepared: unknown = "nothing";
    await assert.rejects(
      (async () => {
        prepared = await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {});
      })(),
    );
    assert.equal(prepared, "nothing");
    assert.equal(calls.length, 0);
  });
}

test("with author human and an empty source, the confirmation shows no source and invoke passes no --source", async (t) => {
  const { studies } = workspace(t, ["only"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "human", source: "", cited_ids: CITED, read_sequence: 0, study: studies[0] };
  const prepared = (await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {})) as { confirmationMessages: { message: string } };
  const text = prepared.confirmationMessages.message;
  assert.ok(text.includes("Source: none"), text);
  assert.equal(text.includes('Source: ""'), false, text);
  await toolOf(WRITE_TOOL).invoke({ input, toolInvocationToken: undefined }, {});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.some((argument) => argument.startsWith("--source")), false, calls[0].args.join(" "));
});

test("a given Study that the walk no longer finds once a second Study takes its last visit gets no write: invoke starts nothing, and the refusal names the Studies found", async (t) => {
  // The walk visits at most `walk_max_folders` folders: here the root, `walk_max_folders` - 2 folders below it, and the
  // given Study, last.
  const { root } = workspace(t, []);
  for (let index = 0; index < contract.walk_max_folders - 3; index += 1) fs.mkdirSync(path.join(root, `f${String(index).padStart(3, "0")}`));
  const given = path.join(root, "z", "given");
  fs.mkdirSync(given, { recursive: true });
  fs.writeFileSync(path.join(given, "study.json"), "{}");
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "human", cited_ids: CITED, read_sequence: 0, study: given };
  const prepared = (await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {})) as { confirmationMessages: { message: string } };
  assert.ok(prepared.confirmationMessages.message.includes(JSON.stringify(given)), prepared.confirmationMessages.message);
  // A second Study, sorted first, takes the last visit of the walk from the given one.
  const second = path.join(root, "a");
  fs.mkdirSync(second);
  fs.writeFileSync(path.join(second, "study.json"), "{}");
  const result = await toolOf(WRITE_TOOL).invoke({ input, toolInvocationToken: undefined }, {});
  const text = result.content.map((part) => part.value).join("");
  assert.equal(calls.length, 0);
  assert.match(text, /Nothing was started\./);
  assert.ok(text.includes(JSON.stringify([second])), text);
});

test("a given Study whose study.json is removed between prepareInvocation and invoke starts nothing, and the refusal names the Studies found", async (t) => {
  const { studies } = workspace(t, ["gone", "kept"]);
  const calls = recorder(t, keptAnswer("decide-success"));
  const input = { question: "q", option: "o", author: "human", cited_ids: CITED, read_sequence: 0, study: studies[0] };
  await toolOf(WRITE_TOOL).prepareInvocation!({ input }, {});
  fs.rmSync(path.join(studies[0], "study.json"));
  const result = await toolOf(WRITE_TOOL).invoke({ input, toolInvocationToken: undefined }, {});
  const text = result.content.map((part) => part.value).join("");
  assert.equal(calls.length, 0);
  assert.match(text, /Nothing was started\./);
  assert.ok(text.includes(JSON.stringify([studies[1]])), text);
});
