# agent-evals

Measure four things about an AI agent: whether the answer is right, whether it took sensible steps to
get there, what it cost in time and money, and whether it broke any rules. Give it a fixed set of
questions; it runs each several times, scores all four, and reports a range around every number.

Works with any agent in any framework — you hand it a function. No required dependencies.

## Why

- **Agents aren't repeatable.** The same question twice gives different wording, tools, cost, sometimes
  a different answer. One run tells you little, so this repeats each question and reports the spread.
- **Right isn't enough.** An agent can be correct while wasting twenty steps, calling a tool it
  shouldn't, or costing a dollar a question. One accuracy number hides all of that.

## Install

```bash
uv pip install "agent-evals @ https://github.com/rishikeshyadav-lg/agent-evals/archive/<commit>.tar.gz"
```

Pin a commit. Not on PyPI.

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
- **Rules** — policy checks that fail a run outright.

Also: reproducible datasets with a checksum, golden trajectories, comparing two versions with proper
statistics, threshold calibration, and an optional MLflow log (`pip install "agent-evals[mlflow]"`).

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

## What this is not

- **Not an agent framework.** It evaluates agents; it doesn't build them.
- **Not a sandbox.** Policy checks detect a forbidden call after the fact, they cannot stop it. Enforce
  destructive actions inside your agent.
- **Not a tracing system.** It reads what your runner hands it.

Plan adherence and multi-step coherence are **experimental** — a model judges the agent's reasoning, and
nobody has measured how often it agrees with a human. Reports using them say so.

## Layout

Everything is re-exported, so `from agent_evals import ExactMatch` works regardless of where it lives.

| Folder | Holds |
|---|---|
| `core/` | Cases, datasets, what a run returned, the steps it took |
| `running/` | Repeats, concurrency, suites, comparing variants |
| `scoring/` | One module per layer: answer, steps, speed and cost, rules |
| `stats/` | Intervals, repeatability, thresholds |
| `reporting/` | The scorecard, run diffs, optional MLflow |

Tests mirror those, plus `contract/` for what the package promises.

- `examples/agent_evals_quickstart/` — runnable, offline.
- `examples/agent_evals_live_langchain/` — a real LangChain agent on a live endpoint.
- `tests/` — 408 tests via `pip install -e ".[dev]"` then `pytest`. 391 pass, 18 skip (they need
  LangChain or the monorepo) and each says so.

Version `0.1.0`, extracted from the `penguiflow` monorepo, which keeps the full history.
