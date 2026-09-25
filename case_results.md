# Test case results

Run 25 September 2026, 14:27. Produced by `run_cases.py`.

| ID | Case | Result | What it showed |
| --- | --- | --- | --- |
| C6 | A topic not covered | pass | 10 of 10 questions with no bearing on the collection stayed under the 0.46 threshold; the closest reached 0.411 |
| D1 | Unanswerable question | pass | all 10 of 10 questions with no bearing on the collection were turned away, 10 by the 0.46 threshold and 0 by the model saying the passages do not answer them. Nothing was invented. The 0 that reached the model cost a call each and left the refusal to its judgement |

## Not covered by this script

| ID | Case | Why |
| --- | --- | --- |
| B2 | Outside the categories | Needs a person to read and judge |
| D2 | Every claim traceable | Needs a person to read and judge |
| D4 | Conflicting evidence | Needs a person to read and judge |
| D5 | A hedged finding | Needs a person to read and judge |
| E2 | Statements about gaps | Needs a person to read and judge |
| E4 | Brief against review | Needs a person to read and judge |
| A4 | Reference list | Needs a paper with pages of references |
| B4 | Multi-sector document | This schema records topics, not sectors |
| G4 | Someone else's machine | Answered when Richa tests it |
