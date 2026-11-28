# Whole-system proof

The round 3 proof follows D-225. [Owner's decision](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7223332432)

The evaluator rehearsal follows D-257. [Owner's Round 5 decision](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7235501369)

Run this manual proof from a Hypotrail checkout with Bash, Git, uv, Python 3.13, Node 22 or later, npm, Chromium and GNU `timeout`. Set `HYPOTRAIL_CHROME` when Chromium is installed somewhere other than `/usr/bin/google-chrome`.

```sh
scripts/e2e_all.sh /path/to/writable/scratch /path/to/cached/online_retail_II.xlsx
```

The second argument is the public MLkit twin workbook from an existing, independently provisioned cache. The script verifies its digest with `mlkit fetch` after copying it to the already-present cache path. A missing or unreadable cache is a failed MLkit proof step. The other checks still run. The script makes no dataset download. Remote activity is limited to Git clones and package installation. The browser loads test pages on loopback and uses the client's VS Code stub. There are no live model calls.

The script creates a new private scratch directory. It uses private package caches by default. Set `NPM_CONFIG_CACHE` or `UV_CACHE_DIR` to reuse a writable cache. It reports all four cloned heads and each consumer's exact Hypotrail pin. The product checks always run from a clean clone of product `main`. Each kit and the lesson repository get a separate detached Hypotrail checkout at their own pin, even when the pins differ. Agentkit's standalone tests run before its pinned checkout is staged for the required twin tests.

| Step | What it checks |
| --- | --- |
| C1 | Fresh clones, explicit pins, the frozen product environment and the compiled VS Code client. |
| C2 | The full product and client suites, each kit's CI and pinned end-to-end workflow, and validation of the pinned example and published packs. MLkit's cache-hit workflow reports tests blocked by the specific owner gate as `SKIPPED`. When `run` and `export` are open, its pinned workflow must pass. The client suite has a five-minute limit, serves test documents on loopback and requires Chromium. The proof rejects a client summary with skipped tests. |
| C3 | The published pack before any Study, the kept A5 Bike development replay, a synthetic panel Decision, station-mark transitions and read-only behaviour. After every write, the lesson read from a Study copy with a synthetic public-check Attempt must match the original byte for byte. A separate literal token check rejects forbidden words without printing the matches. The pack-off read matches its unchanged pre-pack capture byte for byte. |
| C4 | The kept Chinook development Campaign replayed in a scratch Study and a pack unavailable for that Track. |
| C5 | The compiled panel draws the actual Bike and Chinook development reads with and without the pack, at both widths in the four default themes. The renderer checks AA contrast, panel order, first-screen positions against the previously accepted measurements and keyboard access to Record. The contact sheet uses the client's document harness, Chrome driver and theme injections. |
| C6 | The existing Guide suite, actual registered pack read and the declared held-out instruction and station boundary. A natural-language Guide reply at the held-out station requires a model invocation in the host. That proof is `SKIPPED` under [D-235/G6](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7225276774). |
| C7 | The Agentkit scripted development and evaluator tests, including the aggregate leak check, run inside the independent kit's test process. MLkit's build, runs, export, import, assessment and comparison must pass the actual kit test when the gate opens `run` and `export`. An expected failure from the ranking Track prerequisites M1 and M2 still fails this proof. |
| C8 | The MLkit evaluator rehearsal builds synthetic inputs inside the test process and exercises the four acceptance verdict cases, the single-reading refusal and the aggregate file boundary. The proof requires actual passes and invokes only the synthetic test with the GitHub workflow indicator and tokens removed. |

For snapshot checks the harness fingerprints Study records and compares file metadata for frozen References and memberships, without reading their payloads. The only synthetic human-channel Decision goes through the existing panel stub in the temporary Bike test, with fixture words. No proof record is signed or written to a repository.

The output is a status line per test step plus the final counts and scratch location. A nonzero exit means at least one failure occurred. If the first product suite fails, the script runs it once more with no concurrent proof step and records both outcomes. The script intentionally discards raw test output. Share only the summary and reviewed proof artefacts, since a failed assertion in a repository test can contain fixture data.

## Debt

The stock `verify-panel` skill reads all its kept fixture states and accepts only a checkout revision. Its interface cannot select the real development Studies produced by C3 and C4 or restrict its reads to development observations. The proof uses the compiled panel and the client's AA checker with explicit development inputs.
