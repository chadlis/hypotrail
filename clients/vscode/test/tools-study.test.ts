import { test } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";
import { recorder } from "./recorder";
import { CALLERS, invoke, keptAnswer, READ_TOOL, workspace, WRITE_INPUT, WRITE_TOOL } from "./tools-harness";
import * as stub from "./vscode-stub";

// Each case: the Studies made in the workspace, the `study` given (from the workspace's root), and the index of the
// Study each tool takes, absent when it refuses. The write requires `study`; the read takes it as optional.
type Case = { name: string; names: string[]; given?: (root: string) => string; read?: number; write?: number };

const CASES: Case[] = [
  { name: "study absent and one Study found", names: ["only"], read: 0 },
  { name: "study absent and no Study found", names: [] },
  { name: "study absent and two Studies found", names: ["a", "b/c"] },
  { name: "study given as a found Study, written unresolved", names: ["a", "b"], given: (root) => `${root}/a/../b/`, read: 1, write: 1 },
  { name: "study given as a folder the walk does not find", names: ["a", "b"], given: (root) => path.join(root, "c") },
  { name: "study given as the relative path of a found Study", names: ["runs/bike", "b"], given: () => "runs/bike" },
];

const CALLS: [string, string, typeof invoke][] = [
  [READ_TOOL, "", invoke],
  ...CALLERS.map(([how, call]): [string, string, typeof invoke] => [WRITE_TOOL, ` ${how}`, call]),
];

for (const [tool, how, call] of CALLS) {
  for (const each of CASES) {
    const takes = tool === READ_TOOL ? each.read : each.write;
    test(`the tool ${tool}${how} with ${each.name} ${takes === undefined ? "refuses, naming the Studies found, with no start and no pick" : "starts the CLI on that Study"}`, async (t) => {
      const { root, studies } = workspace(t, each.names);
      const calls = recorder(t, keptAnswer(tool === READ_TOOL ? "status-success" : "decide-success"));
      const input = { ...(tool === WRITE_TOOL ? WRITE_INPUT : {}), ...(each.given ? { study: each.given(root) } : {}) };
      const text = await call(tool, input);
      if (takes !== undefined) {
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0].args.filter((argument) => argument.startsWith("--study=")), [`--study=${studies[takes]}`]);
      } else {
        assert.equal(calls.length, 0);
        assert.match(text, /Nothing was started\./);
        for (const study of studies) assert.ok(text.includes(study), study);
        assert.deepEqual(stub.callsOf("showQuickPick"), []);
      }
    });
  }
}
