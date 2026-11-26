// The states the demonstration kept for the client: the kept reads on disk under `test/cli/demonstration/`, and their entries in the
// lists of kept reads that every per-read check of the panel runs on.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { DEMONSTRATION, KEPT } from "./kept";
import { KEPT_FIGURES, KEPT_READS } from "./panel-harness";

// The kept states of the demonstration on disk: each state whose status read the folder holds.
function statesOnDisk(): string[] {
  return fs
    .readdirSync(path.join(KEPT, "demonstration"))
    .filter((name) => name.endsWith(".status.out"))
    .map((name) => name.slice(0, -".status.out".length))
    .sort();
}

const readOf = (state: string): string => `${DEMONSTRATION}${state}.status`;
const figuresOf = (state: string): string => `${DEMONSTRATION}${state}.figures`;

test("the demonstration's entries of KEPT_READS are the kept states of the demonstration on disk, both ways, each with its figures read in KEPT_FIGURES", () => {
  const listed = KEPT_READS.filter((name) => name.startsWith(DEMONSTRATION));
  const onDisk = statesOnDisk();
  assert.ok(onDisk.length > 0, "the folder holds kept states");
  for (const state of [...new Set([...onDisk, ...listed.map((name) => name.slice(DEMONSTRATION.length, -".status".length))])].sort()) {
    assert.ok(onDisk.includes(state), `${state} is listed in KEPT_READS and has no status read on disk`);
    assert.ok(listed.includes(readOf(state)), `the kept state ${state} is not in KEPT_READS`);
    assert.equal(KEPT_FIGURES[readOf(state)], figuresOf(state), state);
  }
});
