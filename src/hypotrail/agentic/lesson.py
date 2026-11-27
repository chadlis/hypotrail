"""The lesson cards of the tool-using agent Track, read only: `lesson` reads them.

A card explains one kind of step that the Study shows: what the step is and how to read it. The cards are data of the Track,
`lesson.json`, checked against `lesson.schema.json` beside it. A card is served only for a kind of which the Study's `status` holds a
record, in the order of `KINDS`; its key paths name values of the `status` or `figures` read, and its text holds no number of the
Study. The read takes no lock, writes nothing and records no Exposure.
"""

import copy
import json
from functools import cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator

from hypotrail.core import state
from hypotrail.core import study as layout
from hypotrail.agentic.study import DOMAIN, TRACK

COMMAND = "lesson"
DATA_NAME = "lesson.json"
SCHEMA_NAME = "lesson.schema.json"
# The kinds of step a card explains, in the order of the steps; each is the key of `status` that holds its records.
KINDS = ("study", "attempts", "assessments", "comparisons", "decisions")


@cache
def validator() -> Draft202012Validator:
    schema = json.loads(resources.files(__package__).joinpath(SCHEMA_NAME).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@cache
def cards() -> tuple:
    """The Track's cards, in the order of `KINDS`; data that does not match the schema raises."""
    data = json.loads(resources.files(__package__).joinpath(DATA_NAME).read_text(encoding="utf-8"))
    validator().validate(data)
    return tuple(sorted(data["cards"], key=lambda card: KINDS.index(card["kind"])))


def lesson(study) -> dict:
    """The cards that apply to the Study; refuses a Study of another domain with `UNSUPPORTED_CAPABILITY`."""
    study = Path(study)
    layout.require_domain(layout.read_spec(study), DOMAIN, COMMAND)
    report = state.status(study)
    shown = [card for card in cards() if report.get(card["kind"])]
    return {"write_sequence": report["write_sequence"], "track": TRACK, "cards": [copy.deepcopy(card) for card in shown]}
