# English parity translations

The English twin uses the English engine and panel of the old Hypotrail at
`4ef4925af0568dbf57ec02ed872a1af2b1f00b14`. The capture records those texts directly.
Proposal restatements in the replay bundle already have English versions and are
used as written. These are scripted inputs to the old engine.

## Chat and scripted inputs

The following texts were available only in French in the frozen reproduction.
"Translated" marks these texts in the twin or in this inventory.

| Location | French source | English rendering |
|---|---|---|
| Data, user opening | `docs/acceptance/runs/copilot-companion-2026-10-26.md:10` | I want to do this study, where do we start? |
| Data, data card fold | Replay builder, `chat_for` | The data card as returned by the engine (the agent summarized it in at most 150 words) |
| Quality check and Models, no-pause message | Replay builder, `chat_for` | No pause at this step: the work planned between two pauses is done without asking again, and the guide stops at the next pause ({next step}). |
| Preparation, verdict fold | Replay builder, `chat_for` | What the quality check found, column by column |
| Preparation, alternative lead | Replay builder, `chat_for` | Comparison option · {label}: {reason} |
| Proposal tool label | Replay builder, `chat_for` | (the agent writes the restatement) |
| Explanation return | Replay builder, `explain_parts` | Here is the decision again. |
| Absent explanation | Replay shell, `resolve` | (The engine has no explanation recorded for this step.) |
| Typed choice acknowledgment | Replay shell, `resolve` | I propose your answer as the decision, in your own words. It is waiting for your confirmation. |
| Unanswered picker | Old `agent_files.py:134` and replay shell, `resolve` | Nothing is recorded yet: here is the decision again. |
| Change prompt | Replay shell, `resolve` | What do you want to change? |
| Change prompt, replay note | Replay shell, `resolve` | In the old tool, the agent proposed the decision again with your change (`hypotrail decide propose`) and asked the same closed question. This replay follows the recorded default path. Type your change to see the sequence or adopt the proposal. |
| Alternative picker choice, replay note | Replay shell, `resolve` | The replay captured the path with "{recorded option}". In the old tool, the agent turned your picker choice into a proposal and asked the closed question for confirmation. The replay continues with the recorded proposal. |
| Free question outside a pause | Replay shell, `Chat` | Away from a pause, the old agent answered the question without moving in the plan ("explain it another way", "show me the calculation", "let me try"). The replay has no generated answer here. |
| Model choice, typed confirmation | Replay `rest.json`, `model_choice.words` | Yes, I adopt the linear model, because it is the simplest within one standard error of the best. |
| Final test, typed confirmation | Replay `rest.json`, `final_test.words` | Yes, I open the final test now, because my choices are fixed. |
| Conclusion, typed confirmation | Replay `rest.json`, `conclusion.words` | Yes, I adopt the linear model, because the criterion fixed in advance is met on the final test, with its limits. |
| Conclusion, scripted Decision text | Replay `rest.json`, `conclusion.value.text` | On the {sealed} rows of the final test, set aside before any look, the linear model is off by {mae} mpg on average. The criterion fixed in advance is met. The study says nothing about cars more recent than these data, nor about why: weight is associated with fuel efficiency, nothing more. |
| End, picker question | Old `docs/plans/mockups/panel-all-steps-fr.html:956` | What do you want to do with this result? |
| End, picker options | Same source | Present the conclusion to your pair / Prepare the handoff pack / Prepare the Azure ML export |
| End, after-actions note | Replay builder, `fin_after` | In the old tool, presenting took place outside the tool. `hypotrail export handoff` wrote the handoff pack (panel button W7 under "And after"). The Azure ML export plan was a read that wrote nothing. |
| End, handoff fold | Replay builder, `fin_after` | The handoff pack written by the engine for this study (handoff.md) |

The three typed confirmations and the Conclusion text are from the sanctioned
Auto MPG script. They are translations of recorded test inputs. Interacting
with the twin records the visitor's own words.

## Review shell

The wrapper's English heading, legend, navigation, verdict form, source notes,
panel status notes, and chat controls translate the frozen reproduction's
`build/shell.html` and `build/build.py`. The shell labels this wrapper as
translated. The English source of the wrapper is in the English twin's
`build/shell.html`, and its structured screen labels and source notes are in
`build/build.py`. This copy belongs to the offline review page.

The eight archival mock-ups are the old repository's original French files.
The approved mock-up tab uses the same French design source and sets the selected
step. The Study panel, reports and engine chat output use the old tool's English
version.
