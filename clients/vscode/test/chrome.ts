// Headless Chrome for the tests that look at a document as a browser draws it: Chrome started with its debugging port, a page of
// it reached with Node's own WebSocket, and a document opened in that page at a given size.
import type { TestContext } from "node:test";
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import { createServer } from "node:http";
import * as os from "node:os";
import * as path from "node:path";

// The path of Chrome; a test run sets another one to see the tests that need it skip.
export const CHROME = process.env.HYPOTRAIL_CHROME ?? "/usr/bin/google-chrome";
// How long Chrome has to start and open its debugging port before a test that needs it is skipped.
export const START_MS = 15000;

export type Session = { send: (method: string, params?: Record<string, unknown>) => Promise<Record<string, any>>; events: Record<string, any>[] };

// Chrome started headless with its debugging port; undefined when it does not start or its port does not open in time.
export async function startChrome(t: TestContext): Promise<string | undefined> {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-chrome-"));
  let chrome: ChildProcess | undefined;
  // Chrome's helper processes write into the profile until they die with the browser: the whole process group is killed, the
  // browser's exit awaited, and a folder a helper still writes into when the removal starts is removed again.
  t.after(async () => {
    if (chrome?.pid !== undefined && chrome.exitCode === null && chrome.signalCode === null) {
      const exited = new Promise((resolve) => chrome!.once("exit", resolve));
      process.kill(-chrome.pid, "SIGKILL");
      await exited;
    }
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 10 });
  });
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(undefined), START_MS);
    const done = (address: string | undefined) => {
      clearTimeout(timer);
      resolve(address);
    };
    try {
      chrome = spawn(CHROME, ["--headless", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: ["ignore", "ignore", "pipe"], detached: true });
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
export async function pageOf(t: TestContext, address: string): Promise<Session> {
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

// An expression evaluated in a page, its value returned.
export type Evaluate = (expression: string) => Promise<any>;

// Serve only the generated document on a temporary loopback listener. No files are exposed by the server.
export async function openDocument(t: TestContext, address: string, document: string, width: number, height: number, before = ""): Promise<Session> {
  const page = await pageOf(t, address);
  const route = `/${randomUUID()}`;
  const server = createServer((request, response) => {
    if (request.method !== "GET" || request.url !== route) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" }).end(document);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  t.after(() => new Promise<void>((resolve, reject) => {
    server.close((error) => error === undefined ? resolve() : reject(error));
    server.closeAllConnections();
  }));
  const bound = server.address();
  if (bound === null || typeof bound === "string") throw new Error("Expected a loopback TCP listener");
  await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await page.send("Page.enable");
  await page.send("Page.addScriptToEvaluateOnNewDocument", { source: `window.acquireVsCodeApi = () => ({ postMessage() {}, getState() {}, setState() {} });${before}` });
  const navigation = await page.send("Page.navigate", { url: `http://127.0.0.1:${bound.port}${route}` });
  if (navigation.errorText) throw new Error(`Could not open the generated document: ${navigation.errorText}`);
  while (!page.events.some((event) => event.method === "Page.loadEventFired")) await new Promise((resolve) => setTimeout(resolve, 20));
  return page;
}

// Evaluate expressions in the generated webview after its document loads.
export async function opened(t: TestContext, address: string, document: string, width: number, height: number, before = ""): Promise<Evaluate> {
  const page = await openDocument(t, address, document, width, height, before);
  return async (expression: string) => {
    const answer = await page.send("Runtime.evaluate", { expression, returnByValue: true });
    if (answer.exceptionDetails) throw new Error(`${expression}: ${answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text}`);
    return answer.result.value;
  };
}

// Whether Chrome is there; a test that needs it is skipped when it is not.
export function hasChrome(t: TestContext, what: string): boolean {
  if (fs.existsSync(CHROME)) return true;
  t.skip(`${what} is skipped: no Chrome at ${CHROME}`);
  return false;
}
