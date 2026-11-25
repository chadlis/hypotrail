# L2 acceptance grid

L2 is the review decision of chadlis/hypotrail#103: a Study's pending decision, its evidence and the Decision recorded through the CLI, from the VS Code panel and from the chat clients. This grid lists every acceptance criterion of L2 with who checks it: a test, the owner, or an engineer who did not implement it.

## Status

L2 is "built, not demonstrated". Who lifts that status is in chadlis/hypotrail#103, "End state", from D-077 on chadlis/hypotrail#75, Q9:

> The owner's demonstration lifts "built, not demonstrated", and the owner lifts it.

This grid holds no result of that demonstration: its owner checks are listed, none of them is marked here.

chadlis/hypotrail#103 also says under "End state":

> "Usable" waits for an engineer who did not implement it.

The owner's demonstration does not make L2 usable.

P2A is not in this grid: it is deferred (chadlis/hypotrail#103, "Acceptance"; D-077 on chadlis/hypotrail#75, Q8).

No picture of the panel was made on the demonstration's Study: the tool that draws the panel outside VS Code draws it only from the saved outputs of `status --json` that the client's tests use, never from a live Study, so no picture of a task stands in for the owner's view in VS Code (the drive's answers on chadlis/hypotrail#204, comment 7159599569, Q3).

## Criteria

Each row quotes the criterion and its "Checked" column from the table "Acceptance" of chadlis/hypotrail#103. A pytest test is named by its node id; a test of the VS Code client by its file under `clients/vscode/test/` and its title, as `npm test` in `clients/vscode/` runs it.

| Id | Criterion, quoted from chadlis/hypotrail#103, with its "Checked" column | Automated | Owner |
|---|---|---|---|
| D1 | "That decision distinguishes "evidence rescored" from "result changed"", with the third state and the guard of D-077, Q3. Checked: "CLI tests, the guard's sequence included ("L2.3 tests the guard's sequence"); panel assertion" | `tests/test_evidence_change.py::test_the_line_state_of_each_row_of_the_matrix_follows_the_later_assessment_and_the_guard`; `tests/test_evidence_change.py::test_the_state_of_the_decision_is_the_strongest_state_of_its_lines`; `clients/vscode/test/panel-decisions.test.ts`: "the phrases of contract.json name the three states the core computes, the strongest first" | none |
| D2 | "shows the Assessments a Comparison depends on". Checked: "CLI test; panel assertion" | `tests/test_pending_decisions.py::test_the_pending_comparisons_of_a_bike_study_are_those_for_which_the_three_conditions_hold`; `tests/test_pending_decisions.py::test_with_no_roles_in_the_comparison_record_the_entry_names_the_left_and_right_assessments`; `clients/vscode/test/panel-content.test.ts`: "the Assessment shown as the Control is the read's control_assessment_id, when the two ids are exchanged" | none |
| C1 | "decide from the panel in two actions". Checked: "Unit test on the panel's message flow; owner in VS Code" | `clients/vscode/test/panel-write.test.ts`: "two messages of the second action before the answer give one decide call, and the document assigned meanwhile holds the line of a write in flight"; `clients/vscode/test/panel-write.test.ts`: "the handlers of the panel's messages are the entries of messages of contract.json, both ways" | owner check, final review: task 3 in VS Code, the answer recorded in two actions |
| C2 | "at 420 px the question within 200 px and the first evidence number within 350 px of the top". Checked: "Owner in VS Code (acceptance); headless Chrome on the panel HTML as a regression guard only (D-031, item 14)" | regression guard only: `clients/vscode/test/panel-layout.test.ts`: "at the width of guard_bounds, the first question and the first evidence number of status-success are within their bounds of the top" | owner check, final review: the panel narrowed to 420 px in VS Code |
| C3 | "one panel configuration, no stages". Checked: "HTML assertion" | `clients/vscode/test/panel-documents.test.ts`: "no tag holds a hidden attribute or opens a details element, and the script holds none of the words of a stage: ${name}" | none |
| C4 | "no hard-coded colour, every surface and text colour from `--vscode-*`, AA contrast and visible focus in the four VS Code themes". Checked: "CSS assertion (no literal colour); contrast and focus: owner" | `clients/vscode/test/panel-style.test.ts`: "the style of the document holds no literal colour of the form ${form}"; `clients/vscode/test/panel-style.test.ts`: "the style sets the color and the background of body from theme variables of VS Code" | owner check, final review: contrast and visible focus in Light, Dark, High Contrast and High Contrast Light |
| C5 | "every number on screen links to its artifact, ids and statuses equal to `status --json`". Checked: "Test against a fixture Study's `status --json`" | `tests/test_vscode_client.py::test_each_kept_status_read_whose_ok_is_true_is_the_clis_own_once_its_values_are_replaced_and_the_four_rules_applied`; `clients/vscode/test/panel-links.test.ts`: "every number is in a link to the part of its record, each link names one element, and each id is the read's: ${name}"; `clients/vscode/test/panel-links.test.ts`: "each status is shown as its key and the value the read holds, each changed in the test to another value of its kind: ${name}" | none |
| C6 | "client under 3,000 lines". Checked: "Line-count test (D-031, item 11)"; the bound is 5,000 lines since its owner amended it (chapter 18 of the handbook) | `tests/test_client_line_budget.py::test_the_client_is_within_its_line_budget` | none |
| C7 | "every option shows its consequence". Checked: "HTML assertion per option, on the consequence texts of the core (D-077, Q7)" | `clients/vscode/test/panel-content.test.ts`: "each option shows its text and its consequence, each whole in a marked element: ${name}"; `clients/vscode/test/panel-content.test.ts`: "on a read whose question, options and consequences are replaced, the document shows the replaced texts, whole" | none |
| C8 | "the same decision recorded through the same CLI command from Copilot chat and from Claude Code, a rule-based answer recorded as a proxy decision". Checked: "Claude Code path: automated; Copilot path: owner, in the "also check" section of the teaching page (D-077, Q11)" | Claude Code path: `tests/test_claude_code_hook.py::test_a_proxy_decision_recorded_as_the_rule_says_is_listed_with_its_source_and_named_by_the_next_prompt` | owner check, final review: the Copilot path, in the "also check" section |
| C9 | "the kept invariants of the old companion (CLI client without own state, strict CSP, `execFile` without a shell, request id on every write, refusals verbatim, deep links) stay tested". Checked: "Unit tests, one per invariant" | without own state and `execFile` without a shell: `tests/test_vscode_client.py::test_only_the_bridge_starts_a_process_and_only_through_execfile_and_no_source_keeps_state_writes_a_file_or_reads_study_json`; strict CSP: `clients/vscode/test/panel.test.ts`: "the document holds one policy of the nine directives with a nonce for each document, and no script or style without it"; request id on every write: `clients/vscode/test/bridge-write.test.ts`: "a write with no id after a write that had one is still a client_refusal: the bridge holds no id"; refusals verbatim: `clients/vscode/test/bridge-write.test.ts`: "the refusal ${name} is given back as the CLI printed it"; deep links: `clients/vscode/test/links.test.ts`: "the two forms of contract.json are the ones the handler accepts" | none |
| C10 | "after a decision recorded in the panel, the next chat turn knows it (Claude Code: a `UserPromptSubmit` hook calling `status --since`, tested automatically; Copilot: an extension or MCP tool plus `.github/copilot-instructions.md`, checked by the owner at the final review), with S1's refusal of a write made on an older Study revision as the backstop". Checked: "Hook: automated; Copilot: owner, in the "also check" section (D-077, Q11)" | hook: `tests/test_claude_code_hook.py::test_after_a_decision_recorded_as_the_panel_records_it_the_next_prompt_of_a_new_session_names_it_and_no_longer_its_pending_decision` | owner check, final review: Copilot, in the "also check" section |
| S1 | "a write made on an older revision is refused with a code that names what changed; agent instructions require reading the Study state at the start of each turn". Checked: "Refusal: delivered by L2.1 (`STUDY_CHANGED`). Agent instructions: L2.2 and L2.6" | refusal: `tests/test_stale_sequence.py::test_given_and_older_the_command_is_refused_with_study_changed_naming_the_writes_since_and_writes_nothing`; agent instructions: `tests/test_handbook.py::test_the_hook_rule_and_the_copilot_template_each_name_the_four_requirements` | none |
| P3B | When CMP-05 withholds the main delta, only "withheld" is shown, with no bounds (#1 comment 7043566976, P3B). Checked: "Panel assertion "on a fixture with a withheld delta" (D-077, Q8)" | `clients/vscode/test/panel-withheld.test.ts`: "status-chinook-withheld: the word stands once for each Comparison whose main delta value is null, and no secondary delta is shown" | none |

## Owner checks

What the drive cannot verify before publishing (chadlis/hypotrail#103, comment 7092994773): the owner checks it at the final review. None is marked here.

| What the drive cannot verify | Check |
|---|---|
| A3: the extension built and installed, visible in VS Code | owner check, final review |
| A6: the panel opened on the demonstration's Study, its Study id and Write sequence equal to `status --json` | owner check, final review |
| Tasks 1 to 6 as seen in the panel | owner check, final review |
| The Copilot checks (C8 and C10 from Copilot chat) | owner check, final review |
| C2: at 420 px, the question and the first evidence number within their bounds of the top | owner check, final review |
| C4: contrast and visible focus in the four VS Code themes | owner check, final review |

## Engineer checks

"Usable" is checked by an engineer who did not implement L2, after the owner's demonstration. None is marked here.

| Sentence, quoted | Source | Check |
|---|---|---|
| "One engineer who did not implement the slice can identify the pending decision, inspect its evidence, record an answer and recover it in a fresh session." | `docs/product/ROADMAP.md`, "Demonstration before calling L2 usable" | engineer check, open |
| "The view shows a real limitation and an outdated conclusion when its supporting evidence changes." | `docs/product/ROADMAP.md`, "Demonstration before calling L2 usable" | engineer check, open |
| "It agrees with the CLI on artifact identities and status." | `docs/product/ROADMAP.md`, "Demonstration before calling L2 usable" | engineer check, open |
| "Direct evaluation remains usable without the workflow." | `docs/product/ROADMAP.md`, "Demonstration before calling L2 usable" | engineer check, open |
| "Do not infer validated usability from screenshots or automated tests alone." | `docs/product/ROADMAP.md`, "Demonstration before calling L2 usable" | engineer check, open |
| ""Usable" waits for an engineer who did not implement it." | chadlis/hypotrail#103, "End state" | engineer check, open |
