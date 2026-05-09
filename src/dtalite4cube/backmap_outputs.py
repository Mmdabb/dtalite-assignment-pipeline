"""Back-map DTALite outputs from compact sequential IDs to original IDs."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .id_mapping import IdMapping, clean_id, read_id_mapping


OPTIONAL_OUTPUTS = {"route_assignment.csv", "columns.csv"}
BACKMAP_SPECS = {
    "link_performance.csv": {
        "node_columns": ("from_node_id", "to_node_id"),
        "zone_columns": (),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": True,
    },
    "od_performance.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "d_zone_id"),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": False,
    },
    "origin_accessibility.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "origin_zone_id"),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": False,
    },
    "destination_accessibility.csv": {
        "node_columns": (),
        "zone_columns": ("d_zone_id", "destination_zone_id"),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": False,
    },
    "inaccessible_od.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "d_zone_id", "origin_zone_id", "destination_zone_id"),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": False,
    },
    "google_maps_od_distance.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "d_zone_id"),
        "node_list_columns": (),
        "link_list_columns": (),
        "maybe_link_id": False,
    },
    "route_assignment.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "d_zone_id"),
        "node_list_columns": ("node_ids",),
        "link_list_columns": ("link_ids",),
        "maybe_link_id": False,
    },
    "columns.csv": {
        "node_columns": (),
        "zone_columns": ("o_zone_id", "d_zone_id"),
        "node_list_columns": ("node_ids",),
        "link_list_columns": ("link_ids",),
        "maybe_link_id": False,
    },
}


@dataclass(frozen=True)
class BackmapResult:
    output_dir: Path
    backmapped_files: list[str] = field(default_factory=list)
    copied_files: list[str] = field(default_factory=list)
    missing_optional_files: list[str] = field(default_factory=list)
    empty_optional_files: list[str] = field(default_factory=list)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _validate_output_dir(sequential_dir: Path, output_dir: Path) -> None:
    source = sequential_dir.resolve()
    target = output_dir.resolve()
    if target == source or target != source.parent:
        raise ValueError(f"Refusing to backmap into unexpected folder: {target}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _remap_value(value: object, mapping: dict[str, str]) -> str:
    text = clean_id(value)
    return mapping.get(text, text)


def _remap_id_list(value: object, mapping: dict[str, str]) -> str:
    text = clean_id(value)
    if not text:
        return text
    tokens = [token.strip() for token in text.split(";") if token.strip()]
    return ";".join(mapping.get(token, token) for token in tokens)


def _backmap_table(path: Path, output_path: Path, mapping: IdMapping) -> bool:
    spec = BACKMAP_SPECS[path.name]
    fieldnames, rows = _read_csv(path)
    if not rows:
        return False

    node_back = mapping.node_id_back
    zone_back = mapping.zone_id_back
    link_back = mapping.link_id_back

    for row in rows:
        for column in spec["node_columns"]:
            if column in row:
                row[column] = _remap_value(row.get(column), node_back)
        for column in spec["zone_columns"]:
            if column in row:
                row[column] = _remap_value(row.get(column), zone_back)
        if spec["maybe_link_id"] and mapping.link_ids_renumbered and "link_id" in row:
            row["link_id"] = _remap_value(row.get("link_id"), link_back)
        for column in spec["node_list_columns"]:
            if column in row:
                row[column] = _remap_id_list(row.get(column), node_back)
        if mapping.link_ids_renumbered:
            for column in spec["link_list_columns"]:
                if column in row:
                    row[column] = _remap_id_list(row.get(column), link_back)

    _write_csv(output_path, fieldnames, rows)
    return True


def verify_backmapped_outputs_use_original_ids(output_dir: Path, mapping: IdMapping) -> None:
    original_nodes = set(mapping.node_id)
    original_zones = set(mapping.zone_id)
    original_links = set(mapping.link_id)

    checks = {
        "link_performance.csv": {
            "node_columns": ("from_node_id", "to_node_id"),
            "zone_columns": (),
            "node_list_columns": (),
            "link_columns": ("link_id",) if mapping.link_ids_renumbered else (),
            "link_list_columns": (),
        },
        "od_performance.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "d_zone_id"),
            "node_list_columns": (),
            "link_columns": (),
            "link_list_columns": (),
        },
        "origin_accessibility.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "origin_zone_id"),
            "node_list_columns": (),
            "link_columns": (),
            "link_list_columns": (),
        },
        "destination_accessibility.csv": {
            "node_columns": (),
            "zone_columns": ("d_zone_id", "destination_zone_id"),
            "node_list_columns": (),
            "link_columns": (),
            "link_list_columns": (),
        },
        "inaccessible_od.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "d_zone_id", "origin_zone_id", "destination_zone_id"),
            "node_list_columns": (),
            "link_columns": (),
            "link_list_columns": (),
        },
        "google_maps_od_distance.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "d_zone_id"),
            "node_list_columns": (),
            "link_columns": (),
            "link_list_columns": (),
        },
        "route_assignment.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "d_zone_id"),
            "node_list_columns": ("node_ids",),
            "link_columns": (),
            "link_list_columns": ("link_ids",) if mapping.link_ids_renumbered else (),
        },
        "columns.csv": {
            "node_columns": (),
            "zone_columns": ("o_zone_id", "d_zone_id"),
            "node_list_columns": ("node_ids",),
            "link_columns": (),
            "link_list_columns": ("link_ids",) if mapping.link_ids_renumbered else (),
        },
    }

    for file_name, spec in checks.items():
        path = output_dir / file_name
        if not path.exists():
            continue
        _, rows = _read_csv(path)
        for row in rows:
            for column in spec["node_columns"]:
                _verify_original_id(row, column, original_nodes, path, "node")
            for column in spec["zone_columns"]:
                _verify_original_id(row, column, original_zones, path, "zone")
            for column in spec["link_columns"]:
                _verify_original_id(row, column, original_links, path, "link")
            for column in spec["node_list_columns"]:
                _verify_original_id_list(row, column, original_nodes, path, "node")
            for column in spec["link_list_columns"]:
                _verify_original_id_list(row, column, original_links, path, "link")


def _verify_original_id(
    row: dict[str, str],
    column: str,
    original_ids: set[str],
    path: Path,
    id_type: str,
) -> None:
    if column not in row:
        return
    value = clean_id(row.get(column))
    if value and value not in original_ids:
        raise ValueError(f"{column} {value} in {path} is not an original {id_type} ID")


def _verify_original_id_list(
    row: dict[str, str],
    column: str,
    original_ids: set[str],
    path: Path,
    id_type: str,
) -> None:
    if column not in row:
        return
    text = clean_id(row.get(column))
    if not text:
        return
    for value in [token.strip() for token in text.split(";") if token.strip()]:
        if value not in original_ids:
            raise ValueError(f"{column} value {value} in {path} is not an original {id_type} ID")


def backmap_dtalite_outputs(
    sequential_dir: Path,
    output_dir: Path | None = None,
    *,
    mapping_path: Path | None = None,
    link_ids_renumbered: bool = False,
) -> BackmapResult:
    sequential_dir = Path(sequential_dir)
    output_dir = output_dir or sequential_dir.parent
    mapping_path = mapping_path or sequential_dir / "id_mapping.csv"
    mapping = read_id_mapping(mapping_path, link_ids_renumbered=link_ids_renumbered)
    _validate_output_dir(sequential_dir, output_dir)

    files_to_backmap = set(BACKMAP_SPECS)
    backmapped_files: list[str] = []
    copied_files: list[str] = []
    missing_optional_files: list[str] = []
    empty_optional_files: list[str] = []

    for file_name in sorted(files_to_backmap):
        source = sequential_dir / file_name
        target = output_dir / file_name
        if not source.exists():
            if target.exists():
                target.unlink()
            if file_name in OPTIONAL_OUTPUTS:
                missing_optional_files.append(file_name)
            continue
        if source.stat().st_size == 0:
            if target.exists():
                target.unlink()
            if file_name in OPTIONAL_OUTPUTS:
                empty_optional_files.append(file_name)
            continue
        if _backmap_table(source, target, mapping):
            backmapped_files.append(file_name)
        elif file_name in OPTIONAL_OUTPUTS:
            empty_optional_files.append(file_name)

    verify_backmapped_outputs_use_original_ids(output_dir, mapping)
    return BackmapResult(output_dir, backmapped_files, copied_files, missing_optional_files, empty_optional_files)
