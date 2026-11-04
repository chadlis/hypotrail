"""Ticket #34: a Configuration that uses a forbidden feature is refused."""

import copy
import json
import shutil
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.ridge import fit_configuration, load_configuration, write_outputs

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"
FORBIDDEN = ["casual", "registered", "cnt", "temp", "atemp", "hum", "windspeed", "weathersit"]


def workload_with(tmp_path, edit):
    target = tmp_path / "bike"
    shutil.copytree(BIKE, target)
    path = target / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    edit(declaration)
    path.write_text(json.dumps(declaration), encoding="utf-8")
    return target


def inject(column, where):
    def edit(declaration):
        config = declaration["configurations"]["ridge_v1"]
        if where == "lag_features":
            config["lag_features"].append({"name": column, "kind": "lag", "period": 1})
        elif where == "calendar_columns":
            config["calendar_columns"].append(column)
        else:
            config[where]["columns"].append(column)
    return edit


def refusal(workload, config_id="ridge_v1"):
    with pytest.raises(InvalidInputError) as caught:
        load_configuration(workload, config_id)
    return caught.value


def test_unmodified_ridge_v1_is_accepted():
    loaded = load_configuration(BIKE, "ridge_v1")
    assert loaded["declaration"]["fit_partition"] == "train"  # declared by the Workload
    assert "fit_partition" not in loaded["configuration"]  # not chosen by the Configuration


# --- the Partition used for fitting belongs to the Workload's protocol -------------


@pytest.mark.parametrize("partition", ["dev", "public_check"])
def test_a_workload_cannot_declare_dev_or_public_check_as_the_fit_partition(tmp_path, partition):
    workload = workload_with(tmp_path, lambda d: d.update(fit_partition=partition))
    error = refusal(workload)
    assert error.code == "FIT_PARTITION_NOT_ALLOWED"
    assert error.details["partition"] == partition


@pytest.mark.parametrize("partition", ["holdout", "", None, 7])
def test_a_fit_partition_the_workload_does_not_declare_is_refused(tmp_path, partition):
    workload = workload_with(tmp_path, lambda d: d.update(fit_partition=partition))
    error = refusal(workload)
    assert error.code == "FIT_PARTITION_NOT_DECLARED"
    assert error.details["partition"] == partition


@pytest.mark.parametrize("partition", ["dev", "public_check"])
def test_dev_and_public_check_are_never_fitted_on(tmp_path, partition):
    from _ml_helpers import fit_probe

    workload = workload_with(tmp_path, lambda d: d.update(fit_partition=partition))
    with fit_probe(strict=True) as probe:
        with pytest.raises(InvalidInputError):
            fit_configuration(workload, "ridge_v1")
        with pytest.raises(InvalidInputError):
            write_outputs(workload, tmp_path / "out", "ridge_v1", "dev")
    assert probe.calls == []


def test_a_workload_without_a_fit_partition_is_refused(tmp_path):
    error = refusal(workload_with(tmp_path, lambda d: d.pop("fit_partition")))
    assert error.code == "DECLARATION_INCOMPLETE"
    assert error.details["key"] == "fit_partition"


def test_the_workload_declares_the_eight_forbidden_features():
    declared = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))["forbidden_features"]
    assert declared == FORBIDDEN


@pytest.mark.parametrize("where", ["calendar_columns", "encoder", "scaler", "lag_features"])
@pytest.mark.parametrize("column", FORBIDDEN)
def test_forbidden_column_is_refused_in_every_input_list(tmp_path, column, where):
    error = refusal(workload_with(tmp_path, inject(column, where)))
    assert error.code == "FORBIDDEN_FEATURE"
    assert error.details["feature"] == column
    assert column in error.message


@pytest.mark.parametrize("column", FORBIDDEN)
def test_refusal_writes_no_predictions(tmp_path, column):
    workload = workload_with(tmp_path, inject(column, "calendar_columns"))
    out = tmp_path / "out"
    with pytest.raises(InvalidInputError):
        write_outputs(workload, out, "ridge_v1", "dev")
    with pytest.raises(InvalidInputError):
        fit_configuration(workload, "ridge_v1")
    assert not out.exists() or not list(out.rglob("predictions.csv"))


def test_refusal_follows_the_declaration_not_the_track(tmp_path):
    def edit(declaration):
        declaration["forbidden_features"] = ["holiday"]

    error = refusal(workload_with(tmp_path / "a", edit))
    assert error.code == "FORBIDDEN_FEATURE" and error.details["feature"] == "holiday"

    def edit_other(declaration):
        declaration["forbidden_features"] = ["hum"]
        declaration["configurations"]["ridge_v1"]["calendar_columns"].append("temp")
        declaration["configurations"]["ridge_v1"]["encoder"]["columns"].append("temp")

    assert load_configuration(workload_with(tmp_path / "b", edit_other), "ridge_v1")


def test_missing_forbidden_declaration_fails_closed(tmp_path):
    workload = workload_with(tmp_path, lambda d: d.pop("forbidden_features"))
    assert refusal(workload).code == "DECLARATION_INCOMPLETE"


@pytest.mark.parametrize("period", [0, -1, -7])
def test_target_feature_reaching_date_t_or_later_is_refused(tmp_path, period):
    def edit(declaration):
        declaration["configurations"]["ridge_v1"]["lag_features"][0]["period"] = period

    error = refusal(workload_with(tmp_path, edit))
    assert error.code == "TARGET_FEATURE_NOT_PAST"
    assert error.details["feature"] == "lag_1"


@pytest.mark.parametrize(
    "feature",
    [
        {"name": "lag_2", "kind": "lag", "period": 2},
        {"name": "mean_previous_14", "kind": "mean_previous", "period": 14},
        {"name": "lag_1", "kind": "mean_previous", "period": 1},
        {"name": "ewm_7", "kind": "ewm", "period": 7},
    ],
)
def test_undeclared_target_transformation_is_refused(tmp_path, feature):
    def edit(declaration):
        declaration["configurations"]["ridge_v1"]["lag_features"].append(feature)

    error = refusal(workload_with(tmp_path, edit))
    assert error.code == "TARGET_TRANSFORMATION_NOT_ALLOWED"
    assert error.details["feature"] == feature["name"]


def test_allowed_transformations_follow_the_declaration(tmp_path):
    lag_2 = {"name": "lag_2", "kind": "lag", "period": 2}

    def edit(declaration):
        declaration["allowed_target_features"].append(lag_2)
        declaration["configurations"]["ridge_v1"]["lag_features"].append(lag_2)
        declaration["configurations"]["ridge_v1"]["scaler"]["columns"].append("lag_2")

    assert load_configuration(workload_with(tmp_path, edit), "ridge_v1")


def test_rules_apply_to_every_configuration(tmp_path):
    def edit(declaration):
        other = copy.deepcopy(declaration["configurations"]["ridge_v1"])
        other["calendar_columns"].append("casual")
        declaration["configurations"]["other"] = other

    workload = workload_with(tmp_path, edit)
    assert load_configuration(workload, "ridge_v1")
    assert refusal(workload, "other").code == "FORBIDDEN_FEATURE"


# --- no model input is dropped, no transformed column is invented -------------------


def test_a_calendar_input_that_the_encoder_does_not_take_is_refused(tmp_path):
    def edit(declaration):
        declaration["configurations"]["ridge_v1"]["calendar_columns"].append("yr")

    error = refusal(workload_with(tmp_path, edit))
    assert error.code == "MODEL_INPUT_NOT_TRANSFORMED"
    assert error.details == {"config_id": "ridge_v1", "feature": "yr"}


def test_a_lag_input_that_the_scaler_does_not_take_is_refused(tmp_path):
    def edit(declaration):
        declaration["configurations"]["ridge_v1"]["scaler"]["columns"].remove("lag_7")

    error = refusal(workload_with(tmp_path, edit))
    assert error.code == "MODEL_INPUT_NOT_TRANSFORMED"
    assert error.details["feature"] == "lag_7"


@pytest.mark.parametrize("where", ["encoder", "scaler"])
def test_an_encoder_or_scaler_column_that_is_not_a_model_input_is_refused(tmp_path, where):
    def edit(declaration):
        declaration["configurations"]["ridge_v1"][where]["columns"].append("yr")

    error = refusal(workload_with(tmp_path, edit))
    assert error.code == "TRANSFORMER_COLUMN_NOT_A_MODEL_INPUT"
    assert error.details == {"config_id": "ridge_v1", "feature": "yr", "transformer": where}


# --- a Configuration declares its kind; validation dispatches on it ------------------


def test_each_declared_configuration_names_its_kind():
    declared = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))["configurations"]
    assert declared["seasonal_7"]["kind"] == "seasonal_baseline"
    assert declared["ridge_v1"]["kind"] == "ridge_pipeline"


def test_a_ridge_configuration_with_a_seasonal_key_is_refused_before_anything_else(tmp_path):
    """The reviewer's case: `period_k` added to ridge_v1 must not switch the checks off."""

    def edit(declaration):
        config = declaration["configurations"]["ridge_v1"]
        config["period_k"] = 7
        config["calendar_columns"].append("casual")
        config["encoder"]["columns"].append("casual")

    workload = workload_with(tmp_path, edit)
    error = refusal(workload)
    assert error.code == "CONFIGURATION_KEY_NOT_FOR_KIND"
    assert error.details == {"config_id": "ridge_v1", "kind": "ridge_pipeline", "key": "period_k"}
    out = tmp_path / "out"
    with pytest.raises(InvalidInputError):
        write_outputs(workload, out, "ridge_v1", "dev")
    assert not out.exists() or not list(out.rglob("predictions.csv"))


def test_forbidden_feature_is_still_refused_once_the_foreign_key_is_gone(tmp_path):
    workload = workload_with(tmp_path, inject("casual", "calendar_columns"))
    assert refusal(workload).code == "FORBIDDEN_FEATURE"


@pytest.mark.parametrize("key", ["lag_features", "calendar_columns", "encoder", "scaler", "ridge", "fit_partition"])
def test_a_seasonal_configuration_with_a_key_of_another_kind_is_refused(tmp_path, key):
    workload = workload_with(tmp_path, lambda d: d["configurations"]["seasonal_7"].update({key: []}))
    error = refusal(workload, "seasonal_7")
    assert error.code == "CONFIGURATION_KEY_NOT_FOR_KIND"
    assert error.details["key"] == key and error.details["kind"] == "seasonal_baseline"


@pytest.mark.parametrize("kind", ["theta", "", None, 7, ["ridge_pipeline"]])
def test_an_unknown_kind_is_refused(tmp_path, kind):
    workload = workload_with(tmp_path, lambda d: d["configurations"]["ridge_v1"].update(kind=kind))
    error = refusal(workload)
    assert error.code == "CONFIGURATION_KIND_UNKNOWN"
    assert error.details["config_id"] == "ridge_v1"


def test_a_configuration_without_a_kind_is_refused(tmp_path):
    workload = workload_with(tmp_path, lambda d: d["configurations"]["seasonal_7"].pop("kind"))
    assert refusal(workload, "seasonal_7").code == "CONFIGURATION_KIND_UNKNOWN"


def test_the_target_checks_run_for_the_seasonal_kind_too(tmp_path):
    def edit(declaration):
        declaration["configurations"]["seasonal_7"]["period_k"] = 0

    assert refusal(workload_with(tmp_path / "a", edit), "seasonal_7").code == "TARGET_FEATURE_NOT_PAST"

    def edit_undeclared(declaration):
        declaration["configurations"]["seasonal_7"]["period_k"] = 14

    error = refusal(workload_with(tmp_path / "b", edit_undeclared), "seasonal_7")
    assert error.code == "TARGET_TRANSFORMATION_NOT_ALLOWED"
