# agent-evals

A Python library for testing AI agents: hand it your agent and a list of questions, and it tells you how
the agent did.

It measures four things — whether the answer is right, whether the steps made sense, what it cost in time
and money, and whether any rule was broken — running each question several times and reporting a range
around every number.

Works with any agent in any framework — you hand it a function. No required dependencies.

## Why

- **Agents aren't repeatable.** The same question twice gives different wording, tools, cost, sometimes
  a different answer. One run tells you little, so this repeats each question and reports the spread.
- **Right isn't enough.** An agent can be correct and still take twenty steps to get there, or call a
  tool it should never have touched.
- **Cost and speed are findings, not footnotes.** Latency percentiles and cost per question each come
  with a range, so an expensive or slow pattern surfaces as something to go and fix rather than as a
  number at the bottom of a report. Most of what you can actually improve shows up here.

## Install

```bash
pip install agent-evals
```

Zero dependencies. Add what you need:

```bash
pip install "agent-evals[cli]"         # the agent-evals command
pip install "agent-evals[databricks]"  # read a Databricks SQL warehouse
pip install "agent-evals[mlflow]"      # mine questions from MLflow traces, log reports to it
```

Quote the brackets: most shells read them as a filename pattern. Needs Python 3.11 or newer.

Pin a version if you are comparing scores over time — the library changing under you between runs
would change the numbers along with it.

## First eval

```python
import asyncio
from agent_evals import EvaluationCase, EvaluationVariant, ExactMatch, PredictionResult, run_repeated

def my_agent(question):                           # your agent, which knows nothing about this library
    return "4" if "2+2" in question else "I don't know"

def run_one(case, variant):                       # the glue
    return PredictionResult(answer=my_agent(case.inputs["question"]))

cases = [
    EvaluationCase("adds", {"question": "what is 2+2?"}, expected="4"),
    EvaluationCase("subtracts", {"question": "what is 9-3?"}, expected="6"),
]

async def main():
    run = await run_repeated(cases, [EvaluationVariant("v1")], run_one, [ExactMatch(name="correct")])
    print(run.case_means("v1", "correct"))

asyncio.run(main())
```

```
{'adds': 1.0, 'subtracts': 0.0}
```

One right, one wrong. You supplied three things, and everything else is built on them:

| | What it is | Above |
|---|---|---|
| **Runner** | Takes one question, returns what your agent said | `run_one` |
| **Cases** | The questions, each with what you expect | `cases` |
| **Scorers** | Turn an answer into a number from 0 to 1 | `ExactMatch` |

A **variant** is one version of your agent — add more to compare old against new.

## Scoring the steps too

Return a trajectory (the steps the agent took) alongside the answer, and build a full scorecard.

```python
import asyncio
from agent_evals import (DatasetManifest, EvaluationCase, EvaluationDataset, EvaluationVariant, ExactMatch,
                         GenericStep, GenericTrajectory, PredictionResult, RunRecord, RunSettings,
                         ToolSelection, build_report, report_markdown, run_suite)

def my_agent(question):                           # an answer and the tools it called
    return "400 clicks.", [("lookup", {"campaign": question.split()[-1]})]

def run_one(case, variant):
    answer, calls = my_agent(case.inputs["question"])
    steps = [GenericStep(tool, args) for tool, args in calls]
    return PredictionResult(answer=answer, trajectory=GenericTrajectory(case.inputs["question"], steps, answer))

def answered(case, output):                       # the report needs one scorer named "success"
    return ExactMatch(name="success")(EvaluationCase(case.case_id, {}, case.expected["answer"]), output)

cases = [EvaluationCase("c1", {"question": "how many clicks for spring"},
                        expected={"answer": "400 clicks.", "tools": ["lookup"]})]
dataset = EvaluationDataset("mine", "v1", cases)
manifest = DatasetManifest.from_dataset(dataset, suite="regression")

async def main():
    run = await run_suite(dataset, manifest, [EvaluationVariant("mine")], run_one, [answered, ToolSelection()],
                          metric_id="mine", metric_version="1", settings=RunSettings(repeats=3))
    record = RunRecord.from_run(run, manifest, "mine", run_id="r1")
    print(report_markdown(build_report(run, manifest, "mine", record=record)))

asyncio.run(main())
```

Two things to know when reading the scorecard:

- **`not measured` is not zero.** Nothing scored it, and the row says why. A zero would mean the agent
  scored nothing; conflating the two is how eval reports mislead people.
- **The range matters more than the number.** 0.83 ranging 0.50 to 1.00 means six questions is too few.

## What it scores

- **Answer** — exact, contains, regex, numeric tolerance, rubric partial credit, pass@k.
- **Steps** — which tools, in what order, with what arguments; rules like "never call this" or "at most five".
- **Speed and cost** — latency percentiles and cost per question with ranges, step counts, loop detection.
- **Rules** — policy checks that fail a run outright. They detect a forbidden call after the fact and
  cannot prevent it, so enforce anything destructive inside your agent.

Also: reproducible datasets with a checksum, golden trajectories, comparing two versions with proper
statistics, threshold calibration, and an optional MLflow log (`pip install "agent-evals[mlflow]"`).
Two scorers are experimental — plan adherence and multi-step coherence ask a model to judge the agent's
reasoning, and nobody has measured how often it agrees with a human. Reports using them say so.

## Checking figures against your own database

An agent that writes "spend was $18,450" is either right or wrong, and your table knows which. Give a
case the query that settles it:

```python
case = EvaluationCase("q1", {"prompt": "how did spring do?"}, expected={"reference": {
    "sql": "SELECT SUM(spend) AS spend, SUM(clicks) AS clicks FROM delivery WHERE campaign = :name",
    "parameters": {"name": "spring"},
    "fields": {"spend": "spent", "clicks": "clicks"},   # column -> the word to look for in the answer
}})

accuracy = AnswerRubric(
    criteria=reference_criteria(SqlReference(execute=open_executor("sqlite", {"path": "my.db"}))),
    rubric=WeightedRubric(weights={"figures": 0.7, "completeness": 0.3}),
)
```

Everything above imports flat: `from agent_evals import AnswerRubric, SqlReference,
reference_criteria, open_executor, WeightedRubric`.

The report then names the field, not just a score:

```
summer: clicks said 980, table says 615      a wrong figure
autumn: never stated clicks                  an omitted figure, which costs completeness, not correctness
winter: not checked - the query returned no rows
```

Those are three different failures with three different fixes, which is why they are reported apart.
A question your table cannot answer is **excluded, never scored zero** — the agent is not blamed for a
row that does not exist.

**Any database.** `open_executor` ships one adapter, `sqlite`. Everything else is a function you
supply, which is why this package has no dependencies:

```python
SqlExecutor = Callable[[str, Mapping[str, Any]], Awaitable[list[dict]]]
```

Six lines over your own driver and `SqlReference` never learns which database is behind it. Write
`:name` parameters; if your driver wants another style, your function rewrites it. The SQL itself is
yours — the library never writes a query or guesses what a question means.

Runnable: `examples/agent_evals_sql_reference/`.

## Verify the claims

```bash
python -m agent_evals.selfcheck
```

```
ok: importing agent_evals loads none of langchain, langchain_core, learning_control_plane, litellm, mlflow, openai, penguiflow
ok: the database layer loads no adapter until one is asked for by name
ok: 3 agent shapes (plain function, coroutine function, callable object) scored identically
     (timing and spend are measured per run, so they are reported but not compared)
     success_rate: 1.0
     tool_selection: 1.0
```

No framework, model client or backend is pulled in, no database driver loads until you name one,
and the same agent written three ways scores identically. Exits non-zero on failure, so it runs in CI.

## Repo layout

```
agent_evals/      the package: six folders, plus __init__.py, selfcheck.py and py.typed
tests/            479 tests, mirroring the package folders, plus contract/
examples/         three runnable examples
pyproject.toml    zero dependencies; mlflow is the one optional extra
CHANGELOG.md      version history and known limits
```

No `src/` layout, no `docs/`, no CI config. Everything is re-exported, so
`from agent_evals import ExactMatch` works regardless of which folder a name lives in, so you never need
to import these paths directly.

### The package, 32 modules

| Folder | Modules | Notes |
|---|---|---|
| `core/` | `evaluation`, `datasets`, `prediction`, `steps`, `evidence`, `splits` | The shapes everything else speaks in. Cases, datasets and variants live in **`evaluation`**, not `datasets`. |
| `running/` | `runner`, `execution`, `suites`, `comparison`, `shadow` | Repeats, concurrency, the two suite kinds, comparing variants, shadow runs against recorded inputs. |
| `scoring/` | `outcome`, `trajectory`, `operational`, `policy`, `golden`, `judging`, `llm_judge`, `answer`, `claims`, `reference` | One module per layer, in the order above: answer, steps, speed and cost, rules. `llm_judge` holds the two experimental scorers. |
| `stats/` | `statistics`, `calibration`, `repeatability`, `thresholds`, `profiles` | Paired bootstrap intervals, run-to-run noise, pass@k, and the bars a promotion gate uses. |
| `sql/` | `executor`, `registry`, `sqlite` | What a database has to offer: run a statement, return rows. The registry loads no adapter until one is asked for by name. |
| `reporting/` | `report`, `diffing`, `mlflow_backend` | The scorecard, run-to-run diffs, and the only module with an optional dependency. |

### Tests

`pip install -e ".[dev]"` then `pytest`. 479 tests: **461 pass, 18 skip.**

| Folder | Covers |
|---|---|
| `core/`, `running/`, `scoring/`, `stats/`, `reporting/` | The matching package folder |
| `contract/` | What the package promises as a whole: agent shapes, the self-check, and that the offline examples still run |

The 18 skips need something this repository deliberately does not depend on, and each says so as it
skips: LangChain for the live example, the `penguiflow` monorepo for the cross-package parity checks,
and `mlflow` for one reporting test.

### Examples

- `examples/agent_evals_quickstart/` — a plain function with two tools, offline, no credentials.
- `examples/agent_evals_sql_reference/` — figures checked against a table, offline on in-memory SQLite.
- `examples/agent_evals_live_langchain/` — a real LangChain agent on a live model endpoint. **Not
  runnable outside the original monorepo:** it imports `learning_control_plane`, which is not published.
  Its test drives it offline with a scripted model instead.

Run one with `python examples/<name>/flow.py` from a clone. Needs Python 3.11 or newer.

Version `0.13.0`, extracted from the `penguiflow` monorepo, which keeps the full history.
