import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import contract from "../contract.json";
import { activate } from "../src/extension";
import * as panel from "../src/panel";
import { exit, recorder } from "./recorder";
import * as stub from "./vscode-stub";

const UUID = "c53337e9-d255-423d-a851-414278d5c3f0";
const REFUSAL = "This Hypotrail link is not valid.";

// A link as VS Code hands it to the handler: its parts, split as `vscode.Uri.parse` splits them.
function uriOf(link: string) {
  const match = /^([a-z-]+):\/\/([^/?#]*)([^?#]*)(?:\?([^#]*))?(?:#(.*))?$/s.exec(link)!;
  return { scheme: match[1], authority: match[2], path: match[3], query: match[4] ?? "", fragment: match[5] ?? "" };
}

function link(form: number, study: string, uuid = UUID): string {
  return contract.link_forms[form].replace("{path}", study).replace("{uuid}", uuid);
}

const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-links-")));
const outside = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-outside-")));
function study(folder: string): string {
  fs.mkdirSync(folder, { recursive: true });
  fs.writeFileSync(path.join(folder, "study.json"), "{}");
  return folder;
}
const BIKE = study(path.join(root, "bike"));
const ODD = study(path.join(root, "a&b+c=d"));
const DEEP = study(path.join(root, "x", "y"));
const DEEPER = study(path.join(root, "d", "e", "f"));
const ELSEWHERE = study(path.join(outside, "elsewhere"));

const VALID: [string, string, { study: string; decision?: string }][] = [
  ["the first form with the Study's path", link(0, BIKE), { study: BIKE }],
  ["the second form with a UUID and the Study's path", link(1, BIKE), { study: BIKE, decision: UUID }],
  ["the first form with a found path that holds &, + and =", link(0, ODD), { study: ODD }],
  ["the first form with a Study at depth 2", link(0, DEEP), { study: DEEP }],
];

const REFUSED: [string, string][] = [
  ["another authority", link(0, BIKE).replace("hypotrail-local.hypotrail", "someone.else")],
  ["a fragment", `${link(0, BIKE)}#top`],
  ["the path /result/<uuid>", link(1, BIKE).replace("/decision/", "/result/")],
  ["the path /study/extra", link(0, BIKE).replace("/study?", "/study/extra?")],
  ["/decision/ with an id that is not a UUID", link(1, BIKE, "not-a-uuid")],
  ["/decision/ with a UUID in capitals", link(1, BIKE, UUID.toUpperCase())],
  ["no query", link(0, BIKE).split("?")[0]],
  ["a query that does not begin with study=", link(0, BIKE).replace("?study=", "?where=")],
  ["an empty path", link(0, "")],
  ["a relative path", link(0, "runs/bike")],
  ["a path with a NUL", link(0, `${BIKE}\0`)],
  ["a path of 4,097 characters", link(0, `/${"a".repeat(4096)}`)],
  ["an absolute path that holds a study.json and lies outside the workspace", link(0, ELSEWHERE)],
  ["a Study at depth 3 below the workspace folder", link(0, DEEPER)],
  ["a found path with a trailing slash", link(0, `${BIKE}/`)],
  ["a path that names a found Study through ..", link(0, `${root}/x/../bike`)],
];

function activated(): void {
  stub.reset();
  stub.state.folders = [root];
  activate({ subscriptions: [], extensionPath: "/home/owner/hypotrail/clients/vscode" } as never);
}

function closeAll(): void {
  for (const panel of stub.state.panels) if (!panel.disposed) panel.dispose();
}

test("the extension registers one link handler", () => {
  activated();
  assert.equal(stub.callsOf("registerUriHandler").length, 1);
});

for (const [name, text, target] of VALID) {
  test(`a valid link opens the panel once, with its target, and shows no notification: ${name}`, async (t) => {
    activated();
    t.after(closeAll);
    const calls = recorder(t, exit(0, "{}"));
    const opened = t.mock.method(panel, "openPanel");
    await stub.state.uriHandlers[0].handleUri(uriOf(text));
    assert.equal(stub.callsOf("createWebviewPanel").length, 1);
    assert.deepEqual(opened.mock.calls.map((call) => call.arguments), [[target]]);
    for (const name of ["showErrorMessage", "showInformationMessage", "showWarningMessage"]) assert.deepEqual(stub.callsOf(name), [], name);
    assert.deepEqual(calls.filter((call) => call.args.includes("decide")), []);
  });
}

for (const [name, text] of REFUSED) {
  test(`a link is refused with the one notification and opens nothing: ${name}`, async (t) => {
    activated();
    t.after(closeAll);
    const calls = recorder(t, exit(0, "{}"));
    await stub.state.uriHandlers[0].handleUri(uriOf(text));
    const shown = [...stub.callsOf("showErrorMessage"), ...stub.callsOf("showInformationMessage"), ...stub.callsOf("showWarningMessage")];
    assert.deepEqual(shown.map((call) => call.args), [[REFUSAL]]);
    assert.equal(contract.link_refusal, REFUSAL);
    assert.deepEqual(stub.callsOf("createWebviewPanel"), []);
    assert.deepEqual(calls.filter((call) => call.args.includes("decide")), []);
  });
}

test("the two forms of contract.json are the ones the handler accepts", async (t) => {
  recorder(t);
  t.after(closeAll);
  for (const form of [0, 1]) {
    activated();
    await stub.state.uriHandlers[0].handleUri(uriOf(link(form, BIKE)));
    assert.equal(stub.callsOf("createWebviewPanel").length, 1, contract.link_forms[form]);
    closeAll();
  }
  assert.equal(contract.link_max_path, 4096);
  assert.equal(contract.link_decision_id, "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
});

test.after(() => {
  fs.rmSync(root, { recursive: true, force: true });
  fs.rmSync(outside, { recursive: true, force: true });
});
