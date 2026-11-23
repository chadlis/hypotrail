// The CLI output kept under `test/cli/`, as the CLI printed it (tests/test_vscode_client.py makes it again and compares).
import * as fs from "node:fs";
import * as path from "node:path";

export const KEPT = path.join(__dirname, "..", "..", "test", "cli");

export function kept(name: string): string {
  return fs.readFileSync(path.join(KEPT, name), "utf8");
}
