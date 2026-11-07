"""AG-10 / #49: the tool loop is observed when a produced Episode shows at least one successful
`query_readonly` call between model turns and then a final answer. `describe_schema` calls may come
anywhere in it. The seam is `live.tool_loop_observed` on projected Episodes (plain records)."""

import pytest

from hypotrail.agentic import live


def turn(n):
    return {"kind": "model_turn", "turn": n, "stop_reason": None}


def call(native, function="query_readonly"):
    return {"kind": "tool_call", "native_tool_call_id": native, "function": function, "arguments": {}}


def result(native, *, error=None, tool_error=None):
    body = {"columns": [], "rows": [], "error": error, "tool_call_id": f"app-{native}"}
    return {"kind": "tool_result", "native_tool_call_id": native, "app_tool_call_id": f"app-{native}",
            "result": body, "tool_error": tool_error}


FINAL = {"kind": "final_answer", "text": "{}"}
SQL_ERROR = {"code": "SQL_ERROR", "message": "x"}


def episode(steps, status="produced"):
    return {"status": status, "steps": steps}


def observed(*steps, status="produced"):
    return live.tool_loop_observed([episode(list(steps), status)])


def test_one_query_then_the_answer_is_a_tool_loop():
    assert observed(turn(1), call("a"), result("a"), turn(2), FINAL)


def test_describe_schema_before_the_query_is_still_a_tool_loop():
    assert observed(turn(1), call("s", "describe_schema"), result("s"), turn(2), call("q"), result("q"), turn(3), FINAL)


def test_two_queries_are_still_a_tool_loop():
    assert observed(turn(1), call("a"), result("a"), turn(2), call("b"), result("b"), turn(3), FINAL)


def test_two_calls_in_one_turn_are_still_a_tool_loop():
    assert observed(turn(1), call("s", "describe_schema"), call("q"), result("s"), result("q"), turn(2), FINAL)


def test_a_failed_query_followed_by_a_successful_one_is_a_tool_loop():
    assert observed(turn(1), call("a"), result("a", error=SQL_ERROR), turn(2), call("b"), result("b"), turn(3), FINAL)


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param([turn(1), FINAL], id="no tool call"),
        pytest.param([turn(1), call("s", "describe_schema"), result("s"), turn(2), FINAL], id="describe_schema only"),
        pytest.param([turn(1), call("a"), result("a", error=SQL_ERROR), turn(2), FINAL], id="query failed in the result"),
        pytest.param([turn(1), call("a"), result("a", tool_error={"type": "timeout"}), turn(2), FINAL], id="tool error"),
        pytest.param([turn(1), call("a"), result("a"), turn(2)], id="no final answer"),
    ],
)
def test_without_a_successful_query_and_a_final_answer_there_is_no_tool_loop(steps):
    assert not observed(*steps)


@pytest.mark.parametrize("status", ["failed", "missing"])
def test_an_episode_that_did_not_produce_is_no_tool_loop(status):
    assert not observed(turn(1), call("a"), result("a"), turn(2), FINAL, status=status)


def test_one_episode_is_enough_among_several():
    good = episode([turn(1), call("a"), result("a"), turn(2), FINAL])
    bad = episode([turn(1), FINAL])
    assert live.tool_loop_observed([bad, good]) and not live.tool_loop_observed([bad])
