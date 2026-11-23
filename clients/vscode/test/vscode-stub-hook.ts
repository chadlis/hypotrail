// Loaded with `node --require` before every client test: `require("vscode")` then gives the stub of this folder,
// so the client's sources run under node:test with no VS Code.
import Module = require("node:module");
import * as path from "node:path";

type Resolver = (request: string, ...rest: unknown[]) => string;
const loader = Module as unknown as { _resolveFilename: Resolver };
const resolve = loader._resolveFilename;
const stub = path.join(__dirname, "vscode-stub.js");

loader._resolveFilename = function (this: unknown, request: string, ...rest: unknown[]): string {
  return request === "vscode" ? stub : resolve.call(this, request, ...rest);
};
