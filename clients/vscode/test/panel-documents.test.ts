// What holds over every document the panel builds: one configuration with no stages, no text of the object read in an
// attribute or as markup, and no fixed text that is not an entry of contract.json.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import contract from "../contract.json";
import { written } from "../src/content";
import { kept } from "./kept";
import {
  KEPT_FIGURES,
  KEPT_READS,
  LITERALS,
  attributeValues,
  cspProblems,
  documentFor,
  followLink,
  geometryValues,
  heldRecorder,
  keptObject,
  lastDocument,
  markedTexts,
  panelOf,
  partsOf,
  runCommand,
  settle,
  success,
  unescaped,
  workspace,
  FIGURES_FAILED,
  S2_INTERVAL,
  holdsTheHeadings,
  withFigures,
} from "./panel-harness";
import { exit, recorder, type Answer } from "./recorder";
import * as stub from "./vscode-stub";

const [, RECORD, , OPEN] = contract.messages;
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
  recorder(t, ...withFigures(...answers));
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
  ...Object.keys(KEPT_FIGURES).map((name): [string, (t: TestContext) => Promise<Built>] => [
    `${name} with ${KEPT_FIGURES[name]}`,
    async (t) => {
      const answers = [read(name), read(KEPT_FIGURES[name])];
      return { document: (await documentFor(t, ...answers)).document, answers };
    },
  ]),
  [
    "status-success with an entry of its figures read whose figures are unavailable",
    async (t) => {
      const figures = keptObject("figures-success");
      Object.assign(figures.comparisons[0], { unavailable: "artifact_missing", paired_deltas: null, histogram: null, quartiles: null });
      const answers = [read("status-success"), success(figures)];
      return { document: (await documentFor(t, ...answers)).document, answers };
    },
  ],
  [
    "status-chinook-spread with ten Cases in its figures read",
    async (t) => {
      const figures = keptObject("figures-chinook-spread");
      const entry = figures.comparisons[0];
      entry.paired_deltas = Array.from({ length: 10 }, (_, at) => ({ ...entry.paired_deltas[at % 4], case_id: `D${10 + at}` }));
      const answers = [read("status-chinook-spread"), success(figures)];
      return { document: (await documentFor(t, ...answers)).document, answers };
    },
  ],
  ...[true, false].map((bounds): [string, (t: TestContext) => Promise<Built>] => [
    `status-success with an injected interval${bounds ? "" : " whose bounds are null"}`,
    async (t) => {
      const object = keptObject("status-success");
      object.comparisons[0].interval = bounds ? S2_INTERVAL : { ...S2_INTERVAL, lower: null, upper: null, reason: "too_few_units" };
      const answers = [success(object)];
      return { document: (await documentFor(t, ...answers)).document, answers };
    },
  ]),
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
      answer(FIGURES_FAILED);
      await settle();
      panelOf().send({ message: RECORD, pending: 0, option: 0 });
      return { document: lastDocument(), answers: [read("status-success")] };
    },
  ],
  ["a write the CLI accepts, then its read", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-success"), read("status-decided"))],
  [
    "a write the CLI accepts, then its read that holds the Decision recorded",
    (t) => {
      const answer = JSON.parse(kept("decide-success.out"));
      answer.decision.decision_id = keptObject("status-decided").decisions[0].decision_id;
      return afterWrite(t, read("status-success"), exit(0, JSON.stringify(answer)), read("status-decided"));
    },
  ],
  ["a write the CLI refuses, then its read", (t) => afterWrite(t, read("status-success"), keptAnswer("decide-study-changed"), read("status-success"))],
  ["a write with no answer", (t) => afterWrite(t, read("status-success"), NO_ANSWERS[1][1])],
  ["a write the bridge refuses", (t) => afterWrite(t, withoutQuestion())],
  [
    "a control that opens whose file the Study folder does not hold",
    async (t) => {
      workspace(t, ["bike"]);
      recorder(t, ...withFigures(read("status-success")));
      await runCommand();
      await settle();
      panelOf().send({ message: OPEN, kind: "assessment", index: 0, ref: contract.open_refs[0] });
      for (let turn = 0; turn < 4; turn += 1) {
        await settle();
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      return { document: lastDocument(), answers: [read("status-success")] };
    },
  ],
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

// The words of a document that would make a stage: a `hidden` attribute in its tags, in the text of its script the words that hide,
// show or rewrite an element, and a fold that a setting hides: a `details` element whose tag holds a `style`, or a rule of the style
// that hides a `details` element. A native `details` and its `summary` make none ("No stages" redefined: no feature level, and nothing
// that a setting hides; D-136).
const SCRIPT_WORDS = ["hidden", "display", "classList", "className", "innerHTML", "insertAdjacent"];

function stagesOf(document: string): string[] {
  const { script, style, tags } = partsOf(document);
  const found = SCRIPT_WORDS.filter((word) => script.includes(word)).map((word) => `the script holds ${word}`);
  if (tags.some((tag) => /^<[a-z0-9]+\s(?:[^>]*\s)?hidden(?:[\s=>/])/i.test(tag))) found.push("a hidden attribute");
  const hidingRule = [...style.matchAll(/([^{}]+)\{([^{}]*)\}/g)].some(([, selector, body]) => /(^|[\s,>+~(])details\b/.test(selector) && /(^|;)\s*(display\s*:\s*none|visibility\s*:\s*hidden|content-visibility\s*:\s*hidden)/.test(body));
  if (tags.some((tag) => /^<details\s(?:[^>]*\s)?style=/i.test(tag)) || hidingRule) found.push("a fold that a setting hides");
  return found;
}

const okReads = KEPT_READS.filter((name) => keptObject(name).ok === true);

for (const name of [...KEPT_READS, "status-not-found"]) {
  test(`the section headings are an in-order subset of the five, with Now, The Study so far and Tools present, each an entry of labels: ${name}`, async (t) => {
    const headings = headingsOf((await documentFor(t, name === "status-not-found" ? NOT_FOUND : read(name))).document);
    assert.ok(holdsTheHeadings(headings), headings.join(" | "));
    for (const heading of headings) assert.ok(contract.labels.includes(heading), heading);
  });
}

for (const name of okReads) {
  test(`no tag holds a hidden attribute, no fold is one that a setting hides, and the script holds none of the words of a stage: ${name}`, async (t) => {
    assert.deepEqual(stagesOf((await documentFor(t, read(name))).document), []);
  });
}

test("a heading out of order, a heading that is not one of the five, and a missing Tools are each found", () => {
  assert.equal(holdsTheHeadings(["The Study so far", "Now", "Tools"]), false);
  assert.equal(holdsTheHeadings(["Now", "Study", "The Study so far", "Tools"]), false);
  assert.equal(holdsTheHeadings(["Now", "The Study so far"]), false);
  assert.equal(holdsTheHeadings(["To handle", "Now", "Waiting", "The Study so far", "Tools"]), true);
  assert.equal(holdsTheHeadings(["Now", "The Study so far", "Tools"]), true);
});

for (const [plant, expected] of [
  ['<p hidden>planted</p>', "a hidden attribute"],
  ['<p data-x="1" hidden="">planted</p>', "a hidden attribute"],
  ['<details style="display: none"><summary>planted</summary></details>', "a fold that a setting hides"],
  ["<style-rule>details[data-x] { display: none; }", "a fold that a setting hides"],
  ...SCRIPT_WORDS.map((word) => [`<script nonce="n">document.body.${word};</script>`, `the script holds ${word}`]),
] as const) {
  test(`a planted document is found to make a stage: ${expected}, by ${plant}`, async (t) => {
    const { document } = await documentFor(t, read("status-success"));
    const planted = plant.startsWith("<script")
      ? document.replace(/(<script[^>]*>)[\s\S]*?(<\/script>)/, plant)
      : plant.startsWith("<style-rule>")
        ? document.replace(/(<style[^>]*>)/, `$1${plant.slice("<style-rule>".length)}\n`)
        : document.replace("</main>", `${plant}</main>`);
    assert.ok(stagesOf(planted).includes(expected), stagesOf(planted).join("; "));
  });
}

test("a planted native details element with its summary makes no stage", async (t) => {
  const { document } = await documentFor(t, read("status-success"));
  assert.deepEqual(stagesOf(document.replace("</main>", "<details><summary>planted</summary><p>planted</p></details></main>")), []);
});

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
    ...contract.applies_phrases.map((entry) => entry.slice(entry.indexOf("=") + 1)),
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
    for (const value of geometryValues(document)) assert.match(value, /^\d+(\.\d+)?$/);
  });
}

// The Study's path as the panel's heading: every builder above opens the panel on the Study "bike" of its workspace.
for (const [name, build] of DOCUMENTS) {
  test(`main opens with one h1, a marked text that is the path the panel was opened with, and every other marked text is a text of the answers: ${name}`, async (t) => {
    const built = await build(t);
    const study = path.join(stub.state.folders[0], "bike");
    assert.ok(/\d/.test(study) && study.includes(" ") && study.includes("<b>"), study);
    assert.equal(built.document.split("<h1").length - 1, 1, "one h1");
    const heading = /<main[^>]*>(<h1 data-text>[^<]*<\/h1>)/.exec(built.document)?.[1];
    assert.ok(heading, "main opens with the h1, marked");
    assert.deepEqual(markedTexts(heading), [study]);
    const values = valuesOf(built.answers);
    for (const text of markedTexts(built.document).slice(1)) assert.ok(values.includes(text), text);
  });
}

// The text between the tags of a document, its script, style and marked texts removed, as one line of words.
const fixedWordsOf = (document: string): string =>
  ` ${partsOf(document.replace(/<([a-z0-9]+) data-text>[^<]*<\/\1>/g, "")).between.split(/\s+/).filter(Boolean).join(" ")} `;

test("every entry of labels is printed outside a marked text by one of the documents the panel builds", async (t) => {
  const printed: string[] = [];
  for (const [, build] of DOCUMENTS) printed.push(fixedWordsOf((await build(t)).document));
  const unprinted = contract.labels.filter((label) => !printed.some((words) => words.includes(` ${label.split(/\s+/).join(" ")} `)));
  assert.deepEqual(unprinted, []);
});
