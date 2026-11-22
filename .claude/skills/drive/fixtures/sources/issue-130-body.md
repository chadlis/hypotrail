Blocked by: #134, #129

## Parent

#120 (R1, milestone #103). The fitness tests of the slice's amendment: the [owner instruction on the fitness functions](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7063639489) (#1, 2026-11-21; the owner's words, « Fitness functions : la proposition retenue. Ok go »), tier 1, which widens the three tests [D-043](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7062406813) on chadlis/hypotrail#75 decided. Rule 2 (F4) is in #127; rules 5 to 7 are in #131.

## What to build

One resolver module for the architecture tests reads every module under `src/` with `rglob` and resolves relative imports to absolute module names. Three rules use it, each in `tests/test_architecture.py`:

- **Rule 1, layering.** cli is above the Tracks and report, which are above core. No Track imports another Track, report or cli. Every package is in an explicit list, and a package missing from it fails. This replaces `test_the_core_imports_no_track`, which misses relative imports and the subpackages of `core`.
- ~~**Rule 3, F2.** The write protocol's functions are called only from the Study-write module of #128, aliases resolved.~~ (replaced by Tightened E)
- **Rule 4, F3.** The Partition role set is read from each Track's partitions module, and no other module holds a role literal, apart from the two core copies Q2 settles later, which the test names.

Each rule is shown red once on a planted violation. No file under `src/` changes, and no dependency is added. No model is called.

## Acceptance criteria

- [ ] `tests/_architecture.py` finds every module under `src/hypotrail/` with `rglob`, subpackages included, and resolves each relative import to the absolute module it names. Rules 1, 3 and 4 read the source through it.
  Source: #120 amendment "**Shared resolver.** `tests/_architecture.py` resolves relative imports and scans with `rglob`. Every rule below uses it." Owner instruction, "Method": "Hand-written AST tests in pytest, sharing one resolver module (`tests/_architecture.py`). The resolver resolves relative imports and scans with `rglob`." ~~Owner instruction, "Found on the way": "The existing « core imports no Track » test misses relative imports and the subpackages of `core` (`tests/test_repo_rules.py:66` uses `glob`)."~~ (replaced by Tightened D)
  Witness: a test of the resolver on a package planted in a temporary folder, written first and shown red: `from . import x` and `from ..core import y` resolve to their absolute names, and a module in a subpackage is found.
  Proves: no T-xx.
- [ ] Rule 1: cli is above the Tracks and report, and those are above core. No Track imports another Track, report or cli. Every package of `src/hypotrail/` is in an explicit list of layers, and a package missing from the list fails. `test_the_core_imports_no_track` is removed.
  Source: #120 amendment "**Rule 1: layering.** cli is above the Tracks and report, and those are above core. No Track imports another Track, report or cli. Every package appears in an explicit list, and a package missing from the list fails. This replaces `test_the_core_imports_no_track`." #120 "no import between the two Tracks". ADR 0001, ADR 0002 (the owner instruction's sources for rule 1).
  Witness: rule 1, passing at the pull request's head; shown red once in the builder's hand-back on a planted relative import of `hypotrail.ml` from an `agentic` module, and once on a planted package missing from the list.
  Proves: no T-xx.
- [ ] Rule 3 (F2): `writer_lock`, `require_current` and `writing` are called only from the Study-write module. A call through an alias (`from … import writer_lock as hold`, a module imported under another name) counts as a call.
  Source: #120 amendment "**Rule 3: F2.** `writer_lock`, `require_current` and `writing` are called only from the Study-write module. Whether `begin` is included follows from the module's design." Owner instruction, rule 3, method: "AST call scan; aliases resolved".
  Witness: rule 3, passing at the pull request's head; shown red once in the builder's hand-back on a planted aliased call of `writer_lock` in a Track module.
  Proves: no T-xx.
- [ ] Rule 4 (F3): the test reads each Track's role set from its partitions module, never from a list typed in the test. A string constant of `src/` that equals a role of either Track is allowed only in that Track's partitions module and in the two files of Q2, `core/comparison.py` and `report/gather.py`, which the test names with the reason. ~~The Workload JSON schemas are read by the test (how, the second INFERRED item below).~~ (replaced by Tightened B)
  Source: #120 amendment "**Rule 4: F3.** The role set is read from each Track's partitions module. The Workload JSON schemas are covered. The Q2 files are named." Owner instruction, rule 4, method: "AST string constants + schema read". #117, Q2: "Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?"
  Witness: rule 4, passing at the pull request's head; shown red once in the builder's hand-back on a planted `"public_check"` literal in an `ml` module.
  Proves: no T-xx.
- [ ] No file under `src/` changes in this ticket, and no dependency is added.
  Source: #120 amendment "Each rule is shown red once on a planted violation. No new dependency is added." Owner instruction, "Method": "No new dependency."
  Witness: `git diff` of this ticket's commits shows no change under `src/` and none to `pyproject.toml` or `uv.lock`; the full suite passing.
  Proves: no T-xx.

### INFERRED (no source settles these; the ticket gate chooses)

- [ ] ~~**INFERRED: whether rule 3 lists `begin`.** It follows from the first INFERRED item of #128: with its option 1A or 1C, rule 3 also lists `begin` and is shown red once on a planted `begin` call outside the module; with 1B, it lists the three functions above only.~~
  ~~Source: #120 amendment, rule 3: "Whether `begin` is included follows from the module's design." Owner instruction, rule 3: "Whether `begin` is included follows from R1's design." D-043 "`writer_lock`, `require_current` and `begin` are called only from the write module", replaced by the amendment: "That text replaces and widens this slice's fitness-test list".~~
  ~~Witness: rule 3 at the pull request's head, and its red on the planted `begin` call when `begin` is listed.~~ (settled by Tightened A)
- [ ] ~~**INFERRED: what "the Workload JSON schemas are covered" asks of rule 4.** At `6c2827c`, `agentic/workload.schema.json` closes `cases` to the property names `dev` and `public_check`, and `ml/workload.schema.json` names no role (its `partitions` takes any name).~~
  ~~Options:~~
  - ~~**2A.** Every role name a Workload schema holds belongs to its Track's role set. Cost: a schema that drops a role still passes.~~
  - ~~**2B.** The agent schema's `cases` property names equal the agent Track's role set exactly, and the `ml` schema holds no role name. Cost: a later `ml` schema that names `train` fails until the test changes.~~
  ~~Source: #120 amendment "The Workload JSON schemas are covered." Owner instruction, rule 4: "the Workload JSON schemas are covered". `agentic/workload.schema.json`, `cases`: "The roles are the Track's (hypotrail.agentic.partitions); a Workload cannot add one."~~
  ~~Witness: rule 4, shown red once on a planted role name in a copy of a schema (2A: a name outside the role set; 2B: also a role removed from the agent schema's `cases`).~~ (settled by Tightened B)

## Tightened (2026-11-21, from D-046)

From [D-046](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064224123) on chadlis/hypotrail#75 (decision by proxy, two readings), which settles this ticket's two `INFERRED` items and the ticket gate's point on the top layer, carries the drive's fix of a line number, and splits #128. D-046 numbers this ticket's second item 9: its option 9B is this ticket's 2B.

- [ ] **A** (`begin` in rule 3). Rule 3 lists `writer_lock`, `require_current` and `writing`, and not `begin`: writers keep calling `begin` just before their first write, through the module's session.
  Source: D-046 item 1: "**`begin`: 1B.** Writers keep calling `begin` just before their first write, through the module's session, and the five calls stay where they are. F2 lists `writer_lock`, `require_current` and `writing`."
  Witness: rule 3, passing at the pull request's head with its three names, and its red on the planted aliased `writer_lock` call (third criterion).
- [ ] **B** (the Workload JSON schemas in rule 4). The test reads both Workload JSON schemas. The property names of the agent schema's `cases` equal the agent Track's role set exactly, and the `ml` schema holds no role name.
  Source: D-046 item 9: "**9B.** The agent schema's `cases` names equal the agent role set exactly, and the `ml` schema holds no role name."
  Witness: rule 4, passing at the pull request's head; shown red once in the builder's hand-back on a role removed from the `cases` of a copy of the agent schema, and once on a role name planted in a copy of the `ml` schema.
- [ ] **C** (the top layer in rule 1). Rule 1 classifies `cli.py`, `__init__.py` and `__main__.py` of `src/hypotrail/` as the top layer, and a top-level module missing from the list fails, as a package does.
  Source: D-046 item 11: "**11A.** `cli.py`, `__init__.py` and `__main__.py` are classified as the top layer."
  Witness: rule 1, shown red once in the builder's hand-back on a planted top-level module missing from the list.
- [ ] **D** (the line the owner instruction cites; replaces a sentence of the first criterion's source). Owner instruction, "Found on the way": "The existing « core imports no Track » test misses relative imports and the subpackages of `core` (`tests/test_repo_rules.py:66` uses `glob`)." At `main` (`18f20c3`) that `glob` is at `tests/test_repo_rules.py:84`.
  Source: D-046, fixed by the drive: "#130's line number is corrected." Sealed drive choice of D-046 on chadlis/hypotrail#75: "It is `tests/test_repo_rules.py:84` at `main`."
  Witness: line 84 of `tests/test_repo_rules.py` at `main` (kept file): `for path in sorted((ROOT / "src" / "hypotrail" / "core").glob("*.py")):`.
- [ ] **E** (rule 3 in "What to build"). Rule 3, F2: `writer_lock`, `require_current` and `writing` are called only from the Study-write module, which #132 adds and #134 completes, aliases resolved.
  Source: D-046 item 13: "#128 splits into three tickets". D-046 item 1: "F2 lists `writer_lock`, `require_current` and `writing`."
  Witness: rule 3 of the third criterion, passing at the pull request's head.


---
_Generated by [Claude Code](https://claude.ai/code)_