# DTALite Assignment Pipeline

This repository runs DTALite assignment and optional postprocessing from JSON config files. Most users only need to edit a file in `configs/` and run `main.py` from the project root.

## Setup

### Windows Batch Setup

For most Windows users, double-click:

```text
setup_environment.bat
```

This installs or updates the `dtalite_pipeline` Conda environment from `setup/environment.yml`, then runs a setup check using `configs/project_assignment.json`.

To check a different config from Command Prompt or PowerShell:

```powershell
.\setup_environment.bat configs\project_assignment.json
```

The window pauses at the end so you can read any success or error messages.

### Manual Python Setup

Use Python 3.10 or newer with the dependencies in `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The assignment stage uses the installed Python `DTALite` package. Make sure `DTALite` can be imported in the Python environment you use to run the pipeline.

## Run

### Windows Batch Run

For most Windows users, double-click:

```text
run_pipeline.bat
```

If no config path is provided, a file picker opens in the `configs/` folder. Select the JSON config to run. If you cancel the picker, the script exits without running the pipeline.

To run a specific config from Command Prompt or PowerShell:

```powershell
.\run_pipeline.bat configs\project_assignment.json
```

The selected config is printed and written to `logs/run_pipeline_log.txt`. The window pauses at the end so you can read success or failure messages.

### Manual Python Run

```powershell
python main.py --config configs/project_assignment.json
```

## Config Files

The main config sections are:

- Top-level scenario and period settings
- `assignment`
- `postprocessing`
- Optional `scenario_overrides`

Example:

```json
{
  "scenario_base_dir": "scenarios",
  "scenario_names": ["FFX134_BD", "FFX134_NB"],
  "time_periods": ["am", "md", "pm", "nt"],
  "period_times": ["0600_0900", "0900_1500", "1500_1900", "1900_0600"],
  "assignment": {
    "iterations": 10,
    "processors": 4,
    "route_output": 0,
    "vehicle_output": 0,
    "unit_system": "metric",
    "vdf_type": "bpr",
    "dtalite_run_mode": "assignment",
    "network_conversion": true,
    "demand_conversion": true,
    "dtalite_assignment": true
  },
  "postprocessing": {
    "enabled": false
  }
}
```

## Top-Level Settings

- `scenario_base_dir`: folder containing scenario folders, such as `scenarios` or `regional`.
- `scenario_names`: scenario folders to process.
- `time_periods`: assignment period labels to create and run.
- `period_times`: matching clock ranges for each period.

## Assignment Settings

- `iterations`: DTALite assignment iterations.
- `processors`: number of processors written to `settings.csv`.
- `route_output`: `1` writes route outputs such as `route_assignment.csv`; `0` disables them.
- `vehicle_output`: `1` writes vehicle-level DTALite output; `0` disables it.
- `unit_system`: `metric` writes link length/speed as km/kph; `imperial` writes mile/mph.
- `vdf_type`: volume-delay function type, currently `bpr` or `qvdf`.
- `dtalite_run_mode`: use `assignment`.
- `network_conversion`: generate period `node.csv` and `link.csv`.
- `demand_conversion`: export period demand CSVs from OMX files.
- `dtalite_assignment`: run DTALite after inputs are prepared. If `false`, the pipeline only performs enabled conversions.

## Postprocessing Settings

Postprocessing can be disabled:

```json
"postprocessing": {
  "enabled": false
}
```

Or enabled for performance summaries and comparisons:

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

- `performance_stats.enabled`: create processed performance summaries.
- `performance_stats.scenario_names`: scenarios included in summary processing.
- `link_performance_comparison.enabled`: compare pairs of scenarios.
- `link_performance_comparison.scenario_pairs`: scenario pairs to compare. Put the build scenario first when comparing build vs no-build.

## Scenario Overrides

Use `scenario_overrides` when one scenario needs a different assignment setting.

```json
"scenario_overrides": {
  "FFX134_NB": {
    "dtalite_assignment": false
  }
}
```

## Inputs

Each scenario folder should contain the source network files and demand matrices needed for conversion. Typical inputs include shapefile components such as `.shp`, `.shx`, `.dbf`, `.prj`, plus period demand matrices such as `AM_SubArea.OMX`, `MD_SubArea.OMX`, `PM_SubArea.OMX`, and `NT_SubArea.OMX`.

## Outputs

Each assignment period is written under the scenario folder:

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
    link_performance.csv
    od_performance.csv
```

Postprocessing may create scenario-level files such as processed link performance outputs, summary CSVs, and comparison folders named like:

```text
scenarios/<build_scenario>_VS_<no_build_scenario>/
```

Generated period folders, logs, DTALite outputs, summaries, and comparison outputs are ignored by Git.

## Common Runs

Only generate network and demand inputs:

```json
"network_conversion": true,
"demand_conversion": true,
"dtalite_assignment": false
```

Run conversion and DTALite assignment:

```json
"network_conversion": true,
"demand_conversion": true,
"dtalite_assignment": true
```

Run postprocessing after assignment outputs already exist:

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

Developer workflow details are in `README_workflow.md`.
