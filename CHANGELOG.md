# Changelog

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
