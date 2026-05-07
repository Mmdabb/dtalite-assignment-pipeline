from __future__ import annotations

import argparse
import csv
import pprint
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
DEFAULT_REPORT_NAME = "benchmark_field_comparison.csv"
EXTRA_FIELDS_ALLOWED = {"node.csv", "link.csv"}

BENCHMARK_SOURCE_FILES = {
    "node.csv": "node.csv",
    "link.csv": "link.csv",
    "settings.csv": "sample_settings.csv",
    "mode_type.csv": "sample_mode_type.csv",
}

# BEGIN EMBEDDED_BENCHMARK_HEADERS
BENCHMARK_HEADERS = {
    "node.csv": ["node_id", "x_coord", "y_coord", "zone_id"],
    "link.csv": [
        "from_node_id",
        "to_node_id",
        "length",
        "lanes",
        "free_speed",
        "capacity",
        "link_type",
        "VDF_alpha",
        "VDF_beta",
    ],
    "settings.csv": [
        "number_of_iterations",
        "number_of_processors",
        "demand_period_starting_hours",
        "demand_period_ending_hours",
        "first_through_node_id",
        "base_demand_mode",
        "route_output",
        "vehicle_output",
        "log_file",
        "odme_mode",
        "odme_vmt",
    ],
    "mode_type.csv": ["mode_type_id", "mode_type", "name", "vot", "pce", "occ", "demand_file"],
}
# END EMBEDDED_BENCHMARK_HEADERS


def read_header(path: Path) -> list[str]:
    with path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        return next(csv.reader(f), [])


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / "main.py").is_file() and (candidate / "configs").is_dir():
            return candidate
    return SCRIPT_DIR.parent


def resolve_input_file(input_dir: Path, logical_name: str) -> Path:
    direct = input_dir / logical_name
    if direct.is_file():
        return direct

    # Convenience for running from dtalite_assignment_test: use the local am folder if present.
    am_file = input_dir / "am" / logical_name
    if am_file.is_file():
        return am_file

    return direct


def extract_benchmark_headers(benchmark_dir: Path) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for logical_name, source_name in BENCHMARK_SOURCE_FILES.items():
        path = benchmark_dir / source_name
        if not path.is_file():
            raise FileNotFoundError(f"Missing benchmark source for {logical_name}: {path}")
        headers[logical_name] = read_header(path)
    return headers


def format_embedded_headers(headers: dict[str, list[str]]) -> str:
    rendered = pprint.pformat(headers, width=120, sort_dicts=False)
    return (
        "# BEGIN EMBEDDED_BENCHMARK_HEADERS\n"
        f"BENCHMARK_HEADERS = {rendered}\n"
        "# END EMBEDDED_BENCHMARK_HEADERS"
    )


def update_embedded_benchmark_headers(headers: dict[str, list[str]]) -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    start_marker = "# BEGIN EMBEDDED_BENCHMARK_HEADERS"
    end_marker = "# END EMBEDDED_BENCHMARK_HEADERS"
    start = text.index(start_marker)
    end = text.index(end_marker) + len(end_marker)
    updated = text[:start] + format_embedded_headers(headers) + text[end:]
    SCRIPT_PATH.write_text(updated, encoding="utf-8")


def compare_headers(input_dir: Path, project_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for logical_name, benchmark_fields in BENCHMARK_HEADERS.items():
        extra_fields_allowed = logical_name in EXTRA_FIELDS_ALLOWED
        input_path = resolve_input_file(input_dir, logical_name)
        project_root_path = project_root / logical_name
        input_exists = input_path.is_file()
        project_root_exists = project_root_path.is_file()

        if input_exists:
            input_fields = read_header(input_path)
            missing_from_input = [field for field in benchmark_fields if field not in set(input_fields)]
            extra_in_input = [field for field in input_fields if field not in set(benchmark_fields)]
            warning = ""
            exact_order_match = benchmark_fields == input_fields
            if missing_from_input:
                status = "missing_fields"
            elif not extra_fields_allowed and extra_in_input:
                status = "extra_fields"
            elif not extra_fields_allowed and not exact_order_match:
                status = "order_mismatch"
            else:
                status = "ok"
        else:
            input_fields = []
            missing_from_input = list(benchmark_fields)
            extra_in_input = []
            status = "missing_file"
            warning = f"{logical_name} was not found in {input_dir}"
            exact_order_match = False

        rows.append(
            {
                "file": logical_name,
                "status": status,
                "warning": warning,
                "input_file": str(input_path),
                "input_exists": str(input_exists),
                "project_root_file": str(project_root_path),
                "project_root_exists": str(project_root_exists),
                "benchmark_field_count": str(len(benchmark_fields)),
                "input_field_count": str(len(input_fields)),
                "covers_benchmark": str(input_exists and not missing_from_input),
                "exact_order_match": str(exact_order_match),
                "extra_fields_allowed": str(extra_fields_allowed),
                "passes_policy": str(status == "ok"),
                "missing_benchmark_fields": "|".join(missing_from_input),
                "extra_input_fields": "|".join(extra_in_input),
                "benchmark_fields": "|".join(benchmark_fields),
                "input_fields": "|".join(input_fields),
            }
        )
    return rows


def write_csv_report(rows: list[dict[str, str]], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file",
        "status",
        "warning",
        "input_file",
        "input_exists",
        "project_root_file",
        "project_root_exists",
        "benchmark_field_count",
        "input_field_count",
        "covers_benchmark",
        "exact_order_match",
        "extra_fields_allowed",
        "passes_policy",
        "missing_benchmark_fields",
        "extra_input_fields",
        "benchmark_fields",
        "input_fields",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare DTALite input CSV headers against embedded benchmark headers. "
            "By default, compares files in the current working directory."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=Path.cwd(), help="Folder containing link/node/settings/mode_type CSVs.")
    parser.add_argument("--report", type=Path, help="CSV report path. Defaults to <input-dir>/benchmark_field_comparison.csv.")
    parser.add_argument("--project-root", type=Path, help="Project root used for the project_root_exists report column.")
    parser.add_argument(
        "--extract-benchmark",
        type=Path,
        help="Read benchmark headers from this folder. Uses sample_settings.csv and sample_mode_type.csv.",
    )
    parser.add_argument(
        "--update-self",
        action="store_true",
        help="With --extract-benchmark, update the embedded BENCHMARK_HEADERS in this script.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.extract_benchmark:
        headers = extract_benchmark_headers(args.extract_benchmark)
        if args.update_self:
            update_embedded_benchmark_headers(headers)
            print(f"Updated embedded benchmark headers in {SCRIPT_PATH}")
        else:
            print(format_embedded_headers(headers))
        return

    input_dir = args.input_dir.resolve()
    project_root = args.project_root.resolve() if args.project_root else find_project_root(input_dir)
    report_path = args.report or (input_dir / DEFAULT_REPORT_NAME)
    rows = compare_headers(input_dir, project_root)
    write_csv_report(rows, report_path)

    print(f"Wrote {report_path}")
    for row in rows:
        if row["status"] == "ok":
            if row["extra_fields_allowed"] == "True":
                print(f"OK: {row['file']} covers benchmark")
            else:
                print(f"OK: {row['file']} exactly matches benchmark")
        elif row["status"] == "missing_file":
            print(f"WARNING: {row['file']} not found")
        elif row["status"] == "extra_fields":
            print(f"EXTRA: {row['file']} has extra fields {row['extra_input_fields']}")
        elif row["status"] == "order_mismatch":
            print(f"ORDER: {row['file']} fields do not match benchmark order")
        else:
            print(f"MISSING: {row['file']} missing {row['missing_benchmark_fields']}")


if __name__ == "__main__":
    main()
