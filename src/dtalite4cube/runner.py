from __future__ import annotations

import argparse
import csv
import logging
import shutil
import time
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Iterable

from .backmap_outputs import BackmapResult
from .backmap_outputs import backmap_dtalite_outputs as backmap_outputs_to_original_ids
from .cube2gmns import get_gmns_from_cube
from .omx2csv import get_gmns_demand_from_omx
from .internal_config import BACKMAP_DTALITE_OUTPUTS
from .internal_config import KEEP_SEQUENTIAL_WORK_DIR
from .internal_config import RENUMBER_LINK_IDS_IF_NEEDED
from .internal_config import RUN_GMNS_READINESS_CHECK
from .internal_config import USE_SEQUENTIAL_IDS_FOR_DTALITE
from .internal_config import WRITE_ASSIGNMENT_SUMMARY
from .readiness_check import ReadinessResult
from .readiness_check import run_gmns_readiness_check as run_period_readiness_check
from .reproducible_run import (
    parse_convergence,
    preflight,
    run_dtalite,
    stage_inputs,
    verify_outputs,
    write_run_card,
)
from .renumbering import RenumberResult, renumber_period_folder
from .settings.dtalite_settings_config import SUPPORTED_MODE_TYPES, demand_file_name
from .settings.generate_dtalite_settings import (
    configure_time_period_hours,
    generate_dtalite_input_files,
    normalize_period_key,
)

logger = logging.getLogger(__name__)

LEGACY_ASSIGNMENT_KEYS = {
    "dta_exe_name",
    "inplace",
    "length",
    "memory_blocks",
    "metric_system",
    "modes",
    "period_scale_factors",
    "route",
    "scenario_output_dir",
    "settings_overrides",
    "simu",
    "speed",
}

INTERNAL_ASSIGNMENT_KEYS = {
    "use_sequential_ids_for_dtalite",
    "renumber_link_ids_if_needed",
    "run_gmns_readiness_check",
    "backmap_dtalite_outputs",
    "write_assignment_summary",
}


@dataclass
class AssignmentConfig:
    network_path: Path
    scenario_name: str | None = None
    ue_converge: float = 0.1
    dtalite_run_mode: str = "assignment"
    time_periods: list[str] = field(default_factory=lambda: ["am", "md", "pm", "nt"])
    period_times: list[str] = field(default_factory=lambda: ["0600_0900", "0900_1500", "1500_1900", "1900_0600"])
    output_files: list[str] = field(default_factory=lambda: [
        "log.txt",
        "summary_log.txt",
        "link_performance.csv",
    ])
    dtalite_assignment: bool = False
    network_conversion: bool = False
    demand_conversion: bool = False
    work_dir: Path | None = None
    output_dir: Path | None = None
    iterations: int = 10
    processors: int = 8
    route_output: int = 0
    vehicle_output: int = 0
    period_start: int = 7
    period_end: int = 8
    unit_system: str = "metric"
    vdf_type: str = "bpr"
    label: str | None = None
    inplace: bool = True
    dry_run: bool = False
    no_rename_columns: bool = False
    scenario_input_dir: Path | None = None
    demand_dir: Path | None = None
    write_legacy_outputs: bool = False
    use_sequential_ids_for_dtalite: bool = field(default=USE_SEQUENTIAL_IDS_FOR_DTALITE, init=False)
    renumber_link_ids_if_needed: bool = field(default=RENUMBER_LINK_IDS_IF_NEEDED, init=False)
    run_gmns_readiness_check: bool = field(default=RUN_GMNS_READINESS_CHECK, init=False)
    backmap_dtalite_outputs: bool = field(default=BACKMAP_DTALITE_OUTPUTS, init=False)
    write_assignment_summary: bool = field(default=WRITE_ASSIGNMENT_SUMMARY, init=False)

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentConfig":
        parsed = data.copy()
        if "iteration" in parsed and "iterations" not in parsed:
            logger.warning("Using legacy assignment config key 'iteration' as 'iterations'.")
            parsed["iterations"] = parsed["iteration"]
        parsed.pop("iteration", None)

        if "metric_system" in parsed and "unit_system" not in parsed:
            logger.warning("Using legacy assignment config key 'metric_system' as 'unit_system'.")
            parsed["unit_system"] = "imperial" if parsed["metric_system"] == 1 else "metric"

        if "period_titles" in parsed and "time_periods" not in parsed:
            logger.warning("Using legacy assignment config key 'period_titles' as 'time_periods'.")
            parsed["time_periods"] = parsed["period_titles"]
        elif "period_titles" in parsed:
            logger.warning("Ignoring legacy assignment config key: period_titles")
        parsed.pop("period_titles", None)

        for legacy_key in LEGACY_ASSIGNMENT_KEYS:
            if legacy_key in parsed:
                logger.warning("Ignoring legacy assignment config key: %s", legacy_key)
                parsed.pop(legacy_key, None)

        for internal_key in INTERNAL_ASSIGNMENT_KEYS:
            if internal_key in parsed:
                logger.warning(
                    "Ignoring internal assignment config key: %s; controlled by src/dtalite4cube/internal_config.py",
                    internal_key,
                )
                parsed.pop(internal_key, None)

        known_fields = {field.name for field in dataclass_fields(cls)}
        unknown_keys = sorted(set(parsed) - known_fields)
        if unknown_keys:
            logger.warning("Ignoring unknown assignment config key(s): %s", ", ".join(unknown_keys))
            for key in unknown_keys:
                parsed.pop(key, None)

        parsed["network_path"] = Path(parsed["network_path"])
        for path_key in ("work_dir", "output_dir", "scenario_input_dir", "demand_dir"):
            if parsed.get(path_key) is not None:
                parsed[path_key] = Path(parsed[path_key])
        return cls(**parsed)

    def validate(self) -> None:
        if not self.network_path.exists():
            raise FileNotFoundError(f"Scenario folder does not exist: {self.network_path}")

        if self.dtalite_run_mode not in {"assignment", "simulation"}:
            raise ValueError("dtalite_run_mode must be 'assignment' or 'simulation'.")

        if self.dtalite_run_mode == "simulation":
            raise NotImplementedError("dtalite_run_mode='simulation' is reserved but not implemented in this workflow.")

        if self.unit_system not in {"imperial", "metric"}:
            raise ValueError("unit_system must be either 'imperial' for mile/mph or 'metric' for km/kph.")

        if self.route_output not in {0, 1}:
            raise ValueError("route_output must be 0 or 1.")

        if self.vehicle_output not in {0, 1}:
            raise ValueError("vehicle_output must be 0 or 1.")

        if self.vdf_type not in {"bpr", "qvdf"}:
            raise ValueError("vdf_type must be either 'bpr' or 'qvdf'.")

        if len(self.active_time_periods) != len(self.period_times):
            raise ValueError("time_periods and period_times must have the same length.")

        if not self.active_time_periods:
            raise ValueError("time_periods cannot be empty.")

    @property
    def active_time_periods(self) -> list[str]:
        return [normalize_period_key(period) for period in self.time_periods]

    @property
    def length_unit(self) -> str:
        return "mile" if self.unit_system == "imperial" else "km"

    @property
    def speed_unit(self) -> str:
        return "mph" if self.unit_system == "imperial" else "kph"

    @property
    def metric_system(self) -> int:
        return 1 if self.unit_system == "imperial" else 0


def run_network_conversion(config: AssignmentConfig) -> None:
    scenario_output_dir = resolve_scenario_output_dir(config)
    logger.info("Running network conversion into period folders under %s", scenario_output_dir)
    get_gmns_from_cube(
        str(config.network_path),
        config.active_time_periods,
        length_unit=config.length_unit,
        speed_unit=config.speed_unit,
        district_id_assignment=True,
        capacity_adjustment=False,
        vdf_type=config.vdf_type,
        output_dir=str(scenario_output_dir),
        period_folder_output=True,
    )


def run_demand_conversion(config: AssignmentConfig) -> None:
    scenario_output_dir = resolve_scenario_output_dir(config)
    demand_dir = config.demand_dir or config.network_path
    logger.info("Running demand conversion into period folders under %s", scenario_output_dir)
    get_gmns_demand_from_omx(
        str(demand_dir),
        config.active_time_periods,
        output_base_dir=scenario_output_dir,
        period_folder_output=True,
    )


def resolve_scenario_input_dir(config: AssignmentConfig) -> Path:
    return config.scenario_input_dir or config.network_path


def resolve_scenario_output_dir(config: AssignmentConfig) -> Path:
    configured = config.output_dir
    if configured is not None:
        return configured if configured.is_absolute() else config.network_path / configured
    return config.network_path


def resolve_run_folder(config: AssignmentConfig, time_period: str | None = None) -> Path:
    configured_path = config.work_dir
    if configured_path is not None:
        base = configured_path if configured_path.is_absolute() else config.network_path / configured_path
    else:
        base = config.network_path / "dtalite_runs" / "latest"

    if time_period is not None:
        return base / time_period
    return base


def prepare_dtalite_period_folders(
    scenario_input_dir: Path,
    scenario_output_dir: Path,
    time_periods: list[str],
    *,
    demand_dir: Path | None = None,
    settings_overrides: dict | None = None,
) -> dict[str, Path]:
    scenario_input_dir = Path(scenario_input_dir)
    scenario_output_dir = Path(scenario_output_dir)
    demand_source_dir = Path(demand_dir) if demand_dir is not None else scenario_input_dir

    prepared_folders: dict[str, Path] = {}
    for raw_period in time_periods:
        period_key = normalize_period_key(raw_period)
        period_folder = scenario_output_dir / period_key
        period_folder.mkdir(parents=True, exist_ok=True)

        period_node = period_folder / "node.csv"
        if not period_node.is_file():
            node_source = scenario_input_dir / "node.csv"
            if not node_source.is_file():
                raise FileNotFoundError(
                    f"Missing node.csv for {period_key}. Expected {period_node} "
                    f"or legacy source {node_source}"
                )
            _copy_if_different(node_source, period_node)

        period_link = period_folder / "link.csv"
        if not period_link.is_file():
            link_source = scenario_input_dir / f"link_{period_key}.csv"
            direct_link_source = scenario_input_dir / period_key / "link.csv"
            if direct_link_source.is_file():
                link_source = direct_link_source
            elif not link_source.is_file():
                raise FileNotFoundError(
                    f"Missing period link file for {period_key}. Expected {period_link}, "
                    f"{direct_link_source}, or legacy source {link_source}"
                )
            _copy_if_different(link_source, period_link)

        for mode in SUPPORTED_MODE_TYPES:
            demand_name = demand_file_name(mode, period_key)
            period_demand = period_folder / demand_name
            if not period_demand.is_file():
                demand_source = demand_source_dir / demand_name
                direct_demand_source = demand_source_dir / period_key / demand_name
                if direct_demand_source.is_file():
                    demand_source = direct_demand_source
                elif not demand_source.is_file():
                    raise FileNotFoundError(
                        f"Missing demand file for {period_key}: expected {period_demand}, "
                        f"{direct_demand_source}, or legacy source {demand_source}"
                    )
                _copy_if_different(demand_source, period_demand)

        generate_dtalite_input_files(period_folder, period_key, overrides=settings_overrides)
        _validate_period_folder(period_folder)
        prepared_folders[period_key] = period_folder
        logger.info("Prepared DTALite period folder for %s: %s", period_key, period_folder)

    return prepared_folders


def remove_root_period_duplicates(scenario_output_dir: Path, time_periods: list[str]) -> list[Path]:
    scenario_output_dir = Path(scenario_output_dir)
    removed: list[Path] = []

    for file_name in ("link.csv", "demand.csv", "settings.csv", "mode_type.csv"):
        path = scenario_output_dir / file_name
        if path.is_file():
            path.unlink()
            removed.append(path)

    node_path = scenario_output_dir / "node.csv"
    if node_path.is_file() and all((scenario_output_dir / period / "node.csv").is_file() for period in time_periods):
        node_path.unlink()
        removed.append(node_path)

    for period in time_periods:
        period_folder = scenario_output_dir / period
        period_file_pairs = {
            f"link_{period}.csv": period_folder / "link.csv",
            f"settings_{period}.csv": period_folder / "settings.csv",
            f"mode_type_{period}.csv": period_folder / "mode_type.csv",
            f"demand_{period}.csv": period_folder / "demand.csv",
        }
        for mode in SUPPORTED_MODE_TYPES:
            demand_name = demand_file_name(mode, period)
            period_file_pairs[demand_name] = period_folder / demand_name

        for root_name, period_path in period_file_pairs.items():
            root_path = scenario_output_dir / root_name
            if root_path.is_file() and period_path.is_file():
                root_path.unlink()
                removed.append(root_path)

    for path in removed:
        logger.info("Removed root-level generated duplicate: %s", path)

    return removed


def _copy_if_different(source: Path, target: Path) -> None:
    source = Path(source)
    target = Path(target)
    if source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    logger.info("Copied %s -> %s", source, target)


def _validate_period_folder(period_folder: Path) -> None:
    for required_file in ("node.csv", "link.csv", "settings.csv", "mode_type.csv"):
        path = period_folder / required_file
        if not path.is_file():
            raise FileNotFoundError(f"Prepared period folder is missing {required_file}: {period_folder}")

    with (period_folder / "settings.csv").open("r", newline="", encoding="utf-8") as f:
        if sum(1 for _ in f) != 2:
            raise ValueError(f"settings.csv must have exactly 2 lines: {period_folder / 'settings.csv'}")

    with (period_folder / "mode_type.csv").open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 6:
        raise ValueError(f"mode_type.csv must have exactly 6 mode rows: {period_folder / 'mode_type.csv'}")

    missing = [row["demand_file"] for row in rows if not (period_folder / row["demand_file"]).is_file()]
    if missing:
        raise FileNotFoundError(
            f"mode_type.csv in {period_folder} references missing demand file(s): {', '.join(missing)}"
        )


def copy_route_assignment_to_columns(work_dir: Path) -> None:
    route_assignment = work_dir / "route_assignment.csv"
    columns = work_dir / "columns.csv"
    shutil.copy2(route_assignment, columns)
    logger.info("Copied %s to %s", route_assignment.name, columns.name)


def run_reproducible_dtalite(
    *,
    config: AssignmentConfig,
    source_network_path: Path,
    work_dir: Path,
    label: str,
    time_period: str | None = None,
) -> Path:
    logger.info("Starting reproducible DTALite run: source=%s work_dir=%s", source_network_path, work_dir)
    preflight_info = preflight(source_network_path)

    if config.dry_run:
        logger.info("DTALite dry_run=True; preflight passed and execution is skipped.")
        return work_dir

    stage_inputs(
        source_network_path,
        source_network_path if config.inplace else work_dir,
        iterations=config.iterations,
        processors=config.processors,
        route_output=config.route_output,
        vehicle_output=config.vehicle_output,
        period_start=config.period_start,
        period_end=config.period_end,
        metric_system=config.metric_system,
    )
    run_folder = source_network_path if config.inplace else work_dir
    elapsed, log = run_dtalite(run_folder)
    verify_info = verify_outputs(run_folder, route_output=config.route_output)
    convergence = parse_convergence(log, run_folder)

    if config.route_output and not config.no_rename_columns:
        copy_route_assignment_to_columns(run_folder)

    args_used = {
        "iterations": config.iterations,
        "processors": config.processors,
        "route_output": config.route_output,
        "vehicle_output": config.vehicle_output,
        "period_start": config.period_start,
        "period_end": config.period_end,
        "unit_system": config.unit_system,
    }
    write_run_card(
        run_folder,
        source_network_path,
        label,
        preflight_info,
        elapsed,
        convergence,
        verify_info,
        args_used,
    )

    if time_period is not None and config.write_legacy_outputs:
        output_files = [
            *config.output_files,
            "od_performance.csv",
            "dtalite_run.log",
            "summary_log_file.txt",
            "RUN_CARD.md",
        ]
        if config.route_output:
            output_files.extend(["route_assignment.csv", "columns.csv"])

        save_period_outputs(
            network_path=config.network_path,
            source_dir=run_folder,
            time_period=time_period,
            output_files=output_files,
            extra_files=[],
        )

    return run_folder


def run_sequential_dtalite_assignment(
    *,
    config: AssignmentConfig,
    source_network_path: Path,
    label: str,
    time_period: str,
    readiness_result: ReadinessResult | None = None,
) -> Path:
    logger.info("Starting sequential-ID DTALite run: source=%s", source_network_path)
    renumber_result: RenumberResult | None = None
    backmap_result: BackmapResult | None = None
    convergence: dict[str, object] = {}
    verify_info: dict[str, object] = {}
    elapsed = 0.0
    dtalite_log_path = source_network_path / f"{source_network_path.name}_seq" / "dtalite_run.log"
    dtalite_log_text = ""
    run_status = "not_started"
    summary_written = False

    try:
        renumber_result = renumber_period_folder(
            source_network_path,
            renumber_link_ids_if_needed=config.renumber_link_ids_if_needed,
        )
        logger.info("sequential renumbering complete: %s", renumber_result.sequential_dir)

        preflight_info = preflight(renumber_result.sequential_dir)
        if config.dry_run:
            run_status = "dry_run"
            logger.info("DTALite dry_run=True; sequential preflight passed and execution is skipped.")
            return renumber_result.sequential_dir

        stage_inputs(
            renumber_result.sequential_dir,
            renumber_result.sequential_dir,
            iterations=config.iterations,
            processors=config.processors,
            route_output=config.route_output,
            vehicle_output=config.vehicle_output,
            period_start=config.period_start,
            period_end=config.period_end,
            metric_system=config.metric_system,
        )
        elapsed, dtalite_log_text = run_dtalite(renumber_result.sequential_dir)
        dtalite_log_path = renumber_result.sequential_dir / "dtalite_run.log"
        verify_info = verify_outputs(renumber_result.sequential_dir, route_output=0)
        convergence = parse_convergence(dtalite_log_text, renumber_result.sequential_dir)

        route_assignment = renumber_result.sequential_dir / "route_assignment.csv"
        if (
            config.route_output
            and not config.no_rename_columns
            and route_assignment.exists()
            and route_assignment.stat().st_size > 0
        ):
            copy_route_assignment_to_columns(renumber_result.sequential_dir)

        args_used = {
            "iterations": config.iterations,
            "processors": config.processors,
            "route_output": config.route_output,
            "vehicle_output": config.vehicle_output,
            "period_start": config.period_start,
            "period_end": config.period_end,
            "unit_system": config.unit_system,
            "use_sequential_ids_for_dtalite": config.use_sequential_ids_for_dtalite,
        }
        write_run_card(
            renumber_result.sequential_dir,
            source_network_path,
            label,
            preflight_info,
            elapsed,
            convergence,
            verify_info,
            args_used,
        )
        run_status = "success"
        logger.info("DTALite assignment complete")

        if config.backmap_dtalite_outputs:
            backmap_result = backmap_outputs_to_original_ids(
                renumber_result.sequential_dir,
                source_network_path,
                mapping_path=renumber_result.mapping_path,
                link_ids_renumbered=renumber_result.stats.link_ids_renumbered,
            )
            logger.info("backmap complete: %s", backmap_result.output_dir)
            output_dir = backmap_result.output_dir
        else:
            output_dir = renumber_result.sequential_dir

        if time_period is not None and config.write_legacy_outputs:
            output_files = [
                *config.output_files,
                "od_performance.csv",
                "dtalite_run.log",
                "summary_log_file.txt",
                "RUN_CARD.md",
            ]
            if config.route_output:
                output_files.extend(["route_assignment.csv", "columns.csv"])
            save_period_outputs(
                network_path=config.network_path,
                source_dir=output_dir,
                time_period=time_period,
                output_files=output_files,
                extra_files=[],
            )

        return output_dir
    except Exception as exc:
        run_status = f"failed: {exc}"
        raise
    finally:
        if config.write_assignment_summary and renumber_result is not None:
            summary_dir = source_network_path if backmap_result is not None else renumber_result.sequential_dir
            _write_assignment_summary(
                summary_dir / "RUN_SUMMARY.md",
                config=config,
                time_period=time_period,
                renumber_result=renumber_result,
                run_status=run_status,
                convergence=convergence,
                dtalite_log=dtalite_log_path,
                readiness_result=readiness_result,
                backmap_result=backmap_result,
            )
            logger.info("summary written: %s", summary_dir / "RUN_SUMMARY.md")
            summary_written = True
        if run_status == "success" and summary_written and renumber_result is not None and backmap_result is not None:
            _cleanup_sequential_work_dir(renumber_result.sequential_dir)


def _write_assignment_summary(
    path: Path,
    *,
    config: AssignmentConfig,
    time_period: str,
    renumber_result: RenumberResult,
    run_status: str,
    convergence: dict[str, object],
    dtalite_log: Path,
    readiness_result: ReadinessResult | None,
    backmap_result: BackmapResult | None,
) -> None:
    stats = renumber_result.stats
    missing_optional = backmap_result.missing_optional_files if backmap_result else []
    empty_optional = backmap_result.empty_optional_files if backmap_result else []
    readiness_log = readiness_result.log_path if readiness_result else None
    convergence_lines = [f"  - {key}: {value}" for key, value in convergence.items()] or ["  - not available"]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# DTALite Assignment Summary",
                "",
                f"- Scenario: {config.scenario_name or config.network_path.name}",
                f"- Period: {time_period}",
                f"- Original node count: {stats.original_node_count}",
                f"- Original max node ID: {stats.original_max_node_id}",
                f"- Sequential node count: {stats.sequential_node_count}",
                f"- Sequential max node ID: {stats.sequential_max_node_id}",
                f"- Original zone count: {stats.original_zone_count}",
                f"- Original max zone ID: {stats.original_max_zone_id}",
                f"- Sequential zone count: {stats.sequential_zone_count}",
                f"- Sequential max zone ID: {stats.sequential_max_zone_id}",
                f"- Original link count: {stats.original_link_count}",
                f"- Original max link ID: {stats.original_max_link_id}",
                f"- Sequential link count: {stats.sequential_link_count}",
                f"- Sequential max link ID: {stats.sequential_max_link_id}",
                f"- Link IDs renumbered: {stats.link_ids_renumbered}",
                f"- DTALite run status: {run_status}",
                f"- Missing optional files: {', '.join(missing_optional) if missing_optional else 'none'}",
                f"- Empty optional files: {', '.join(empty_optional) if empty_optional else 'none'}",
                f"- Full DTALite log: {dtalite_log}",
                f"- GMNS readiness log: {readiness_log if readiness_log else 'not run'}",
                "",
                "## Convergence",
                *convergence_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _cleanup_sequential_work_dir(seq_dir: Path) -> None:
    if KEEP_SEQUENTIAL_WORK_DIR:
        logger.warning(
            "Keeping internal sequential work folder because DTALITE_KEEP_SEQ_DIR is enabled: %s",
            seq_dir,
        )
        return

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            shutil.rmtree(seq_dir)
            logger.info("Removed internal sequential work folder: %s", seq_dir)
            return
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(0.5)

    logger.warning(
        "Could not remove internal sequential work folder %s: %s",
        seq_dir,
        last_error,
    )


def save_period_outputs(
    *,
    network_path: Path,
    source_dir: Path,
    time_period: str,
    output_files: Iterable[str],
    extra_files: Iterable[str],
) -> None:
    output_dir = network_path / "Outputs" / "DTALite"
    output_dir.mkdir(parents=True, exist_ok=True)

    period_suffix = f"_{time_period}"

    for file_name in output_files:
        source_path = source_dir / file_name
        if not source_path.exists():
            logger.warning("Expected output file not found: %s", source_path)
            continue

        new_name = f"{source_path.stem}{period_suffix}{source_path.suffix}"
        target_path = output_dir / new_name
        shutil.copyfile(source_path, target_path)
        logger.info("Saved %s", target_path)

    for file_name in extra_files:
        source_path = network_path / file_name
        if not source_path.exists():
            logger.warning("Extra file not found: %s", source_path)
            continue

        target_path = output_dir / source_path.name
        shutil.copyfile(source_path, target_path)
        logger.info("Saved %s", target_path)


def run_assignment_pipeline(config: AssignmentConfig) -> bool:
    config.validate()
    configure_time_period_hours(config.active_time_periods, config.period_times)
    # logger.info("Running assignment pipeline for: %s", config.network_path)
    logger.info(
        "Running assignment pipeline for scenario=%s path=%s",
        config.scenario_name or "<unnamed>",
        config.network_path,
    )
    if KEEP_SEQUENTIAL_WORK_DIR:
        logger.warning(
            "DEBUG MODE ENABLED: DTALITE_KEEP_SEQ_DIR=1. Internal <period>_seq folders will be preserved."
        )

    if config.network_conversion:
        run_network_conversion(config)

    if config.demand_conversion:
        run_demand_conversion(config)

    scenario_input_dir = resolve_scenario_input_dir(config)
    scenario_output_dir = resolve_scenario_output_dir(config)
    prepared_period_folders = prepare_dtalite_period_folders(
        scenario_input_dir=scenario_input_dir,
        scenario_output_dir=scenario_output_dir,
        time_periods=config.active_time_periods,
        demand_dir=config.demand_dir,
        settings_overrides={
            "number_of_iterations": config.iterations,
            "number_of_processors": config.processors,
            "route_output": config.route_output,
            "vehicle_output": config.vehicle_output,
        },
    )
    remove_root_period_duplicates(scenario_output_dir, config.active_time_periods)
    logger.info("conversion complete")

    readiness_results: dict[str, ReadinessResult] = {}
    if config.run_gmns_readiness_check:
        for time_period, period_source in prepared_period_folders.items():
            readiness_results[time_period] = run_period_readiness_check(period_source)
        logger.info("readiness check complete")

    if not config.dtalite_assignment:
        logger.info("DTALite assignment is disabled for: %s", config.network_path)
        return False

    for time_period, period_source in prepared_period_folders.items():
        period_label = f"{config.label or config.scenario_name or 'scenario'}_{time_period}"
        if config.use_sequential_ids_for_dtalite:
            run_sequential_dtalite_assignment(
                config=config,
                source_network_path=period_source,
                label=period_label,
                time_period=time_period,
                readiness_result=readiness_results.get(time_period),
            )
        else:
            run_reproducible_dtalite(
                config=config,
                source_network_path=period_source,
                work_dir=resolve_run_folder(config, time_period=time_period),
                label=period_label,
                time_period=time_period,
            )

    logger.info("Finished DTALite assignment pipeline for: %s", config.network_path)
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run DTALite4Cube assignment pipeline for a scenario."
    )

    parser.add_argument("--network-path", required=True, help="Scenario folder path")
    parser.add_argument("--dtalite-run-mode", choices=["assignment", "simulation"], default="assignment")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--scenario-input-dir", type=Path)
    parser.add_argument("--demand-dir", type=Path)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--processors", type=int, default=8)
    parser.add_argument("--route-output", type=int, choices=[0, 1], default=0)
    parser.add_argument("--vehicle-output", type=int, choices=[0, 1], default=0)
    parser.add_argument("--period-start", type=int, default=7)
    parser.add_argument("--period-end", type=int, default=8)
    parser.add_argument("--unit-system", choices=["imperial", "metric"], default="metric")
    parser.add_argument("--metric-system", type=int, choices=[0, 1], help="Legacy alias: 1=imperial, 0=metric.")
    parser.add_argument("--vdf-type", choices=["bpr", "qvdf"], default="bpr")
    parser.add_argument("--label")

    parser.add_argument("--network-conversion", action="store_true")
    parser.add_argument("--demand-conversion", action="store_true")
    parser.add_argument("--dtalite-assignment", action="store_true")
    parser.add_argument("--isolated-work-dir", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-rename-columns", action="store_true")
    parser.add_argument("--time-periods", nargs="+", default=["am", "md", "pm", "nt"])
    parser.add_argument(
        "--period-times",
        nargs="+",
        default=["0600_0900", "0900_1500", "1500_1900", "1900_0600"],
    )

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args()

    config = AssignmentConfig(
        network_path=Path(args.network_path),
        dtalite_run_mode=args.dtalite_run_mode,
        time_periods=args.time_periods,
        period_times=args.period_times,
        dtalite_assignment=args.dtalite_assignment,
        network_conversion=args.network_conversion,
        demand_conversion=args.demand_conversion,
        work_dir=args.work_dir,
        output_dir=args.output_dir,
        scenario_input_dir=args.scenario_input_dir,
        demand_dir=args.demand_dir,
        iterations=args.iterations,
        processors=args.processors,
        route_output=args.route_output,
        vehicle_output=args.vehicle_output,
        period_start=args.period_start,
        period_end=args.period_end,
        unit_system=args.unit_system if args.metric_system is None else ("imperial" if args.metric_system == 1 else "metric"),
        vdf_type=args.vdf_type,
        label=args.label,
        inplace=not args.isolated_work_dir,
        dry_run=args.dry_run,
        no_rename_columns=args.no_rename_columns,
    )

    run_assignment_pipeline(config)


if __name__ == "__main__":
    main()
