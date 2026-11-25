"""The inventory of the paths that take the writer lock: the locked function each row of `tests/_order_table.py` enters, and the calls that follow each stale check.

`tests/test_order_probe.py` holds it equal to the code of `src`. Later tickets of #120 may change this module when the lock moves; `tests/_order_table.py`, the expected codes, stays as it is.
"""

# The function of `LOCKED_PATHS` that the call of a row of `CHECKS_BEFORE_THE_LOCK` or of `UNDER_THE_LOCK` enters, and no other one:
# `init`, `init --new-revision` and `assess` have one for each Track, and a row of one of them gives the same code on both.
ML_INIT = "hypotrail.ml.study:init_study"
AGENT_INIT = "hypotrail.agentic.study:init_study"
ML_REVISION = "hypotrail.ml.study:new_revision"
AGENT_REVISION = "hypotrail.agentic.study:new_revision"
RUN_ML = "hypotrail.ml.run:run_ml"
RUN_AGENT = "hypotrail.agentic.run:run_agent"
IMPORT_ML = "hypotrail.ml.imports:import_ml"
IMPORT_AGENT = "hypotrail.agentic.imports:import_agent"
ML_ASSESS = "hypotrail.ml.assess:assess"
AGENT_ASSESS = "hypotrail.agentic.assess:assess"
COMPARE = "hypotrail.core.comparison:compare"
RECOVER = "hypotrail.core.state:recover"
REPORT = "hypotrail.report.command:report"
DECIDE = "hypotrail.core.decisions:decide"
DEVIATION = "hypotrail.core.deviations:record"

ENTERS = {
    "init data": ML_INIT,
    "init Track": ML_INIT,
    "init declaration schema": ML_INIT,
    "init declaration": ML_INIT,
    "init agent data": AGENT_INIT,
    "init agent Workload": AGENT_INIT,
    "init agent declaration": AGENT_INIT,
    "run agent Track": RUN_AGENT,
    "run agent examples": RUN_AGENT,
    "run agent Workload": RUN_AGENT,
    "run agent --config": RUN_AGENT,
    "run agent scenarios not declared": RUN_AGENT,
    "run agent scenarios file": RUN_AGENT,
    "run agent Partition cases": RUN_AGENT,
    "run agent --cases outside": RUN_AGENT,
    "import agent Inspect": IMPORT_AGENT,
    "compare --factor": COMPARE,
    "report records": REPORT,
    "report --out": REPORT,
    "init --new-revision examples": ML_REVISION,
    "init --new-revision agent examples": AGENT_REVISION,
    "run ml examples": RUN_ML,
    "run ml Track": RUN_ML,
    "run ml data": RUN_ML,
    "run ml Study artifact": RUN_ML,
    "run ml --partition": RUN_ML,
    "run ml --config": RUN_ML,
    "run ml --retry-of": RUN_ML,
    "run ml declaration file": RUN_ML,
    "run ml declaration JSON": RUN_ML,
    "run ml replay": RUN_ML,
    "run ml replay artifacts": RUN_ML,
    "run ml request conflict": RUN_ML,
    "run ml request_id of a decision": RUN_ML,
    "run ml declaration keys": RUN_ML,
    "run agent --retry-of": RUN_AGENT,
    "run agent replay": RUN_AGENT,
    "run agent replay artifacts": RUN_AGENT,
    "run agent request conflict": RUN_AGENT,
    "run agent request_id of a decision": RUN_AGENT,
    "run agent Workload lock": RUN_AGENT,
    "import ml Track": IMPORT_ML,
    "import ml data": IMPORT_ML,
    "import ml Study artifact": IMPORT_ML,
    "import ml source": IMPORT_ML,
    "import ml mapping": IMPORT_ML,
    "import ml population": IMPORT_ML,
    "import ml examples": IMPORT_ML,
    "import ml declaration file": IMPORT_ML,
    "import ml declaration JSON": IMPORT_ML,
    "import ml replay": IMPORT_ML,
    "import ml replay artifacts": IMPORT_ML,
    "import ml request conflict": IMPORT_ML,
    "import ml request_id of a decision": IMPORT_ML,
    "import ml declaration keys": IMPORT_ML,
    "import agent Track": IMPORT_AGENT,
    "import agent Workload files": IMPORT_AGENT,
    "import agent Study artifact": IMPORT_AGENT,
    "import agent source": IMPORT_AGENT,
    "import agent population": IMPORT_AGENT,
    "import agent examples": IMPORT_AGENT,
    "import agent Workload": IMPORT_AGENT,
    "import agent log": IMPORT_AGENT,
    "import agent replay": IMPORT_AGENT,
    "import agent replay artifacts": IMPORT_AGENT,
    "import agent request conflict": IMPORT_AGENT,
    "import agent request_id of a decision": IMPORT_AGENT,
    "import agent answer schema": IMPORT_AGENT,
    "assess Scorer": ML_ASSESS,
    "assess agent Observation set": AGENT_ASSESS,
    "compare Assessment": COMPARE,
    "recover Attempt": RECOVER,
    "report Exposure": REPORT,
    "report examples": REPORT,
    "decide replay": DECIDE,
    "decide request conflict": DECIDE,
    "decide request_id of an Attempt": DECIDE,
    "decide cited id": DECIDE,
    "run ml request_id of a declared deviation": RUN_ML,
    "run agent request_id of a declared deviation": RUN_AGENT,
    "import ml request_id of a declared deviation": IMPORT_ML,
    "import agent request_id of a declared deviation": IMPORT_AGENT,
    "decide request_id of a declared deviation": DECIDE,
    "deviation replay": DEVIATION,
    "deviation request conflict": DEVIATION,
    "deviation request_id of an Attempt": DEVIATION,
    "deviation request_id of a decision": DEVIATION,
    "deviation cited id": DEVIATION,
}

# A row of `CHECKS_BEFORE_THE_LOCK` or of `UNDER_THE_LOCK` whose refusal comes before the call reaches any locked function, with the reason.
ENTERS_NONE = {
    "init examples": "`_init` in `cli.py` resolves the examples directory to pick the Track's module, before it calls that module's `init_study`",
}

# A row of `LOCK_HELD` that has no locked path, with the reason.
LOCK_HELD_ENTERS_NONE = {
    "init --read-sequence": "`_init` in `cli.py` refuses `--read-sequence` for a Study that is created, before it calls any `init_study`",
    "deviation empty text": "`_deviation` in `cli.py` runs `deviations.check_arguments`, which refuses an empty text, before it calls `deviations.record`",
}

# --- the paths that take the writer lock ---------------------------------------------------------------------------------------

# Every function under `src` that takes the writer lock, as `module:function`: by `study_write.locked`, which takes it for every writer;
# `tests/test_order_probe.py` holds this set equal to the set found in the source. `reads_sequence`: the function takes `--read-sequence`. `lock_held`
# and `after`: its row of `LOCK_HELD` and of `UNDER_THE_LOCK` (the `AFTER` one). `stale_check_in`: the function that calls `require_current`, the
# `replay_attempt`, `replay_decision` or `replay_deviation` of the Study-write module that runs it, or the Attempt recorder's `replayed` that runs
# `replay_attempt`, when it is not the locked function itself.
# `then`: the function the locked function calls after `require_current`, whose calls are the ones that follow it.
LOCKED_PATHS = {
    ML_INIT: {"writer": "init", "reads_sequence": False, "lock_held": "init", "after": None},
    AGENT_INIT: {"writer": "init", "reads_sequence": False, "lock_held": "init agent", "after": None},
    ML_REVISION: {
        "writer": "init --new-revision", "reads_sequence": True, "lock_held": "init --new-revision", "after": "init --new-revision examples",
    },
    AGENT_REVISION: {
        "writer": "init --new-revision", "reads_sequence": True, "lock_held": "init --new-revision agent",
        "after": "init --new-revision agent examples",
    },
    RUN_ML: {
        "writer": "run ml", "reads_sequence": True, "lock_held": "run ml", "after": "run ml declaration keys", "stale_check_in": "_run_locked",
    },
    RUN_AGENT: {
        "writer": "run agent", "reads_sequence": True, "lock_held": "run agent", "after": "run agent Workload lock", "stale_check_in": "_run_locked",
    },
    IMPORT_ML: {
        "writer": "import ml", "reads_sequence": True, "lock_held": "import ml", "after": "import ml declaration keys",
        "stale_check_in": "_import_locked",
    },
    IMPORT_AGENT: {
        "writer": "import agent", "reads_sequence": True, "lock_held": "import agent", "after": "import agent answer schema",
        "stale_check_in": "_import_locked",
    },
    ML_ASSESS: {
        "writer": "assess", "reads_sequence": True, "lock_held": "assess", "after": "assess Scorer", "then": "_assess_locked",
    },
    AGENT_ASSESS: {
        "writer": "assess", "reads_sequence": True, "lock_held": "assess agent", "after": "assess agent Observation set", "then": "_assess_locked",
    },
    COMPARE: {
        "writer": "compare", "reads_sequence": True, "lock_held": "compare", "after": "compare Assessment", "then": "_compare_locked",
    },
    RECOVER: {"writer": "recover", "reads_sequence": True, "lock_held": "recover", "after": "recover Attempt"},
    REPORT: {"writer": "report", "reads_sequence": True, "lock_held": "report", "after": "report examples"},
    DECIDE: {
        "writer": "decide", "reads_sequence": True, "lock_held": "decide", "after": "decide cited id", "stale_check_in": "_decide_locked",
    },
    DEVIATION: {
        "writer": "deviation", "reads_sequence": True, "lock_held": "deviation", "after": "deviation cited id", "stale_check_in": "_record_locked",
    },
}

# The call each `AFTER` row provokes: the first call of its path after `require_current`, once the calls that cannot refuse are skipped (each with
# its reason). A call to a builtin, or to a method of a value that is no name, is never counted. The fault of the row is the first refusal inside
# that call: `report examples` is `exposure.record`, which calls `checked_basis`, which calls the `live_basis` the command line passes, which
# resolves the examples directory.
SPEC_READ = "the spec was read and validated before the lock"
ROUTED_BY_THE_COMMAND_LINE_NEW_REVISION = (
    "; `test_init_new_revision_enters_the_new_revision_of_the_track_of_the_study_and_not_the_other` in `tests/test_order_probe.py` pins that routing"
)
ROUTED_BY_THE_COMMAND_LINE_ASSESS = (
    "; `test_assess_enters_the_agentic_module_for_a_registered_agentic_scorer_and_the_regression_module_for_any_other_scorer` in "
    "`tests/test_order_probe.py` pins that routing"
)
SKIPPED_CALLS = {
    "init --new-revision examples": ("data.resolve_examples_dir", {
        "layout.read_spec": SPEC_READ,
        "layout.require_domain": "the command line picks this module from the domain of the spec read before the lock"
        + ROUTED_BY_THE_COMMAND_LINE_NEW_REVISION,
    }),
    "init --new-revision agent examples": ("data.resolve_examples_dir", {
        "layout.read_spec": SPEC_READ,
        "layout.require_domain": "the command line picks this module from the domain of the spec read before the lock"
        + ROUTED_BY_THE_COMMAND_LINE_NEW_REVISION,
    }),
    "run ml declaration keys": ("protocol_content", {}),
    "run agent Workload lock": ("data.verify_workloads", {}),
    "import ml declaration keys": ("protocol_content", {}),
    "import agent answer schema": ("protocol_content", {}),
    "assess Scorer": ("scorers.get", {"layout.read_spec": SPEC_READ}),
    "assess agent Observation set": ("layout.find_observation_set", {
        "layout.read_spec": SPEC_READ,
        "scorers.get": "the command line picks this module only for a registered agentic Scorer" + ROUTED_BY_THE_COMMAND_LINE_ASSESS,
    }),
    "compare Assessment": ("_side", {}),
    "recover Attempt": ("layout.attempt_ids", {}),
    "report examples": ("exposure.record", {
        "gather.load": "it reads again the records the page read and verified before the lock",
        "gather.touched": "it lists what the model just loaded shows",
    }),
    "decide cited id": ("held_ids", {"layout.read_spec": SPEC_READ}),
    "deviation cited id": ("_check_cited", {}),
}
