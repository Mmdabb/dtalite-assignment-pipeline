"""Create compact sequential-ID DTALite run folders."""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from .id_mapping import (
    IdMapping,
    clean_id,
    id_sort_key,
    is_nonzero_id,
    is_one_based_sequential,
    max_numeric_id,
    write_id_mapping,
)


@dataclass(frozen=True)
class RenumberStats:
    original_node_count: int
    original_max_node_id: int | None
    sequential_node_count: int
    sequential_max_node_id: int | None
    original_zone_count: int
    original_max_zone_id: int | None
    sequential_zone_count: int
    sequential_max_zone_id: int | None
    original_link_count: int
    original_max_link_id: int | None
    sequential_link_count: int
    sequential_max_link_id: int | None
    link_ids_renumbered: bool


@dataclass(frozen=True)
class RenumberResult:
    source_dir: Path
    sequential_dir: Path
    mapping_path: Path
    mapping: IdMapping
    stats: RenumberStats


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


def _reset_generated_dir(source_dir: Path, target_dir: Path, suffix: str) -> None:
    source = source_dir.resolve()
    target = target_dir.resolve()
    if target == source or target.parent not in {source, source.parent} or not target.name.endswith(suffix):
        raise ValueError(f"Refusing to reset unexpected generated folder: {target}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _demand_files_from_mode_type(mode_type_path: Path) -> list[str]:
    if not mode_type_path.exists():
        return []
    _, rows = _read_csv(mode_type_path)
    files: list[str] = []
    for row in rows:
        demand_file = clean_id(row.get("demand_file"))
        if demand_file and demand_file not in files:
            files.append(demand_file)
    return files


def verify_node_ids_are_sequential(node_csv: Path) -> None:
    _, rows = _read_csv(node_csv)
    values = [row.get("node_id") for row in rows]
    if not is_one_based_sequential(values):
        raise ValueError(f"node_id is not compact sequential in {node_csv}")


def verify_zone_ids_are_mapped(node_csv: Path, mapping: IdMapping) -> None:
    _, rows = _read_csv(node_csv)
    mapped_zones = set(mapping.zone_id.values())
    for row in rows:
        zone_id = clean_id(row.get("zone_id"))
        if zone_id and zone_id != "0" and zone_id not in mapped_zones:
            raise ValueError(f"zone_id {zone_id} in {node_csv} is not in the zone map")


def verify_link_endpoints_exist(link_csv: Path, mapping: IdMapping) -> None:
    _, rows = _read_csv(link_csv)
    node_ids = set(mapping.node_id.values())
    for row in rows:
        for column in ("from_node_id", "to_node_id"):
            value = clean_id(row.get(column))
            if value not in node_ids:
                raise ValueError(f"{column} {value} in {link_csv} is not in the node map")


def verify_demand_od_zones_exist(demand_csv: Path, mapping: IdMapping) -> None:
    _, rows = _read_csv(demand_csv)
    zone_ids = set(mapping.zone_id.values())
    for row in rows:
        for column in ("o_zone_id", "d_zone_id"):
            value = clean_id(row.get(column))
            if value and value not in zone_ids:
                raise ValueError(f"{column} {value} in {demand_csv} is not in the zone map")


def renumber_period_folder(
    source_dir: Path,
    sequential_dir: Path | None = None,
    *,
    renumber_link_ids_if_needed: bool = True,
) -> RenumberResult:
    """Copy a period folder and rewrite GMNS IDs to compact DTALite IDs."""
    source_dir = Path(source_dir)
    sequential_dir = sequential_dir or source_dir / f"{source_dir.name}_seq"
    _reset_generated_dir(source_dir, sequential_dir, "_seq")

    node_fields, node_rows = _read_csv(source_dir / "node.csv")
    link_fields, link_rows = _read_csv(source_dir / "link.csv")
    if "node_id" not in node_fields:
        raise ValueError(f"node.csv missing node_id: {source_dir / 'node.csv'}")
    if "from_node_id" not in link_fields or "to_node_id" not in link_fields:
        raise ValueError(f"link.csv missing from_node_id/to_node_id: {source_dir / 'link.csv'}")

    zone_nodes = [row for row in node_rows if is_nonzero_id(row.get("zone_id"))]
    non_zone_nodes = [row for row in node_rows if not is_nonzero_id(row.get("zone_id"))]
    ordered_nodes = zone_nodes + non_zone_nodes

    node_map: dict[str, str] = {}
    zone_map: dict[str, str] = {}
    mapping_node_rows: list[tuple[str, str, str, str]] = []
    rewritten_nodes: list[dict[str, str]] = []
    for seq_id, row in enumerate(ordered_nodes, start=1):
        orig_node_id = clean_id(row.get("node_id"))
        if not orig_node_id:
            raise ValueError(f"node.csv contains a blank node_id in {source_dir}")
        seq_node_id = str(seq_id)
        node_map[orig_node_id] = seq_node_id
        new_row = dict(row)
        new_row["node_id"] = seq_node_id
        orig_zone_id = clean_id(row.get("zone_id"))
        seq_zone_id = ""
        if is_nonzero_id(orig_zone_id):
            seq_zone_id = seq_node_id
            zone_map[orig_zone_id] = seq_zone_id
            new_row["zone_id"] = seq_zone_id
        mapping_node_rows.append((orig_node_id, seq_node_id, orig_zone_id, seq_zone_id))
        rewritten_nodes.append(new_row)

    link_id_values = [clean_id(row.get("link_id")) for row in link_rows] if "link_id" in link_fields else []
    link_ids_renumbered = bool(
        link_id_values
        and renumber_link_ids_if_needed
        and not is_one_based_sequential(link_id_values)
    )

    link_map: dict[str, str] = {}
    mapping_link_rows: list[tuple[str, str]] = []
    rewritten_links: list[dict[str, str]] = []
    for seq_id, row in enumerate(link_rows, start=1):
        new_row = dict(row)
        from_node_id = clean_id(row.get("from_node_id"))
        to_node_id = clean_id(row.get("to_node_id"))
        if from_node_id not in node_map:
            raise ValueError(f"from_node_id {from_node_id} is missing from node.csv")
        if to_node_id not in node_map:
            raise ValueError(f"to_node_id {to_node_id} is missing from node.csv")
        new_row["from_node_id"] = node_map[from_node_id]
        new_row["to_node_id"] = node_map[to_node_id]
        if "link_id" in link_fields:
            orig_link_id = clean_id(row.get("link_id"))
            seq_link_id = str(seq_id) if link_ids_renumbered else orig_link_id
            new_row["link_id"] = seq_link_id
            if orig_link_id:
                link_map[orig_link_id] = seq_link_id
                mapping_link_rows.append((orig_link_id, seq_link_id))
        rewritten_links.append(new_row)

    rewritten_nodes.sort(key=lambda row: (id_sort_key(row.get("node_id")), id_sort_key(row.get("zone_id"))))
    rewritten_links.sort(key=lambda row: (id_sort_key(row.get("from_node_id")), id_sort_key(row.get("to_node_id"))))

    rewritten_names = {"node.csv", "link.csv", "id_mapping.csv"}
    demand_files = set(_demand_files_from_mode_type(source_dir / "mode_type.csv"))
    rewritten_names.update(demand_files)
    for source_file in source_dir.iterdir():
        if source_file.is_file() and source_file.name not in rewritten_names:
            shutil.copy2(source_file, sequential_dir / source_file.name)

    _write_csv(sequential_dir / "node.csv", node_fields, rewritten_nodes)
    _write_csv(sequential_dir / "link.csv", link_fields, rewritten_links)

    mapping = IdMapping(node_map, zone_map, link_map, link_ids_renumbered)
    for demand_file in demand_files:
        source_demand = source_dir / demand_file
        if not source_demand.exists():
            continue
        demand_fields, demand_rows = _read_csv(source_demand)
        for row in demand_rows:
            for column in ("o_zone_id", "d_zone_id"):
                original_zone = clean_id(row.get(column))
                if original_zone:
                    if original_zone not in zone_map:
                        raise ValueError(f"{column} {original_zone} in {source_demand} is missing from zone map")
                    row[column] = zone_map[original_zone]
        _write_csv(sequential_dir / demand_file, demand_fields, demand_rows)

    mapping_path = sequential_dir / "id_mapping.csv"
    write_id_mapping(mapping_path, mapping_node_rows, mapping_link_rows)

    verify_node_ids_are_sequential(sequential_dir / "node.csv")
    verify_zone_ids_are_mapped(sequential_dir / "node.csv", mapping)
    verify_link_endpoints_exist(sequential_dir / "link.csv", mapping)
    for demand_file in demand_files:
        demand_path = sequential_dir / demand_file
        if demand_path.exists():
            verify_demand_od_zones_exist(demand_path, mapping)

    stats = RenumberStats(
        original_node_count=len(node_rows),
        original_max_node_id=max_numeric_id(row.get("node_id") for row in node_rows),
        sequential_node_count=len(rewritten_nodes),
        sequential_max_node_id=max_numeric_id(row.get("node_id") for row in rewritten_nodes),
        original_zone_count=len(zone_map),
        original_max_zone_id=max_numeric_id(zone_map.keys()),
        sequential_zone_count=len(zone_map),
        sequential_max_zone_id=max_numeric_id(zone_map.values()),
        original_link_count=len(link_rows),
        original_max_link_id=max_numeric_id(link_id_values),
        sequential_link_count=len(rewritten_links),
        sequential_max_link_id=max_numeric_id(row.get("link_id") for row in rewritten_links),
        link_ids_renumbered=link_ids_renumbered,
    )
    return RenumberResult(source_dir, sequential_dir, mapping_path, mapping, stats)
