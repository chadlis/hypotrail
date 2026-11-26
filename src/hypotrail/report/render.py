"""The page: one HTML document, its text, styles and tables inline, in English, in light mode (SPEC §9, chadlis/hypotrail#85).

Safe by construction: every value goes through `cell`, which HTML-escapes anything that is not already `Safe` (the
fragments this module builds itself), in text and in attributes. A string that comes from outside the code is never
turned into a link or a resource: the only `href` is a relative path to a Study artifact. The page holds no script,
loads nothing and computes nothing when it is opened.
"""

from hypotrail.report import gather
from hypotrail.report import render_agent
from hypotrail.report.markup import Links, Row, Safe, UNKNOWN, cell, esc, interval, join, json_block, number, paragraph, rescoring_note, scoped, sub, table, tag
from hypotrail.core.attempts import SCENARIO_BANNER, SCENARIO_MODE
from hypotrail.core.comparison import DEVIATIONS

# The sections of SPEC §9 in their order (id, heading), then the Exposure section the ticket adds. The handbook lists them.
SECTIONS = (
    ("question-mode", "Question and Mode"),
    ("data-licences", "Data and licences"),
    ("protocol-partitions", "Protocol and Partitions"),
    ("configurations", "Configurations compared"),
    ("coverage-statuses", "Coverage and statuses"),
    ("metrics-differences", "Metrics and differences"),
    ("individual-errors", "Individual errors"),
    ("limits", "Limits"),
    ("artifact-origin", "Origin of the artifacts"),
    ("exposure", "Exposure"),
)
DELTA_SENTENCE = "A positive delta means the Candidate is worse: the delta is the Metric of the Candidate minus the Metric of the Control, and the Metric is lower-is-better."
DENIAL = "This report does not state that any output, Configuration or Study is production-ready, safe or independent."
CHARTER_STYLE = """
:root{--bg:#FFFCF7;--bg2:#F4EEE4;--ink:#15111C;--ink2:#3E3749;--faint:#7A7187;--line:rgba(21,17,28,.10);--line2:rgba(21,17,28,.20);
--gold:#9C7633;--pink:#C2306D;--green:#4E8A25;--teal:#21806F;--violet:#8A4FA6;--sky:#2F64A3;--coral:#C9500F;--amber:#A86E1E;--paper:#FFFFFF;
--serif:'Fraunces',Georgia,serif;--sans:'Jost','Avenir Next',Avenir,'Segoe UI',sans-serif;--mono:'JetBrains Mono',ui-monospace,Menlo,monospace;--pad:56px;--maxw:1120px}
*{box-sizing:border-box}
html,body{margin:0;background:#EDE6DA;overflow-x:hidden}
body{font:300 16px/1.6 var(--sans);color:var(--ink);overflow-wrap:break-word}
b{font-weight:500;color:var(--ink)}
.hero,section,footer{--g:max(var(--pad),calc((100% - var(--maxw)) / 2));padding-left:var(--g);padding-right:var(--g)}
.hero{padding-top:56px;padding-bottom:44px;border-bottom:1px solid var(--line);background:radial-gradient(60% 85% at 92% 0%,rgba(232,168,87,.30),transparent 62%),radial-gradient(45% 70% at 0% 100%,rgba(192,139,214,.16),transparent 65%),linear-gradient(180deg,#FFFDF9,#F6EFE3)}
.org{font:500 12px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;color:var(--ink2);margin:0 0 40px}
.org b{color:var(--gold)}
.kick{font:500 12px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;color:var(--gold);margin:0 0 14px}
.hero h1{font:560 clamp(28px,5.4vw,44px)/1.1 var(--serif);margin:0 0 14px;max-width:24ch}
.hero .sub{font-size:18px;color:var(--ink2);max-width:60ch;margin:0}
section{position:relative;padding-top:48px;padding-bottom:52px;border-bottom:1px solid var(--line);background:radial-gradient(60% 80% at 100% 0%,color-mix(in srgb,var(--ac) 11%,transparent),transparent 60%),var(--bg)}
.sh{display:flex;align-items:baseline;gap:22px;margin:0 0 22px}
.sh .n{font:italic 450 clamp(42px,8vw,64px)/.9 var(--serif);color:transparent;-webkit-text-stroke:1.2px var(--ac)}
.sh .k{font:500 11.5px/1 var(--sans);letter-spacing:.3em;text-transform:uppercase;color:var(--ac);margin:0 0 8px}
.sh h2{font:560 clamp(21px,3.6vw,28px)/1.15 var(--serif);margin:0}
.sub2{font:500 11.5px/1 var(--sans);letter-spacing:.24em;text-transform:uppercase;color:var(--faint);margin:28px 0 12px}
p{color:var(--ink2);margin:0 0 14px;max-width:80ch}
.lead{font-size:17px}
.card{background:var(--paper);border:1px solid var(--line2);box-shadow:inset 3px 0 0 var(--ac),0 10px 24px -18px rgba(60,40,20,.35);padding:14px 18px 14px 20px;margin:0 0 14px;font-size:15px;color:var(--ink2)}
.note{margin-top:18px;padding:12px 16px;border:1px dashed var(--line2);font-size:14.5px;color:var(--ink2)}
code,.mono{font:400 .88em/1.4 var(--mono)}
code{background:var(--bg2);border:1px solid var(--line);padding:1px 6px;border-radius:4px;color:var(--ink)}
pre.code{margin:0;padding:10px 14px;background:var(--paper);border:1px solid var(--line2);font:400 12.5px/1.5 var(--mono);color:var(--ink);overflow-x:auto;white-space:pre-wrap}
.tblwrap{overflow-x:auto;margin:14px 0 0;border:1px solid var(--line2);background:var(--paper)}
.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th{font:500 11px/1.2 var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--ac);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line2);white-space:nowrap}
.tbl td{padding:9px 12px;border-top:1px solid var(--line);color:var(--ink2);vertical-align:top}
.tbl tr:first-child td{border-top:0}
.banner{margin:0;padding:18px var(--pad);background:var(--bg2);border-bottom:2px solid var(--coral)}
.banner p{margin:0 0 4px;color:var(--ink)}
.num{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--sky)}
footer{padding-top:24px;padding-bottom:24px;background:var(--bg);font-size:13px;color:var(--faint)}
@media (max-width:640px){:root{--pad:20px}.hero{padding-top:30px}section{padding-top:28px;padding-bottom:30px}.sh{gap:14px}}
@media print{section,.hero{break-inside:avoid-page}}
"""
ACCENTS = ("gold", "teal", "violet", "sky", "green", "pink", "amber", "coral", "gold", "teal")


def _section(index: int, section_id: str, heading: str, body) -> Safe:
    head = tag(
        "div",
        join([tag("div", f"{index:02d}", class_="n"), tag("div", join([tag("p", "Report", class_="k"), tag("h2", heading)]))]),
        class_="sh",
    )
    return tag("section", join([head, *body]), id=section_id, style=f"--ac:var(--{ACCENTS[index - 1]})")


def _status(text) -> Safe:
    return esc(text)


# --- the sections ---------------------------------------------------------------------------------------------------


def _question(model) -> list:
    spec = model["spec"]
    modes = sorted({a["manifest"]["mode"] for a in model["attempts"]})
    metric = spec["primary_metric"]
    return [
        tag("p", "The question the Study asks, as its Workload declares it.", class_="lead"),
        tag("div", join([tag("p", join([tag("b", "Question. "), spec["question"]])), tag("p", join([tag("b", "Objective. "), spec["objective"]]))]), class_="card"),
        table(
            "study-identity",
            ["Field", "Value"],
            [
                ["Study", spec["study_id"]],
                ["Workload", spec["workload"]],
                ["Track (domain)", spec["domain"]],
                ["Primary Metric", f"{metric['id']}, {metric['unit']}, {metric['direction']}"],
                ["Revision", f"{model['revision_number']}"],
                ["Modes of the Attempts", ", ".join(modes) if modes else "no Attempt recorded"],
            ],
        ),
    ]


def _data(model) -> list:
    spec = model["spec"]
    rows = [[ref["role"], ref["path"], ref["sha256"], ref["size_bytes"]] for ref in spec["dataset_refs"]]
    notices = sorted({a["licence_notice"] for a in model["attempts"] if a["licence_notice"]})
    return [
        paragraph("The dataset is a copy the Study keeps, referenced by its SHA-256."),
        table("data-files", ["Role", "Path", "SHA-256", "Bytes"], rows, numeric=(3,)),
        paragraph(
            "The licence notice and the attribution of the dataset stay with the Workload, not in the Study: this report reads the Study alone and shows no notice text."
        ),
        paragraph("Licence notice file named by the Workload: " + (", ".join(notices) if notices else "not recorded by this Study") + "."),
    ]


def _protocol(model) -> list:
    spec = model["spec"]
    return [
        table(
            "protocol",
            ["Field", "Value"],
            [["Protocol", spec["protocol_id"]], ["Protocol digest", spec["protocol_digest"]], ["Revision", spec["revision"]], ["Previous revision", spec.get("previous_revision") or "none"]],
        ),
        sub("Partitions"),
        table("partitions", ["Partition", "Items", "First date", "Last date"], gather.partitions(model), numeric=(1,)),
    ]


def _configurations(model) -> list:
    out = []
    for a in model["attempts"]:
        manifest = a["manifest"]
        configuration = manifest["effective_config"].get("configuration")
        if isinstance(configuration, dict):
            body = join([tag("p", join([tag("b", "Configuration "), configuration.get("id", UNKNOWN)])), json_block(configuration.get("declared"))])
        else:
            body = paragraph("An Import: it declares no Configuration. How its outputs were produced is declared or unknown per field, in the origin of the artifacts below.")
        out.append(tag("div", join([tag("p", join([tag("b", "Attempt "), manifest["attempt_id"], f" (Mode {manifest['mode']})"])), body]), class_="card"))
    return out or [paragraph("No Attempt is recorded.")]


def _attempts(model) -> list:
    rows = []
    for a in model["attempts"]:
        m = a["manifest"]
        counts = m.get("item_counts")
        rows.append(
            Row(
                [
                m["attempt_id"],
                m["mode"],
                _status(m["technical_status"]),
                m["request_id"],
                "yes" if m["outcome_unknown"] else "no",
                number(counts["produced"] if counts else None),
                number(counts["failed"] if counts else None),
                number(counts["missing"] if counts else None),
                m.get("reason") or "none",
                ],
                **({"data_attempt_id": m["attempt_id"]} if m["mode"] == SCENARIO_MODE else {}),
            )
        )
    return rows


def _coverage(model) -> list:
    out = [
        sub("Attempts and their Observation sets"),
        table(
            "attempts",
            ["Attempt", "Mode", "Technical status", "request_id", "Outcome unknown", "Produced", "Failed", "Missing", "Reason"],
            _attempts(model),
            numeric=(5, 6, 7),
        ),
        paragraph("An Attempt that is running is shown as running, whether or not a writer is alive; an interrupted one is shown as interrupted. A null count is shown as unknown, never as 0."),
    ]
    rows = []
    for a in model["assessments"]:
        r, c = a["record"], a["record"]["counts"]
        rows.append(
            [r["assessment_id"], r["observation_set_id"], f"{r['scorer']['id']} {r['scorer']['version']}"]
            + [number(c[k]) for k in ("expected", "attempted", "produced", "scored", "unscored", "errored", "correct", "incorrect")]
        )
    out += [
        sub("Assessments"),
        table(
            "assessments",
            ["Assessment", "Observation set", "Scorer", "Expected", "Attempted", "Produced", "Scored", "Unscored", "Errored", "Correct", "Incorrect"],
            rows,
            numeric=tuple(range(3, 11)),
        )
        if rows
        else paragraph("No Assessment is recorded."),
    ]
    reason_rows = [[a["record"]["assessment_id"], *[(x if x is not None else "none") for x in entry[:3]], number(entry[3])] for a in model["assessments"] for entry in gather.reasons(a)]
    if reason_rows:
        out += [sub("Criteria, states and Reasons"), table("reasons", ["Assessment", "Criterion", "State", "Reason", "Items"], reason_rows, numeric=(4,))]
    return out + (render_agent.self_checks(model) if model["domain"] == gather.AGENTIC else [])


def _single_feature_check(record, unit) -> str:
    """The state of an Assessment's single-feature check: the features that beat it, checked with none that does, or not checked."""
    check = record.get("single_feature_check")
    if check is None:
        return "not checked"
    if not check["beating"]:
        return "checked: no declared lag feature beats this Assessment"
    return "beaten by " + "; ".join(f"{entry['feature']} {number(entry['value'])} {unit}" for entry in check["beating"])


def _metrics(model) -> list:
    out = []
    memberships = model["memberships"]
    for index, a in enumerate(model["assessments"]):
        r = a["record"]
        metric = r["metrics"][0]
        revision = r.get("study_revision") or {}
        rows = [
            ["Metric", metric["id"]],
            ["Value", join([number(metric["value"]), f" {metric['unit']}" if metric["value"] is not None else ""])],
            ["Single-feature check", _single_feature_check(r, metric["unit"])],
            ["Direction", metric["direction"]],
            ["Denominator", number(metric["denominator"])],
            ["Status", metric["status"]],
            ["Reason", metric.get("reason") or "none"],
            ["Revision", number(revision.get("number"))],
            ["References set", join([r["references_ref"]["sha256"]])],
        ]
        body = [tag("p", join([tag("b", "Assessment "), r["assessment_id"]])), table(f"assessment-{index}", ["Field", "Value"], rows)]
        if r.get("rescoring"):
            body.append(rescoring_note(r["rescoring"]))
        body += [
            sub(f"By month, Assessment {r['assessment_id']}"),
            table(
                f"monthly-{index}",
                ["Month", "Items", "Scored", "Mean absolute error"],
                [[month or UNKNOWN, number(items), number(scored), number(mean)] for month, items, scored, mean in gather.monthly(a, memberships)],
                numeric=(1, 2, 3),
            ),
        ]
        out.append(tag("div", join(body), class_="card"))
    out.append(sub("Comparisons"))
    out.append(paragraph(DELTA_SENTENCE))
    if not model["comparisons"]:
        out.append(paragraph("No Comparison is recorded."))
    for index, c in enumerate(model["comparisons"]):
        delta, coverage, comparability = c["delta"], c["coverage"], c["comparability"]
        codes = [w["code"] for w in c.get("warnings", []) if w["code"] in DEVIATIONS]
        rows = [
            ["Control Assessment", c["roles"]["control_assessment_id"]],
            ["Candidate Assessment", c["roles"]["candidate_assessment_id"]],
            ["Comparability", comparability["status"] + (" (descriptive)" if c.get("descriptive") or comparability["status"] == "descriptive_only" else "") + (f", with warning {', '.join(codes)}" if codes else "")],
            ["Coverage", f"expected {c['coverage']['expected']}, Control scored {coverage['control_scored']}, Candidate scored {coverage['candidate_scored']}, paired {coverage['paired']}"],
            ["Delta", join([delta["metric"], " ", number(delta["value"]), f" {delta['unit']}" if delta["value"] is not None else "", f" ({delta['reason']})" if delta.get("reason") else ""])],
            ["Interval", interval(c)],
        ]
        body = [tag("p", join([tag("b", "Comparison "), c["comparison_id"]])), table(f"comparison-{index}", ["Field", "Value"], rows)]
        for warning in c.get("warnings", []):
            body.append(tag("div", join([tag("b", f"Warning {warning['code']}. "), warning["message"]]), class_="note"))
        out.append(tag("div", join(body), class_="card"))
    return out


def _errors(model, links) -> list:
    out = []
    for index, a in enumerate(model["assessments"]):
        r = a["record"]
        attempt_id = a["attempt"]["manifest"]["attempt_id"] if a["attempt"] else UNKNOWN
        rows = [
            [
                str(rank),
                e["date"] or UNKNOWN,
                e["row_id"],
                number(e["y_true"]),
                number(e["y_pred"]),
                number(e["difference"]),
                number(e["abs_error"]),
                attempt_id,
                r["assessment_id"],
                links.file(r["per_item_ref"]["path"], "per_item.csv"),
                r["per_item_ref"]["sha256"],
            ]
            for rank, e in enumerate(gather.largest_errors(a, model["memberships"]), 1)
        ]
        out += [
            sub(f"Ten largest absolute errors, Assessment {r['assessment_id']}"),
            table(
                f"largest-errors-{index}",
                ["Rank", "Date", "Item", "True", "Predicted", "Difference (predicted minus true)", "Absolute error", "Attempt", "Assessment", "Per-Item file", "SHA-256 of the file"],
                rows,
                numeric=(3, 4, 5, 6),
            )
            if rows
            else paragraph("No Item of this Assessment is scored."),
        ]
    return out or [paragraph("No Assessment is recorded, so no individual error is shown.")]


def _limits(model) -> list:
    items = [("Study", t) for t in model["spec"]["limitations"]]
    items += [(f"Assessment {a['record']['assessment_id']}", t) for a in model["assessments"] for t in a["record"]["limitations"]]
    items += [(f"Comparison {c['comparison_id']}", t) for c in model["comparisons"] for t in c["limitations"]]
    return [table("limitations", ["Recorded by", "Limitation"], items), tag("p", DENIAL, class_="note")]


def _origin(model, links) -> list:
    def rows_of(refs):
        return [[links.artifact(ref), ref["sha256"], number(ref["size_bytes"]), ref["role"]] for ref in refs]

    headers = ["Path", "SHA-256", "Bytes", "Role"]
    spec = model["spec"]
    out = [sub("Study artifacts"), table("study-artifacts", headers, rows_of([*spec["dataset_refs"], *(e["ref"] for e in spec["artifacts"])]), numeric=(2,))]
    for index, a in enumerate(model["attempts"]):
        m = a["manifest"]
        refs = list(m.get("output_refs", []))
        block = [sub(f"Attempt {m['attempt_id']}")]
        block.append(table(f"attempt-artifacts-{index}", headers, rows_of(refs), numeric=(2,)) if refs else paragraph("This Attempt lists no output artifact."))
        producer = m["effective_config"].get("producer")
        if isinstance(producer, dict):
            block.append(
                table(
                    f"producer-{index}",
                    ["Producer field", "Value", "Origin"],
                    [[field, entry["value"] if entry["value"] is not None else UNKNOWN, entry["origin"]] for field, entry in sorted(producer.items())],
                )
            )
        declared = m["effective_config"].get("log")
        if isinstance(declared, dict):  # what an Inspect log declares of its execution, kept by an Import of the log
            block.append(
                table(
                    f"log-{index}",
                    ["Log field", "Value", "Origin"],
                    [[field, entry["value"] if entry["value"] is not None else UNKNOWN, entry["origin"]] for field, entry in sorted(declared.items())],
                )
            )
        out.append(scoped(m, join(block), SCENARIO_MODE))
    records = [a["record"] for a in model["assessments"]]
    files = [r["per_item_ref"] for r in records] + [r["detailed_metrics_ref"] for r in records if r.get("detailed_metrics_ref")]
    files += [ref for c in model["comparisons"] for ref in (c["population_ref"], c.get("paired_deltas_ref"), c.get("matrix_ref")) if ref]
    if files:
        out += [sub("Assessment and Comparison files"), table("record-artifacts", headers, rows_of(files), numeric=(2,))]
    return out


def _exposure(model, recorded) -> list:
    summary = model["exposure"]
    out = [
        paragraph(f"Exposures recorded in this Study: {summary['recorded_in_this_study']}."),
        paragraph(summary["statement"]),
    ]
    if recorded:
        out.append(paragraph(f"This report shows public_check Items: it is an Exposure, recorded as journal entry {recorded['entry_id']}, and the count above includes it."))
    else:
        out.append(paragraph("This report shows no public_check Item and recorded no Exposure."))
    entries = [
        [e["entry_id"], e["recorded_at"], ", ".join(e["attempt_ids"]) or "none", ", ".join(e["assessment_ids"]) or "none", ", ".join(e["comparison_ids"]) or "none"]
        for e in summary["entries"]
    ]
    out.append(table("journal", ["Entry", "Recorded at", "Attempts", "Assessments", "Comparisons"], entries) if entries else paragraph("The journal holds no entry."))
    marks = [[m["kind"], m["id"]] for m in summary["check_informed"]]
    out.append(sub("check_informed"))
    out.append(table("check-informed", ["Kind", "ID"], marks) if marks else paragraph("No Attempt, Assessment, Comparison or revision is marked check_informed."))
    return out


def render(model: dict, links: Links, recorded=None) -> str:
    """The page for `model`; `recorded` is the journal entry this report appended, or None."""
    agent = model["domain"] == gather.AGENTIC
    bodies = {
        "question-mode": _question(model),
        "data-licences": _data(model),
        "protocol-partitions": render_agent.protocol(model) if agent else _protocol(model),
        "configurations": render_agent.configurations(model) if agent else _configurations(model),
        "coverage-statuses": _coverage(model),
        "metrics-differences": render_agent.metrics(model) if agent else _metrics(model),
        "individual-errors": render_agent.errors(model, links) if agent else _errors(model, links),
        "limits": _limits(model),
        "artifact-origin": _origin(model, links),
        "exposure": _exposure(model, recorded),
    }
    sections = join(_section(i, sid, heading, bodies[sid]) for i, (sid, heading) in enumerate(SECTIONS, 1))
    spec = model["spec"]
    hero = tag(
        "header",
        join(
            [
                tag("p", join(["Hypotrail ", tag("b", "·"), " Report"]), class_="org"),
                tag("p", "Study report", class_="kick"),
                tag("h1", f"Study {spec['study_id']}"),
                tag("p", "Rendered from the records of the Study. Nothing is computed when this page is opened.", class_="sub"),
            ]
        ),
        class_="hero",
    )
    scenarios = [a["manifest"]["attempt_id"] for a in model["attempts"] if a["manifest"]["mode"] == SCENARIO_MODE]
    banner = (
        tag(
            "aside",
            join([tag("p", tag("b", SCENARIO_BANNER)), tag("p", f"Scenario Attempts of this Study, covered by this banner: {', '.join(scenarios)}.")]),
            id="scenario-banner",
            class_="banner",
        )
        if scenarios
        else ""
    )
    page = join(
        [
            Safe('<!doctype html><html lang="en" data-mode="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'),
            tag("title", f"Hypotrail report, Study {spec['study_id']}"),
            Safe(f"<style>{CHARTER_STYLE}</style></head><body>"),
            tag("div", join([hero, banner, sections, tag("footer", "Hypotrail · report · the Study's records are the source; this page is rebuilt, never stored as one.")]), class_="page"),
            Safe("</body></html>\n"),
        ]
    )
    return str(page)
