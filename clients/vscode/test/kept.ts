// The CLI output kept under `test/cli/`, as the CLI printed it (tests/test_vscode_client.py makes it again and compares).
import * as fs from "node:fs";
import * as path from "node:path";

export const KEPT = path.join(__dirname, "..", "..", "test", "cli");

// A file kept by the demonstration, under `test/cli/demonstration/`, is named by this prefix and its own name, with no slash: the
// lists of kept reads give their names to the files verify-panel writes for each, one folder deep.
export const DEMONSTRATION = "demonstration.";

export function kept(name: string): string {
  const file = name.startsWith(DEMONSTRATION) ? path.join("demonstration", name.slice(DEMONSTRATION.length)) : name;
  return fs.readFileSync(path.join(KEPT, file), "utf8");
}
