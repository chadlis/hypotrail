// What holds over every document the panel builds: one configuration with no stages, no text of the object read in an
// attribute or as markup, and no fixed text that is not an entry of contract.json.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { written } from "../src/content";
import { kept } from "./kept";
import {
  KEPT_READS,
  LITERALS,
  attributeValues,
  cspProblems,
  documentFor,
  followLink,
  heldRecorder,
  keptObject,
  lastDocument,
  panelOf,
  partsOf,
  runCommand,
  settle,
  success,
  unescaped,
  workspace,
} from "./panel-harness";
import { exit, recorder, type Answer } from "./recorder";

const [, RECORD] = contract.messages;
const keptAnswer = (name: string): Answer => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
const NOT_FOUND = keptAnswer("status-not-found");
const NO_ANSWERS: [string, Answer][] = [
  ["not_started", { error: { code: "ENOENT" } }],
  ["timeout", { error: { code: null, killed: true, signal: "SIGTERM" } }],
  ["too_large", { error: { code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER", killed: true } }],
  ["no_json", exit(0, "Study status\n")],
  ["inconsistent", exit(0, kept("status-not-found.out"))],
];

// A document and what it was built from: the answers of the recorder and the id of the link the panel was opened by.
type Built = { document: string; answers: Answer[]; link?: string };

async function afterWrite(t: TestContext, ...answers: Answer[]): Promise<Built> {
  workspace(t, ["bike"]);
  recorder(t, ...answers);
  await runCommand();
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  await settle();
  await settle();
  return { document: lastDocument(), answers };
}

const read = (name: string): Answer => success(keptObject(name));
const withoutQuestion = (): Answer => {
  const object = keptObject("status-success");
  object.pending_decisions[0].question.text = "";
  return success(object);
};

// Every document the tests of the panel build, by the case it shows.
const DOCUMENTS: [string, (t: TestContext) => Promise<Built>][] = [
  ...KEPT_READS.map((name): [string, (t: TestContext) => Promise<Built>] => [name, async (t) => ({ document: (await documentFor(t, read(name))).document, answers: [read(name)] })]),
  ["a read the CLI refuses", async (t) => ({ document: (await documentFor(t, NOT_FOUND)).document, answers: [NOT_FOUND] })],
  ...NO_ANSWERS.map(([cause, answer]): [string, (t: TestContext) => Promise<Built>] => [`a read with no answer (${cause})`, async (t) => ({ document: (await documentFor(t, answer)).document, answers: [answer] })]),
  [
    "a read in flight",
    async (t) => {
      workspace(t, ["bike"]);
      heldRecorder(t);
      await runCommand();
      return { document: lastDocument(), answers: [] };
    },
  ],
  [
    "a write in flight",
    async (t) => {
      workspace(t, ["bike"]);
      const { answer } = heldRecorder(t);
      await runCommand();
      answer(read("status-success"));
      await settle();
      panelOf().send({ message: RECORD, pending: 0, option: 0 });
      return { document: lastDocument(), answers: [read("status-success")] };
    },
  ],
  ["a write the CLI accepts, then its read", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-success"), read("status-decided"))],
  ["a write the CLI refuses, then its read", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-study-changed"), read("status-success"))],
  ["a write with no answer", (t) => afterWrite(t, read("status-success"), NO_ANSWERS[1][1])],
  ["a write the bridge refuses", (t) => afterWrite(t, withoutQuestion())],
  ["a write the CLI refuses, then a read that fails", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-study-changed"), NOT_FOUND)],
  ["a write the CLI accepts, then a read that fails", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-success"), NOT_FOUND)],
  [
    "a link to a Decision the Study holds",
    async (t) => {
      const [study] = workspace(t, ["bike"]);
      const link = keptObject("status-decided").decisions[0].decision_id;
      recorder(t, read("status-decided"));
      await followLink(1, study, link);
      await settle();
      return { document: lastDocument(), answers: [read("status-decided")], link };
    },
  ],
  [
    "a link to a Decision the Study does not hold",
    async (t) => {
      const [study] = workspace(t, ["bike"]);
      const link = "c53337e9-d255-423d-a851-414278d5c3f0";
      recorder(t, read("status-decided"));
      await followLink(1, study, link);
      await settle();
      return { document: lastDocument(), answers: [read("status-decided")], link };
    },
  ],
];

// The section headings of a document, as text.
const headingsOf = (document: string): string[] => [...document.matchAll(/<h2>([^<]*)<\/h2>/g)].map((match) => unescaped(match[1]));

// The words of a document that would make a stage: a `hidden` attribute or a `details` element in its tags, and in the text of
// its script the words that hide, show or rewrite an element.
const SCRIPT_WORDS = ["hidden", "display", "classList", "className", "innerHTML", "insertAdjacent"];

function stagesOf(document: string): string[] {
  const { script, tags } = partsOf(document);
  const found = SCRIPT_WORDS.filter((word) => script.includes(word)).map((word) => `the script holds ${word}`);
  if (tags.some((tag) => /^<[a-z0-9]+\s(?:[^>]*\s)?hidden(?:[\s=>/])/i.test(tag))) found.push("a hidden attribute");
  if (tags.some((tag) => /^<details[\s>]/i.test(tag))) found.push("a details element");
  return found;
}

const okReads = KEPT_READS.filter((name) => keptObject(name).ok === true);

for (const name of okReads) {
  test(`the section headings are those of status-success, each an entry of labels: ${name}`, async (t) => {
    const headings = headingsOf((await documentFor(t, read(name))).document);
    assert.deepEqual(headings, headingsOf((await documentFor(t, read("status-success"))).document));
    for (const heading of headings) assert.ok(contract.labels.includes(heading), heading);
  });

  test(`no tag holds a hidden attribute or opens a details element, and the script holds none of the words of a stage: ${name}`, async (t) => {
    assert.deepEqual(stagesOf((await documentFor(t, read(name))).document), []);
  });
}

for (const [plant, expected] of [
  ['<p hidden>planted</p>', "a hidden attribute"],
  ['<p data-x="1" hidden="">planted</p>', "a hidden attribute"],
  ["<details><summary>planted</summary></details>", "a details element"],
  ...SCRIPT_WORDS.map((word) => [`<script nonce="n">document.body.${word};</script>`, `the script holds ${word}`]),
] as const) {
  test(`a planted document is found to make a stage: ${expected}, by ${plant}`, async (t) => {
    const { document } = await documentFor(t, read("status-success"));
    const planted = plant.startsWith("<script") ? document.replace(/(<script[^>]*>)[\s\S]*?(<\/script>)/, plant) : document.replace("</main>", `${plant}</main>`);
    assert.ok(stagesOf(planted).includes(expected), stagesOf(planted).join("; "));
  });
}

// Each value of an answer as the panel writes it: the leaves of the object its output holds, and the keys of a map the panel
// shows whole.
function valuesOf(answers: Answer[]): string[] {
  const values: string[] = [];
  const walk = (value: unknown, key: string): void => {
    if (Array.isArray(value)) value.forEach((each) => walk(each, key));
    else if (value !== null && typeof value === "object") {
      for (const [name, each] of Object.entries(value)) {
        if (key === "coverage") values.push(name);
        walk(each, name);
      }
    } else values.push(unescaped(written(value)));
  };
  for (const answer of answers) {
    try {
      walk(JSON.parse(answer.stdout ?? ""), "");
    } catch {
      // An output that is not JSON shows none of its values.
    }
  }
  return values;
}

// What is left of the text between the tags of `body` once the script and the marked texts are set apart and every text the
// panel may print is removed, longest first.
function leftOf(built: Built): string {
  const body = built.document.slice(built.document.indexOf("<body>"), built.document.indexOf("</body>"));
  let left = unescaped(
    body
      .replace(/<script[^>]*>[\s\S]*?<\/script>/, "\n")
      .replace(/<([a-z0-9]+) data-text>[^<]*<\/\1>/g, "\n")
      .split(/<[^>]*>/)
      .join("\n"),
  );
  const removable = [
    ...contract.labels,
    contract.write_no_answer_words,
    ...contract.no_answer_causes,
    ...contract.client_refusal_fields,
    ...contract.evidence_phrases.map((entry) => entry.slice(entry.indexOf("=") + 1)),
    contract.no_value,
    contract.withheld,
    ...valuesOf(built.answers),
    ...(built.link ? [built.link] : []),
  ]
    .filter((text) => text.length > 0)
    .sort((a, b) => b.length - a.length);
  for (const text of removable) left = left.split(text).join("\n");
  return left;
}

for (const [name, build] of DOCUMENTS) {
  test(`no letter is left once the panel's fixed texts and the answers' values are removed: ${name}`, async (t) => {
    const built = await build(t);
    assert.deepEqual(leftOf(built).match(/\p{L}+/gu) ?? [], []);
  });

  test(`the document has no problem of the document test, and every attribute value is a literal of the client: ${name}`, async (t) => {
    const { document } = await build(t);
    assert.deepEqual(cspProblems(document), []);
    for (const value of attributeValues(document)) assert.ok(LITERALS.includes(value.replace(/\d+$/, "")), value);
  });
}
