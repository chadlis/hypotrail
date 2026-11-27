// The CLI output kept under `test/cli/`, as the CLI printed it (tests/test_vscode_client.py makes it again and compares).
import * as fs from "node:fs";
import * as path from "node:path";

export const KEPT = path.join(__dirname, "..", "..", "test", "cli");

// A file kept by the demonstration, under `test/cli/demonstration/`, is named by this prefix and its own name, with no slash: the
// lists of kept reads give their names to the files verify-panel writes for each, one folder deep.
export const DEMONSTRATION = "demonstration.";

// A file kept of the journey the panel mockups show, under `test/cli/journey/` (tests/_journey_states.py), the same way.
export const JOURNEY = "journey.";

// A kept `lesson` read, under `test/cli/lesson/` (tests/_client_helpers.py, `lesson_outputs`), the same way.
export const LESSON = "lesson.";

export function kept(name: string): string {
  const folder = [DEMONSTRATION, JOURNEY, LESSON].find((prefix) => name.startsWith(prefix));
  const file = folder ? path.join(folder.slice(0, -1), name.slice(folder.length)) : name;
  return fs.readFileSync(path.join(KEPT, file), "utf8");
}
