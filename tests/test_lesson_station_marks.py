"""Station marks consume only the explicit read metadata needed to derive them."""

import pytest


@pytest.mark.parametrize(
    ("partitions", "assessed", "compared", "decided", "expected"),
    [
        ([], [], False, False, (False, False, False)),
        (["dev"], [], False, False, (False, False, False)),
        (["dev"], ["obs-0"], False, False, (True, False, False)),
        (["dev", "dev"], ["obs-0", "obs-1"], False, False, (True, True, False)),
        (["public_check", "dev"], ["obs-1"], False, False, (True, False, False)),
        (["public_check", "dev"], ["obs-0", "obs-1"], False, False, (True, False, False)),
        ([None, "dev"], ["obs-0", "unmatched"], False, False, (False, False, False)),
        ([], [], True, False, (False, False, True)),
        ([], [], False, True, (False, False, True)),
    ],
)
def test_station_marks_use_only_matching_dev_assessments_and_existence_of_comparison_or_decision(
    partitions, assessed, compared, decided, expected
):
    from hypotrail.lessons import station_marks

    marks = station_marks(
        {
            "attempts": [
                {"observation_set_id": f"obs-{index}", "partition": partition}
                for index, partition in enumerate(partitions)
            ],
            "assessments": [{"observation_set_id": observation} for observation in assessed],
            "comparisons": [{}] if compared else [],
            "decisions": [{}] if decided else [],
        }
    )
    assert marks == dict(zip(("baseline", "iterate", "compare_decide"), expected, strict=True))
