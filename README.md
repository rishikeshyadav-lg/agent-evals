# agent-evals

A library for testing how well an AI agent actually does its job.

If you have an agent — anything that takes a question and returns an answer, maybe calling some tools
along the way — this runs it over a fixed list of questions, scores what came back, and gives you a
report. It works with any agent, in any framework, because you hand it a function rather than
inheriting from anything. It has no required dependencies.

## Why you'd want this

Normal tests ask "did this function return 4?" Agents are harder, for two reasons.

**They're not repeatable.** Ask an agent the same question twice and you can get different wording,
different tools, a different cost, and sometimes a different answer. So a single run tells you very
little. This library runs each question several times and reports the spread, not just one number.

**Being right isn't the only thing that matters.** An agent can reach a correct answer while taking
twenty wasted steps, calling a tool it shouldn't have touched, or costing a dollar a question. A
single accuracy score hides all of that, so this scores four separate things: the answer, the steps,
the speed and cost, and the rules.

## Install

```bash
uv pip install "agent-evals @ https://github.com/rishikeshyadav-lg/agent-evals/archive/<commit>.tar.gz"
```

Pin a commit and bump it when you choose to, so a dependency never changes under you. It's not on
PyPI.

## Your first eval

Copy this into a file and run it. The "agent" is a deliberately bad function so you can see a failure.

```python
import asyncio
from agent_evals import EvaluationCase, EvaluationVariant, ExactMatch, PredictionResult, run_repeated

# 1. Your agent. It knows nothing about this library.
def my_agent(question):
    return "4" if "2+2" in question else "I don't know"

# 2. The glue: take one question, call your agent, hand back what it said.
def run_one(case, variant):
    return PredictionResult(answer=my_agent(case.inputs["question"]))

# 3. The questions, each with the answer you expect.
cases = [
    EvaluationCase("adds", {"question": "what is 2+2?"}, expected="4"),
    EvaluationCase("subtracts", {"question": "what is 9-3?"}, expected="6"),
]

async def main():
    run = await run_repeated(cases, [EvaluationVariant("v1")], run_one, [ExactMatch(name="correct")])
    print(run.case_means("v1", "correct"))

asyncio.run(main())
```

You'll see:

```
{'adds': 1.0, 'subtracts': 0.0}
```

One question right, one wrong. That's a complete eval: questions in, scores out.

### The three pieces you just wrote

Everything in this library is built on these three. Once they click, the rest is detail.

| You provide | What it is | In the example |
|---|---|---|
| A **runner** | A function taking one question, returning what your agent said | `run_one` |
| **Cases** | The fixed questions, each with what you expect | `cases` |
| **Scorers** | Functions that turn an answer into a number from 0 to 1 | `ExactMatch` |

A **case** is one test question. A **variant** is one version of your agent — you'll have one to start
with, and more when you want to compare an old version against a new one. A **scorer** gives a number
between 0 and 1, where 1 is perfect.

## Scoring the steps, not just the answer

Most agents call tools. To score which tools your agent used, tell the library about them by returning
a trajectory — the list of steps the agent took — alongside the answer.

This version also builds a **scorecard**: the full report, with a range around every number.

```python
import asyncio
from agent_evals import (DatasetManifest, EvaluationCase, EvaluationDataset, EvaluationVariant, ExactMatch,
                         GenericStep, GenericTrajectory, PredictionResult, RunRecord, RunSettings,
                         ToolSelection, build_report, report_markdown, run_suite)

def my_agent(question):                           # returns an answer and the tools it called
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

`RunSettings(repeats=3)` is the important part: it asks each question three times, which is what makes
the ranges in the report mean something.

### Reading the report

The scorecard has a row per measure. Two things are worth knowing.

**"not measured" is a real answer, and it's deliberate.** If you didn't configure a scorer for
something, the report says so and why, rather than printing a reassuring zero:

```
| Argument correctness | trajectory | not measured | - | - | no scorer produced 'argument_correctness' |
| Cost per task | operational | not measured | - | - | the runner reported no cost |
```

A zero would read as "your agent scored nothing." "Not measured" reads as "nobody checked." Those are
very different, and conflating them is how evaluation reports mislead people.

**The range matters more than the number.** A success rate of 0.83 with a range of 0.50 to 1.00 means
six questions is not enough to know much. Add questions and the range narrows.

## What it can score

Four layers. Start with the first, add the others when you need them.

- **The answer.** Exact match, contains, regex, numbers with a tolerance, partial credit against a
  rubric, and pass@k (did any of k attempts work).
- **The steps.** Which tools were called, in what order, with what arguments, and rules like "must
  never call this tool" or "at most five calls."
- **Speed and cost.** Latency percentiles and cost per question, each with a range; step counts; loop
  detection.
- **The rules.** Policy checks that mark a run as failed when the agent did something it shouldn't.

There's more once you need it: datasets saved to disk with a checksum so a run is reproducible, golden
trajectories, comparing two versions with proper statistics, calibrating a pass/fail threshold from a
baseline, and an optional MLflow log (`pip install "agent-evals[mlflow]"`).

## Checking the claims yourself

Two claims here are easy to make and worth verifying. Run this after installing:

```bash
python -m agent_evals.selfcheck
```

```
ok: importing agent_evals loads none of langchain, langchain_core, learning_control_plane, litellm, mlflow, openai, penguiflow
ok: 3 agent shapes (plain function, coroutine function, callable object) scored identically
```

The first line proves importing this pulls in no agent framework, model client or backend. The second
writes the same agent three different ways and checks the scorecards match, which is what "works with
any framework" has to mean to be worth anything. It exits non-zero on failure, so you can put it in CI.

## What this is not

- **Not an agent framework.** It evaluates agents; it doesn't help you build one.
- **Not a sandbox.** Policy checks *detect* a forbidden tool call after the fact. They cannot stop it.
  Enforce anything destructive inside your agent, not here.
- **Not a tracing system.** Bring your own; this reads what your runner hands it.

Two scorers are **experimental**: plan adherence and multi-step coherence, both of which ask a language
model to judge the agent's reasoning. Nobody has measured how often they agree with a human, and any
report using them says so.

## Where things are

- `examples/agent_evals_quickstart/` — a runnable file, offline, close to the second example above.
- `examples/agent_evals_live_langchain/` — a real LangChain agent against a live model endpoint.
- `tests/` — 402 tests. Run them with `pip install -e ".[dev]"` then `pytest`; 385 pass and 18 skip,
  because they need either LangChain or the monorepo this was extracted from. Each says so when it skips.

Version `0.1.0`. Extracted from the `penguiflow` monorepo, which keeps the full history at
`packages/agent-evals`.
