"""The order in which every Study writer refuses, as today's code gives it: one table, read by `tests/test_order_probe.py`.

A row is `case: (writer, exit code, error code)`. `REPLAYED` stands for the recorded record a replay returns (exit 0, `replayed` true).
Every call but `init` that creates a Study is made with a `--read-sequence` below the Study's Write sequence (that `init` takes no such option), so a call that reaches the stale check gives `STUDY_CHANGED`.
"""

REPLAYED = "replayed"

# --- the writer lock is held by another process ------------------------------------------------------------------------

# Arguments that pass every check before the lock: the lock is the refusal. `init` that creates a Study is called without `--read-sequence`,
# which it refuses; the two Tracks of `init`, of `init --new-revision` and of `assess` are separate code, so each has its row.
LOCK_HELD = {
    "init": ("init", 6, "STUDY_LOCKED"),
    "init agent": ("init", 6, "STUDY_LOCKED"),
    "init --new-revision": ("init --new-revision", 6, "STUDY_LOCKED"),
    "init --new-revision agent": ("init --new-revision", 6, "STUDY_LOCKED"),
    "run ml": ("run ml", 6, "STUDY_LOCKED"),
    "run agent": ("run agent", 6, "STUDY_LOCKED"),
    "import ml": ("import ml", 6, "STUDY_LOCKED"),
    "import agent": ("import agent", 6, "STUDY_LOCKED"),
    "assess": ("assess", 6, "STUDY_LOCKED"),
    "assess agent": ("assess", 6, "STUDY_LOCKED"),
    "compare": ("compare", 6, "STUDY_LOCKED"),
    "recover": ("recover", 6, "STUDY_LOCKED"),
    "report": ("report", 6, "STUDY_LOCKED"),
    "decide": ("decide", 6, "STUDY_LOCKED"),
}

# The checks before the lock that read more than the command's own arguments (chapter 04, table `checks-before-the-lock`): each is
# refused with the lock held, and before any older value is looked at.
CHECKS_BEFORE_THE_LOCK = {
    "init examples": ("init", 2, "EXAMPLES_DIR_NOT_FOUND"),
    "init data": ("init", 3, "DATA_INTEGRITY"),
    "init Track": ("init", 2, "WORKLOAD_TRACK_NOT_SUPPORTED"),
    "init declaration schema": ("init", 2, "TRAIN_PARTITION_NOT_DECLARED"),
    "init declaration": ("init", 2, "DECLARATION_INCOMPLETE"),
    "init agent data": ("init", 3, "DATA_INTEGRITY"),
    "init agent Workload": ("init", 2, "DECLARATION_KEY_UNKNOWN"),
    "init agent declaration": ("init", 2, "DECLARATION_INCOMPLETE"),
    "run agent Track": ("run agent", 2, "UNSUPPORTED_CAPABILITY"),
    "run agent examples": ("run agent", 2, "EXAMPLES_DIR_NOT_FOUND"),
    "run agent Workload": ("run agent", 2, "FILE_NOT_FOUND"),
    "run agent --config": ("run agent", 2, "CONFIGURATION_NOT_DECLARED"),
    "run agent scenarios not declared": ("run agent", 2, "SCENARIOS_NOT_DECLARED"),
    "run agent scenarios file": ("run agent", 2, "FILE_NOT_FOUND"),
    "run agent Partition cases": ("run agent", 2, "PARTITION_NOT_DECLARED"),
    "run agent --cases outside": ("run agent", 2, "CASE_NOT_IN_PARTITION"),
    "import agent Inspect": ("import agent", 5, "INSPECT_UNAVAILABLE"),
    "compare --factor": ("compare", 2, "UNSUPPORTED_CAPABILITY"),
    "report records": ("report", 3, "ARTIFACT_INTEGRITY"),
    "report --out": ("report", 2, "REPORT_OUTPUT_INVALID"),
}

# --- the lock is free ------------------------------------------------------------------------------------------------------

# `BEFORE`: a check under the lock that comes before the stale check gives its own result. `THE_CHECK`: the call reaches the stale check.
# `AFTER`: the first check that comes after the stale check gives the stale refusal; the last column is the result of the same call when the value
# read is the current one, which shows the check is real. A path has one `AFTER` row, and `AFTER_CALLS` names the call it provokes.
BEFORE, THE_CHECK, AFTER = "before the stale check", "the stale check", "after the stale check"
STALE = (6, "STUDY_CHANGED")

UNDER_THE_LOCK = {
    "init --new-revision examples": ("init --new-revision", AFTER, STALE, (2, "EXAMPLES_DIR_NOT_FOUND")),
    "init --new-revision agent examples": ("init --new-revision", AFTER, STALE, (2, "EXAMPLES_DIR_NOT_FOUND")),
    "run ml examples": ("run ml", BEFORE, (2, "EXAMPLES_DIR_NOT_FOUND"), None),
    "run ml Track": ("run ml", BEFORE, (2, "UNSUPPORTED_CAPABILITY"), None),
    "run ml data": ("run ml", BEFORE, (3, "DATA_INTEGRITY"), None),
    "run ml Study artifact": ("run ml", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "run ml --partition": ("run ml", BEFORE, (2, "PARTITION_NOT_DECLARED"), None),
    "run ml --config": ("run ml", BEFORE, (2, "CONFIGURATION_NOT_DECLARED"), None),
    "run ml --retry-of": ("run ml", BEFORE, (2, "RETRY_OF_UNKNOWN"), None),
    "run ml declaration file": ("run ml", BEFORE, (2, "FILE_NOT_FOUND"), None),
    "run ml declaration JSON": ("run ml", BEFORE, (2, "FILE_NOT_JSON"), None),
    "run ml replay": ("run ml", BEFORE, (0, REPLAYED), None),
    "run ml replay artifacts": ("run ml", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "run ml request conflict": ("run ml", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "run ml request_id of a decision": ("run ml", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "run ml declaration keys": ("run ml", AFTER, STALE, (2, "DECLARATION_INCOMPLETE")),
    "run agent --retry-of": ("run agent", BEFORE, (2, "RETRY_OF_UNKNOWN"), None),
    "run agent replay": ("run agent", BEFORE, (0, REPLAYED), None),
    "run agent replay artifacts": ("run agent", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "run agent request conflict": ("run agent", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "run agent request_id of a decision": ("run agent", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "run agent Workload lock": ("run agent", AFTER, STALE, (2, "UNKNOWN_WORKLOAD")),
    "import ml Track": ("import ml", BEFORE, (2, "UNSUPPORTED_CAPABILITY"), None),
    "import ml data": ("import ml", BEFORE, (3, "DATA_INTEGRITY"), None),
    "import ml Study artifact": ("import ml", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "import ml source": ("import ml", BEFORE, (2, "SOURCE_NOT_FOUND"), None),
    "import ml mapping": ("import ml", BEFORE, (2, "MAPPING_NOT_FOUND"), None),
    "import ml population": ("import ml", BEFORE, (2, "POPULATION_NOT_FOUND"), None),
    "import ml examples": ("import ml", BEFORE, (2, "EXAMPLES_DIR_NOT_FOUND"), None),
    "import ml declaration file": ("import ml", BEFORE, (2, "FILE_NOT_FOUND"), None),
    "import ml declaration JSON": ("import ml", BEFORE, (2, "FILE_NOT_JSON"), None),
    "import ml replay": ("import ml", BEFORE, (0, REPLAYED), None),
    "import ml replay artifacts": ("import ml", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "import ml request conflict": ("import ml", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "import ml request_id of a decision": ("import ml", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "import ml declaration keys": ("import ml", AFTER, STALE, (2, "DECLARATION_INCOMPLETE")),
    "import agent Track": ("import agent", BEFORE, (2, "UNSUPPORTED_CAPABILITY"), None),
    "import agent Workload files": ("import agent", BEFORE, (3, "LICENCE_NOTICE_CHANGED"), None),
    "import agent Study artifact": ("import agent", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "import agent source": ("import agent", BEFORE, (2, "SOURCE_NOT_FOUND"), None),
    "import agent population": ("import agent", BEFORE, (2, "POPULATION_NOT_FOUND"), None),
    "import agent examples": ("import agent", BEFORE, (2, "EXAMPLES_DIR_NOT_FOUND"), None),
    "import agent Workload": ("import agent", BEFORE, (2, "FILE_NOT_FOUND"), None),
    "import agent log": ("import agent", BEFORE, (2, "LOG_NOT_READABLE"), None),
    "import agent replay": ("import agent", BEFORE, (0, REPLAYED), None),
    "import agent replay artifacts": ("import agent", BEFORE, (3, "ARTIFACT_INTEGRITY"), None),
    "import agent request conflict": ("import agent", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "import agent request_id of a decision": ("import agent", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "import agent answer schema": ("import agent", AFTER, STALE, (2, "ANSWER_SCHEMA_NOT_DECLARED")),
    "assess Scorer": ("assess", AFTER, STALE, (2, "SCORER_NOT_REGISTERED")),
    "assess agent Observation set": ("assess", AFTER, STALE, (2, "OBSERVATION_SET_NOT_FOUND")),
    "compare Assessment": ("compare", AFTER, STALE, (2, "ASSESSMENT_NOT_FOUND")),
    "recover Attempt": ("recover", AFTER, STALE, (2, "ATTEMPT_NOT_FOUND")),
    "report Exposure": ("report", THE_CHECK, STALE, None),
    "report examples": ("report", AFTER, STALE, (2, "EXAMPLES_DIR_NOT_FOUND")),
    "decide replay": ("decide", BEFORE, (0, REPLAYED), None),
    "decide request conflict": ("decide", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "decide request_id of an Attempt": ("decide", BEFORE, (6, "REQUEST_CONFLICT"), None),
    "decide cited id": ("decide", AFTER, STALE, (2, "CITED_ID_NOT_FOUND")),
}


# --- the locked function each row enters --------------------------------------------------------------------------------------

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
}

# A row whose refusal comes before the call reaches any locked function, with the reason.
ENTERS_NONE = {
    "init examples": "`_init` in `cli.py` resolves the examples directory to pick the Track's module, before it calls that module's `init_study`",
}

# --- the paths that take the writer lock ---------------------------------------------------------------------------------------

# Every function under `src` that takes the writer lock (`lock.writer_lock`), as `module:function`; `tests/test_order_probe.py` holds this
# set equal to the set found in the source. `reads_sequence`: the function takes `--read-sequence`. `lock_held` and `after`: its row of `LOCK_HELD`
# and of `UNDER_THE_LOCK` (the `AFTER` one). `stale_check_in`: the function that calls `require_current` when it is not the locked function itself.
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
}
