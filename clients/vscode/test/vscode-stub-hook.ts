// Loaded with `node --require` before every client test: `require("vscode")` then gives the stub of this folder,
// so the client's sources run under node:test with no VS Code. No client test starts the CLI: `execFile` answers as
// a program that is not found, unless a test puts the recorder in its place. The guard of the layout alone starts a
// process, Chrome, with `spawn`.
import Module = require("node:module");
import childProcess = require("node:child_process");
import * as path from "node:path";

type Resolver = (request: string, ...rest: unknown[]) => string;
const loader = Module as unknown as { _resolveFilename: Resolver };
const resolve = loader._resolveFilename;
const stub = path.join(__dirname, "vscode-stub.js");

loader._resolveFilename = function (this: unknown, request: string, ...rest: unknown[]): string {
  return request === "vscode" ? stub : resolve.call(this, request, ...rest);
};

const notFound = (...args: unknown[]): object => {
  const callback = args[args.length - 1] as (error: unknown, stdout: string, stderr: string) => void;
  setImmediate(() => callback(Object.assign(new Error("not started in a test"), { code: "ENOENT" }), "", ""));
  return {};
};
(childProcess as unknown as { execFile: unknown }).execFile = notFound;
