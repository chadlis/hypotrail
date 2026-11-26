// The panel as headless Chrome draws it under approximations of VS Code's four default themes: the contrast of its text while the
// controls are inert, the length of equal bars, where a radio stands beside its option, the outline of the checked option and the
// border of a disabled button in a High Contrast theme, and where the view stands once a write is recorded. VS Code itself is not run.
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { CHROME, START_MS, hasChrome, opened, startChrome, type Evaluate } from "./chrome";
import { documentFor, heldRecorder, keptObject, lastDocument, panelOf, runCommand, settle, success, workspace, FIGURES_FAILED, withFigures } from "./panel-harness";
import { exit, recorder } from "./recorder";
import { kept } from "./kept";
import { BELOW_AA, THEMES, themed } from "./themes";

const [, RECORD] = contract.messages;
const TIMEOUT = { error: { code: null, killed: true, signal: "SIGTERM" } };


// The browser, or a skip when it does not start.
async function browser(t: TestContext, what: string): Promise<string | undefined> {
  if (!hasChrome(t, what)) return undefined;
  const address = await startChrome(t);
  if (address === undefined) t.skip(`${what} is skipped: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
  return address;
}

async function view(t: TestContext, address: string, document: string, theme: string, width = 420, height = 900): Promise<Evaluate> {
  const evaluate = await opened(t, address, document, width, height);
  await evaluate(themed(theme));
  return evaluate;
}

// The document of a write in flight and of a write with no answer, each after the read of status-success and the first option chosen.
async function writeInFlight(t: TestContext): Promise<string> {
  workspace(t, ["bike"]);
  const { answer } = heldRecorder(t);
  await runCommand();
  answer(success(keptObject("status-success")));
  await settle();
  answer(FIGURES_FAILED);
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  return lastDocument();
}

async function writeWithNoAnswer(t: TestContext): Promise<string> {
  workspace(t, ["bike"]);
  recorder(t, ...withFigures(success(keptObject("status-success")), TIMEOUT));
  await runCommand();
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  await settle();
  await settle();
  return lastDocument();
}


for (const [state, build] of [
  ["a write in flight", writeInFlight],
  ["a write with no answer", writeWithNoAnswer],
] as const) {
  test(`in each of the four themes, every text of the document of ${state} stands at AA contrast against what it is drawn on`, { timeout: 60000 }, async (t) => {
    const address = await browser(t, "the contrast of the inert controls");
    if (address === undefined) return;
    const document = await build(t);
    for (const theme of Object.keys(THEMES)) {
      const evaluate = await view(t, address, document, theme);
      assert.deepEqual(await evaluate(BELOW_AA), [], theme);
    }
  });
}

// The drawn width of each `rect` of a class, in a chart of a kind.
const widthsOf = (chart: string, kind: string) =>
  `[...document.querySelectorAll('[data-chart="${chart}"] rect.${kind}')].map((rect) => Math.round(rect.getBoundingClientRect().width * 10) / 10)`;

test("at 420 and 900 px, the two bars of chart 2 of status-success, 182 of 182 each, are drawn equally long", { timeout: 60000 }, async (t) => {
  const address = await browser(t, "the length of equal bars");
  if (address === undefined) return;
  const object = keptObject("status-success");
  const coverage = object.comparisons[0].coverage;
  assert.equal(coverage.control_scored, coverage.candidate_scored);
  const { document } = await documentFor(t, success(object));
  for (const width of [420, 900]) {
    const evaluate = await view(t, address, document, "light", width);
    const [control] = await evaluate(widthsOf("coverage", "scored-control"));
    const [candidate] = await evaluate(widthsOf("coverage", "scored-candidate"));
    assert.ok(control > 0, `${width}: ${control}`);
    assert.equal(candidate, control, `${width} px: Control ${control} px, Candidate ${candidate} px`);
  }
});

test("at 420 px, each radio of status-success stands on the first line of its option's text", { timeout: 60000 }, async (t) => {
  const address = await browser(t, "where a radio stands");
  if (address === undefined) return;
  const { document } = await documentFor(t, success(keptObject("status-success")));
  const evaluate = await view(t, address, document, "light");
  const places = await evaluate(`[...document.querySelectorAll('input[type="radio"]')].map((radio) => {
    const line = radio.closest("label").querySelector("strong").getClientRects()[0];
    const box = radio.getBoundingClientRect();
    return { middle: box.top + box.height / 2, top: line.top, bottom: line.bottom };
  })`);
  assert.ok(places.length > 0);
  for (const place of places) assert.ok(place.middle >= place.top && place.middle <= place.bottom, JSON.stringify(place));
});

test("in High Contrast and High Contrast Light, the checked option is outlined in --vscode-contrastActiveBorder", { timeout: 60000 }, async (t) => {
  const address = await browser(t, "the outline of the checked option");
  if (address === undefined) return;
  const { document } = await documentFor(t, success(keptObject("status-success")));
  for (const theme of ["hc", "hcl"]) {
    const evaluate = await view(t, address, document, theme);
    const outline = await evaluate(`(() => {
      const radio = document.querySelector('input[type="radio"]');
      radio.checked = true;
      const probe = document.createElement("i");
      probe.style.color = "var(--vscode-contrastActiveBorder)";
      document.body.append(probe);
      const style = getComputedStyle(radio.closest("label"));
      return { style: style.outlineStyle, width: style.outlineWidth, colour: style.outlineColor, expected: getComputedStyle(probe).color };
    })()`);
    assert.notEqual(outline.style, "none", `${theme}: ${JSON.stringify(outline)}`);
    assert.notEqual(outline.width, "0px", `${theme}: ${JSON.stringify(outline)}`);
    assert.equal(outline.colour, outline.expected, theme);
  }
});

test("at 420 by 700 px, once a write is recorded and read again, the view stays at the top, the notice in view and holding the focus", { timeout: 60000 }, async (t) => {
  const address = await browser(t, "where the view stands once a write is recorded");
  if (address === undefined) return;
  const read = keptObject("status-decided");
  const answer = JSON.parse(kept("decide-success.out"));
  answer.decision.decision_id = read.decisions[0].decision_id;
  workspace(t, ["bike"]);
  recorder(t, ...withFigures(success(keptObject("status-success")), exit(0, JSON.stringify(answer)), success(read)));
  await runCommand();
  await settle();
  panelOf().send({ message: RECORD, pending: 0, option: 0 });
  await settle();
  await settle();
  const evaluate = await view(t, address, lastDocument(), "light", 420, 700);
  const at = await evaluate(`(() => {
    const notice = document.querySelector('[data-element="notice"]').getBoundingClientRect();
    return { scrollY, top: notice.top, bottom: notice.bottom, focused: document.activeElement.getAttribute("data-element") };
  })()`);
  assert.equal(at.scrollY, 0, JSON.stringify(at));
  assert.ok(at.top >= 0 && at.bottom <= 700, JSON.stringify(at));
  assert.equal(at.focused, "notice");
});

test("in High Contrast and High Contrast Light, a disabled button is drawn unlike an enabled one: status-success, Read again against the control that records", { timeout: 60000 }, async (t) => {
  const address = await browser(t, "how a disabled button is drawn");
  if (address === undefined) return;
  const { document } = await documentFor(t, success(keptObject("status-success")));
  for (const theme of ["hc", "hcl"]) {
    const evaluate = await view(t, address, document, theme);
    const drawn = await evaluate(`["read-again", "record"].map((name) => {
      const style = getComputedStyle(document.querySelector('button[data-message="' + name + '"]'));
      return [style.color, style.backgroundColor, style.borderTopStyle, style.borderTopColor].join(" ");
    })`);
    assert.notEqual(drawn[0], drawn[1], `${theme}: ${drawn.join(" | ")}`);
  }
});
