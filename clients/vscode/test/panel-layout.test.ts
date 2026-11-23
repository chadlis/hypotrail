// The layout of a document with a pending decision: a guard, in headless Chrome, of how far from the top the first question and
// the first evidence number stand at the width of `guard_bounds`, and their order in the document's text, which runs without
// Chrome and stands beside the guard.
// "C2 at 420 px: a headless measurement is a regression guard only. The owner's check in VS Code is the acceptance."
// (D-031 on chadlis/hypotrail#75, item 14.)
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";
import contract from "../contract.json";
import { KEPT_READS, documentFor, keptObject, success } from "./panel-harness";

// The path of Chrome; a test run sets another one to see the guard skip.
const CHROME = process.env.HYPOTRAIL_CHROME ?? "/usr/bin/google-chrome";
// How long Chrome has to start and open its debugging port before the guard is skipped.
const START_MS = 15000;
const HEIGHT = 900;
const BOUND = Object.fromEntries(contract.guard_bounds.map((entry) => [entry.split("=")[0], Number(entry.split("=")[1])]));

const QUESTION = 'section[data-part="pending"] h3[data-text]';
const DELTA = 'section[data-part="pending"] [data-element="delta"]';

// The selector of the first evidence number: the delta's value of the first pending Comparison, or the delta's element when
// that delta is withheld.
function evidenceOf(object: Record<string, any>): string {
  const first = object.comparisons.find((each: Record<string, any>) => each.comparison_id === object.pending_decisions[0].comparison_id);
  return first.delta.value === null ? DELTA : `${DELTA} a[data-kind="delta"]`;
}

type Session = { send: (method: string, params?: Record<string, unknown>) => Promise<Record<string, any>>; events: Record<string, any>[] };

// Chrome started headless with its debugging port; undefined when it does not start or its port does not open in time.
async function startChrome(t: TestContext): Promise<string | undefined> {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-chrome-"));
  let chrome: ChildProcess | undefined;
  t.after(() => {
    chrome?.kill("SIGKILL");
    fs.rmSync(profile, { recursive: true, force: true });
  });
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(undefined), START_MS);
    const done = (address: string | undefined) => {
      clearTimeout(timer);
      resolve(address);
    };
    try {
      chrome = spawn(CHROME, ["--headless", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
    } catch {
      return done(undefined);
    }
    let printed = "";
    chrome.on("error", () => done(undefined));
    chrome.on("exit", () => done(undefined));
    chrome.stderr!.on("data", (chunk: Buffer) => {
      printed += chunk.toString();
      const address = /DevTools listening on (ws:\/\/\S+)/.exec(printed)?.[1];
      if (address) done(address);
    });
  });
}

// One page of the browser, reached over the debugging port with Node's own WebSocket.
async function pageOf(t: TestContext, address: string): Promise<Session> {
  const socket = new WebSocket(address);
  t.after(() => socket.close());
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  const waiting = new Map<number, (message: Record<string, any>) => void>();
  const events: Record<string, any>[] = [];
  socket.onmessage = (event) => {
    const message = JSON.parse(String(event.data));
    if (message.id !== undefined) waiting.get(message.id)?.(message);
    else events.push(message);
  };
  let last = 0;
  const call = (method: string, params: Record<string, unknown> = {}, sessionId?: string) =>
    new Promise<Record<string, any>>((resolve, reject) => {
      last += 1;
      waiting.set(last, (message) => (message.error ? reject(new Error(`${method}: ${message.error.message}`)) : resolve(message.result)));
      socket.send(JSON.stringify({ id: last, method, params, sessionId }));
    });
  const { targetId } = await call("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await call("Target.attachToTarget", { targetId, flatten: true });
  return { send: (method, params) => call(method, params, sessionId), events };
}

// The tops of the first question and of the first evidence number, from the top of the page, in a document shown at the
// guard's width; `innerWidth` is asserted before anything is measured.
async function measured(t: TestContext, document: string, evidence: string): Promise<{ innerWidth: number; question: number | null; evidence: number | null } | undefined> {
  const address = await startChrome(t);
  if (address === undefined) {
    t.skip(`the guard of how far from the top the first question and the first evidence number stand is skipped: Chrome at ${CHROME} did not start, or its debugging port did not open within ${START_MS} ms`);
    return undefined;
  }
  const page = await pageOf(t, address);
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-layout-")), "panel.html");
  t.after(() => fs.rmSync(path.dirname(file), { recursive: true, force: true }));
  fs.writeFileSync(file, document);
  await page.send("Emulation.setDeviceMetricsOverride", { width: BOUND.width, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
  await page.send("Page.enable");
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.acquireVsCodeApi = () => ({ postMessage() {}, getState() {}, setState() {} });" });
  await page.send("Page.navigate", { url: pathToFileURL(file).href });
  while (!page.events.some((event) => event.method === "Page.loadEventFired")) await new Promise((resolve) => setTimeout(resolve, 20));
  const evaluate = async (expression: string) => (await page.send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
  const innerWidth = await evaluate("innerWidth");
  assert.equal(innerWidth, BOUND.width, `innerWidth=${innerWidth}`);
  const top = (selector: string) => `(() => { const found = document.querySelector(${JSON.stringify(selector)}); return found ? found.getBoundingClientRect().top + scrollY : null; })()`;
  return { innerWidth, question: await evaluate(top(QUESTION)), evidence: await evaluate(top(evidence)) };
}

const guarded = (t: TestContext): boolean => {
  if (fs.existsSync(CHROME)) return true;
  t.skip(`the guard of how far from the top the first question and the first evidence number stand is skipped: no Chrome at ${CHROME}`);
  return false;
};

test("at the width of guard_bounds, the first question and the first evidence number of status-success are within their bounds of the top", { timeout: 60000 }, async (t) => {
  if (!guarded(t)) return;
  const object = keptObject("status-success");
  const { document } = await documentFor(t, success(object));
  const at = await measured(t, document, evidenceOf(object));
  if (at === undefined) return;
  assert.notEqual(at.question, null, "the first question is found");
  assert.notEqual(at.evidence, null, "the first evidence number is found");
  assert.ok(at.question! <= BOUND.question, `innerWidth=${at.innerWidth}: the first question is ${at.question} px from the top, past ${BOUND.question}`);
  assert.ok(at.evidence! <= BOUND.evidence, `innerWidth=${at.innerWidth}: the first evidence number is ${at.evidence} px from the top, past ${BOUND.evidence}`);
});

test("the guard of how far from the top the first question and the first evidence number stand finds the element it measures on status-chinook-withheld: the delta's element", { timeout: 60000 }, async (t) => {
  if (!guarded(t)) return;
  const object = keptObject("status-chinook-withheld");
  assert.equal(evidenceOf(object), DELTA);
  const { document } = await documentFor(t, success(object));
  const at = await measured(t, document, evidenceOf(object));
  if (at === undefined) return;
  assert.notEqual(at.evidence, null, `innerWidth=${at.innerWidth}: the delta's element is found`);
});

// "From the question: the Comparison, its delta" (chadlis/hypotrail#103, comment 7092994773, task 2).
for (const name of KEPT_READS.filter((read) => keptObject(read).pending_decisions?.length > 0)) {
  test(`the text of the first question comes before the delta's element of the first pending Comparison: ${name}`, async (t) => {
    const object = keptObject(name);
    const { document } = await documentFor(t, success(object));
    const question = document.indexOf("<h3 data-text>", document.indexOf('<section data-part="pending">'));
    const delta = document.indexOf('<p data-element="delta">', document.indexOf('<section data-part="pending">'));
    assert.ok(question >= 0 && delta >= 0, "both are found");
    assert.ok(question < delta, `the question at ${question}, the delta's element at ${delta}`);
  });
}
