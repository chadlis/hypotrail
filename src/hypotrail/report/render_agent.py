"""The sections of the page that differ for a Study of the tool-using agent Track (chadlis/hypotrail#86).

The page, its sections and its rules are those of `hypotrail.report.render`; this module writes what an agent Study has
in their place: the Case by Repeat matrix, the counters and the two named rates per Criterion, the agent Comparisons,
the Configurations with their exact system text, an `llm_live` Attempt's recorded facts and a scenario Attempt's
self-check. Every value is read from a record: nothing is scored, ranked or aggregated here, except counting the Reasons
of the per-Item file. An Inspect log is linked with its SHA-256 and never opened.
"""

import json

from hypotrail.core.agent_comparison import DEVIATIONS
from hypotrail.core.attempts import SCENARIO_MODE
from hypotrail.core import scorers
from hypotrail.core.chinook_contract import CRITERIA
from hypotrail.report import gather_agent
from hypotrail.report.markup import UNKNOWN, Links, Safe, esc, interval, join, json_text, number, paragraph, rescoring_note, scoped, sub, table, tag

LIVE_MODE = "llm_live"
COUNT_KEYS = ("expected", "attempted", "produced", "scored", "correct", "incorrect", "unscored", "errored")
QUALITY = "Quality among the scored (N_correct / N_scored)"
CONFIRMED = "Share of the planned Episodes with a confirmed success (N_correct / N_expected)"
CRITERIA_COLUMNS = ("Criterion", *[f"N_{key}" for key in COUNT_KEYS], QUALITY, CONFIRMED, "Unknowns")
WRAPPED = {"raw_answer": "raw_answer", "embedded_object": "embedded_object (Wrapped answer)", "": "nothing read"}
TRACE_LABELS = {"log": "Trace", "source": "Trace in the import source"}
ABSENT = "trace absent"
# What an `llm_live` Attempt shows beside its Configuration, as the handbook lists it.
LIVE_FIELDS = (
    "Model (requested)",
    "Served model (reported)",
    "Effective limits",
    "Limit note, <name>",
    "Effective parameters",
    "Chinook file SHA-256 before",
    "Chinook file SHA-256 after",
)
SELF_CHECK_HEADING = "Self-check of the scripted scenarios, not an Assessment"
SELF_CHECK_SENTENCE = (
    "The Mode scripted_fixture runs technical scenarios to test the harness. Its statuses and counts are a self-check: "
    "they are not an Assessment, they are never compared, and they measure no system."
)


def cell_lines(criteria: tuple) -> tuple:
    """What one cell of the matrix holds, in order (the handbook lists them for Chinook): one line per Criterion of the Assessment's Scorer between the answer and the trace."""
    return ("Case and Repeat", "Execution", "Answer read from", *criteria, "Trace")


def _text(value) -> str:
    return UNKNOWN if value is None or value == "" else str(value)


def _rate(metric: dict) -> Safe:
    """A rate as recorded; a null is shown null with its Reason, never 0."""
    if metric["value"] is None:
        return esc(f"null (Reason: {metric['reason']})")
    return number(metric["value"])


# --- Protocol, Configurations -----------------------------------------------------------------------------------------


def protocol(model) -> list:
    spec = model["spec"]
    return [
        table(
            "protocol",
            ["Field", "Value"],
            [["Protocol", spec["protocol_id"]], ["Protocol digest", spec["protocol_digest"]], ["Revision", spec["revision"]], ["Previous revision", spec.get("previous_revision") or "none"]],
        ),
        sub("Partitions"),
        table("partitions", ["Partition", "Cases", "Case IDs"], gather_agent.partitions(model), numeric=(1,)),
    ]


def _live_table(manifest: dict, run_record) -> Safe:
    config = manifest["effective_config"]
    databases = (run_record or {}).get("database_sha256") or {}
    rows = [
        ["Model (requested)", _text(config.get("model"))],
        ["Served model (reported)", _text(config.get("served_model"))],
        ["Effective limits", json_text(config["limits"]) if config.get("limits") is not None else UNKNOWN],
        *[[f"Limit note, {name}", _text(note)] for name, note in sorted((config.get("limit_notes") or {}).items())],
        ["Effective parameters", json_text(config["effective_parameters"]) if config.get("effective_parameters") is not None else UNKNOWN],
        ["Chinook file SHA-256 before", _text(databases.get("before"))],
        ["Chinook file SHA-256 after", _text(databases.get("after"))],
    ]
    return table(f"live-{manifest['attempt_id']}", ["Field", "Value"], rows)


def _usage_table(attempt: dict) -> Safe:
    rows = []
    for (case_id, repeat), entry in sorted(attempt["entries"].items()):
        usage = entry.get("usage") or {}
        rows.append([case_id, repeat, number(usage.get("latency_seconds")), number(usage.get("tokens")), number(usage.get("cost"))])
    return table(f"usage-{attempt['manifest']['attempt_id']}", ["Case", "Repeat", "Latency (seconds)", "Tokens", "Cost"], rows, numeric=(1, 2, 3, 4))


def configurations(model) -> list:
    out = []
    for attempt in model["attempts"]:
        manifest = attempt["manifest"]
        configuration = manifest["effective_config"].get("configuration")
        head = tag("p", join([tag("b", "Attempt "), manifest["attempt_id"], f" (Mode {manifest['mode']})"]))
        if isinstance(configuration, dict):
            body = [
                head,
                table(
                    f"configuration-{manifest['attempt_id']}",
                    ["Field", "Value"],
                    [
                        ["Configuration id", configuration.get("id", UNKNOWN)],
                        ["Declared content", json_text(configuration.get("declared"))],
                        ["System text", tag("pre", configuration.get("system_text", UNKNOWN), class_="code")],
                    ],
                ),
            ]
            if manifest["mode"] == LIVE_MODE:
                body += [sub("Recorded by the Attempt"), _live_table(manifest, attempt["run_record"]), sub("Tokens, cost and latency per Episode, as recorded"), _usage_table(attempt)]
        else:
            body = [head, paragraph("An Import: it declares no Configuration. How its outputs were produced is declared or unknown per field, in the origin of the artifacts below.")]
        out.append(scoped(manifest, tag("div", join(body), class_="card"), SCENARIO_MODE))
    return out or [paragraph("No Attempt is recorded.")]


# --- Coverage: the self-check of a scenario Attempt ---------------------------------------------------------------------


def self_checks(model) -> list:
    out = []
    for attempt in model["attempts"]:
        manifest, check = attempt["manifest"], attempt["self_check"]
        if manifest["mode"] != SCENARIO_MODE or not isinstance(check, dict):
            continue
        attempt_id = manifest["attempt_id"]
        counts = check.get("counts") or {}
        tool_errors = check.get("tool_errors") or {}
        out.append(
            scoped(
                manifest,
                join(
                    [
                        sub(f"{SELF_CHECK_HEADING}, Attempt {attempt_id}"),
                        paragraph(SELF_CHECK_SENTENCE),
                        table(
                            f"selfcheck-{attempt_id}",
                            ["Scenario", "Case", "Execution", "Reason"],
                            [[s["scenario_id"], s["case_id"], s["status"], s.get("reason") or "none"] for s in check.get("scenarios", [])],
                        ),
                        table(
                            f"selfcheck-counts-{attempt_id}",
                            ["Criterion", *[f"N_{key}" for key in COUNT_KEYS]],
                            [[name, *[number(counts[name].get(f"N_{key}")) for key in COUNT_KEYS]] for name in CRITERIA if name in counts],
                            numeric=tuple(range(1, 9)),
                        ),
                        paragraph(f"Tool errors in the scenarios: {tool_errors.get('total', 0)}."),
                    ]
                ),
                SCENARIO_MODE,
            )
        )
    return out


# --- Metrics and differences ------------------------------------------------------------------------------------------


def criteria_of(record: dict) -> tuple:
    """The Criteria of the Assessment's Scorer, by its registry entry; those of `chinook_contract_v1` for a Scorer the registry no longer holds."""
    scorer = scorers.REGISTRY.get(record["scorer"]["id"])
    return scorer.criteria if scorer is not None and scorer.criteria else CRITERIA


def _criteria_table(assessment: dict) -> Safe:
    record = assessment["record"]
    primary = record["primary_criterion"]
    rows = []
    for name in criteria_of(record):
        source = {"counts": record["counts"], "metrics": record["metrics"]} if name == primary else assessment["detailed"]["criteria"].get(name)
        if source is None:
            rows.append([name, *[UNKNOWN] * 11])
            continue
        counts, rates = source["counts"], {m["id"]: m for m in source["metrics"]}
        why = gather_agent.non_scores(assessment, name)
        unknowns = f"unscored {counts['unscored']}, errored {counts['errored']}" + (
            "; reasons: " + ", ".join(f"{reason or 'none'} {count}" for reason, count in why.items()) if why else ""
        )
        rows.append([name, *[number(counts[key]) for key in COUNT_KEYS], _rate(rates["quality_among_scored"]), _rate(rates["confirmed_share_of_expected"]), unknowns])
    return table(f"criteria-{record['assessment_id']}", list(CRITERIA_COLUMNS), rows, numeric=tuple(range(1, 9)))


def _comparison(index: int, record: dict, paired) -> Safe:
    delta, coverage, comparability = record["delta"], record["coverage"], record["comparability"]

    def shown(entry) -> Safe:
        if entry["value"] is None:
            return Safe("withheld")  # P3B: only "withheld", the coverage rates beside it, no bounds
        return join([entry["metric"], " ", number(entry["value"]), " ", entry["unit"]])

    codes = [w["code"] for w in record.get("warnings", []) if w["code"] in DEVIATIONS]
    deviations = f", with warning {', '.join(codes)}" if codes else ""
    rows = [
        ["Control Assessment", record["roles"]["control_assessment_id"]],
        ["Candidate Assessment", record["roles"]["candidate_assessment_id"]],
        ["Comparability", comparability["status"] + (" (descriptive)" if comparability["status"] == "descriptive_only" else "") + deviations],
        ["Checks", "; ".join(f"{c['check']}: {'passed' if c['passed'] else 'not passed'}" + (f" ({c['reason']})" if c["reason"] else "") for c in comparability["checks"])],
        ["Coverage", f"expected {coverage['expected']}, Control scored {coverage['control_scored']}, Candidate scored {coverage['candidate_scored']}, paired {coverage['paired']}"],
        ["Coverage rates", join(["Control ", number(coverage.get("control_rate")), ", Candidate ", number(coverage.get("candidate_rate"))])],
        ["Primary Criterion", record.get("primary_criterion", UNKNOWN)],
        ["Delta", shown(delta)],
        ["Interval", interval(record)],
        ["Delta definition", delta["definition"]],
        ["Declared factor", _text(record.get("declared_factor"))],
    ]
    body = [tag("p", join([tag("b", "Comparison "), record["comparison_id"]])), table(f"comparison-{index}", ["Field", "Value"], rows)]
    secondary = record.get("secondary_deltas") or []
    if secondary:
        body += [
            sub("Secondary deltas"),
            table(f"comparison-secondary-{index}", ["Criterion", "Delta"], [[d["metric"], shown(d)] for d in secondary]),
        ]
    if paired is not None:
        body += [
            sub("By Case, as recorded (each Case weighs the same)"),
            table(
                f"comparison-cases-{index}",
                ["Case", "Repeats", "Control share", "Candidate share", "Delta (Candidate minus Control)"],
                [[r["case_id"], r["repeats"], *[number(float(r[key])) for key in ("control_share", "candidate_share", "delta_share")]] for r in paired],
                numeric=(1, 2, 3, 4),
            ),
        ]
    rates = record.get("rates") or {}
    rate_rows = []
    for side in ("control", "candidate"):
        for metric in (rates.get(side) or {}).get("metrics", []):
            unknowns = (rates[side].get("unknowns") or {})
            rate_rows.append([side, metric["id"], _rate(metric), number(metric["denominator"]), f"unscored {number(unknowns.get('unscored'))}, errored {number(unknowns.get('errored'))}"])
    if rate_rows:
        body += [sub("The two named rates of each side"), table(f"comparison-rates-{index}", ["Side", "Rate", "Value", "Denominator", "Unknowns"], rate_rows, numeric=(3,))]
    descriptive = record.get("descriptive")
    if descriptive:
        measures = ("latency_seconds", "model_calls", "tool_calls", "tokens", "cost")
        body += [
            sub("Descriptive measures (no Criterion rests on them)"),
            table(f"comparison-descriptive-{index}", ["Side", *measures], [[side, *[number(descriptive[side].get(m)) for m in measures]] for side in ("control", "candidate")]),
        ]
    settings = record.get("settings")
    if settings:
        body += [
            sub(f"Declared settings (Control {settings['control']}, Candidate {settings['candidate']}; no check reads them)"),
            table(
                f"comparison-settings-{index}",
                ["Key", "Control", "Candidate", "State"],
                [[entry["key"], json_text(entry["control"]), json_text(entry["candidate"]), entry["state"]] for entry in settings["keys"]],
            ),
        ]
    for warning in record.get("warnings", []):
        body.append(tag("div", join([tag("b", f"Warning {warning['code']}. "), warning["message"]]), class_="note"))
    return tag("div", join(body), class_="card")


def metrics(model) -> list:
    out = []
    for index, assessment in enumerate(model["assessments"]):
        r = assessment["record"]
        rows = [
            ["Primary Criterion", r["primary_criterion"]],
            ["Scorer", f"{r['scorer']['id']} {r['scorer']['version']}"],
            ["Revision", number((r.get("study_revision") or {}).get("number"))],
            ["References set", r["references_ref"]["sha256"]],
        ]
        body = [tag("p", join([tag("b", "Assessment "), r["assessment_id"]])), table(f"assessment-{index}", ["Field", "Value"], rows)]
        if r.get("rescoring"):
            body.append(rescoring_note(r["rescoring"]))
        body += [sub(f"Counters and the two named rates per Criterion, Assessment {r['assessment_id']}"), _criteria_table(assessment)]
        out.append(tag("div", join(body), class_="card"))
    out.append(sub("Comparisons"))
    if not model["comparisons"]:
        out.append(paragraph("No Comparison is recorded."))
    for index, record in enumerate(model["comparisons"]):
        out.append(_comparison(index, record, model["paired"][record["comparison_id"]]))
    return out


# --- Individual errors: the matrix and the answers ---------------------------------------------------------------------


def _execution(status: str, entry) -> str:
    return "produced" if status == "produced" else f"{status} (Reason: {(entry or {}).get('reason') or UNKNOWN})"


def _cell(case_id: str, repeat: int, episode: dict, entry, trace, links: Links, criteria: tuple) -> Safe:
    lines = [f"Case {case_id}, Repeat {repeat}", f"Execution: {_execution(episode['status'], entry)}"]
    if episode["status"] == "produced" and episode["answer_given_as"]:
        read = episode["answer_read_from"]
        lines.append(f"Answer read from: {WRAPPED.get(read, read)}")
    for name in criteria:
        row = episode["criteria"].get(name)
        if row is None:
            lines.append(f"{name}: not recorded")
        elif row["state"] == "scored":
            lines.append(f"{name}: {row['score']}" + (f" (Reason: {row['reason']})" if row["reason"] else ""))
        else:  # an Instrument failure: never held against the evaluated system
            lines.append(f"{name}: {row['state']} (Reason: {row['reason'] or UNKNOWN}), Instrument failure")
    shown = [tag("div", line) for line in lines]
    if trace is not None and isinstance((entry or {}).get("trace"), list):
        ref = trace["ref"]
        shown.append(tag("div", join([f"{TRACE_LABELS[trace['kind']]}: ", links.file(ref["path"]), f", SHA-256 {ref['sha256']}"])))
    else:
        shown.append(tag("div", f"Trace: {ABSENT}"))
    return join(shown)


def _matrix(assessment: dict, links: Links) -> Safe:
    episodes = gather_agent.episodes(assessment)
    attempt = assessment["attempt"]
    entries, trace = (attempt["entries"], attempt["trace"]) if attempt is not None else ({}, None)
    cases = sorted({case for case, _ in episodes})
    repeats = sorted({repeat for _, repeat in episodes})
    criteria = criteria_of(assessment["record"])
    rows = [
        [case, *[_cell(case, r, episodes[(case, r)], entries.get((case, r)), trace, links, criteria) if (case, r) in episodes else "not planned" for r in repeats]]
        for case in cases
    ]
    return table(f"matrix-{assessment['record']['assessment_id']}", ["Case", *[f"Repeat {r}" for r in repeats]], rows)


def _answer(entry: dict) -> str:
    given = entry.get("answer_given_as")
    if given == "raw_answer":
        return entry.get("raw_answer") or ""
    if given == "final_answer":
        return json.dumps(entry.get("final_answer"), sort_keys=True, ensure_ascii=False)
    return "no answer"


def _answers(attempt: dict) -> Safe | None:
    manifest = attempt["manifest"]
    if not attempt["entries"]:
        return None
    scenario = manifest["mode"] == SCENARIO_MODE
    rows = [
        [case_id, repeat, _execution(entry["status"], entry), entry.get("answer_given_as") or "none", tag("pre", _answer(entry), class_="code")]
        for (case_id, repeat), entry in sorted(attempt["entries"].items())
    ]
    heading = f"{'Scenario final answers' if scenario else 'Answers'}, Attempt {manifest['attempt_id']} (shown as text, never interpreted)"
    return scoped(
        manifest,
        join([sub(heading), table(f"answers-{manifest['attempt_id']}", ["Case", "Repeat", "Execution", "Answer given as", "Answer"], rows, numeric=(1,))]),
        SCENARIO_MODE,
    )


def errors(model, links: Links) -> list:
    out = []
    for assessment in model["assessments"]:
        out += [sub(f"Case by Repeat matrix, Assessment {assessment['record']['assessment_id']}"), _matrix(assessment, links)]
    if not model["assessments"]:
        out.append(paragraph("No Assessment is recorded, so no matrix is shown."))
    out += [block for block in (_answers(attempt) for attempt in model["attempts"]) if block is not None]
    return out
