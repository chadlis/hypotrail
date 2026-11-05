"""What the evaluated model is sent for one Case, and nothing else.

The renderer takes the question, the requested columns and the unit as its only
arguments, so no other Case field (identifier, Partition, family) and no
Reference value can reach the model by construction. The system text is not
here: it belongs to the Configuration and is declared by the Workload.
"""


def render_user_message(*, question: str, columns: list[str], unit: str | None) -> str:
    """The user message of one Case. A Case with no unit is rendered like any other."""
    return (
        f"Question: {question}\n"
        f"Requested columns: {', '.join(columns)}\n"
        f"Unit: {unit if unit is not None else 'none'}"
    )
