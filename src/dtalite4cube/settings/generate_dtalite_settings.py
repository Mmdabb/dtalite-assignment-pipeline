from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

try:
    from .dtalite_settings_config import (
        ALLOWED_SETTINGS_OVERRIDES,
        DEFAULT_SETTINGS,
        MODE_TYPE_CONFIG,
        MODE_TYPE_FILENAME,
        MODE_TYPE_HEADER,
        SETTINGS_FILENAME,
        SETTINGS_HEADER,
        TIME_PERIODS,
        demand_file_name,
    )
except ImportError:
    from dtalite_settings_config import (
        ALLOWED_SETTINGS_OVERRIDES,
        DEFAULT_SETTINGS,
        MODE_TYPE_CONFIG,
        MODE_TYPE_FILENAME,
        MODE_TYPE_HEADER,
        SETTINGS_FILENAME,
        SETTINGS_HEADER,
        TIME_PERIODS,
        demand_file_name,
    )


def normalize_period_key(period_key: str) -> str:
    normalized = period_key.lower()
    if normalized not in TIME_PERIODS:
        valid_periods = ", ".join(sorted(TIME_PERIODS))
        raise ValueError(f"Unknown DTALite period '{period_key}'. Expected one of: {valid_periods}")
    return normalized


def build_settings_row(period_key: str, overrides: dict[str, Any] | None = None) -> list[Any]:
    period_key = normalize_period_key(period_key)
    period = TIME_PERIODS[period_key]
    settings = dict(DEFAULT_SETTINGS)

    if overrides:
        unknown_keys = sorted(set(overrides) - ALLOWED_SETTINGS_OVERRIDES)
        if unknown_keys:
            raise ValueError(f"Unsupported settings override(s): {', '.join(unknown_keys)}")
        settings.update({key: value for key, value in overrides.items() if value is not None})

    settings["demand_period_starting_hours"] = period["start_hour"]
    settings["demand_period_ending_hours"] = period["end_hour"]

    return [settings[field] for field in SETTINGS_HEADER]


def build_mode_type_rows(period_key: str) -> list[list[Any]]:
    period_key = normalize_period_key(period_key)
    rows = []

    for mode in MODE_TYPE_CONFIG[period_key]:
        mode_type = mode["mode_type"]
        rows.append(
            [
                mode["mode_type_id"],
                mode_type,
                mode["name"],
                mode["vot"],
                mode["pce"],
                mode["occ"],
                demand_file_name(mode_type, period_key),
            ]
        )

    return rows


def generate_settings_csv(
    output_dir: str | Path,
    period_key: str,
    overrides: dict[str, Any] | None = None,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    settings_path = output_path / SETTINGS_FILENAME

    with settings_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(SETTINGS_HEADER)
        writer.writerow(build_settings_row(period_key, overrides))

    return settings_path


def generate_mode_type_csv(output_dir: str | Path, period_key: str) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    mode_type_path = output_path / MODE_TYPE_FILENAME

    with mode_type_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(MODE_TYPE_HEADER)
        writer.writerows(build_mode_type_rows(period_key))

    return mode_type_path


def generate_dtalite_input_files(
    output_dir: str | Path,
    period_key: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Path]:
    return {
        SETTINGS_FILENAME: generate_settings_csv(output_dir, period_key, overrides),
        MODE_TYPE_FILENAME: generate_mode_type_csv(output_dir, period_key),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate current DTALite settings.csv and mode_type.csv files.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--period", required=True, help="One of am, md, pm, nt, or all.")
    parser.add_argument("--number-of-iterations", type=int)
    parser.add_argument("--number-of-processors", type=int)
    parser.add_argument("--route-output", type=int)
    return parser


def collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    override_args = {
        "number_of_iterations": args.number_of_iterations,
        "number_of_processors": args.number_of_processors,
        "route_output": args.route_output,
    }
    return {key: value for key, value in override_args.items() if value is not None}


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    overrides = collect_overrides(args)
    period = args.period.lower()

    if period == "all":
        for period_key in TIME_PERIODS:
            generate_dtalite_input_files(args.output_dir / period_key, period_key, overrides)
        return

    generate_dtalite_input_files(args.output_dir, period, overrides)


if __name__ == "__main__":
    main()
