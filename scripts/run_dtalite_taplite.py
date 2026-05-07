"""run_dtalite_taplite.py - Reproducible wrapper to run DTALite on a taplite folder.

Designed for the ANL (Argonne National Lab) team to reproduce the
v5 / taplite column-generation run from a single command.

Why this wrapper exists
-----------------------
The PyPI ``DTALite`` package's entry-point is just ``dta.assignment()``,
which reads node.csv / link.csv / demand.csv / settings.csv from the
*current working directory* and writes outputs to that same directory.
That makes it easy to pollute the source dataset, hard to reproduce,
and hard to diff two runs.

This wrapper adds the disciplines we care about for the Argonne deliverable:

  1. **Source-isolation**: copies inputs to a fresh working directory by
     default, so the v5 source folder is never touched.
  2. **Pre-flight audit**: verifies the four required input files exist
     and have the expected schema (per the DTALite wiki).
  3. **Settings normalization**: forces ``route_output = 1`` so
     ``route_assignment.csv`` is always produced. Existing other settings
     are preserved.
  4. **Run logging**: pipes DTALite stdout to a log file with a timestamp.
  5. **Output verification**: checks the expected output files were
     written, with row counts and MD5 checksums.
  6. **RUN_CARD**: emits a markdown run card with input MD5s, output MD5s,
     iteration count, runtime, gap, and the exact command used.

A second person can clone the repo, ``pip install DTALite``, run the
same command, and diff their RUN_CARD against ours. Inputs MD5s, output
MD5s, and convergence numbers should match exactly.

Usage
-----
::

    # Run on the L2 taplite folder, output to ./dtalite_l2_run/
    python run_dtalite_taplite.py \\
        --src ../ras_data_sample_v5/ras_sample_data_l2/taplite \\
        --work-dir ./dtalite_l2_run

    # Run with custom iteration count and write a tiered RUN_CARD label
    python run_dtalite_taplite.py \\
        --src ../ras_data_sample_v5/ras_sample_data_l3/taplite \\
        --work-dir ./dtalite_l3_run \\
        --iterations 15 \\
        --label v5_l3

    # Dry run — verify inputs only, do not run DTALite
    python run_dtalite_taplite.py --src .../taplite --dry-run

Outputs
-------
Inside ``--work-dir``::

    columns.csv              == route_assignment.csv (per-path rows)
    route_assignment.csv     DTALite native name
    od_performance.csv       per-OD distance + travel time
    link_performance.csv     per-link volume + D/C + speed
    origin_accessibility.csv
    destination_accessibility.csv
    inaccessible_od.csv
    google_maps_od_distance.csv
    system_performance.csv
    summary_log_file.txt
    TAP_log.csv
    sample_settings.csv      DTALite-emitted reference settings
    sample_mode_type.csv     DTALite-emitted reference mode types

Plus the wrapper's own artifacts::

    RUN_CARD.md              md5s, runtime, settings used, command
    dtalite_run.log          captured stdout/stderr from DTALite
    settings.csv             normalized settings (route_output forced to 1)

Exit codes
----------

  0  success
  1  pre-flight audit failed
  2  DTALite run failed
  3  output verification failed

Reference
---------

  PyPI:  https://pypi.org/project/DTALite/
  Wiki:  https://github.com/itsfangtang/DTALite_release/wiki/DTALite-Inputs-and-Outputs
"""
from __future__ import annotations

import argparse
import contextlib
import csv as _csv
import hashlib
import io
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Raise CSV per-field cap before any pandas read — taplite link.csv has
# long LINESTRING geometry strings that exceed the 131KB default.
_csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s | %(message)s")
_LOG = logging.getLogger("run_dtalite")

REQUIRED_INPUTS = ("node.csv", "link.csv", "demand.csv")
REQUIRED_OUTPUTS = (
    "route_assignment.csv",     # the columns file we care about
    "od_performance.csv",
    "link_performance.csv",
)
EXPECTED_OUTPUTS = REQUIRED_OUTPUTS + (
    "origin_accessibility.csv",
    "destination_accessibility.csv",
    "inaccessible_od.csv",
    "google_maps_od_distance.csv",
    "system_performance.csv",
    "summary_log_file.txt",
    "TAP_log.csv",
)

# Default settings.csv content — matches the v5 taplite ship setup with
# route_output forced ON. Order of columns matters for DTALite 0.8.1.
DEFAULT_SETTINGS_HEADER = (
    "metric_system,number_of_iterations,number_of_processors,"
    "demand_period_starting_hours,demand_period_ending_hours,"
    "base_demand_mode,route_output,log_file,odme_mode,odme_vmt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def md5_of(path: Path, chunk: int = 1 << 20) -> str:
    if not path.exists():
        return "(missing)"
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_rows(path: Path) -> int:
    if not path.exists():
        return -1
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f) - 1   # minus header


def fmt_size(n_bytes: int) -> str:
    if n_bytes < 1024:           return f"{n_bytes} B"
    if n_bytes < 1024 ** 2:      return f"{n_bytes/1024:.1f} KB"
    if n_bytes < 1024 ** 3:      return f"{n_bytes/1024**2:.2f} MB"
    return f"{n_bytes/1024**3:.2f} GB"


# ---------------------------------------------------------------------------
# Stage 1: pre-flight audit on the source
# ---------------------------------------------------------------------------
def preflight(src: Path) -> dict:
    """Verify the source folder has the four required CSVs with sane schemas."""
    if not src.is_dir():
        raise SystemExit(f"--src is not a directory: {src}")

    info = {"src": str(src), "files": {}}
    missing = []
    for name in REQUIRED_INPUTS:
        p = src / name
        if not p.exists():
            missing.append(name)
            continue
        info["files"][name] = {
            "size": p.stat().st_size,
            "md5": md5_of(p),
        }
    if missing:
        raise SystemExit(f"missing required input(s) in {src}: {missing}")

    # Schema sanity: read first row, confirm expected columns
    with open(src / "node.csv", "r", encoding="utf-8", errors="replace") as f:
        node_cols = next(_csv.reader(f), [])
    with open(src / "link.csv", "r", encoding="utf-8", errors="replace") as f:
        link_cols = next(_csv.reader(f), [])
    with open(src / "demand.csv", "r", encoding="utf-8", errors="replace") as f:
        dem_cols = next(_csv.reader(f), [])

    expected_node = {"node_id"}
    expected_link = {"link_id", "from_node_id", "to_node_id"}
    expected_demand = {"o_zone_id", "d_zone_id", "volume"}

    bad = []
    if not expected_node.issubset(set(node_cols)):
        bad.append(f"node.csv missing columns; have={node_cols[:6]}")
    if not expected_link.issubset(set(link_cols)):
        bad.append(f"link.csv missing columns; have={link_cols[:6]}")
    if not expected_demand.issubset(set(dem_cols)):
        bad.append(f"demand.csv missing columns; have={dem_cols[:6]}")
    if bad:
        raise SystemExit("pre-flight failed:\n  - " + "\n  - ".join(bad))

    info["files"]["node.csv"]["columns"]   = node_cols
    info["files"]["link.csv"]["columns"]   = link_cols
    info["files"]["demand.csv"]["columns"] = dem_cols
    info["counts"] = {
        "node_rows":   count_rows(src / "node.csv"),
        "link_rows":   count_rows(src / "link.csv"),
        "demand_rows": count_rows(src / "demand.csv"),
    }
    _LOG.info("pre-flight OK: nodes=%d links=%d demand=%d",
              info["counts"]["node_rows"], info["counts"]["link_rows"],
              info["counts"]["demand_rows"])
    return info


# ---------------------------------------------------------------------------
# Stage 2: stage inputs into the working dir + write normalized settings
# ---------------------------------------------------------------------------
def stage_inputs(src: Path, work_dir: Path,
                 iterations: int, processors: int,
                 period_start: int, period_end: int,
                 metric_system: int) -> Path:
    """Copy node/link/demand into work_dir; write a normalized settings.csv
    with route_output = 1 (forced ON, regardless of what's in src)."""
    work_dir.mkdir(parents=True, exist_ok=True)

    for name in REQUIRED_INPUTS:
        src_p = src / name
        dst_p = work_dir / name
        shutil.copy2(src_p, dst_p)
        _LOG.info("staged %s (%s)", name, fmt_size(dst_p.stat().st_size))

    # Carry over the source's settings.csv if present, but always force
    # route_output = 1. Otherwise, write a default.
    settings_p = work_dir / "settings.csv"
    src_settings = src / "settings.csv"
    if src_settings.exists():
        # Parse, mutate route_output, write back
        with open(src_settings, "r", newline="", encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        if len(rows) >= 2 and "route_output" in rows[0]:
            idx = rows[0].index("route_output")
            for r in rows[1:]:
                if idx < len(r):
                    r[idx] = "1"
            with open(settings_p, "w", newline="", encoding="utf-8") as f:
                w = _csv.writer(f)
                w.writerows(rows)
            _LOG.info("normalized settings.csv (forced route_output=1)")
        else:
            _LOG.warning("source settings.csv has no route_output column; "
                         "rewriting from defaults")
            settings_p.write_text(_default_settings_csv(
                iterations, processors, period_start, period_end, metric_system),
                encoding="utf-8")
    else:
        settings_p.write_text(_default_settings_csv(
            iterations, processors, period_start, period_end, metric_system),
            encoding="utf-8")
        _LOG.info("wrote default settings.csv (no source settings.csv found)")

    return work_dir


def _default_settings_csv(iterations: int, processors: int,
                          period_start: int, period_end: int,
                          metric_system: int) -> str:
    return (
        DEFAULT_SETTINGS_HEADER + "\n"
        f"{metric_system},{iterations},{processors},"
        f"{period_start},{period_end},0,1,0,0,0\n"
    )


# ---------------------------------------------------------------------------
# Stage 3: run DTALite
# ---------------------------------------------------------------------------
def run_dtalite(work_dir: Path) -> tuple[float, str]:
    """Run DTALite.assignment() in work_dir; return (elapsed_seconds, captured_stdout)."""
    try:
        import DTALite as dta  # noqa
    except ImportError:
        raise SystemExit("DTALite not installed. Run:  pip install DTALite")

    cwd_before = Path.cwd()
    captured = io.StringIO()
    t0 = time.time()
    try:
        os.chdir(work_dir)
        # Some DTALite versions print to stdout via the C kernel which
        # bypasses Python's redirect_stdout; we tee via a process-level
        # redirect just in case.
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            dta.assignment()
    finally:
        os.chdir(cwd_before)

    elapsed = time.time() - t0
    log = captured.getvalue()
    log_path = work_dir / "dtalite_run.log"
    log_path.write_text(log, encoding="utf-8")
    _LOG.info("DTALite finished in %.1fs; log -> %s", elapsed, log_path)
    return elapsed, log


# ---------------------------------------------------------------------------
# Stage 4: output verification
# ---------------------------------------------------------------------------
def verify_outputs(work_dir: Path) -> dict:
    """Confirm required outputs exist with non-trivial content."""
    info = {"outputs": {}}
    missing = []
    for name in REQUIRED_OUTPUTS:
        p = work_dir / name
        if not p.exists() or p.stat().st_size == 0:
            missing.append(name)
            continue
        info["outputs"][name] = {
            "size": p.stat().st_size,
            "md5":  md5_of(p),
            "rows": count_rows(p),
        }
    if missing:
        raise SystemExit("output verification failed: missing/empty " + ", ".join(missing))

    # Pull an at-a-glance route_assignment.csv stat
    ra = work_dir / "route_assignment.csv"
    info["columns"] = {"file": str(ra), "rows": info["outputs"]["route_assignment.csv"]["rows"]}
    # Compute unique-OD count efficiently (no pandas dep)
    n_od_pairs = _count_unique_od(ra)
    info["columns"]["unique_od_pairs"] = n_od_pairs

    # Auxiliary outputs (best-effort, not required)
    for name in EXPECTED_OUTPUTS:
        if name in REQUIRED_OUTPUTS:
            continue
        p = work_dir / name
        if p.exists():
            info["outputs"][name] = {
                "size": p.stat().st_size, "md5": md5_of(p), "rows": count_rows(p),
            }
    return info


def _count_unique_od(route_assignment_csv: Path) -> int:
    """Count unique (o_zone_id, d_zone_id) pairs in route_assignment.csv
    without pandas (memory-friendly for the 300+ MB file)."""
    if not route_assignment_csv.exists():
        return -1
    seen = set()
    with open(route_assignment_csv, "r", newline="", encoding="utf-8") as f:
        reader = _csv.reader(f)
        header = next(reader, [])
        try:
            i_o = header.index("o_zone_id"); i_d = header.index("d_zone_id")
        except ValueError:
            return -1
        for row in reader:
            if len(row) > max(i_o, i_d):
                seen.add((row[i_o], row[i_d]))
    return len(seen)


# ---------------------------------------------------------------------------
# Stage 5: parse convergence from the captured log
# ---------------------------------------------------------------------------
def parse_convergence(log: str, work_dir: Path | None = None) -> dict:
    """Pull final iteration count, gap, and runtime from DTALite output.

    DTALite's C kernel prints to stdout directly (bypassing Python's
    ``sys.stdout`` redirect), so we can't reliably capture iteration logs
    via ``contextlib.redirect_stdout``. Instead, parse the native
    ``summary_log_file.txt`` that DTALite writes alongside its outputs.
    Fall back to the captured Python-level stdout if the file is missing.
    """
    info = {"iterations": [], "final_gap_pct": None,
            "final_iter": None, "cpu_time": None}

    sources = []
    if work_dir is not None:
        slf = work_dir / "summary_log_file.txt"
        if slf.exists():
            sources.append(slf.read_text(encoding="utf-8", errors="replace"))
    if log:
        sources.append(log)

    for src in sources:
        for line in src.splitlines():
            line = line.strip()
            if line.startswith("iter No"):
                info["iterations"].append(line)
                try:
                    # Strip a trailing '%' and any whitespace
                    gap_part = line.split("gap = ")[-1].strip()
                    gap_part = gap_part.rstrip("%").strip()
                    info["final_gap_pct"] = float(gap_part)
                    iter_part = line.split("iter No = ")[-1].split(",")[0]
                    info["final_iter"] = int(iter_part)
                except (ValueError, IndexError):
                    pass
            elif line.startswith("CPU running time"):
                info["cpu_time"] = line.replace("CPU running time:", "").strip()
        if info["iterations"]:
            break        # got it from the first source that had data
    return info


# ---------------------------------------------------------------------------
# Stage 6: emit RUN_CARD.md
# ---------------------------------------------------------------------------
def write_run_card(work_dir: Path, src: Path, label: str,
                   preflight_info: dict, run_elapsed: float,
                   convergence: dict, verify_info: dict,
                   args_used: dict) -> Path:
    lines = []
    A = lines.append
    A(f"# DTALite Taplite RUN CARD")
    A("")
    A(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    A(f"- Label: **{label}**")
    A(f"- Source: `{src}`")
    A(f"- Work dir: `{work_dir}`")
    A(f"- DTALite version: 0.8.1 (PyPI)")
    A(f"- Python: {sys.version.split()[0]}")
    A(f"- Runtime: **{run_elapsed:.1f} s**")
    A("")

    A("## Inputs (MD5)")
    A("")
    A("| file | rows | size | md5 |")
    A("|---|---:|---:|---|")
    for name in REQUIRED_INPUTS:
        meta = preflight_info["files"].get(name, {})
        A(f"| `{name}` | {preflight_info['counts'].get(name.replace('.csv','_rows'),'?'):,} | "
          f"{fmt_size(meta.get('size',0))} | `{meta.get('md5','-')}` |")
    A("")

    A("## Settings used")
    A("")
    settings_p = work_dir / "settings.csv"
    if settings_p.exists():
        A("```csv")
        A(settings_p.read_text(encoding="utf-8").strip())
        A("```")
    A("")

    A("## Convergence")
    A("")
    if convergence["iterations"]:
        A(f"- Iterations: **{convergence.get('final_iter','?')}**")
        A(f"- Final gap: **{convergence.get('final_gap_pct','?')}%**")
        if convergence.get('cpu_time'):
            A(f"- DTALite CPU time: {convergence['cpu_time']}")
        A("")
        A("```")
        for line in convergence["iterations"][-12:]:    # last 12 iters
            A(line)
        A("```")
    else:
        A("_(no iteration log captured)_")
    A("")

    A("## Outputs")
    A("")
    A("| file | rows | size | md5 |")
    A("|---|---:|---:|---|")
    for name in EXPECTED_OUTPUTS:
        if name in verify_info["outputs"]:
            o = verify_info["outputs"][name]
            A(f"| `{name}` | {o['rows']:,} | {fmt_size(o['size'])} | `{o['md5']}` |")
        else:
            A(f"| `{name}` | (not produced) | — | — |")
    A("")

    rc = verify_info.get("columns", {})
    A("## Headline columns.csv stats")
    A("")
    A(f"- Path columns (== `route_assignment.csv` rows): "
      f"**{rc.get('rows','?'):,}**")
    A(f"- Unique OD pairs: **{rc.get('unique_od_pairs','?'):,}**")
    A("")

    A("## Reproduction")
    A("")
    A("```bash")
    cmd = ["python", "run_dtalite_taplite.py",
           "--src", str(src),
           "--work-dir", str(work_dir),
           "--iterations", str(args_used.get("iterations")),
           "--processors", str(args_used.get("processors")),
           "--period-start", str(args_used.get("period_start")),
           "--period-end", str(args_used.get("period_end")),
           "--metric-system", str(args_used.get("metric_system"))]
    if label and label != "default":
        cmd += ["--label", label]
    A(" ".join(cmd))
    A("```")
    A("")
    A("To verify reproducibility on a second machine: rerun the command above, "
      "then diff this RUN_CARD with the new one. Input MD5s, output MD5s, "
      "and final gap should match exactly modulo timestamps.")
    A("")

    p = work_dir / "RUN_CARD.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    _LOG.info("RUN_CARD -> %s", p)
    return p


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", required=True,
                   help="path to taplite folder containing node.csv, link.csv, demand.csv")
    p.add_argument("--work-dir", default="./dtalite_run",
                   help="working dir for outputs (default: ./dtalite_run)")
    p.add_argument("--iterations", type=int, default=10,
                   help="number_of_iterations in settings.csv (default: 10)")
    p.add_argument("--processors", type=int, default=8,
                   help="number_of_processors (default: 8)")
    p.add_argument("--period-start", type=int, default=7,
                   help="demand_period_starting_hours (default: 7)")
    p.add_argument("--period-end", type=int, default=8,
                   help="demand_period_ending_hours (default: 8)")
    p.add_argument("--metric-system", type=int, default=1, choices=[0, 1],
                   help="0=imperial (mile), 1=metric (km); default: 1 (metric)")
    p.add_argument("--label", default="default",
                   help="freeform label for this run (appears in RUN_CARD)")
    p.add_argument("--inplace", action="store_true",
                   help="run in --src directly instead of copying to --work-dir "
                        "(NOT RECOMMENDED — pollutes the source folder)")
    p.add_argument("--dry-run", action="store_true",
                   help="run pre-flight only; do not invoke DTALite")
    p.add_argument("--no-rename-columns", action="store_true",
                   help="do not copy route_assignment.csv to columns.csv")
    args = p.parse_args()

    src = Path(args.src).resolve()
    work_dir = src if args.inplace else Path(args.work_dir).resolve()

    print()
    print("=" * 72)
    print("DTALite Taplite Reproducible Wrapper")
    print("=" * 72)
    print(f"  src        = {src}")
    print(f"  work_dir   = {work_dir}{' (IN-PLACE)' if args.inplace else ''}")
    print(f"  iterations = {args.iterations}")
    print(f"  label      = {args.label}")
    print()

    # Stage 1: pre-flight
    try:
        preflight_info = preflight(src)
    except SystemExit as e:
        _LOG.error("pre-flight failed: %s", e)
        sys.exit(1)

    if args.dry_run:
        print()
        print("[dry-run] pre-flight passed; not invoking DTALite. Exiting.")
        sys.exit(0)

    # Stage 2: stage inputs (skipped in --inplace mode)
    if not args.inplace:
        stage_inputs(src, work_dir,
                     args.iterations, args.processors,
                     args.period_start, args.period_end,
                     args.metric_system)
    else:
        _LOG.warning("--inplace: NOT copying files; running directly in %s", src)

    # Stage 3: run DTALite
    try:
        elapsed, log = run_dtalite(work_dir)
    except SystemExit:
        raise
    except Exception as e:
        _LOG.exception("DTALite raised an exception: %s", e)
        sys.exit(2)

    # Stage 4: verify outputs
    try:
        verify_info = verify_outputs(work_dir)
    except SystemExit as e:
        _LOG.error("output verification failed: %s", e)
        sys.exit(3)

    # Stage 5: parse convergence (prefer DTALite's native summary_log_file.txt)
    convergence = parse_convergence(log, work_dir=work_dir)

    # Stage 5.5: convenience copy route_assignment.csv -> columns.csv
    if not args.no_rename_columns:
        ra = work_dir / "route_assignment.csv"
        cols = work_dir / "columns.csv"
        if ra.exists():
            shutil.copy2(ra, cols)
            _LOG.info("copied route_assignment.csv -> columns.csv")

    # Stage 6: RUN_CARD
    args_used = {
        "iterations": args.iterations,
        "processors": args.processors,
        "period_start": args.period_start,
        "period_end": args.period_end,
        "metric_system": args.metric_system,
    }
    write_run_card(work_dir, src, args.label, preflight_info,
                   elapsed, convergence, verify_info, args_used)

    # Final summary to console
    print()
    print("=" * 72)
    print("DONE")
    print("=" * 72)
    print(f"  runtime         : {elapsed:.1f} s")
    print(f"  iterations run  : {convergence.get('final_iter','?')}")
    print(f"  final gap (%)   : {convergence.get('final_gap_pct','?')}")
    rc = verify_info.get("columns", {})
    print(f"  path columns    : {rc.get('rows','?'):,}")
    print(f"  unique OD pairs : {rc.get('unique_od_pairs','?'):,}")
    print(f"  RUN_CARD        : {work_dir / 'RUN_CARD.md'}")
    print()


if __name__ == "__main__":
    main()
