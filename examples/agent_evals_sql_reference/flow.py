"""Check an agent's figures against your own database, offline, in one file.

    uv run python examples/agent_evals_sql_reference/flow.py

Everything here runs on the standard library: the "warehouse" is an in-memory SQLite table, so this
needs no credentials, no network and no extras installed. Point `open_executor` at another adapter
and the rest is unchanged.

The agent answers four questions and gets each one wrong in a different way, because that is what
makes the report worth reading:

    spring   every figure right
    summer   states clicks wrongly        -> loses on figures, not on completeness
    autumn   never mentions clicks        -> loses on completeness, not on figures
    winter   is not in the table at all   -> scored on neither; excluded and named

The last two are the point. An omitted figure and a wrong one are different mistakes, and a question
your table cannot answer is not the agent's failure at all.
"""

from __future__ import annotations

import asyncio

from agent_evals import (
    DatasetManifest,
    EvaluationCase,
    EvaluationDataset,
    EvaluationVariant,
    PredictionResult,
    RunRecord,
    RunSettings,
    ScorecardMetrics,
    SqlReference,
    SuiteRule,
    Tolerance,
    WeightedRubric,
    build_report,
    report_markdown,
    run_suite,
)
from agent_evals.scoring.answer import AnswerRubric
from agent_evals.scoring.reference import reference_criteria
from agent_evals.sql import open_executor

# ---- your warehouse, which here is a file that never touches disk ------------------------------------
DELIVERY = [
    # campaign, spend, clicks, ctr (stored as a fraction, as a real table usually would)
    ("spring", 18_450.00, 400, 0.0042),
    ("summer", 22_100.00, 615, 0.0051),
    ("autumn", 9_100.00, 150, 0.0038),
]


async def build_table():
    """An executor over a table standing in for yours."""

    execute = open_executor("sqlite", {"path": ":memory:"})
    await execute("CREATE TABLE delivery (campaign TEXT, spend REAL, clicks INTEGER, ctr REAL)", {})
    for row in DELIVERY:
        await execute(
            "INSERT INTO delivery VALUES (:campaign, :spend, :clicks, :ctr)",
            dict(zip(("campaign", "spend", "clicks", "ctr"), row, strict=True)),
        )
    return execute


# ---- the agent under test: it knows nothing about agent_evals ----------------------------------------
ANSWERS = {
    "spring": "Spring spent $18,450 across 400 clicks, a ctr of 0.42%.",
    "summer": "Summer spent $22,100 across 980 clicks, a ctr of 0.51%.",  # clicks is wrong
    "autumn": "Autumn spent $9,100, a ctr of 0.38%.",  # clicks never mentioned
    "winter": "Winter spent $5,000 across 90 clicks, a ctr of 0.30%.",  # no such campaign
}


def my_agent(question: str) -> str:
    return ANSWERS[question]


def run_one(case: EvaluationCase, variant: EvaluationVariant) -> PredictionResult:
    return PredictionResult(answer=my_agent(case.inputs["campaign"]))


# ---- the cases, each carrying the query that establishes its truth ------------------------------------
def case_for(campaign: str) -> EvaluationCase:
    return EvaluationCase(
        campaign,
        {"campaign": campaign},
        expected={
            "reference": {
                "sql": "SELECT spend, clicks, ctr FROM delivery WHERE campaign = :name",
                "parameters": {"name": campaign},
                # column -> the word to look for in the answer, when they differ
                "fields": {"spend": "spent", "clicks": "clicks", "ctr": "ctr"},
            }
        },
    )


async def main() -> str:
    execute = await build_table()

    reference = SqlReference(
        execute=execute,
        # The table stores ctr as a fraction while the agent writes it as a percentage.
        fraction_fields=["ctr"],
        # Money to the penny; a click count is a whole thing either way.
        tolerances={"spend": Tolerance("relative", 0.001, floor=0.01), "clicks": Tolerance("absolute", 0.5)},
    )
    accuracy = AnswerRubric(
        criteria=reference_criteria(reference),
        rubric=WeightedRubric(weights={"figures": 0.7, "completeness": 0.3}),
    )

    cases = [case_for(name) for name in ANSWERS]
    dataset = EvaluationDataset("delivery", "v1", cases)
    manifest = DatasetManifest.from_dataset(dataset, suite="capability")
    # Without "exclude", a case the table cannot answer would stop the run rather than be set aside.
    rule = SuiteRule("accuracy", unmeasured_cases="exclude")

    run = await run_suite(
        dataset, manifest, [EvaluationVariant("my_agent")], run_one, accuracy,
        metric_id="delivery", metric_version="1", settings=RunSettings(repeats=1),
    )  # fmt: skip

    record = RunRecord.from_run(run, manifest, "my_agent", run_id="sql-reference-example")
    report = build_report(
        run, manifest, "my_agent", record=record, rule=rule, metrics=ScorecardMetrics(success="accuracy")
    )

    lines = [report_markdown(report), "", "## What each answer got wrong", ""]
    for row in run.rows:
        details = row.result.score_details
        wrong = details.get("accuracy.figures", {}).get("disagreed") or {}
        missing = details.get("accuracy.completeness", {}).get("never_stated") or []
        unmeasured = details.get("accuracy.measured", {}).get("unmeasured") or {}
        if unmeasured:
            lines.append(f"- **{row.case_id}**: not checked — {'; '.join(sorted(set(unmeasured.values())))}")
        for name, verdict in wrong.items():
            lines.append(
                f"- **{row.case_id}**: {name} said {verdict['claimed']:g}, table says {verdict['expected']:g}"
            )
        for name in missing:
            lines.append(f"- **{row.case_id}**: never stated {name}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(asyncio.run(main()))
