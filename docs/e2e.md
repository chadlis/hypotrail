# Whole-system proof

Run this manual proof from a Hypotrail checkout with Bash, Git, uv, Python 3.13, Node 22 or later, npm and Chromium. Set `HYPOTRAIL_CHROME` when Chromium is installed somewhere other than `/usr/bin/google-chrome`.

```sh
scripts/e2e_all.sh /path/to/writable/scratch /path/to/cached/online_retail_II.xlsx
```

The second argument is the public MLkit twin workbook from an existing, independently provisioned cache. The script verifies its digest with `mlkit fetch` after copying it to the already-present cache path. A missing or unreadable cache is a failed MLkit proof step. The other checks still run. The script makes no dataset download. Remote activity is limited to Git clones and package installation. The browser uses local files, loopback and the client's VS Code stub. There are no live model calls.

The script creates a new private scratch directory. It uses private package caches by default. Set `NPM_CONFIG_CACHE` or `UV_CACHE_DIR` to reuse a writable cache. It reports all four cloned heads and each consumer's exact Hypotrail pin. The product checks always run from a clean clone of product `main`. Each kit and the lesson repository get a separate detached Hypotrail checkout at their own pin, even when the pins differ.

| Step | What it checks |
| --- | --- |
| C1 | Fresh clones, explicit pins, the frozen product environment and the compiled VS Code client. |
| C2 | The full product and client suites, each kit's CI and pinned end-to-end workflow, and validation of the pinned example and published packs. The MLkit workflow uses its cache-hit path. |
| C3 | The published pack before any Study, the Bike development Import, Assessment, Comparison and synthetic panel Decision, every station-mark transition, and read-only behaviour. A synthetic public-check Attempt tests that the three pack keys are identical. A separate literal token check rejects forbidden words without printing the matches. The old serializer is checked byte for byte over the scratch Study's actual identifiers. The kept-read suite in C2 covers the pre-pack captures. |
| C4 | The kept Chinook development Campaign replayed in a scratch Study and a pack unavailable for that Track. |
| C5 | The compiled panel draws the actual Bike and Chinook development reads with and without the pack, at both widths in the four default themes. The renderer checks panel order, first-screen positions and keyboard access to Record. The contact sheet uses the client's document harness, Chrome driver and theme injections. The stock `verify-panel` command cannot take these Studies or select only development reads, so the manual proof supplies its own safe input driver. |
| C6 | The existing Guide suite and a scripted four-station walk using the real registered read tool. The held-out turn in this model-free script has the single boundary answer and no call. This proves the script, instructions and available tools. The Guide's behaviour with a model in the actual VS Code host is outside this proof. |
| C7 | The Agentkit scripted development and evaluator tests, including the aggregate leak check, run inside the independent kit's test process. The MLkit ranking round trip is reported as `SKIPPED` when `mlkit gate` exits 7 and requires a completed test when the gate is open. |

For snapshot checks the harness fingerprints Study records and compares file metadata for frozen References and memberships, without reading their payloads. The only synthetic human-channel Decision goes through the existing panel stub in the temporary Bike test, with fixture words. No proof record is signed or written to a repository.

The output is a status line per test step plus the final counts and scratch location. A nonzero exit means at least one failure occurred. If the first product suite fails, the script runs it once more with no concurrent proof step and records both outcomes. The script intentionally discards raw test output. Share only the summary and reviewed proof artefacts, since a failed assertion in a repository test can contain fixture data.
