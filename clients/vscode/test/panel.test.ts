import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import contract from "../contract.json";
import { activate } from "../src/extension";
import * as stub from "./vscode-stub";

const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "package.json"), "utf8"));

function workspace(t: { after(fn: () => void): void }, studies: string[]): string[] {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-panel-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  stub.state.folders = [root];
  return studies.map((name) => {
    fs.mkdirSync(path.join(root, name), { recursive: true });
    fs.writeFileSync(path.join(root, name, "study.json"), "{}");
    return path.join(root, name);
  });
}

function activated(): void {
  stub.reset();
  activate({ subscriptions: [], extensionPath: "/home/owner/hypotrail/clients/vscode" } as never);
}

function closeAll(): void {
  for (const panel of stub.state.panels) if (!panel.disposed) panel.dispose();
}

async function runCommand(): Promise<void> {
  await stub.state.commands.get("hypotrail.openPanel")!();
}

test("the extension registers exactly the commands the manifest contributes, and one link handler", () => {
  activated();
  const registered = stub.callsOf("registerCommand").map((call) => call.args[0]).sort();
  assert.deepEqual(registered, MANIFEST.contributes.commands.map((command: { command: string }) => command.command).sort());
  assert.equal(stub.callsOf("registerUriHandler").length, 1);
});

test("with one Study the command opens one panel, with no pick, and its options are the four values", async (t) => {
  activated();
  workspace(t, ["bike"]);
  await runCommand();
  assert.deepEqual(stub.callsOf("showQuickPick"), []);
  const created = stub.callsOf("createWebviewPanel");
  assert.equal(created.length, 1);
  const options = created[0].args[3] as Record<string, unknown>;
  assert.deepEqual(Object.keys(options).sort(), ["enableCommandUris", "enableForms", "enableScripts", "localResourceRoots"]);
  assert.equal(options.enableScripts, true);
  assert.equal(options.enableCommandUris, false);
  assert.equal(options.enableForms, false);
  assert.deepEqual(options.localResourceRoots, []);
  assert.deepEqual(contract.panel_options, ["enableScripts=true", "enableCommandUris=false", "enableForms=false", "localResourceRoots=[]"]);
  closeAll();
});

test("with two Studies the command asks with one pick, then opens one panel", async (t) => {
  activated();
  workspace(t, ["a", "b"]);
  await runCommand();
  assert.equal(stub.callsOf("showQuickPick").length, 1);
  assert.equal(stub.callsOf("createWebviewPanel").length, 1);
  assert.ok(stub.calls.findIndex((call) => call.name === "showQuickPick") < stub.calls.findIndex((call) => call.name === "createWebviewPanel"));
  closeAll();
});

test("with no Study the command shows the message and creates no panel", async (t) => {
  activated();
  workspace(t, []);
  await runCommand();
  assert.deepEqual(stub.callsOf("showInformationMessage").map((call) => call.args[0]), ["No Hypotrail Study was found in this workspace."]);
  assert.deepEqual(stub.callsOf("createWebviewPanel"), []);
});

test("a second run reveals the open panel and creates none; once it is closed, the command creates one again", async (t) => {
  activated();
  workspace(t, ["bike"]);
  await runCommand();
  await runCommand();
  assert.equal(stub.callsOf("createWebviewPanel").length, 1);
  assert.equal(stub.callsOf("reveal").length, 1);
  closeAll();
  await runCommand();
  assert.equal(stub.callsOf("createWebviewPanel").length, 2);
  closeAll();
});

// What makes a document break the policy, by patterns, with no parser.
function cspProblems(document: string): string[] {
  const problems: string[] = [];
  const policies = [...document.matchAll(/http-equiv="Content-Security-Policy" content="([^"]*)"/g)];
  if (policies.length !== 1) return [`${policies.length} policies`];
  const nonce = /script-src 'nonce-([^']*)'/.exec(policies[0][1])?.[1] ?? "";
  if (!/^[A-Za-z0-9]+$/.test(nonce)) problems.push(`the nonce ${nonce}`);
  const expected = contract.csp_directives.map((directive) => directive.replace("{nonce}", nonce)).join("; ");
  if (policies[0][1] !== expected) problems.push(`the policy ${policies[0][1]}`);
  for (const element of ["script", "style"]) {
    const opened = document.split(`<${element} `).length - 1;
    const withNonce = document.split(`<${element} nonce="${nonce}"`).length - 1;
    if (opened !== 1 || withNonce !== 1 || document.split(`<${element}>`).length > 1) problems.push(`${element}: ${opened} opened, ${withNonce} with the nonce`);
  }
  if (/\sstyle=/i.test(document)) problems.push("a style attribute");
  if (/\son[a-z]+\s*=/i.test(document)) problems.push("an inline event handler");
  if (/https?:\/\//i.test(document)) problems.push("a remote address");
  return problems;
}

test("the document holds one policy of the nine directives with a nonce for each document, and no script or style without it", async (t) => {
  activated();
  workspace(t, ["bike"]);
  await runCommand();
  await runCommand();
  const [first, second] = stub.state.panels[0].documents;
  assert.deepEqual(cspProblems(first), []);
  assert.deepEqual(cspProblems(second), []);
  const nonceOf = (document: string) => /script-src 'nonce-([^']*)'/.exec(document)![1];
  assert.notEqual(nonceOf(first), nonceOf(second));
  assert.equal(contract.csp_directives.length, 9);
  assert.deepEqual(contract.csp_directives, [
    "default-src 'none'",
    "style-src 'nonce-{nonce}'",
    "script-src 'nonce-{nonce}'",
    "img-src 'none'",
    "font-src 'none'",
    "connect-src 'none'",
    "frame-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
  ]);
  const planted = [
    first.replace("</body>", "<script>run()</script></body>"),
    first.replace("<body>", '<body style="color: red">'),
    first.replace("<body>", '<body onclick="go()">'),
    first.replace("</body>", '<img src="https://example.com/x.png"></body>'),
  ];
  for (const copy of planted) assert.notDeepEqual(cspProblems(copy), [], copy);
  closeAll();
});
