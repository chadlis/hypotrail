import { test } from "node:test";
import assert from "node:assert/strict";
import * as path from "node:path";

test("the module the client's sources import as vscode is the stub of the tests", () => {
  assert.equal(require.resolve("vscode"), path.join(__dirname, "vscode-stub.js"));
  assert.equal(require("vscode").isTheStub, true);
});
