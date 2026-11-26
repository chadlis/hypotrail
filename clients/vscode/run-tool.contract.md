# The run tool's contract

`hypotrail_run` is the Copilot tool through which the chat runs a command of the CLI on a Study. It runs only the commands listed below, and it refuses some inputs before it starts the command. It may write records and advance the Study's Write sequence, but it never writes an act. The guard covers act writers, not record writers (D-174 on chadlis/hypotrail#75, item 4).

The corpus of command cases is `clients/vscode/test/run-tool-corpus/cases.jsonl`. It was written from this contract before the tool's code.

## The input

```json
{
  "type": "object",
  "properties": {
    "study": {
      "type": "string",
      "description": "The absolute path of the folder of the Study to run the command on, as a read or a refusal of these tools lists it. Required, even when the workspace holds one Study."
    },
    "command": {
      "type": "string",
      "enum": ["run", "import", "assess", "compare", "profile", "report"],
      "description": "The command of the CLI to run. import is always refused: a person runs an Import through the CLI."
    },
    "arguments": {
      "type": "array",
      "items": { "type": "string" },
      "description": "The arguments after the command, one string each: for run, the Track (ml or agent) first, then the options, each as --name=value or as --name followed by its value. Leave out --study, --read-sequence and --json: the tool passes them."
    },
    "read_sequence": {
      "type": "integer",
      "minimum": 0,
      "description": "The write_sequence of the Study as last read. Required for run, assess, compare and report; profile writes nothing and does not take it."
    }
  },
  "required": ["study", "command", "arguments"]
}
```

## The commands

The tool runs only these commands, each with only the options its row lists. An option is given once, as `--name=value` or as `--name` followed by its value. In the second form, a value that starts with `--` is read as a missing value. The tool passes each option as one argument, `--name=value`, so that no value is read as an option. A name is never shortened, and it is compared as written.

| Command | Track | Options the chat gives | Read sequence |
|---|---|---|---|
| `run` | `ml` | `--config`, `--partition`, `--request-id`, `--retry-of` | passed |
| `run` | `agent` | `--mode`, `--config`, `--request-id`, `--retry-of` | passed |
| `assess` | none | `--observations`, `--scorer`, `--references` | passed |
| `compare` | none | `--control`, `--candidate`, `--factor` | passed |
| `profile` | none | none | not passed |
| `report` | none | `--out` | passed |

For `run agent`, the only value of `--mode` the tool passes is `scripted_fixture`.

The tool starts the CLI with the program and first arguments of `contract.json` (`program`, `first_arguments`), from the checkout root, with no shell. The arguments after them are, in this order:

1. the command, then the Track for `run`;
2. `--study=<the Study's absolute path>`;
3. each option the chat gives, as `--name=value`, in the order given;
4. `--read-sequence=<read_sequence>`, except for `profile`;
5. `--json`.

What the CLI checks is left to the CLI: a required option that is missing, an unknown Configuration, Scorer or id, a stale Write sequence (`STUDY_CHANGED`). The tool reports the CLI's answer as printed, and it never starts the command again.

VS Code asks the person to confirm each call before the command starts, unless they chose "Always Allow" for the tool.

## What the tool reads before it starts the command

The tool takes the facts below from the arguments. For `assess`, `compare` and `report`, it also reads the Study through `status --study=<path> --json`, the read of `hypotrail_read_study`, which writes nothing. It never reads a file of the Study.

- An Attempt's Partition is `attempts[].partition` of that read, the Partition of the Observation set the Attempt produced (D-175 on chadlis/hypotrail#75).
- `assess` would touch the Attempt whose `observation_set_id` is the value of `--observations`.
- `compare` would touch the Attempts whose Observation sets are cited by the Assessments named by `--control` and `--candidate`, through `assessments[].observation_set_id`.
- `report` would touch every Attempt of the Study.

Ids are compared without their surrounding white space and without regard to case. An id that the read does not hold touches no Attempt, and the CLI then refuses it.

## What is refused before any command starts

A refusal starts no command: nothing is written, and the Write sequence does not move. The tool checks the rules in the order of the table below and gives the code of the first rule that refuses. Only the checks after the read in the order start the read.

Before any check, an argument is normalized for the two scans. It is lowercased, and every white space, `-` and `_` is removed.

| Code | When |
|---|---|
| `STUDY_NOT_FOUND` | `study` is not the absolute path of one of the Studies the walk finds in the workspace. |
| `COMMAND_NOT_ALLOWED` | `command` is not exactly one of the six commands of the input: `decide`, `deviation`, `init`, `recover`, `status`, `figures`, `data` and `spike` included, and any other spelling. |
| `IMPORT_REFUSED` | `command` is `import`: a person runs an Import through the CLI, since no read gives the Partition of an Import's population before it is recorded. |
| `ARGUMENTS_NOT_VALID` | `arguments` is not a list of strings. |
| `LIVE_RUN_REFUSED` | An argument holds `llmlive` once normalized. Or, for `run` with `agent` first, an option name that is not exactly one of its row's names is a prefix, in any case, of an option that only `llm_live` takes: `--partition`, `--repeats`, `--model`, `--cases`, `--episode-cost-limit-usd` or `--price-list`. Or the value of `--mode` is not `scripted_fixture`. |
| `PUBLIC_CHECK_REFUSED` | An argument holds `publiccheck` once normalized. |
| `ARGUMENTS_NOT_VALID` | For `run`, the first argument is neither `ml` nor `agent`. An argument that is not an option stands where no value is taken, or an option has no value. |
| `OPTION_NOT_ALLOWED` | An option is not one of its command's row: `--study`, `--json`, `--read-sequence`, `--examples-dir`, `--help`, `-h` and every shortened name included. |
| `OPTION_REPEATED` | An option is given more than once. |
| `READ_SEQUENCE_MISSING` | The command is not `profile`, and `read_sequence` is not an integer of 0 or more. |
| `STATUS_UNREADABLE` | For `assess`, `compare` and `report`, the read of the Study did not succeed. |
| `PUBLIC_CHECK_REFUSED` | For `assess`, `compare` and `report`, an Attempt the command would touch has the Partition `public_check` (D-174 item 4; D-165 item 3: "The chat is allowed at every station except the held-out pass."). |

`decide` and `deviation` are refused because they are act writers: "The chat prepares and relays." (ADR 0006, Decision 1). `llm_live` is refused because it is a paid live run (D-174 item 4). A `public_check` read is refused because there is no chat at the held-out pass (D-165 item 3).

## What the tool gives back

- A refusal: its code, why it refused, and that nothing was started.
- The CLI's answer: the object it printed, its error with the exit code, or what the bridge holds of a call that got no usable answer. A command that got no usable answer may have written. The tool does not start it again, and it asks for a new read of the Study first.
