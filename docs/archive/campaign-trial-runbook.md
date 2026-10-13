> **Archived 2026-10-13. History, not instruction.**
>
> The runbook for a one-off trial of this package against the campaign performance agent, from
> `~/Desktop/agent-evals-campaign-trial/`. Superseded by that project's own `prd-eval/` scripts. Kept
> because its first step records why the trial was needed at all: the campaign pinned agent-evals to a
> monorepo commit with no SQL scorer, so the newer build had to be installed over it.

---

# Trying agent-evals on the campaign performance agent

Four steps. The first three cost nothing; only step 4 calls the agent.

## 1. Install the new agent-evals into the campaign environment

The campaign repo pins agent-evals to a monorepo commit that has no SQL scorer, so the trial needs
the new build installed over it. This is reversible.

```bash
cd ~/Desktop/acp-eval-stages
uv pip install -e ~/Desktop/agent-evals-repo
.venv/bin/python -c "from agent_evals import SqlReference; print('ok')"
```

**To undo it afterwards:** `cd ~/Desktop/acp-eval-stages && uv sync` puts the pinned version back.
Do that before running the real eval suites, so they run against what CI runs.

## 2. Make sure the warehouse credentials are in the environment

The trial reads the same config as the agent, so whatever you normally export for a live eval is what
it needs — `DATABRICKS_HOST` and a token, plus the delivery-table settings already in your `.env`.
Nothing is written to your shell history by the script; it reads the environment.

## 3. Inspect, which is free

```bash
cd ~/Desktop/acp-eval-stages
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --inspect
```

One SQL query, no agent calls. It prints the table name, how many columns it has, whether the four
columns the trial needs are present, and how many campaigns have spend. It withholds the campaign
names. If `missing` is anything but `none`, stop — the SQL in `trial.py` needs the real column names
before step 4 is worth paying for.

## 4. Run it, which costs money

```bash
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --run --limit 2
```

Two campaigns, one agent call each, roughly **$1.30**. `--limit` above 5 refuses without `--yes-really`,
so a typo cannot spend $40. Add `--save ~/Desktop/campaign-trial-report.md` for the full
Markdown scorecard — keep that path outside any repository.

## What you should see

```
asking the agent about 2 campaign(s); about $1.30

mean accuracy : 0.912 over 2 case(s)
not checked   : 0
  campaign-1: ctr said 0.38, table says 0.0042
  campaign-1: never stated impressions
```

Three kinds of line, and the difference between them is the point:

- **`X said A, table says B`** — the agent stated a figure and it disagrees with your table.
- **`never stated X`** — the agent did not mention a figure the question asked for. A different
  failure, and it costs completeness rather than correctness.
- **`not checked — <reason>`** — your table could not answer, so the case is set aside instead of
  scored zero. The agent is not blamed for a row that does not exist.

## If it goes wrong

- **`this agent-evals has no SQL scorer`** — step 1 did not take. The script tells you the two
  commands; re-run the install and check the `import` line prints `ok`.
- **`CAMPAIGN_DELIVERY_TABLE_FULL_NAME is not set`** — step 2 did not take. Export the same
  environment you use for a live eval.
- **`the reference query failed: ...`** — the trial's SQL does not match your table. Run `--inspect`
  and fix `SUMMED` / `DERIVED` at the top of `trial.py`.
- **Every campaign reports the same figure wrong** — suspect the reference SQL before the agent. A
  division that returns an integer gave `ctr = 0` for every row during development, which looked
  exactly like an agent bug and was not one.
- **`the reference query returned N rows; it must return one`** — the WHERE clause is not narrowing
  to a single campaign; the scorer refuses to guess which row you meant.

## What this does and does not prove

It proves the whole path works against your real agent and your real warehouse: the question, the
agent call, the reference query, the comparison, the report.

It does not prove the SQL asks the right question. The trial asks for lifetime totals per campaign
with no date filter, which is a deliberately simple question. If the agent answers about a different
period than the reference query covers, the figures will disagree for a reason that is nobody's bug
but the case's. That is the thing to look at first if a disagreement surprises you.

---

# Running against a deployed app (rc1 or prd)

An in-process run tests the code in your checkout. A deployed run tests what users actually reach:
the deployment, its settings and its services. Add `--app`:

```bash
# rc1 — same deployment path as production, without production's consequences
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --run --app rc1-ai-campaign-performance --limit 2

# prd — refuses without --yes-really
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --run --app prd-ai-campaign-performance --limit 2 --yes-really
```

It resolves the app's URL through the Databricks SDK and authenticates as the signed-in Databricks
user, so no token is ever passed on a command line. `az`/`databricks auth login` must be current.

Known app names in this workspace: `rc1-ai-campaign-performance`, `prd-ai-campaign-performance`,
`dev-ai-campaign-performance`.

## What a deployed run cannot measure

The app returns an answer and its tool calls, but no cost, no token usage and no per-tool timing. So
on a remote run those metrics are reported **not measured**, with the reason — never as zero. If you
need cost per task, that has to come from an in-process run or from the traces.

## Prefer rc1 unless you specifically need prd

Both exercise the same deployment path. A prd run spends production budget, consumes production rate
limits, and writes sessions and traces into production. The questions this trial asks are read-only,
but the agent's own calls are not free and not invisible. Start with rc1.

## There was already a path for this

`scripts/remote_baseline.py --app <name> --prompts <file> --output-dir <folder>` has existed and is
tested. It asks a prompts file of a deployed app and writes a runs file for the judge to score later.
What it could not do is check figures against your warehouse: the cases it builds carry no reference
query, so there is nothing for a SQL scorer to compare against. That is the gap `--app` closes here.

---

# Running against real production questions

The sections above ask questions this script makes up. This section asks questions **real users
actually asked**, mined from production traces into `evaluation_bank_v1.json` (38 questions).

## Why there is a manual step

A mined question is text. The scorer needs SQL. "How did campaign X do last week" has to become a
query before anything can check it, and nothing turns one into the other reliably — deriving SQL from
a question is what the existing judge attempts, and where its known problems live.

So each question's reference query is written once, by hand, by someone who can read the question and
decide what it asks. A question with no query written is **skipped**, never guessed at.

## 1. Generate the entries to fill in (free)

```bash
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --write-stubs
```

Writes one entry per question to `~/Desktop/campaign-lcp/mining/banks_v1/evaluation_reference_sql.json`
— outside both repositories, because it contains customer questions. Defaults to the
`overall_summary` category (16 of the 38, and the most tractable to write SQL for); pass
`--category ""` for all, or another category name.

Re-running it is safe: it adds only what is missing and never overwrites SQL you have written.

## 2. Write the SQL

Each entry looks like this. Fill in `sql` and `parameters`; leave `fields` unless the question asks
about different metrics.

```json
{
  "tr-abc123": {
    "question": "<the real question, for you to read>",
    "category": "overall_summary",
    "sql": "SELECT SUM(`spend`) AS spend, SUM(`clicks`) AS clicks FROM <table> WHERE `campaign_name` = :campaign",
    "parameters": {"campaign": "..."},
    "fields": {"spend": "spent", "clicks": "clicks"}
  }
}
```

Two things to get right:

- **The query must return exactly one row.** More than one and the scorer refuses rather than
  guessing which you meant.
- **`fields` maps a column to the word to look for in the answer.** The agent writes "spent" where
  the column says "spend".

## 3. Run it

```bash
.venv/bin/python ~/Desktop/agent-evals-campaign-trial/trial.py --run --bank --app rc1-ai-campaign-performance --limit 5
```

Only questions with SQL written are asked, so you can start with two and grow the set. Cost is stated
before the run: roughly $0.65 a question.

## What this measures, and what it does not

It measures whether the deployed agent gets the **figures** right on questions real users asked, and
whether it **states** the figures that were asked for.

It does not measure the 22 questions in other categories — recommendations, data availability,
trends — because a SQL reference cannot check them. Those need a different kind of judge, and the
report says `not measured` with the reason rather than scoring them zero.
