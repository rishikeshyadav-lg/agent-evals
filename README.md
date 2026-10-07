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

Pin a version — `agent-evals==0.1.0` — if you are comparing scores over time. The library changing under
you between runs would change the numbers along with it.

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

## Verify the claims

```bash
python -m agent_evals.selfcheck
```

```
ok: importing agent_evals loads none of langchain, langchain_core, learning_control_plane, litellm, mlflow, openai, penguiflow
ok: 3 agent shapes (plain function, coroutine function, callable object) scored identically
```

No framework, model client or backend is pulled in, and the same agent written three ways scores
identically. Exits non-zero on failure, so it runs in CI.

## Repo layout

```
agent_evals/      the package: five folders, plus __init__.py, selfcheck.py and py.typed
tests/            408 tests, mirroring the package folders, plus contract/
examples/         two runnable examples
pyproject.toml    zero dependencies; mlflow is the one optional extra
CHANGELOG.md      version history and known limits
```

No `src/` layout, no `docs/`, no CI config. Everything is re-exported, so
`from agent_evals import ExactMatch` works regardless of which folder a name lives in — you never import
these paths directly.

### The package, 26 modules

| Folder | Modules | Notes |
|---|---|---|
| `core/` | `evaluation`, `datasets`, `prediction`, `steps`, `evidence`, `splits` | The shapes everything else speaks in. Cases, datasets and variants live in **`evaluation`**, not `datasets`. |
| `running/` | `runner`, `execution`, `suites`, `comparison`, `shadow` | Repeats, concurrency, the two suite kinds, comparing variants, shadow runs against recorded inputs. |
| `scoring/` | `outcome`, `trajectory`, `operational`, `policy`, `golden`, `judging`, `llm_judge` | One module per layer, in the order above: answer, steps, speed and cost, rules. `llm_judge` holds the two experimental scorers. |
| `stats/` | `statistics`, `calibration`, `repeatability`, `thresholds`, `profiles` | Paired bootstrap intervals, run-to-run noise, pass@k, and the bars a promotion gate uses. |
| `reporting/` | `report`, `diffing`, `mlflow_backend` | The scorecard, run-to-run diffs, and the only module with an optional dependency. |

### Tests

`pip install -e ".[dev]"` then `pytest`. 408 tests: **391 pass, 18 skip.**

| Folder | Covers |
|---|---|
| `core/`, `running/`, `scoring/`, `stats/`, `reporting/` | The matching package folder |
| `contract/` | What the package promises as a whole: agent shapes, the self-check, and that both examples still run |

The 18 skips need something this repository deliberately does not depend on, and each says so as it
skips: LangChain for the live example, the `penguiflow` monorepo for the cross-package parity checks,
and `mlflow` for one reporting test.

### Examples

- `examples/agent_evals_quickstart/` — a plain function with two tools, offline, no credentials.
- `examples/agent_evals_live_langchain/` — a real LangChain agent on a live model endpoint. Needs
  credentials and network; its test drives it offline with a scripted model instead.

Version `0.1.0`, extracted from the `penguiflow` monorepo, which keeps the full history.
