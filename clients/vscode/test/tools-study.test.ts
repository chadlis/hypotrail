import { test } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import { recorder } from "./recorder";
import { invoke, keptAnswer, READ_TOOL, workspace, WRITE_INPUT, WRITE_TOOL } from "./tools-harness";
import * as stub from "./vscode-stub";

// Each case: the Studies made in the workspace, the `study` given (from the workspace's root), and the index of the
// Study the tool takes, absent when it refuses.
type Case = { name: string; names: string[]; given?: (root: string) => string; takes?: number };

const CASES: Case[] = [
  { name: "study absent and one Study found", names: ["only"], takes: 0 },
  { name: "study absent and no Study found", names: [] },
  { name: "study absent and two Studies found", names: ["a", "b/c"] },
  { name: "study given as a found Study, written unresolved", names: ["a", "b"], given: (root) => `${root}/a/../b/`, takes: 1 },
  { name: "study given as a folder the walk does not find", names: ["a", "b"], given: (root) => path.join(root, "c") },
  { name: "study given as a relative path that resolves, from the working folder, to a found Study", names: ["a", "b"], given: (root) => path.relative(process.cwd(), path.join(root, "a")) },
];

for (const tool of [READ_TOOL, WRITE_TOOL]) {
  for (const each of CASES) {
    test(`the tool ${tool} with ${each.name} ${each.takes === undefined ? "refuses, naming the Studies found, with no start and no pick" : "starts the CLI on that Study"}`, async (t) => {
      const { root, studies } = workspace(t, each.names);
      const calls = recorder(t, keptAnswer(tool === READ_TOOL ? "status-success" : "decide-success"));
      const input = { ...(tool === WRITE_TOOL ? WRITE_INPUT : {}), ...(each.given ? { study: each.given(root) } : {}) };
      const text = await invoke(tool, input);
      if (each.takes !== undefined) {
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0].args.filter((argument) => argument.startsWith("--study=")), [`--study=${studies[each.takes]}`]);
      } else {
        assert.equal(calls.length, 0);
        assert.match(text, /Nothing was started\./);
        for (const study of studies) assert.ok(text.includes(study), study);
        assert.deepEqual(stub.callsOf("showQuickPick"), []);
      }
    });
  }
}
