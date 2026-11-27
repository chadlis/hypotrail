// Manual browser assertions on the actual safe development reads made by the CLI.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test } = require("node:test");

const client = process.cwd();
const from = (file) => require(path.join(client, file));
const { lastDocument, runCommand, settle, success, workspace } = from("out/test/panel-harness.js");
const { lesson, recorder } = from("out/test/recorder.js");
const { pageOf, startChrome } = from("out/test/chrome.js");
const { BELOW_AA, themed } = from("out/test/themes.js");
const [, record] = from("contract.json").messages;
const themes = ["light", "dark", "hc", "hcl"];
// The question, first evidence and Record tops in the accepted C5 capture.
// https://github.com/chadlis/hypotrail/issues/306#issuecomment-7222056726
const keptPositions = {
    bike: { 420: [121, 184, 622], 900: [121, 164, 532] },
    chinook: { 420: [121, 184, 657], 900: [121, 164, 548] },
};

const checks = `(() => {
    const section = document.querySelector('details[data-element="lesson-packs"]');
    const now = document.querySelector('section[data-part="now"]');
    const button = now?.querySelector('button[data-message="${record}"]');
    const position = (el) => el ? Math.round(el.getBoundingClientRect().top) : null;
    return {
        statusLine: section?.querySelector(":scope > p")?.textContent,
        packCount: section?.querySelectorAll(":scope > ul > li").length,
        folded: section?.open === false,
        belowRecord: !!button && !!(button.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING),
        position: [position(now?.querySelector('[data-element="now-question"]')),
            position(now?.querySelector('[data-element="delta"] a, [data-element="delta"] span')),
            position(button)],
        content: Array.from(section?.querySelectorAll('[data-element="pack-lesson"] dd, [data-element="pack-illustration"]') ?? [])
            .map((element) => element.textContent).join(" "),
        illustrationCount: section?.querySelectorAll('[data-element="pack-illustration"]').length
    };
})()`;

async function documentAt(t, browser, url, theme, width) {
    const page = await pageOf(t, browser);
    await page.send("Emulation.setDeviceMetricsOverride", { width, height: 700, deviceScaleFactor: 1, mobile: false });
    await page.send("Page.enable");
    await page.send("Page.addScriptToEvaluateOnNewDocument", {
        source: "window.acquireVsCodeApi = () => ({ postMessage() {}, getState() {}, setState() {} });",
    });
    await page.send("Page.navigate", { url });
    const deadline = Date.now() + 5000;
    while (!page.events.some((event) => event.method === "Page.loadEventFired")) {
        assert.ok(Date.now() < deadline, "the panel document has not loaded");
        await new Promise((resolve) => setTimeout(resolve, 20));
    }
    async function evaluate(expression) {
        const response = await page.send("Runtime.evaluate", { expression, returnByValue: true });
        assert.ok(!response.exceptionDetails, "the panel browser check threw");
        return response.result.value;
    }
    await evaluate(themed(theme));
    return { evaluate, send: page.send };
}

async function reachesRecord(page) {
    const keys = {
        Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
        Space: { key: " ", code: "Space", text: " ", windowsVirtualKeyCode: 32 },
    };
    async function press(key) {
        await page.send("Input.dispatchKeyEvent", { type: "keyDown", ...keys[key] });
        await page.send("Input.dispatchKeyEvent", { type: "keyUp", ...keys[key], text: undefined });
    }
    const path = [];
    for (let count = 0; count < 50; count++) {
        await press("Tab");
        const active = await page.evaluate(`(() => {
            const el = document.activeElement;
            return { tag: el.tagName, type: el.type ?? null, message: el.dataset.message ?? null };
        })()`);
        path.push(active);
        if (active.message === record) return path;
        if (active.type === "radio") await press("Space");
    }
    assert.fail("the keyboard did not reach Record");
}

test("the real Bike and Chinook reads render under each theme, with and without a pack", async (t) => {
    const output = path.join(process.env.HYPOTRAIL_E2E_READS, "panel-sheet");
    fs.mkdirSync(output);
    const documents = new Map();
    const captures = [];
    for (const track of Object.keys(keptPositions)) {
        const file = path.join(process.env.HYPOTRAIL_E2E_READS, `${track}-panel.json`);
        const data = JSON.parse(fs.readFileSync(file, "utf8"));
        for (const kind of ["with_pack", "without_pack"]) {
            workspace(t, [track]);
            recorder(t, success(data.status), success(data.figures), lesson(success(data[kind])));
            await runCommand();
            await settle();
            documents.set(`/${track}-${kind}`, lastDocument());
        }
    }
    // Serve only generated HTML on loopback. There is no external navigation.
    const local = http.createServer((request, response) => {
        const document = documents.get(request.url);
        response.writeHead(document ? 200 : 404, { "Content-Type": "text/html; charset=utf-8" });
        response.end(document ?? "");
    });
    await new Promise((resolve) => local.listen(0, "127.0.0.1", resolve));
    t.after(() => local.close());
    const browser = await startChrome(t);
    assert.ok(browser, "Chromium is required for the manual proof");
    for (const theme of themes) {
        for (const width of [420, 900]) {
            for (const track of Object.keys(keptPositions)) {
                const origin = `http://127.0.0.1:${local.address().port}`;
                const baseline = keptPositions[track][width];
                let keyboard;
                for (const kind of ["without_pack", "with_pack"]) {
                    const page = await documentAt(t, browser, `${origin}/${track}-${kind}`, theme, width);
                    const seen = await page.evaluate(checks);
                    const installed = kind === "with_pack";
                    assert.equal(seen.statusLine, installed ? "Lesson packs" : "Lesson packs: none");
                    assert.equal(seen.packCount, installed ? 1 : 0);
                    assert.ok(seen.folded && seen.belowRecord, `${track} ${theme} ${width}`);
                    assert.doesNotMatch(seen.content, /[0-9]/, "lesson content contains a number");
                    assert.equal(seen.illustrationCount, track === "bike" && kind === "with_pack" ? 7 : 0);
                    const name = `${track}-${theme}-${width}-${kind}`;
                    assert.deepEqual(seen.position, baseline, `the first screen differs from its kept baseline for ${name}`);
                    assert.equal((await page.evaluate(BELOW_AA)).length, 0, `text below AA contrast for ${name}`);
                    const screenshot = await page.send("Page.captureScreenshot", { format: "png" });
                    fs.writeFileSync(path.join(output, `${name}.png`), screenshot.data, "base64");
                    const captured = { name, width, position: seen.position, keptPosition: baseline };
                    captures.push(captured);
                    assert.ok(seen.position[2] >= 0 && seen.position[2] < 700, `Record is outside the first screen for ${name}`);
                    const keys = await reachesRecord(page);
                    captured.recordTabStops = keys.length;
                    if (keyboard) assert.deepEqual(keys, keyboard, "installing a pack changes the keyboard path");
                    else keyboard = keys;
                    if (installed && track === "bike") {
                        await page.evaluate(`document.querySelectorAll('details[data-element="lesson-packs"], details[data-element="lesson-packs"] details').forEach((details) => { details.open = true; })`);
                        assert.equal((await page.evaluate(BELOW_AA)).length, 0, `open lesson text below AA contrast for ${name}`);
                    }
                    await page.send("Page.close");
                }
            }
        }
    }
    fs.writeFileSync(path.join(output, "positions.json"), JSON.stringify(captures, null, 2));
    const items = captures.map(({ name, width }) =>
        `<figure><figcaption>${name}</figcaption><img src="${name}.png" alt="${name}" width="${width}" loading="lazy"></figure>`);
    fs.writeFileSync(path.join(output, "index.html"), [
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Hypotrail development panel</title>',
        '<style>body{font:1rem system-ui;color:#eee;background:#181818}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(22rem,1fr));gap:1rem}figure{margin:0}img{display:block;max-width:100%}figcaption{padding:.4rem}</style>',
        '<h1>Study panel in Chromium</h1><main>', ...items, '</main></html>',
    ].join("\n"));
});
