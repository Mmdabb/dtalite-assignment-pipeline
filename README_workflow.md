# Pipeline Workflow and Developer Notes

This document describes the package workflow and implementation details for future development. The user-facing run and config guide is `README.md`.

## Package Layout

```text
project_root/
  main.py                         # JSON-driven orchestration entry point
  configs/                        # User run configs
  scenarios/                      # Scenario input/output folders
  regional/                       # Regional input/output folders
  src/
    dtalite4cube/                 # Network/demand conversion and DTALite assignment
      runner.py                   # Assignment orchestration
      internal_config.py          # Developer-owned workflow defaults
      cube2gmns/                  # Cube network to GMNS conversion
      settings/                   # settings.csv and mode_type.csv generation
      omx2csv.py                  # OMX demand export
      renumbering.py              # Original IDs to compact sequential IDs
      backmap_outputs.py          # Sequential DTALite outputs back to original IDs
      readiness_check.py          # Optional GMNS readiness diagnostics
      reproducible_run.py         # DTALite staging, execution, verification
    dtalite_postprocessing/       # Postprocessing and scenario comparisons
      runner.py
      pipeline/
```

## Entry Point

`main.py` loads a JSON config and coordinates two stages:

1. Assignment, via `run_assignment_from_config()`
2. Postprocessing, via `run_postprocessing_from_config()`

Assignment config is merged in this order:

1. Shared `assignment` block
2. Matching `scenario_overrides[scenario_name]`
3. Generated fields such as `network_path` and `scenario_name`

The merged dict is converted to `AssignmentConfig.from_dict()`.

## User Config Boundary

Only user-facing run choices should appear in JSON config files. Examples include:

- Scenario folders and periods
- Assignment iterations/processors
- `route_output` and `vehicle_output`
- Unit system and VDF type
- Whether to run network conversion, demand conversion, assignment, and postprocessing

Developer-owned workflow controls live in `src/dtalite4cube/internal_config.py`:

```python
USE_SEQUENTIAL_IDS_FOR_DTALITE = True
RENUMBER_LINK_IDS_IF_NEEDED = True
RUN_GMNS_READINESS_CHECK = True
BACKMAP_DTALITE_OUTPUTS = True
WRITE_ASSIGNMENT_SUMMARY = True
```

These settings are intentionally hidden from user JSON configs. If old configs include their previous snake-case names, `AssignmentConfig.from_dict()` logs a warning and ignores them.

## Assignment Stage

`run_assignment_pipeline()` performs the assignment workflow for each scenario:

1. Validate `AssignmentConfig`.
2. Resolve the scenario output directory.
3. Optionally convert Cube network inputs to period GMNS folders.
4. Optionally export period demand CSVs from OMX files.
5. Generate `settings.csv` and `mode_type.csv`.
6. Remove duplicate root-level period folders.
7. Optionally run the GMNS readiness check.
8. If `dtalite_assignment` is false, log that assignment is disabled and return without a finished-assignment message.
9. If assignment is enabled, run DTALite through the sequential-ID workflow by default.

`run_assignment_pipeline()` returns `True` only when DTALite assignment actually ran. `main.py` uses that return value to decide whether to log `Finished DTALite assignment stage.` or `DTALite assignment is disabled.`

## Period Folder Layout

Network and demand conversion produce one folder per time period:

```text
scenarios/<scenario>/<period>/
  node.csv
  link.csv
  settings.csv
  mode_type.csv
  *_<period>.csv
```

The sequential-ID workflow creates the DTALite run folder inside the period folder:

```text
scenarios/<scenario>/<period>/
  <period>_seq/
```

DTALite runs in `<period>/<period>_seq/`. Backmapped original-ID result files are written directly into `<period>/`, overwriting existing files with the same names.

There is no `orgID_<period>` output folder.

By default, `<period>_seq/` is an internal temporary work folder and is deleted after DTALite completes, outputs are verified, backmapping is complete, and `RUN_SUMMARY.md` is written.

## Sequential-ID Workflow

DTALite can allocate memory based on maximum node/zone IDs. Sparse Cube IDs can therefore be expensive even for small subnetworks. The sequential-ID layer avoids that by renumbering each period folder before DTALite execution.

`renumber_period_folder()`:

- Copies the period folder to `<period>/<period>_seq/`.
- Maps original `node_id` values to compact `1..N`.
- Maps nonzero `zone_id` values to the matching sequential node IDs.
- Rewrites `link.csv` endpoints.
- Rewrites demand `o_zone_id` and `d_zone_id`.
- Renumbers `link_id` only when `link.csv` link IDs are not already one-based sequential and `RENUMBER_LINK_IDS_IF_NEEDED` is true.
- Writes `id_mapping.csv`.

Validation checks confirm:

- Sequential `node_id` values are compact.
- Zone IDs are mapped.
- Link endpoints exist.
- Demand OD zones exist.

## DTALite Run Workflow

`run_sequential_dtalite_assignment()`:

1. Creates `<period>_seq/` with compact IDs.
2. Runs `preflight()` on the sequential folder.
3. Calls `stage_inputs()` to normalize `settings.csv`.
4. Runs the Python `DTALite` package.
5. Verifies required outputs.
6. Copies `route_assignment.csv` to `columns.csv` when route output exists and `no_rename_columns` is false.
7. Writes `RUN_CARD.md` in the sequential folder.
8. Backmaps DTALite outputs to the original period folder.
9. Writes `RUN_SUMMARY.md` in the original period folder.

`route_output` and `vehicle_output` are passed through config to `settings.csv`.

## Link Unit and VDF Fields

Metric is the default unit system. For metric output:

- `length` is written in km.
- `free_speed` is written in kph.

For imperial output:

- `length` is written in mile.
- `free_speed` is written in mph.

Two VDF helper fields are always written regardless of the selected unit system:

- `vdf_free_speed_mph`
- `vdf_length_mi`

Those remain mph and mile so DTALite/VDF workflows can rely on stable imperial reference fields.

## Backmapping Scope

Backmapping is intentionally limited to DTALite result files. It does not copy or remap converted network files, demand files, settings, logs, or summaries.

Files and fields currently backmapped:

- `link_performance.csv`: `from_node_id`, `to_node_id`; `link_id` only when link IDs were renumbered.
- `od_performance.csv`: `o_zone_id`, `d_zone_id`.
- `origin_accessibility.csv`: `o_zone_id` and `origin_zone_id` when present.
- `destination_accessibility.csv`: `d_zone_id` and `destination_zone_id` when present.
- `inaccessible_od.csv`: `o_zone_id`, `d_zone_id`, `origin_zone_id`, `destination_zone_id` when present.
- `google_maps_od_distance.csv`: `o_zone_id`, `d_zone_id`.
- `route_assignment.csv` and `columns.csv`: `o_zone_id`, `d_zone_id`, semicolon-separated `node_ids`, and semicolon-separated `link_ids` when link IDs were renumbered.

Optional route files may be missing or empty when `route_output=0`; that is reported as a warning-style summary, not a failure.

After backmapping, verification checks that existing result files use original IDs in the fields above.

## Preserving Sequential Work Folders

Sequential work folders are deleted by default. Developers can preserve them locally for debugging by setting an environment variable before running the pipeline.

In PowerShell:

```powershell
$env:DTALITE_KEEP_SEQ_DIR = "1"
```

To disable it again in the same PowerShell session:

```powershell
Remove-Item Env:\DTALITE_KEEP_SEQ_DIR
```

Accepted true values are `1`, `true`, `True`, `yes`, and `on`. Accepted false values are empty string, `0`, `false`, `False`, `no`, and `off`. Invalid values fall back to the default, which is false.

This is intentionally not part of the user JSON config.

## Readiness Diagnostics

`readiness_check.py` wraps the optional `gmns_ready` package. If `gmns_ready` is unavailable, the workflow writes:

- `gmns_readiness.log`
- `gmns_readiness_summary.md`

with status `not_installed` and continues. This keeps assignment runs independent from optional diagnostics.

## Postprocessing Workflow

Postprocessing reads original-ID period outputs, primarily:

```text
scenarios/<scenario>/<period>/link_performance.csv
scenarios/<scenario>/<period>/link.csv
```

Legacy fallback paths are still supported in the resolver where needed, but new assignment output should be read directly from `<period>/`.

`run_postprocessing_from_config()` supports:

- Performance stats for selected scenarios.
- Link performance comparisons for configured scenario pairs.

Comparison folders are written as:

```text
scenarios/<build_scenario>_VS_<no_build_scenario>/
```

## Logging Expectations

Assignment logging should distinguish disabled assignment from a successful DTALite run:

- If `dtalite_assignment=false`, log that DTALite assignment is disabled.
- Only log finished DTALite assignment messages after a successful DTALite run.

This behavior depends on the boolean return value from `run_assignment_pipeline()`.

## Development Checks

Useful smoke checks:

```powershell
python -c "from pathlib import Path; compile(Path('src/dtalite4cube/runner.py').read_text(), 'runner.py', 'exec')"
python main.py --config configs/project_assignment.json
```

For one-period development tests, call `run_assignment_from_config()` with `time_periods=['am']`, one scenario, and a scratch `output_dir`. This avoids rerunning all scenarios and all periods while still exercising the real pipeline.

Generated scenario outputs and scratch folders should stay out of Git.

## Packaging Notes

Client-facing Windows setup is handled by:

- `setup_environment.bat`
- `run_pipeline.bat`
- `setup/check_setup.py`
- `setup/select_config.ps1`
- `setup/environment.yml`

`requirements.txt` is kept for manual Python environments and should stay reasonably aligned with `setup/environment.yml`. Runtime dependencies currently include `DTALite`, `pandas`, `numpy`, `openmatrix`, `tqdm`, `geopandas`, `shapely`, `fiona`, and `pyproj`.

`gmns_ready` is optional. If it is not installed, readiness diagnostics are skipped and the assignment workflow continues.

## TODO: Cross-Midnight Assignment Periods

DTALite currently cannot run assignment settings where the period starts before midnight and ends after midnight, such as `1900_0600` producing `19 -> 6`.

Temporary behavior:

- The assignment settings are truncated to the pre-midnight part only.
- Postprocessing duration uses the same truncated pre-midnight duration for DTALite-output-based aggregation.
- Example: `1900_0600` is written to `settings.csv` as `19 -> 24`.
- The postprocessing duration for `1900_0600` is therefore 5 hours, not the original configured 11 hours.
- This is calculated from the configured period time range for each period; no period name has a fixed hardcoded duration.
- The post-midnight portion, such as `0 -> 6`, is not assigned or represented in postprocessing yet.

Future development:

- Create two internal sub-runs for cross-midnight periods:
  1. start hour -> 24
  2. 0 -> end hour
- Decide how outputs should be combined:
  - Option A: aggregate the two assignment outputs into one period-level result. This is more difficult.
  - Option B: let postprocessing treat them as additional runs/sub-periods.
- Before choosing Option B, verify how postprocessing uses fixed period durations and weighted-hour aggregation, because current aggregation may assume one fixed duration per named time period.
- Refactor the cross-midnight helpers into a neutral shared utility module if assignment settings and postprocessing gain more time-period logic. Today, postprocessing imports the assignment-side normalization helper so the truncation rule cannot drift.
