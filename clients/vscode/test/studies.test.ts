import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import fsp = require("node:fs/promises");
import * as os from "node:os";
import * as path from "node:path";
import contract from "../contract.json";
import { chooseStudy, findStudies } from "../src/studies";
import * as stub from "./vscode-stub";

function tree(t: { after(fn: () => void): void }): string {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hypotrail-walk-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function study(folder: string, content = "{}"): string {
  fs.mkdirSync(folder, { recursive: true });
  fs.writeFileSync(path.join(folder, "study.json"), content);
  return folder;
}

test("the walk finds the Studies to depth 2, breadth first, sorted by absolute path, and not the one at depth 3", async (t) => {
  const root = tree(t);
  const found = [study(path.join(root, "b", "c")), study(path.join(root, "a")), study(root)];
  study(path.join(root, "d", "e", "f"));
  assert.equal(contract.walk_depth, 2);
  assert.deepEqual(await findStudies([root]), [...found].sort());
});

test("the walk skips node_modules, .venv and dot-folders and follows no symbolic link", async (t) => {
  const root = tree(t);
  const outside = tree(t);
  study(path.join(root, "node_modules"));
  study(path.join(root, ".venv"));
  study(path.join(root, ".git"));
  study(path.join(outside, "elsewhere"));
  fs.symlinkSync(path.join(outside, "elsewhere"), path.join(root, "linked"), "dir");
  assert.deepEqual(contract.walk_skipped, ["node_modules", ".venv", ".*"]);
  assert.deepEqual(await findStudies([root]), []);
});

test("the walk lists at most 500 folders", async (t) => {
  const root = tree(t);
  for (let i = 0; i < 30; i += 1) for (let j = 0; j < 20; j += 1) fs.mkdirSync(path.join(root, `d${i}`, `e${j}`), { recursive: true });
  const listed: string[] = [];
  const readdir = fsp.readdir;
  t.mock.method(fsp, "readdir", (folder: string, ...rest: unknown[]) => {
    listed.push(folder);
    return (readdir as (...args: unknown[]) => unknown)(folder, ...rest);
  });
  await findStudies([root]);
  assert.equal(contract.walk_max_folders, 500);
  assert.ok(listed.length > 0 && listed.length <= 500, `${listed.length} folders listed`);
});

test("a study.json that is an empty file marks a Study: the walk does not read it", async (t) => {
  const root = tree(t);
  study(path.join(root, "empty"), "");
  assert.deepEqual(await findStudies([root]), [path.join(root, "empty")]);
});

test("with two Studies the client asks with one pick that holds both paths, sorted", async (t) => {
  stub.reset();
  const root = tree(t);
  const paths = [study(path.join(root, "z")), study(path.join(root, "a"))];
  stub.state.folders = [root];
  stub.state.pick = (items) => items[1];
  const chosen = await chooseStudy();
  const picks = stub.callsOf("showQuickPick");
  assert.equal(picks.length, 1);
  assert.deepEqual(picks[0].args[0], [...paths].sort());
  assert.equal(chosen, [...paths].sort()[1]);
});

test("with no Study the client shows the one message, opens no dialog and no pick", async (t) => {
  stub.reset();
  stub.state.folders = [tree(t)];
  assert.equal(await chooseStudy(), undefined);
  assert.deepEqual(stub.callsOf("showInformationMessage").map((call) => call.args[0]), ["No Hypotrail Study was found in this workspace."]);
  assert.equal(contract.no_study_message, "No Hypotrail Study was found in this workspace.");
  for (const name of ["showOpenDialog", "showSaveDialog", "showWorkspaceFolderPick", "showQuickPick"]) assert.deepEqual(stub.callsOf(name), [], name);
});

test("with one Study the client takes it with no pick", async (t) => {
  stub.reset();
  const root = tree(t);
  stub.state.folders = [root];
  const only = study(path.join(root, "only"));
  assert.equal(await chooseStudy(), only);
  assert.deepEqual(stub.callsOf("showQuickPick"), []);
});
