"""Helpers for writing and reading DTALite sequential ID mappings."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAPPING_COLUMNS = (
    "orig_node_id",
    "seq_node_id",
    "orig_zone_id",
    "seq_zone_id",
    "orig_link_id",
    "seq_link_id",
)


def clean_id(value: object) -> str:
    """Return an ID as a stripped string, preserving blanks."""
    if value is None:
        return ""
    return str(value).strip()


def int_id(value: object) -> int | None:
    text = clean_id(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def max_numeric_id(values: Iterable[object]) -> int | None:
    parsed = [value for value in (int_id(item) for item in values) if value is not None]
    return max(parsed) if parsed else None


def is_nonzero_id(value: object) -> bool:
    text = clean_id(value)
    if not text:
        return False
    parsed = int_id(text)
    return parsed is None or parsed != 0


def is_one_based_sequential(values: Iterable[object]) -> bool:
    parsed: list[int] = []
    for item in values:
        value = int_id(item)
        if value is None:
            return False
        parsed.append(value)
    return parsed == list(range(1, len(parsed) + 1))


def id_sort_key(value: object) -> tuple[int, int | str]:
    parsed = int_id(value)
    if parsed is None:
        return (1, clean_id(value))
    return (0, parsed)


@dataclass(frozen=True)
class IdMapping:
    node_id: dict[str, str]
    zone_id: dict[str, str]
    link_id: dict[str, str]
    link_ids_renumbered: bool = False

    @property
    def node_id_back(self) -> dict[str, str]:
        return {seq: orig for orig, seq in self.node_id.items()}

    @property
    def zone_id_back(self) -> dict[str, str]:
        return {seq: orig for orig, seq in self.zone_id.items()}

    @property
    def link_id_back(self) -> dict[str, str]:
        return {seq: orig for orig, seq in self.link_id.items()}


def write_id_mapping(
    path: Path,
    node_rows: list[tuple[str, str, str, str]],
    link_rows: list[tuple[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_rows = max(len(node_rows), len(link_rows), 1)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MAPPING_COLUMNS)
        writer.writeheader()
        for index in range(max_rows):
            orig_node_id, seq_node_id, orig_zone_id, seq_zone_id = (
                node_rows[index] if index < len(node_rows) else ("", "", "", "")
            )
            orig_link_id, seq_link_id = (
                link_rows[index] if index < len(link_rows) else ("", "")
            )
            writer.writerow(
                {
                    "orig_node_id": orig_node_id,
                    "seq_node_id": seq_node_id,
                    "orig_zone_id": orig_zone_id,
                    "seq_zone_id": seq_zone_id,
                    "orig_link_id": orig_link_id,
                    "seq_link_id": seq_link_id,
                }
            )


def read_id_mapping(path: Path, *, link_ids_renumbered: bool = False) -> IdMapping:
    node_map: dict[str, str] = {}
    zone_map: dict[str, str] = {}
    link_map: dict[str, str] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            orig_node_id = clean_id(row.get("orig_node_id"))
            seq_node_id = clean_id(row.get("seq_node_id"))
            orig_zone_id = clean_id(row.get("orig_zone_id"))
            seq_zone_id = clean_id(row.get("seq_zone_id"))
            orig_link_id = clean_id(row.get("orig_link_id"))
            seq_link_id = clean_id(row.get("seq_link_id"))
            if orig_node_id and seq_node_id:
                node_map[orig_node_id] = seq_node_id
            if orig_zone_id and seq_zone_id:
                zone_map[orig_zone_id] = seq_zone_id
            if orig_link_id and seq_link_id:
                link_map[orig_link_id] = seq_link_id
    return IdMapping(node_map, zone_map, link_map, link_ids_renumbered)
