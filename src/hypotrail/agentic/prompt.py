"""What the evaluated model is sent, and nothing else.

The renderer takes the question, the requested columns and the unit as its only
arguments, so no other Case field (identifier, Partition, family) and no
Reference value can reach the model by construction. This is the spike's single
prompt; the `plain` and `verify` prompts come with the agentic Track itself.
"""

SYSTEM_TEXT = """\
You answer questions about the Chinook music-store SQLite database. Use the \
query_readonly tool to look the data up; do not guess. The tool takes one SQL \
SELECT statement and returns columns, rows, row_count, truncated, error and a \
tool_call_id.

Finish with a single JSON object and nothing else: no Markdown fence, no extra \
prose. Its fields are:
- "status": "answered", "needs_clarification" or "not_answerable".
- "reason_code": null when answered; "criterion_undefined" for \
needs_clarification; "field_not_available" for not_answerable.
- "columns": the requested columns, in order, when answered; otherwise [].
- "rows": the result rows when answered; otherwise [].
- "unit": the requested unit when answered; otherwise null.
- "evidence": the tool_call_id values of the tool calls the answer relies on.
"""


def render_model_input(*, question: str, columns: list[str], unit: str | None) -> tuple[str, str]:
    """Return the (system, user) texts for one Case."""
    user = (
        f"Question: {question}\n"
        f"Requested columns: {', '.join(columns)}\n"
        f"Unit: {unit if unit is not None else 'none'}"
    )
    return SYSTEM_TEXT, user
