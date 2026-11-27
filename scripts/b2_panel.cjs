// B2 contact sheet for the compiled panel on the kept Bike development view.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const [, , reads, output] = process.argv;
const client = path.resolve(__dirname, "../clients/vscode/out/test");
const from = (name) => require(path.join(client, name));
from("vscode-stub-hook");
const { documentFor, keptObject, settle, success, workspace } = from("panel-harness");
const { lesson, recorder } = from("recorder");
const { state } = from("vscode-stub");
const { openDocument, startChrome } = from("chrome");
const { BELOW_AA, THEMES, themed } = from("themes");

const SECTION = 'details[data-element="lesson-packs"]';
const STATION = 'details[data-element="pack-station"]';
const METHOD = 'details[data-element="pack-lesson"]';
const ILLUSTRATION = '[data-element="pack-illustration"]';
const RECORD = 'section[data-part="now"] button[data-message="record"]';
const packTrack = "temporal_regression";
const otherTrack = "tool_using_agent";

const read = (name) => JSON.parse(fs.readFileSync(path.join(reads, name + ".json"), "utf8"));
function developmentStudy() {
    // These exact kept views contain only Bike development observations.
    const status = keptObject("journey.04-pending.status");
    assert.equal(status.study.workload, "bike_day");
    assert.ok(status.attempts.length && status.attempts.every(({ partition }) => partition === "dev"));
    const observations = new Set(status.attempts.map(({ observation_set_id }) => observation_set_id));
    assert.ok(status.assessments.every(({ observation_set_id }) => observations.has(observation_set_id)));
    const assessments = new Set(status.assessments.map(({ assessment_id }) => assessment_id));
    assert.ok(status.comparisons.every(({ left_assessment_id, right_assessment_id }) =>
        assessments.has(left_assessment_id) && assessments.has(right_assessment_id)));
    const comparisons = new Set(status.comparisons.map(({ comparison_id }) => comparison_id));
    const figures = keptObject("journey.04-pending.figures");
    assert.ok(figures.comparisons.every(({ comparison_id }) => comparisons.has(comparison_id)));
    const legacy = keptObject("lesson.after-compare");
    assert.equal(status.write_sequence, legacy.write_sequence);
    assert.equal(status.write_sequence, figures.write_sequence);
    return { status, figures, legacy };
}

const visibleAA = BELOW_AA.replace(
    "    const style = getComputedStyle(element);",
    "    const range = new Range(); range.selectNodeContents(node);\n" +
    "    if (element.closest(':disabled') || ![...range.getClientRects()].some(rect => rect.width && rect.height)" +
    " || getComputedStyle(element).visibility !== 'visible') continue;\n" +
    "    const style = getComputedStyle(element);"
);
assert.notEqual(visibleAA, BELOW_AA);

async function browserPage(t, browser, document, theme, width) {
    const page = await openDocument(t, browser, document, width, 700,
        "window.messages = []; window.acquireVsCodeApi = () => ({postMessage: msg => window.messages.push(msg)});");
    async function evaluate(expression) {
        const result = await page.send("Runtime.evaluate", {expression, returnByValue: true});
        assert.ok(!result.exceptionDetails, "B2 browser evaluation failed");
        return result.result.value;
    }
    await evaluate(themed(theme));
    return {evaluate, send: page.send};
}

const keys = {
    Tab: {key: "Tab", code: "Tab", windowsVirtualKeyCode: 9},
    Space: {key: " ", code: "Space", text: " ", windowsVirtualKeyCode: 32},
    Enter: {key: "Enter", code: "Enter", text: "\r", windowsVirtualKeyCode: 13},
};

async function press(page, key) {
    await page.send("Input.dispatchKeyEvent", {type: "keyDown", ...keys[key]});
    await page.send("Input.dispatchKeyEvent", {type: "keyUp", ...keys[key], text: undefined});
}

async function reachesRecord(page) {
    const steps = [];
    for (let count = 0; count < 40; count++) {
        await press(page, "Tab");
        const active = await page.evaluate(`(() => {
            const e = document.activeElement;
            return {tag: e.tagName, option: e.hasAttribute("data-option"), message: e.dataset.message, href: e.getAttribute("href")};
        })()`);
        steps.push(active);
        if (active.option) await press(page, "Space");
        if (active.message === "record") {
            assert.ok(await page.evaluate("!document.activeElement.disabled"));
            return steps;
        }
    }
    assert.fail("Record was not reachable with the keyboard");
}

async function recordTop(page) {
    return page.evaluate(`Math.round(document.querySelector(${JSON.stringify(RECORD)}).getBoundingClientRect().top + scrollY)`);
}

async function capture(page, name, items, expression) {
    assert.equal((await page.evaluate(visibleAA)).length, 0, `visible text below AA contrast in ${name}`);
    const params = {format: "png"};
    if (expression) {
        params.clip = await page.evaluate(`(() => {
            const {x, y, width, height} = (${expression}).getBoundingClientRect();
            return {x: x + scrollX, y: y + scrollY, width, height, scale: 1};
        })()`);
        params.captureBeyondViewport = true;
    }
    const png = await page.send("Page.captureScreenshot", params);
    fs.writeFileSync(path.join(output, `${name}.png`), png.data, "base64");
    items.push(`<figure><figcaption>${name}</figcaption><img src="${name}.png" alt="${name}" loading="lazy"></figure>`);
}

async function stations(t, packPacket) {
    const responses = [packPacket, read(otherTrack), read("no-pack")];
    workspace(t, []);
    const calls = recorder(t, ...responses.map((packet) => lesson(success(packet))));
    await state.commands.get("hypotrail.showStations")();
    const panel = state.panels[0];
    const chooser = panel.webview.html;
    const documents = [];
    for (const track of [packTrack, otherTrack, packTrack]) {
        const nonce = /<script nonce="([a-f0-9]+)">/.exec(panel.webview.html)[1];
        panel.send({track, nonce});
        await settle();
        assert.ok(calls[documents.length].args.includes("--track=" + track));
        documents.push(panel.webview.html);
    }
    return [chooser, ...documents];
}

test("B2 contact sheet", {timeout: 180000}, async (t) => {
    fs.mkdirSync(output);
    const {status, figures, legacy} = developmentStudy();
    const packet = read(packTrack);
    assert.equal(packet.packs.length, 1);
    assert.equal(packet.packs[0].id, "forecasting-en");
    assert.equal(packet.stations.length, 8);
    assert.equal(packet.lessons.length, 28);
    assert.equal(packet.lessons.filter(({illustration}) => illustration).length, 7);
    const marks = {
        baseline: status.assessments.length >= 1,
        iterate: status.assessments.length >= 2,
        compare_decide: Boolean(status.comparisons.length || status.decisions.length),
    };
    const packRead = {
        ...legacy,
        packs: packet.packs,
        stations: packet.stations.map((station) => ({...station, has_records: marks[station.id] ?? null})),
        lessons: packet.lessons,
    };
    const noPack = (await documentFor(t, success(status), success(figures), lesson(success(legacy)))).document;
    const withPack = (await documentFor(t, success(status), success(figures), lesson(success(packRead)))).document;
    const [chooser, temporal, agent, empty] = await stations(t, packet);
    const browser = await startChrome(t);
    assert.ok(browser, "Chrome is required to produce the contact sheet");
    const items = [];
    const section = `document.querySelector(${JSON.stringify(SECTION)})`;
    for (const theme of Object.keys(THEMES)) {
        for (const width of [420, 900]) {
            await t.test(`${theme} at ${width} px`, async (view) => {
                const open = (document) => browserPage(view, browser, document, theme, width);
                const save = (page, viewName, element) => capture(page, `${theme}-${width}-${viewName}`, items, element);
                const plain = await open(noPack);
                const baseline = await recordTop(plain);
                const steps = await reachesRecord(plain);
                await plain.evaluate(`${section}.open = true`);
                assert.match(await plain.evaluate(`${section}.innerText`), /Lesson packs: none/);
                await save(plain, "study-no-pack", section);
                await plain.send("Page.close");

                const packed = await open(withPack);
                assert.equal(await recordTop(packed), baseline);
                assert.ok(baseline > 0 && baseline < 700, "Record is outside the first screen");
                assert.ok(await packed.evaluate(`!!(document.querySelector(${JSON.stringify(RECORD)}).compareDocumentPosition(${section}) & Node.DOCUMENT_POSITION_FOLLOWING)`));
                assert.equal(await packed.evaluate(`${section}.open`), false);
                await save(packed, "first-screen");
                assert.deepEqual(await reachesRecord(packed), steps);
                await save(packed, "record-focus");
                await save(packed, "lessons-closed", section);
                await packed.evaluate(`${section}.open = true`);
                assert.equal(await packed.evaluate(`${section}.querySelectorAll('${STATION}').length`), 8);
                await save(packed, "lessons-open", section);
                const method = `[...${section}.querySelectorAll('${METHOD}')].find(e => e.querySelector("summary").textContent === "Check when each feature becomes available")`;
                assert.ok(await packed.evaluate(`Boolean((${method})?.querySelector('${ILLUSTRATION}'))`));
                await packed.evaluate(`(${method}).closest('${STATION}').open = true; (${method}).open = true`);
                await save(packed, "illustrated-lesson", method);
                const link = 'document.querySelector("a[data-pack-figure]")';
                await packed.evaluate(`${link}.closest('${STATION}').open = true; ${link}.focus()`);
                await press(packed, "Enter");
                assert.ok(await packed.evaluate(`document.activeElement === document.querySelector(${link}.getAttribute("href"))`));
                await save(packed, "development-interval", 'document.querySelector(\'[data-element="development-interval"]\')');
                await packed.send("Page.close");

                const choose = await open(chooser);
                await save(choose, "choose-track");
                for (const track of [packTrack, otherTrack]) {
                    await press(choose, "Tab");
                    assert.equal(await choose.evaluate("document.activeElement.dataset.track"), track);
                    await press(choose, "Enter");
                }
                assert.deepEqual(await choose.evaluate("window.messages.map(({track}) => track)"), [packTrack, otherTrack]);
                await choose.send("Page.close");
                for (const [pageName, document, count] of [
                    ["forecasting-stations", temporal, 8], ["agent-stations", agent, 0], ["no-study-no-pack", empty, 0],
                ]) {
                    const view = await open(document);
                    assert.equal(await view.evaluate(`document.querySelectorAll('${STATION}').length`), count);
                    if (pageName === "no-study-no-pack") assert.match(await view.evaluate("document.body.innerText"), /Lesson packs: none/);
                    await save(view, pageName);
                    await view.send("Page.close");
                }
            });
        }
    }
    assert.equal(items.length, 88);
    fs.writeFileSync(path.join(output, "index.html"), [
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Development panel contact sheet</title>',
        '<style>body{font:1rem system-ui;margin:1rem}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(22rem,1fr));gap:1rem}figure{margin:0}img{display:block;max-width:100%}</style>',
        '<h1>Development panel contact sheet</h1><p>Compiled VS Code panel with the API stub, kept Bike development inputs and the pinned forecasting lesson pack.</p>',
        '<main>', ...items, '</main></html>',
    ].join("\n"));
});
