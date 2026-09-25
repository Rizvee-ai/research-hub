# Test case results

Run 25 September 2026, 19:27. Produced by `run_cases.py`.

| ID | Case | Result | What it showed |
| --- | --- | --- | --- |
| C1 | Different words, same meaning | partial | retrieval accuracy 80% — the source document came back in the top 20 for 77 of 96 paraphrased questions, and was first for 38. One passage per document, so the figure describes the collection rather than its longest documents; 4 questions named nothing and were dropped. Target is 90% |

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
