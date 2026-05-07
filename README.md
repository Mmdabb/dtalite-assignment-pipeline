# Pipline User Guide

This repo runs the NVTA DTALite assignment and postprocessing workflow from JSON configuration files. Most runs only require editing a config in `configs/`, then running `main.py` from the repo root.

## Setup

Use Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The active assignment workflow uses the installed Python `DTALite` package. The reproducible runner expects DTALite to be importable as `DTALite`; the historical scenario-level `DTALite_0324b.exe` setting is not used by the current config flow.

## Run

```powershell
python main.py --config configs/project_assignment.json
```

## Project Structure

```text
project_root/
  main.py                  # Config-driven entry point
  benchmark.py             # Field/header comparison helper
  configs/                 # JSON run configurations
  scenarios/               # Project scenario input folders
  regional/                # Regional input/reference data
  scripts/                 # Standalone DTALite helper scripts
  src/
    dtalite4cube/          # Assignment pipeline
    dtalite_postprocessing/ # Postprocessing pipeline
```

## Config Basics

Top-level fields:

```json
{
  "scenario_base_dir": "scenarios",
  "scenario_names": ["FFX134_BD", "FFX134_NB"],
  "time_periods": ["am", "md", "pm", "nt"],
  "period_times": ["0600_0900", "0900_1500", "1500_1900", "1900_0600"]
}
```

- `scenario_base_dir`: folder containing scenario folders.
- `scenario_names`: scenario folders to process.
- `time_periods`: assignment periods to generate and run.
- `period_times`: matching clock ranges for each period.

Assignment fields:

```json
"assignment": {
  "iterations": 20,
  "processors": 8,
  "route_output": 0,
  "unit_system": "imperial",
  "vdf_type": "bpr",
  "dtalite_run_mode": "assignment",
  "network_conversion": true,
  "demand_conversion": true,
  "dtalite_assignment": false
}
```

- `iterations`: DTALite assignment iterations.
- `processors`: number of processors passed to DTALite settings.
- `route_output`: `1` writes `route_assignment.csv`; `0` skips route output.
- `unit_system`: `imperial` writes link length/speed as mile/mph; `metric` writes meter/kph.
- `vdf_type`: `bpr` or `qvdf`.
- `network_conversion`: generate period `node.csv` and `link.csv`.
- `demand_conversion`: export period demand CSVs from OMX files.
- `dtalite_assignment`: run DTALite after inputs are prepared.

Postprocessing fields:

```json
"postprocessing": {
  "enabled": false,
  "performance_stats": {
    "enabled": true,
    "scenario_names": ["FFX134_BD", "FFX134_NB"]
  },
  "link_performance_comparison": {
    "enabled": true,
    "scenario_pairs": [["FFX134_BD", "FFX134_NB"]]
  }
}
```

Postprocessing uses the same top-level `time_periods` and `period_times`.

## Inputs

Each scenario folder should contain the network files and demand matrices needed for conversion. Typical source files include shapefile components such as `.shp`, `.shx`, `.dbf`, `.prj`, plus period demand matrices such as `AM_SubArea.OMX`, `MD_SubArea.OMX`, `PM_SubArea.OMX`, and `NT_SubArea.OMX`.

## Outputs

Each assignment period is written as a self-contained DTALite folder under the scenario:

```text
scenarios/FFX134_BD/
  am/
    node.csv
    link.csv
    settings.csv
    mode_type.csv
    sov_am.csv
    hov2_am.csv
    hov3_am.csv
    com_am.csv
    trk_am.csv
    apv_am.csv
```

If `dtalite_assignment` is enabled, DTALite outputs such as `link_performance.csv`, `od_performance.csv`, `dtalite_run.log`, and `RUN_CARD.md` are created in the period folder. When `route_output` is `1`, `route_assignment.csv` and `columns.csv` are also created.

Postprocessing may create scenario-level files such as `link_performance_combined_processed.csv`, summary CSVs, and comparison folders named like:

```text
scenarios/<build_scenario>_VS_<no_build_scenario>/
```

Generated period folders, run logs, run cards, DTALite outputs, and comparison outputs are intentionally ignored by Git.

## Minimal Examples

To only generate network and demand inputs:

```json
"network_conversion": true,
"demand_conversion": true,
"dtalite_assignment": false
```

To run the full assignment too:

```json
"dtalite_assignment": true
```

To enable postprocessing after assignment outputs exist:

```json
"postprocessing": {
  "enabled": true,
  "performance_stats": {
    "enabled": true,
    "scenario_names": ["FFX134_BD", "FFX134_NB"]
  },
  "link_performance_comparison": {
    "enabled": true,
    "scenario_pairs": [["FFX134_BD", "FFX134_NB"]]
  }
}
```
