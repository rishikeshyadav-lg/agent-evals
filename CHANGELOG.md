# Changelog

## 0.18.1 — 2026-10-08

Two fixes found by the first real run, one of which cost a batch of paid agent calls.

### Fixed
- **A scoring failure no longer discards the answer it was scoring.** `run_case_variant` caught every
  exception and returned a result with no `output`, so a bug in a scorer threw away the prediction —
  39 recorded runs against a deployed agent, every one with an empty `answer`, unrescorable, the
  whole batch wasted on a fixable mistake. The output is now carried on the error path, so a run can
  be scored again offline instead of bought again.
- **`SqlBreakdown` no longer returns `None` for a case that declares no breakdown.** `None` is the
  `AnswerRubric` convention for "this criterion does not apply", and `SqlBreakdown` cannot be a
  rubric criterion — it returns two scores where a criterion must return one — so it runs as a plain
  scorer, where `None` is not a score value and raises. It now reports an empty result. This was the
  bug that wasted the batch above.

## 0.18.0 — 2026-10-08

Why a run went wrong, where its time went, and where its money went.

### Added
- `agent_evals.attribution`: one dominant cause per bad run, over a 15-code precedence that is
  **causal, not severity-ranked** — a cause sits above every cause it can produce. Wrong scope
  outranks wrong figures because right numbers about the wrong campaign are wrong numbers.
- `RunFacts`, built from a recorded `RunRow` or a live result, so a cause is decided identically
  whether watched live or read back a week later.
- `usage_attribution` / `usage_summary`: the LLM share of wall-clock, call count, input tokens and
  per-`client_role` split. On one deployment 85% of wall-clock was LLM time and $0.651/run came
  almost entirely from 203,190 input tokens — a latency number nobody can split says to be faster,
  not what to make faster.
- `cause_report` / `failure_code_report`: counts per code across a run, ranked, with the cases named.
- `agent_evals.reporting.segments`: per-category scorecards by slicing the run and reusing
  `build_scorecard` and `operational_summary`, never reimplementing them.
- `RunRow.steps_recorded`, and p50/p99 of latency and cost in `report_json`'s operational block.

### Four rules that shape it
- **Never assert a cause from absence.** `_tool_calls` returns `[]` both for a run with no steps and
  one with no trajectory, so `no_tool_calls` fires only on `steps_recorded`; otherwise the honest
  answer is unknown.
- **Empty result is not fabrication.** An agent correctly reporting no data has the same empty tool
  result. The stronger code needs the stronger evidence: `SqlReference` emits a `figures` score only
  when the answer stated one, so the metric's presence is the proof.
- **A measurement gap never acquits the agent.** `measurement_unavailable` yields whenever any
  measured criterion is below its bar, and the unmeasured map travels on the attribution regardless.
- **A bad run nothing explains is unattributable with a reason**, never "no cause" — that would read
  as a clean bill of health for the case that most needs one.

### Notes
- p50/p99 go in the operational block, not as scorecard entries: `selfcheck.MEASURED_NOT_DERIVED`
  excludes only `p95_latency` and `cost_per_task` from its cross-agent shape comparison, so a
  `p50_latency` entry would make the selfcheck fail on measured wall-clock.
- `attribution` imports only `core` and `running`, and `reporting/report.py` does not import it, so
  a report cannot start depending on a diagnosis.

## 0.17.0 — 2026-10-08

A field may accept either of two columns.

### Added
- `alternatives: {field: [other_column, ...]}` in a case's reference block. A match against any
  accepted value is a match, and the verdict names the one it matched so a reader can see which
  column the answer gave.

A reviewed rubric for one agent's real traffic asks for "a reach figure: device_reach ~203,646 or
ip_reach ~178,540 (either is acceptable)". Both are honest answers to "what was the reach", and the
agent is not wrong for picking one — but comparing against a single column failed whichever it did
not pick. 26 of 235 reviewed metric requirements are of this shape.

### Notes
- Alternative columns must be in the query's own result; an acceptable value nobody selected is not
  a value. They ride along in the truth row because that is the only place the full result is still
  in scope.
- With nothing matched the verdict reports the field's own column, not the nearest alternative: a
  difference from a column the answer never used would not help anyone read the failure.

## 0.16.0 — 2026-10-08

Questions whose correct answer is "that cannot be answered from this data".

### Fixed
- **An answer that correctly declined was scored wrong for being right.** On a question asking for
  the top 30 apps by impressions, against a table with no app dimension, the reference query returns
  campaign totals and the correct answer states the data does not exist — so `figures` scored it
  0.0. Of 50 hand-reviewed rubrics for one agent's real traffic, 10 accept a refusal and 7 have no
  checkable metric at all. This was not a coverage gap; it was a wrong verdict with a number
  attached.

### Added
- `AcceptedRefusal`: scores the refusal itself, and it is not a free pass. A case that accepts a
  refusal and gets one scores 1.0; one that accepts a refusal and gets confident figures instead
  scores **0.0**, because those figures came from somewhere other than the source. Nothing else in
  the library would have caught that.
- `WhenNotRefused`: wraps any criterion so it does not apply to an answer that correctly declined.
  Wrapping rather than teaching each criterion about refusals — `SqlReference` has no business
  knowing what a refusal is.
- `DataGapStated`: did the answer state the limitation it runs into? Required by 23 of those 50
  rubrics and checked by nothing. Scored per gap, so a partially caveated answer scores partially.
- `JudgeRefusal` and `JudgeDataGap`, the model-backed readers. Neither is ever asked whether a
  refusal was *acceptable* — the case already says that — so the judge is only asked what it can
  read from the text in front of it.

### Verified against production
The real rubric for a real `ranking` question, through a live judge:

| answer | figures | refusal |
|---|---|---|
| correctly declines | does not apply | 1.000 |
| invents a top-30 app list | coverage 0.000 | 0.000 |

### Notes
- A reader that cannot decide whether an answer declined makes the wrapped criterion `Unmeasured`,
  never falls through to scoring. Falling through would reinstate the inversion, because on these
  questions the reference disagrees with the right answer by design.
- An empty answer is not a refusal. A refusal states what cannot be done and why; silence is a
  failure that happens to look like one.

## 0.15.0 — 2026-10-08

Questions that ask for a table can now be scored.

### Added
- `SqlBreakdown`: scores an answer against a reference query returning one row per key — a week, a
  placement, a creative. Two scores, because they fail differently and need different fixes.
  `breakdown.rows` is how many of the keys the answer stated at all; `breakdown.figures` is, of the
  rows it stated, how many carried the right numbers. An answer covering every week with wrong
  figures and one covering half the weeks correctly are both wrong, and not in the same way.
- `JudgeRows`, the row reader. No proximity-based alternative exists on purpose: a breakdown
  multiplies the failure that made distance-based reading unusable on a single row, because a
  metric's name appears once per row and the nearest figure belongs to whichever row is laid out
  closest.
- `extra["rows"]` is preferred over reading the answer, exactly as `extra["figures"]` is.

### Why this was needed
Of 64 checkable questions mined from one agent's 90 days of production traffic, 30 asked for a
weekly trend, 15 for a per-placement split and 7 for a per-creative one. None could be scored:
`verify` refuses a query returning five rows, correctly, because which row is "the" answer is not
for a tool to guess. A scalar check could see about a third of real questions.

### Verified against production
One real answer's five-week table, against the warehouse's five rows for that campaign:
`breakdown.rows 1.000`, `breakdown.figures 1.000` — 15 of 15 figures, no missing weeks, no invented
ones.

### Notes
- A case declaring no breakdown returns `None` rather than zero, so a suite can mix questions that
  ask for one with questions that do not.
- A reader that fails leaves the case unmeasured; an answer that gave no breakdown at all scores
  zero on `rows`, because that is a verdict about the answer rather than a failure to measure.

## 0.14.0 — 2026-10-08

A judge can now be reached by name, and one read the real agent's figures.

### Added
- `agent_evals.judges`, the mirror of `agent_evals.sql`: `open_judge(name, settings)` resolves a
  model client lazily, so no provider SDK enters `import agent_evals`. The selfcheck still passes.
- `open_judge("databricks", {...})` for a Databricks model serving endpoint. `temperature` defaults
  to 0, because a judge asked the same question on every run should not move when nothing about the
  agent did. No default endpoint: changing the model changes every score it produced, so which model
  judges belongs in a config a reader can see.

### Measured on three real production answers
With `JudgeClaims` on `databricks-claude-haiku-4-5`, against the same warehouse rows:

| | parser | judge |
|---|---|---|
| figures correct | 9 of 12 | 12 of 12 |

The judge is also right in a way the parser cannot be. One answer gave clicks only as four
per-placement rows that sum to the true 6,521 and never stated a campaign total. The parser bound
the first row's 5,020 to "clicks" and reported a **wrong figure**; the judge reported **no figure
stated**, which moved it to coverage (0.5) where it belongs. Those two verdicts need different
fixes, and only the second is true.

### Notes
- A judge's reply arrives wrapped in a markdown fence from some endpoints; the existing scan for the
  first JSON object already handles it.
- Structured `extra["figures"]` still outranks both, and the parser is still the default.

## 0.13.0 — 2026-10-08

Reading an answer's figures is now a seam, so a model can do it where a parser cannot.

### Fixed
- **A pipe is not a list separator.** It was added to the separator set in 0.11.0, but a markdown
  table puts a label and its own value either side of one — so `| Spend | $10,222.57 |` scored the
  correct figure 1003 characters away and the parser took fragments from elsewhere in the document.
  Measured on three real agent answers this took figure reading from 3/12 to 9/12.

### Added
- `SqlReference(claims_of=...)`: how an answer's claimed figures are read is now pluggable. The
  truth still comes from your query and the comparison is still arithmetic; only the reading changes.
- `JudgeClaims`, which asks a model instead. **It is given the true value and asked to verify, never
  to extract** — "the table says 173, does this answer state that as the total?" has a right answer
  that can be checked later, while "what did it state?" invites a number to be invented.
- A reader that fails leaves the case unmeasured rather than scoring zero: a reader that broke saw
  nothing, which is not the same as the answer stating nothing.

### Notes
- Structured figures in `extra["figures"]` still outrank both. A number handed over as data needs
  neither reading nor judging, and is the only path that is exact, free and identical every run.
- The parser remains the default. The judge costs a model call per case and its verdict can change
  between runs; that is a real trade against a check that is otherwise exact.

## 0.12.0 — 2026-10-08

The fifth and last criterion: interpretation, reported beside the headline and never inside it.

### Added
- `Interpretation`, which asks a model whether an answer's conclusions follow from the data it
  showed. Built as its own criterion rather than on `JudgeScorer`, which cannot say a criterion did
  not apply, cannot say the judge was unreachable, and drops the verdict's codes.
- `AnswerRubric(reported_only=...)`: criteria that are scored and shown but never weighted. An
  unvalidated judge must not move a number people act on, and an unreliable one must not be able to
  void the headline either.
- Every reported-only score is marked `experimental` and `weighted: False` in its detail, so a
  reader can tell which numbers were validated and which were not.

### Notes
- Promoting it into the weights is a decision for after `validate_judge` has measured how often it
  agrees with a person. It is the one criterion that can make a number worse by being added.
- An unreadable reply, an unknown outcome and an unreachable judge are all `Unmeasured`, never zero.
  Scoring zero would call the answer wrong on the strength of the judge malfunctioning.

## 0.11.0 — 2026-10-08

The fourth criterion: completeness, in its two halves. And two extraction bugs it uncovered.

### Added
- `Completeness`, combining a countable coverage score with an optional check that can report an
  omission. The asymmetry is deliberate: the reading check can only *lower* the score, because
  having looked and found nothing missing is not the same as having established nothing is missing.
- Routing is the caller's. A project whose omission check already fails the case through
  `failure_codes_of` leaves `omission_of` unset and nothing is counted twice.
- A configured check that cannot run withholds rather than reporting the countable half alone.

### Fixed
- **A figure bound to the label on the wrong side of a list separator.** In
  `"20,566 clicks, 592,877,053 impressions"` the second figure sits two characters after "clicks"
  and twelve before "impressions", so on raw distance it bound to clicks, clicks took it over its
  own 20,566, and impressions came away with nothing. A separator between a number and a label now
  counts as far away; the comma inside `592,877,053` is not one.
- **A number could end in a comma.** `"900,"` matched whole, so its span ran up to the next label
  and the gap between them looked empty — which is how a figure crossed a separator unnoticed.

## 0.10.0 — 2026-10-08

The third criterion: grounding, which enters as a failure code rather than a score.

### Changed
- `failure_codes_of` may now be async, because the checks that produce codes — a model asked
  whether a claim is supported — are network calls.
- Codes are gathered **before** the headline is decided. A fabricated figure is worth recording
  whatever else could be scored, and the runs where it matters most are exactly the ones where
  other criteria came back unmeasured.
- **A failure code now zeroes the reported headline.** `score_rubric` keeps the weighted score
  deliberately, as the diagnosis, and it is preserved under `score_before_failure`. But a capability
  suite averages the headline, and an answer that invented a figure sitting at 1.0 in that mean —
  because the figures it did state happened to match — is exactly the overclaiming this rubric is for.
- A grounding check that cannot run is no longer a clean bill. Without credentials it finds nothing,
  which looks identical to every answer being clean; that reading is more flattering and wrong, so
  it is recorded as unmeasured and the headline is withheld.

### Notes
- Grounding is never a score. It can fail a run and never verify one, so there is no `grounding`
  number and the report never says an answer was grounded — only that nothing was detected.
- The check runs once per case regardless of how many criteria the rubric has, by construction.

## 0.9.0 — 2026-10-08

The second criterion of accuracy: is the answer about the thing that was asked about.

### Added
- `EntityScope`, a deterministic scope criterion. A case declares
  `expected["scope"] = {"entity": ..., "aliases": [...], "pattern": ...}`; the answer scores 1.0
  when it names the entity, 0.0 when it names a different one of the same kind instead, and
  `Unmeasured` when there is no evidence either way.
- The entity comes from the case, never from the agent. Taking it from the agent's own call asks
  the thing under test what it was supposed to be doing, and a wrong answer then agrees with itself.

### Notes
- Naming the right entity alongside others still scores 1.0; a comparison legitimately names both,
  and the others are recorded in the detail. Whether the agent actually *fetched* the right one
  cannot be read from text — that needs its tool arguments and is a separate check.
- Without a `pattern` the criterion cannot recognise another entity, so it reports `Unmeasured`
  rather than inventing a verdict the case gave it no way to reach.

## 0.8.0 — 2026-10-08

Accuracy stops claiming more than it measured. The prerequisite for every criterion still to come.

### Fixed
- **A question asking for three things, scored on one, reported full marks.** A real question —
  metrics, notable trends, and recommended actions — scored `accuracy 1.000` on an answer giving
  only the metrics, because `figures` was the only criterion wired and the roll-up was still called
  accuracy. A case now declares `expected["requires"]`, and anything required with no criterion
  withholds the headline and names what went unchecked.
- **A criterion that raised scored the agent zero.** It propagated out of the rubric, became a case
  error, and `case_scores` counts an errored row as `0.0`. A judge that is down, rate-limited or
  returning unparseable text is a failure of the measurement, not of the agent; it is now
  `Unmeasured` carrying the exception, so a bug in a criterion stays visible instead of silently
  marking good answers wrong.

- The Result line now says how many cases could not be measured. It is the sentence people quote,
  and a mean over one case of four otherwise reads as a verdict on all four.

### Added
- `build_dataset(..., requires=...)`, so mined cases can declare what each question demands. Yours
  to supply, for the same reason `classify` is: deciding that "notable trends" demands an
  interpretation criterion is a reading of what the question means.

## 0.7.0 — 2026-10-08

First release intended for PyPI, and the adapter that makes the detected config work.

### Added
- A Databricks adapter: `open_executor("databricks", {...})`, behind `agent-evals[databricks]`.
  Authentication is never passed in — the SDK already resolves it from the environment or
  `~/.databrickscfg`, and asking again would mean copying credentials that are already on the machine.
- Parameters go as parameter markers, never formatted into the statement. An evaluation runs queries
  built from text that came out of a trace, so that is a safety property, not a style choice.

### Fixed
- `init` wrote `database = "databricks"` whenever it found a warehouse, and no such adapter existed.
  Every config it produced for a warehouse-backed project raised `KeyError` at the first query.

## 0.6.0 — 2026-10-08

Onboarding rewritten. `agent-evals init` now reads what your project already records.

### Changed
- `init` detects instead of asking. Every value it previously wanted typed — the deployment, the
  table, the warehouse, the catalog, the schema, the MLflow experiment — was already written in the
  project's own deploy manifests, and the credentials were already in `~/.databrickscfg`. It reads
  them, shows what it found and where, and you pick.
- Settings are grouped per deployment, so one choice settles all of them. Pooling them handed you
  dev's experiment beside prd's table.
- The profile goes in the config, and every command sets `DATABRICKS_HOST` from it. **No exports.**
- `init` scaffolds `eval_drafter.py` filled in with your table, and it runs as written.
- `--yes` accepts every default, `--agent` names a deployment when nothing is detected, and neither
  ever waits for an answer a script cannot give.

### Notes
- Detection is shallow on purpose — key names and file shapes, no product-specific schema. A
  detector that is clever about one project is wrong about the next, so nothing is applied silently.

## 0.5.0 — 2026-10-08

`agent-evals draft` and `review`: a query per question, and the gate it has to pass.

### Added
- `agent_evals.drafting`: a `QueryDrafter` seam, and `TemplateDrafter`, which fills a query you
  wrote from a value found in the question. Deterministic, offline, and it declines rather than
  guessing when the pattern does not match.
- A review gate in two parts. The mechanical one rejects anything that cannot be ground truth: the
  query raised, returned nothing, returned more than one row, is missing a field, or a figure is not
  finite. The human one catches the query that runs perfectly and answers the wrong question.
- `approve` takes a verified check, so a draft cannot be accepted without the row it returned. A
  reviewer shown only SQL is reviewing syntax, and syntax is not what goes wrong here.
- Drafts persist, so a slow review survives interruption, and re-drafting never replaces a decision
  already made.
- `agent-evals draft` and `agent-evals review`.

### Notes
- An aggregate over no matching rows returns one row of nulls, not zero rows. That is reported as a
  filter matching nothing, rather than as bad data, so the author looks at the WHERE clause.

## 0.4.0 — 2026-10-08

`agent-evals mine`: the questions people actually asked, as a dataset you can run twice.

### Added
- `agent_evals.mining`: a `TraceSource` seam shaped like the database one. Reading a trace and
  finding the question inside needs to know that agent's format, so the knowledge stays with you.
- `open_source("mlflow", ...)` with a lazy registry, and `question_of` for the one part only you
  can answer. The default reader handles the common request shapes and returns nothing rather than
  a guess when it does not recognise one.
- `build_dataset` collapses duplicates, fixes the order and derives each id from the question, so
  mining the same window twice gives the same checksum.
- `agent-evals mine` asks how far back to look (90, 120 or 180 days) and writes the dataset under
  the log directory, which git is already refusing to commit.
- The selfcheck now proves both registries stay lazy, not just the first.

## 0.3.0 — 2026-10-08

The beginning of a command-line tool you install at your agent's root. Two commands so far.

### Added
- `agent-evals init` writes `agent-evals.toml` and prepares a log directory git will not commit.
- `agent-evals doctor` answers "will a run work from here", naming what is missing. It separates a
  fault from a limitation: no table configured is a warning, not a failure.
- OpenTelemetry spans for everything the tool does, written as JSON lines under the log directory,
  and exported to a collector when `otlp_endpoint` is set.
- `pip install "agent-evals[cli]"` installs the command and its dependencies. The library itself
  stays dependency-free, and the selfcheck now proves it by forbidding `typer` and `opentelemetry`
  alongside the agent frameworks.

### Notes
- Credentials are never prompted for or stored. The tool reads the environment the agent already
  uses and says which variable is missing when it cannot.
- Logs hold the questions users asked. They live at the agent's root by request, so the tool writes
  two layers of `.gitignore` and refuses to write at all if git says the directory is not ignored.

## 0.2.1 — 2026-10-07

### Fixed
- A case can now ask for no figures in particular. `required: []` was falsy, so it collapsed into the
  default of every field, and an answer to an open-ended question ("how is it performing") lost
  coverage for not volunteering figures nobody asked for. An omitted `required` still means all of
  them; an explicitly empty one now means none.

## 0.2.0 — 2026-10-07

Accuracy as named criteria, and checking an agent's figures against your own tables.

### Added
- `AnswerRubric`: accuracy as several named criteria rolled up with weights, so a wrong figure and an
  omitted one are different failures rather than one averaged score.
- `SqlReference` and `reference_criteria`: run the query a case declares, compare each field within a
  per-field `Tolerance`, and report which field disagreed and by how much.
- `Unmeasured`: a criterion that could not reach the truth now withholds the headline instead of
  scoring zero, and the reason travels to the report as `{name}.measured`.
- `MultiScoreResult`, `SuiteRule.unmeasured_cases`, `Tolerance.abbreviated_multiplier`.
- `agent_evals.sql`: `open_executor` with a lazy adapter registry and a stdlib SQLite adapter. The
  selfcheck proves no adapter loads until one is asked for by name.
- `numbers_by_label`: resolves every label together, so no field takes the figure beside another's name.

### Removed
- `number_near`. It resolved one label at a time, which cannot work: English puts the figure on either
  side of the word, so whichever side the rule preferred, the other reading took a neighbour's number
  ("400 clicks, a ctr of 0.42%" returned 0.42 for clicks). `numbers_by_label` replaces it.

### Fixed
- The scorecard counted rows that merely ran rather than rows that reached the score, reporting
  "4 used, 0 excluded" for a run where 3 cases were scored.
- A windowed slice could cut `18,450` into `1845`; a label matched inside a longer word.

## 0.1.0 — 2026-10-07

First version extracted from the `penguiflow` monorepo, where it lives at `packages/agent-evals`.
That repository keeps the full history; this one starts fresh.

- Agent-agnostic evaluation: bring any agent as a callable, get repeated runs, scorers across four
  layers, case-clustered statistics and a report that names what it could not measure.
- No required dependencies. `mlflow` is an optional extra.
- `python -m agent_evals.selfcheck` proves, from an installed copy, that importing the package pulls in
  no agent framework, model client or backend, and that unrelated agent shapes score identically.
- A run row names its variant `variant_id`. Rows written as `arm`, the first consumer's word for it,
  still load.

### Known limits
- Plan adherence and multi-step coherence are experimental; their agreement with human labels is
  unmeasured.
- `dry_run` in shadow comparison is a request the agent must honour; nothing is sandboxed.
- Policy checks detect violations; they do not enforce them.
