# Changelog

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
