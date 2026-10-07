# Check an agent's figures against your own database

`flow.py` evaluates an agent whose answers are prose, against a table that holds the truth. It runs
offline on the standard library — the "warehouse" is an in-memory SQLite table — so it needs no
credentials, no network and no extras.

```bash
uv run python examples/agent_evals_sql_reference/flow.py
```

The agent answers four questions and gets each wrong in a different way, because that is what makes
the report worth reading:

| Case | What the agent did | What it costs |
|---|---|---|
| `spring` | every figure right | nothing |
| `summer` | states clicks wrongly | `figures`, not completeness |
| `autumn` | never mentions clicks | `completeness`, not figures |
| `winter` | asks about a campaign the table does not hold | neither — excluded and named |

Those last two are the point. A figure stated wrongly and a figure never stated are different
mistakes with different fixes, and a question your table cannot answer is not the agent's failure at
all, so it is set aside rather than scored zero.

What to change for your own setup:

1. Point `open_executor` at your adapter instead of `sqlite`.
2. Give each case a `reference` block: the SQL, its parameters, and the fields to check. `fields` may
   be a list when the column name is also the word to look for, or a mapping when they differ — the
   example maps `spend` to `spent`, because that is what the agent writes.
3. Set a `Tolerance` per field. Money to the penny and a click count to the nearest whole thing are
   different questions.
4. Name any field your table stores as a fraction in `fraction_fields`, so `0.42%` is read as
   `0.0042` rather than compared as `0.42`.

If your agent can return its figures as data, put them in `PredictionResult.extra["figures"]` and
they are used in preference to reading the prose, which is exact rather than best-effort.

Test: `tests/contract/test_sql_reference_example.py` runs this file and checks the report.
