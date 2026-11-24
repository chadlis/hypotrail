// Usage: node .claude/skills/verify-panel/render.js <output folder> <head>
//
// Renders the Study panel of the VS Code client at <head> as headless Chrome draws it, and writes a contact sheet,
// <output folder>/sheet.html, with the shots beside it. VS Code itself is not run: the variables of its four default themes
// (Light+, Dark+, High Contrast, High Contrast Light; a variable VS Code leaves undefined in a theme is left out) and the part of
// its default webview style that sets the text's colour and font are added to each document, and the body gets the class of the
// theme's kind.
//
// 1. `clients/vscode/` at <head> is extracted with `git archive` into a scratch folder, never the checkout, then `npm ci` and the
//    TypeScript build run there, so the client's own harness (`test/panel-harness.ts`), its kept CLI output (`test/cli/`) and
//    its Chrome driver (`test/chrome.ts`) are those of <head>.
// 2. The panel's documents are made by the harness on the kept CLI output: each read, and each step of a write.
// 3. Each document is drawn at 420 and 900 px wide in each theme, full page. At 420 px, every text whose contrast with what it
//    stands on (every opacity and background composited) is under WCAG's AA (4.5, or 3 for large text) is listed, with the
//    positions of the first pending question, its first number and its Record control.
// 4. On the read of status-success at 420 by 700 px, in each theme: Tab up to the first radio, Space, Tab, Enter, then the
//    pointer over the options, each step shot, with the Tab stops and the messages the document posted.
//
// The sheet lists every shot under its document, the contrast findings and the keyboard steps. Exit 0 when every document was
// made and drawn; Chrome missing, a failed build or a failed step exits 1.
"use strict";
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const [OUT_ARG, HEAD_ARG] = process.argv.slice(2);
if (!OUT_ARG || !HEAD_ARG || process.argv.length !== 4) {
  console.error("usage: node .claude/skills/verify-panel/render.js <output folder> <head>");
  process.exit(2);
}
const OUT = path.resolve(OUT_ARG);

function ran(program, args, options = {}) {
  const done = spawnSync(program, args, { encoding: "utf8", maxBuffer: 1 << 28, ...options });
  if (done.status !== 0) {
    console.error(`${program} ${args.join(" ")} exited ${done.status}:\n${done.stderr ?? ""}${done.error ?? ""}`);
    process.exit(1);
  }
  return done.stdout;
}

const REPO = ran("git", ["rev-parse", "--show-toplevel"]).trim();
const HEAD = ran("git", ["-C", REPO, "rev-parse", "--short", `${HEAD_ARG}^{commit}`]).trim();
const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-verify-panel-"));
process.on("exit", () => fs.rmSync(SCRATCH, { recursive: true, force: true, maxRetries: 10 }));
const archive = ran("git", ["-C", REPO, "archive", "--format=tar", HEAD, "clients/vscode"], { encoding: "buffer" });
ran("tar", ["-x", "-C", SCRATCH], { input: archive });
const CLIENT = path.join(SCRATCH, "clients", "vscode");
ran("npm", ["ci", "--no-audit", "--no-fund", "--prefer-offline"], { cwd: CLIENT });
ran("npm", ["run", "compile"], { cwd: CLIENT });

// From here on, `require("vscode")` gives the client's stub, as in its tests.
require(path.join(CLIENT, "out", "test", "vscode-stub-hook.js"));
const { test } = require("node:test");
const H = require(path.join(CLIENT, "out", "test", "panel-harness.js"));
const { exit, recorder } = require(path.join(CLIENT, "out", "test", "recorder.js"));
const { kept } = require(path.join(CLIENT, "out", "test", "kept.js"));
const chrome = require(path.join(CLIENT, "out", "test", "chrome.js"));
const contract = require(path.join(CLIENT, "contract.json"));
const [, RECORD, SEND_AGAIN] = contract.messages;

const THEMES = {
  light: { kind: "vscode-light", v: { "panel-border": "rgba(128,128,128,0.35)", foreground: "#616161", "editor-foreground": "#000000", "editor-background": "#ffffff", descriptionForeground: "#717171", "textLink-foreground": "#006ab1", focusBorder: "#0090f1",
    "button-background": "#007acc", "button-foreground": "#ffffff", "button-hoverBackground": "#0062a3", "button-secondaryBackground": "#5f6a79", "button-secondaryForeground": "#ffffff",
    "textBlockQuote-background": "#f2f2f2", "inputValidation-errorBorder": "#be1100", "list-hoverBackground": "#f0f0f0", "list-inactiveSelectionBackground": "#e4e6f1",
    "editorWidget-background": "#f3f3f3", "charts-blue": "#1a85ff", "charts-orange": "#d18616", "charts-lines": "rgba(97,97,97,0.5)", "charts-foreground": "#616161", "badge-background": "#c4c4c4", "badge-foreground": "#333333", "editorWarning-foreground": "#bf8803" } },
  dark: { kind: "vscode-dark", v: { "panel-border": "rgba(128,128,128,0.35)", foreground: "#cccccc", "editor-foreground": "#d4d4d4", "editor-background": "#1e1e1e", descriptionForeground: "rgba(204,204,204,0.7)", "textLink-foreground": "#3794ff", focusBorder: "#007fd4",
    "button-background": "#0e639c", "button-foreground": "#ffffff", "button-hoverBackground": "#1177bb", "button-secondaryBackground": "#3a3d41", "button-secondaryForeground": "#ffffff",
    "textBlockQuote-background": "#222222", "inputValidation-errorBorder": "#be1100", "list-hoverBackground": "#2a2d2e", "list-inactiveSelectionBackground": "#37373d",
    "editorWidget-background": "#252526", "charts-blue": "#3794ff", "charts-orange": "#d18616", "charts-lines": "rgba(204,204,204,0.5)", "charts-foreground": "#cccccc", "badge-background": "#4d4d4d", "badge-foreground": "#ffffff", "editorWarning-foreground": "#cca700" } },
  hc: { kind: "vscode-high-contrast", v: { foreground: "#ffffff", "editor-foreground": "#ffffff", "editor-background": "#000000", descriptionForeground: "rgba(255,255,255,0.7)", "textLink-foreground": "#21a6ff", focusBorder: "#f38518", contrastBorder: "#6fc3df", contrastActiveBorder: "#f38518",
    "button-foreground": "#ffffff", "button-secondaryForeground": "#ffffff", "panel-border": "#6fc3df", "inputValidation-errorBorder": "#6fc3df", "list-hoverBackground": "rgba(255,255,255,0.1)",
    "editorWidget-background": "#0c141f", "charts-blue": "#3794ff", "charts-orange": "#d18616", "charts-lines": "rgba(255,255,255,0.5)", "charts-foreground": "#ffffff", "badge-background": "#000000", "badge-foreground": "#ffffff", "editorWarning-foreground": "#ffd370" } },
  hcl: { kind: "vscode-high-contrast vscode-high-contrast-light", v: { foreground: "#292929", "editor-foreground": "#292929", "editor-background": "#ffffff", descriptionForeground: "rgba(41,41,41,0.7)", "textLink-foreground": "#0f4a85", focusBorder: "#006bbd", contrastBorder: "#0f4a85", contrastActiveBorder: "#006bbd",
    "button-background": "#0f4a85", "button-foreground": "#ffffff", "button-hoverBackground": "rgba(15,74,133,0.8)", "button-secondaryBackground": "#ffffff", "button-secondaryForeground": "#292929", "panel-border": "#0f4a85",
    "textBlockQuote-background": "#f2f2f2", "inputValidation-errorBorder": "#0f4a85", "list-hoverBackground": "rgba(15,74,133,0.1)", "list-inactiveSelectionBackground": "rgba(15,74,133,0.1)",
    "editorWidget-background": "#ffffff", "charts-blue": "#1a85ff", "charts-orange": "#d18616", "charts-lines": "rgba(41,41,41,0.5)", "charts-foreground": "#292929", "badge-background": "#0f4a85", "badge-foreground": "#ffffff", "editorWarning-foreground": "#895503" } },
};
const WIDTHS = [420, 900];

// The theme's variables and VS Code's default text style, added with the nonce of the document's own style, which the policy allows.
function themed(name) {
  const theme = THEMES[name];
  const css = `:root{${Object.entries(theme.v).map(([key, value]) => `--vscode-${key}:${value};`).join("")}--vscode-font-family:system-ui,-apple-system,"Segoe UI",Ubuntu,sans-serif;--vscode-font-size:13px;--vscode-font-weight:normal;}
html{background:var(--vscode-editor-background)}
body{background-color:transparent;color:var(--vscode-editor-foreground);font-family:var(--vscode-font-family);font-weight:var(--vscode-font-weight);font-size:var(--vscode-font-size);margin:0;padding:0 20px;}
a,a code{color:var(--vscode-textLink-foreground);}`;
  return `(() => { const style = document.createElement("style"); style.nonce = document.querySelector("style").nonce; style.textContent = ${JSON.stringify(css)}; document.head.append(style); document.body.className = ${JSON.stringify(theme.kind)}; return true; })()`;
}

// Each text under AA against what it stands on, every opacity and background under it composited.
const BELOW_AA = `(() => {
  const parse = (c) => { const m = /rgba?\\(([^)]+)\\)/.exec(c); if (!m) return [0, 0, 0, 0]; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const bgOf = (el) => { const chain = []; for (let e = el; e; e = e.parentElement) chain.unshift(e); let bg = parse(getComputedStyle(document.documentElement).backgroundColor); for (const e of chain) { const b = parse(getComputedStyle(e).backgroundColor); if (b[3] > 0) bg = over(b, bg); } return bg; };
  const opacity = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim() || node.parentElement.closest("script, style")) continue;
    const el = node.parentElement, style = getComputedStyle(el), bg = bgOf(el);
    let fg = parse(style.color); fg = [fg[0], fg[1], fg[2], fg[3] * opacity(el)];
    const shown = over(fg, bg), a = lum(shown), b = lum(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) out.push({ text: node.textContent.trim().slice(0, 40), tag: el.tagName, ratio: +ratio.toFixed(2), disabled: !!el.closest("button:disabled, label:has(input:disabled)") });
  }
  return out;
})()`;

// Where the first pending question, its first number and its Record control stand, and the page's height.
const POSITIONS = `(() => {
  const top = (e) => e && Math.round(e.getBoundingClientRect().top + scrollY);
  const question = document.querySelector('section[data-part="pending"] h3');
  const number = document.querySelector('section[data-part="pending"] [data-element="delta"] a, section[data-part="pending"] [data-element="delta"] span');
  const record = document.querySelector('section[data-part="pending"] button[data-message="${RECORD}"]');
  return { question: top(question), number: top(number), numberText: number && number.textContent, record: top(record), height: document.documentElement.scrollHeight, scrollY };
})()`;

const documents = new Map();
const keptAnswer = (name) => exit(Number(kept(`${name}.exit`)), kept(`${name}.out`), kept(`${name}.err`));
const TIMEOUT = { error: { code: null, killed: true, signal: "SIGTERM" } };
const NOT_FOUND = { error: { code: "ENOENT" } };

for (const name of ["status-success", "status-chinook-pending", "status-several-pending", "status-chinook-withheld", "status-rescored", "status-result-changed", "status-repeated", "status-decided", "status-deviation", "status-chinook-decided", "status-bike-withheld"]) {
  test(name, async (t) => documents.set(name, (await H.documentFor(t, keptAnswer(name))).document));
}
test("read-refused", async (t) => documents.set("read-refused", (await H.documentFor(t, keptAnswer("status-not-found"))).document));
test("read-noanswer", async (t) => documents.set("read-noanswer", (await H.documentFor(t, NOT_FOUND)).document));
test("linked-decision", async (t) => {
  const [study] = H.workspace(t, ["bike"]);
  recorder(t, keptAnswer("status-rescored"));
  await H.followLink(1, study, JSON.parse(kept("status-rescored.out")).decisions[0].decision_id);
  await H.settle();
  documents.set("linked-decision", H.lastDocument());
});
test("status-decided-cited-twice", async (t) => {
  const read = JSON.parse(kept("status-decided.out"));
  read.decisions.push({ ...structuredClone(read.decisions[0]), decision_id: "3c9e7a51-8d24-4f6b-a0e3-6b1f2d9c4e87" });
  documents.set("status-decided-cited-twice", (await H.documentFor(t, H.success(read))).document);
});

// A write after the read of status-success with the first option chosen: the document of each step, unless `prefix` is null.
async function writeFlow(t, prefix, writeAnswer, readAfter) {
  const keep = (step) => prefix && documents.set(`${prefix}-${step}`, H.lastDocument());
  H.workspace(t, ["bike"]);
  const held = H.heldRecorder(t);
  await H.runCommand(); await H.settle(); keep("0-reading");
  held.answer(keptAnswer("status-success")); await H.settle(); keep("0b-read");
  H.panelOf().send({ message: RECORD, pending: 0, option: 0 }); await H.settle(); keep("1-writing");
  held.answer(writeAnswer); await H.settle(); keep("2-after-write");
  if (readAfter) { held.answer(readAfter); await H.settle(); keep("3-after-read"); }
  return held;
}
test("w-success", (t) => writeFlow(t, "w-success", keptAnswer("decide-success"), keptAnswer("status-decided")));
test("w-refused", (t) => writeFlow(t, "w-refused", keptAnswer("decide-study-changed"), keptAnswer("status-success")));
test("w-noanswer", (t) => writeFlow(t, "w-noanswer", TIMEOUT, null));
test("w-success-readfail", (t) => writeFlow(t, "w-success-readfail", keptAnswer("decide-success"), NOT_FOUND));
test("w-invalid", (t) => writeFlow(t, "w-invalid", keptAnswer("decide-invalid-arguments"), keptAnswer("status-success")));
test("w-noanswer-send-again", async (t) => {
  const held = await writeFlow(t, null, TIMEOUT, null);
  H.panelOf().send({ message: SEND_AGAIN }); await H.settle(); documents.set("w-noanswer-3-sending-again", H.lastDocument());
  held.answer(keptAnswer("decide-replay")); await H.settle(); documents.set("w-noanswer-4-replay", H.lastDocument());
  held.answer(keptAnswer("status-decided")); await H.settle(); documents.set("w-noanswer-5-after-read", H.lastDocument());
});
test("w-success-4-matched", async (t) => {
  const read = JSON.parse(kept("status-decided.out"));
  const answer = JSON.parse(kept("decide-success.out"));
  answer.decision.decision_id = read.decisions[0].decision_id;
  H.workspace(t, ["bike"]);
  recorder(t, keptAnswer("status-success"), exit(0, JSON.stringify(answer)), H.success(read));
  await H.runCommand(); await H.settle();
  H.panelOf().send({ message: RECORD, pending: 0, option: 0 }); await H.settle(); await H.settle();
  documents.set("w-success-4-matched", H.lastDocument());
});

// One page of Chrome at a size, that opens documents from files and records what they post.
async function page(t, address, width, height) {
  const session = await chrome.pageOf(t, address);
  await session.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await session.send("Page.enable");
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__posted = []; window.acquireVsCodeApi = () => ({ postMessage: (m) => window.__posted.push(m), getState() {}, setState() {} });" });
  const evaluate = async (expression) => {
    const answer = await session.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (answer.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text}`);
    return answer.result.value;
  };
  const open = async (name, theme) => {
    const loads = session.events.filter((event) => event.method === "Page.loadEventFired").length;
    await session.send("Page.navigate", { url: pathToFileURL(path.join(OUT, "html", `${name}.html`)).href });
    while (session.events.filter((event) => event.method === "Page.loadEventFired").length === loads) await new Promise((resolve) => setTimeout(resolve, 20));
    await evaluate(themed(theme));
  };
  const shoot = async (file, full) => {
    const params = { format: "png" };
    if (full) {
      const { cssContentSize } = await session.send("Page.getLayoutMetrics");
      Object.assign(params, { captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.ceil(cssContentSize.height), scale: 1 } });
    }
    fs.writeFileSync(path.join(OUT, file), Buffer.from((await session.send("Page.captureScreenshot", params)).data, "base64"));
    return file;
  };
  const key = async (name) => {
    const keys = { Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 }, Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32, text: " " }, Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" } };
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", ...keys[name] });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", ...keys[name], text: undefined });
  };
  const pointer = (x, y) => session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  return { open, shoot, evaluate, key, pointer };
}

const shots = new Map();
const contrast = {};
const positions = {};
const keyboard = {};

test("render", async (t) => {
  if (!fs.existsSync(chrome.CHROME)) throw new Error(`no Chrome at ${chrome.CHROME}`);
  const address = await chrome.startChrome(t);
  if (address === undefined) throw new Error(`Chrome at ${chrome.CHROME} did not start within ${chrome.START_MS} ms`);
  fs.mkdirSync(path.join(OUT, "html"), { recursive: true });
  for (const [name, document] of documents) fs.writeFileSync(path.join(OUT, "html", `${name}.html`), document);
  for (const theme of Object.keys(THEMES)) for (const width of WIDTHS) {
    const view = await page(t, address, width, 700);
    for (const name of documents.keys()) {
      await view.open(name, theme);
      if (!shots.has(name)) shots.set(name, []);
      shots.get(name).push({ theme, width, file: await view.shoot(`${name}--${theme}-${width}.png`, true) });
      if (width === 420) {
        const below = await view.evaluate(BELOW_AA);
        if (below.length) contrast[`${name}--${theme}`] = below;
        positions[`${name}--${theme}`] = await view.evaluate(POSITIONS);
      }
    }
  }
  for (const theme of Object.keys(THEMES)) {
    const view = await page(t, address, 420, 700);
    await view.open("status-success", theme);
    const stops = [];
    for (let at = 0; at < 30; at += 1) {
      await view.key("Tab");
      const stop = await view.evaluate('(() => { const e = document.activeElement; return e.tagName + ":" + (e.getAttribute("data-option") ?? e.textContent.trim().slice(0, 20)); })()');
      stops.push(stop);
      if (stop.startsWith("INPUT")) break;
    }
    const steps = [{ step: "Tab to the first radio", file: await view.shoot(`i-focus-radio--${theme}-420.png`, false) }];
    await view.key("Space");
    steps.push({ step: "Space", file: await view.shoot(`i-selected--${theme}-420.png`, false) });
    await view.key("Tab");
    const after = await view.evaluate("document.activeElement.textContent.trim()");
    steps.push({ step: `Tab (focus: ${after})`, file: await view.shoot(`i-focus-record--${theme}-420.png`, false) });
    await view.key("Enter");
    await view.pointer(60, 470);
    steps.push({ step: "Enter, then the pointer at (60, 470)", file: await view.shoot(`i-hover--${theme}-420.png`, false) });
    keyboard[theme] = { stops, steps, posted: await view.evaluate("window.__posted") };
  }
  writeSheet();
});

const escaped = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function writeSheet() {
  const count = [...shots.values()].reduce((sum, list) => sum + list.length, 0) + Object.values(keyboard).reduce((sum, k) => sum + k.steps.length, 0);
  const sections = [...shots].map(([name, list]) => {
    const below = Object.keys(THEMES).filter((theme) => contrast[`${name}--${theme}`]).map((theme) => `<li>${theme}: ${contrast[`${name}--${theme}`].map((b) => `${escaped(b.text)} (${b.tag}, ${b.ratio}${b.disabled ? ", disabled" : ""})`).join("; ")}</li>`);
    const figures = list.map((shot) => `<figure><a href="${shot.file}"><img loading="lazy" src="${shot.file}" alt="${escaped(name)} in ${shot.theme} at ${shot.width} px"></a><figcaption>${shot.theme}, ${shot.width} px</figcaption></figure>`);
    return `<section id="${escaped(name)}"><h2>${escaped(name)}</h2>${below.length ? `<p>Under AA at 420 px:</p><ul>${below.join("")}</ul>` : "<p>No text under AA at 420 px.</p>"}<div class="shots">${figures.join("")}</div></section>`;
  });
  const keys = Object.entries(keyboard).map(([theme, k]) => `<section><h2>Keyboard, ${theme}</h2><p>Tab stops: ${k.stops.map(escaped).join(" → ")}</p><p>Posted: <code>${escaped(JSON.stringify(k.posted))}</code></p><div class="shots">${k.steps.map((s) => `<figure><a href="${s.file}"><img loading="lazy" src="${s.file}" alt="${escaped(s.step)}"></a><figcaption>${escaped(s.step)}</figcaption></figure>`).join("")}</div></section>`);
  const sheet = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Panel sheet ${HEAD}</title>
<style>body{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}nav a{margin-right:.6em}.shots{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}figure{margin:0;max-width:440px}img{max-width:100%;border:1px solid #999}figcaption{font-size:.85em}</style></head>
<body><h1>The Study panel at ${HEAD}</h1>
<p>${documents.size} documents, ${count} shots: each document in VS Code's four default themes (approximated, VS Code not run) at ${WIDTHS.join(" and ")} px, and the keyboard steps on status-success. Drawn by headless Chrome through <code>clients/vscode/test/chrome.ts</code> at ${HEAD}.</p>
<nav>${[...shots.keys()].map((name) => `<a href="#${escaped(name)}">${escaped(name)}</a>`).join(" ")}</nav>
${sections.join("\n")}
${keys.join("\n")}
</body></html>
`;
  fs.writeFileSync(path.join(OUT, "sheet.html"), sheet);
  fs.writeFileSync(path.join(OUT, "contrast.json"), JSON.stringify(contrast, null, 1));
  fs.writeFileSync(path.join(OUT, "positions.json"), JSON.stringify(positions, null, 1));
  fs.writeFileSync(path.join(OUT, "keyboard.json"), JSON.stringify(keyboard, null, 1));
  console.log(`verify-panel: ${path.join(OUT, "sheet.html")} (${documents.size} documents, ${count} shots, head ${HEAD})`);
}
