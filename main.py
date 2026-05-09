from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from src.dtalite4cube.runner import AssignmentConfig, run_assignment_pipeline
from src.dtalite_postprocessing.runner import PostprocessingConfig, run_postprocessing


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


def load_json(json_path: Path) -> dict[str, Any]:
    if not json_path.exists():
        raise FileNotFoundError(f"Config file not found: {json_path}")

    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_assignment_scenario_config(
    *,
    scenario_path: str,
    scenario_base_dir: Path,
    shared_assignment: dict[str, Any],
    scenario_overrides: dict[str, Any] | None = None,
) -> AssignmentConfig:
    merged = dict(shared_assignment)

    if scenario_overrides:
        merged.update(scenario_overrides)

    merged["network_path"] = scenario_base_dir / scenario_path
    merged["scenario_name"] = scenario_path

    return AssignmentConfig.from_dict(merged)


def build_postprocessing_config(
    *,
    catalog_dir: Path,
    scenario_names: list[str],
    postprocessing_block: dict[str, Any],
    time_periods: list[str],
    period_times: list[str],
    performance_stats: bool,
    link_performance_comparison: bool,
) -> PostprocessingConfig:
    return PostprocessingConfig(
        catalog_dir=catalog_dir,
        scenario_names=scenario_names,
        performance_stats=performance_stats,
        link_performance_comparison=link_performance_comparison,
        bus_delay_analysis=postprocessing_block.get("bus_delay_analysis", {}).get("enabled", False),
        time_periods=time_periods,
        time_period_duration_list=period_times,
    )


def run_assignment_from_config(
    *,
    scenario_base_dir: Path,
    scenario_paths: list[str],
    shared_assignment: dict[str, Any],
    scenario_overrides_map: dict[str, Any],
) -> bool:
    if not scenario_paths:
        raise ValueError(
            "Config must contain a non-empty 'scenario_paths' or 'scenario_names' list."
        )

    logger.info("Using scenario base directory: %s", scenario_base_dir)

    dtalite_runs_completed = 0
    for scenario_path in scenario_paths:
        logger.info("Starting assignment for scenario: %s", scenario_path)

        overrides = scenario_overrides_map.get(scenario_path, {})
        config = build_assignment_scenario_config(
            scenario_path=scenario_path,
            scenario_base_dir=scenario_base_dir,
            shared_assignment=shared_assignment,
            scenario_overrides=overrides,
        )

        if run_assignment_pipeline(config):
            dtalite_runs_completed += 1

    if dtalite_runs_completed:
        logger.info("Finished DTALite assignment stage.")
    else:
        logger.info("DTALite assignment is disabled.")

    return bool(dtalite_runs_completed)


def run_postprocessing_from_config(
    *,
    scenario_base_dir: Path,
    top_level_scenario_names: list[str],
    postprocessing_block: dict[str, Any],
    time_periods: list[str],
    period_times: list[str],
) -> None:
    if not postprocessing_block:
        logger.info("No postprocessing block found. Skipping postprocessing.")
        return

    if not postprocessing_block.get("enabled", False):
        logger.info("Postprocessing is disabled in config.")
        return

    performance_block = postprocessing_block.get("performance_stats", {})
    comparison_block = postprocessing_block.get("link_performance_comparison", {})

    # -------------------------
    # Performance stats
    # -------------------------
    if performance_block.get("enabled", False):
        performance_scenarios = performance_block.get("scenario_names", top_level_scenario_names)

        if not performance_scenarios:
            raise ValueError(
                "Postprocessing performance_stats is enabled, but no scenario_names were provided."
            )

        logger.info("Starting postprocessing performance stats for scenarios: %s", performance_scenarios)

        config = build_postprocessing_config(
            catalog_dir=scenario_base_dir,
            scenario_names=performance_scenarios,
            postprocessing_block=postprocessing_block,
            time_periods=time_periods,
            period_times=period_times,
            performance_stats=True,
            link_performance_comparison=False,
        )

        run_postprocessing(config)

    # -------------------------
    # Link performance comparisons
    # -------------------------
    if comparison_block.get("enabled", False):
        scenario_pairs = comparison_block.get("scenario_pairs", [])

        if not scenario_pairs:
            raise ValueError(
                "Postprocessing link_performance_comparison is enabled, but no scenario_pairs were provided."
            )

        for pair in scenario_pairs:
            if len(pair) != 2:
                raise ValueError(
                    f"Each scenario pair must contain exactly two scenario names. Got: {pair}"
                )

            logger.info("Starting postprocessing comparison for pair: %s vs %s", pair[0], pair[1])

            config = build_postprocessing_config(
                catalog_dir=scenario_base_dir,
                scenario_names=pair,
                postprocessing_block=postprocessing_block,
                time_periods=time_periods,
                period_times=period_times,
                performance_stats=False,
                link_performance_comparison=True,
            )

            run_postprocessing(config)

    logger.info("Finished postprocessing stage.")


def run_from_config(config_data: dict[str, Any]) -> None:
    scenario_base_dir_raw = config_data.get("scenario_base_dir", "scenarios")
    scenario_paths = config_data.get("scenario_paths") or config_data.get("scenario_names", [])
    shared_assignment = config_data.get("assignment", {})
    scenario_overrides_map = config_data.get("scenario_overrides", {})
    postprocessing_block = config_data.get("postprocessing", {})
    time_periods = config_data.get(
        "time_periods",
        shared_assignment.get("time_periods", postprocessing_block.get("time_periods", ["am", "md", "pm", "nt"])),
    )
    period_times = config_data.get(
        "period_times",
        shared_assignment.get(
            "period_times",
            postprocessing_block.get("time_period_duration_list", ["0600_0900", "0900_1500", "1500_1900", "1900_0600"]),
        ),
    )

    if shared_assignment:
        shared_assignment = dict(shared_assignment)
        shared_assignment.setdefault("time_periods", time_periods)
        shared_assignment.setdefault("period_times", period_times)

    scenario_base_dir = PROJECT_ROOT / scenario_base_dir_raw

    # -------------------------
    # Assignment
    # -------------------------
    if shared_assignment:
        run_assignment_from_config(
            scenario_base_dir=scenario_base_dir,
            scenario_paths=scenario_paths,
            shared_assignment=shared_assignment,
            scenario_overrides_map=scenario_overrides_map,
        )
    else:
        logger.info("No assignment block found. Skipping assignment stage.")

    # -------------------------
    # Postprocessing
    # -------------------------
    run_postprocessing_from_config(
        scenario_base_dir=scenario_base_dir,
        top_level_scenario_names=scenario_paths,
        postprocessing_block=postprocessing_block,
        time_periods=time_periods,
        period_times=period_times,
    )

    logger.info("Finished all configured stages.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run DTALite assignment and postprocessing pipelines from a project config file."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to the JSON config file, relative to project root or absolute.",
    )

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    config_data = load_json(config_path)
    run_from_config(config_data)


if __name__ == "__main__":
    main()
