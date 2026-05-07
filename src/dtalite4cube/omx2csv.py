import openmatrix as omx
import numpy as np
import csv
import time
from pathlib import Path

try:
    from .settings.dtalite_settings_config import DEMAND_LANE_USES, demand_file_name
except ImportError:
    from settings.dtalite_settings_config import DEMAND_LANE_USES, demand_file_name


def export_matrix_data(output_dir, time_period, lane_uses, matrix_file):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for lu in lane_uses:
        matrix_name = f"{time_period}_{lu.upper()}s"
        arr = np.asarray(matrix_file[matrix_name])

        output_file_name = demand_file_name(lu, time_period)
        output = output_dir / output_file_name

        positive_mask = arr > 0
        o_idx, d_idx = np.nonzero(positive_mask)
        volumes = arr[o_idx, d_idx]

        with output.open("w", newline="", encoding="utf-8") as df:
            f_csv = csv.writer(df)
            f_csv.writerow(["o_zone_id", "d_zone_id", "volume"])
            f_csv.writerows(zip(o_idx + 1, d_idx + 1, volumes))

        print(f"Wrote {len(volumes):,} rows to {output_file_name}")

# Main function to process OMX files
def get_gmns_demand_from_omx(demand_dir, time_period_list, output_base_dir=None, period_folder_output=True):
    demand_path = Path(demand_dir)
    output_root = Path(output_base_dir) if output_base_dir is not None else demand_path
    output_root.mkdir(parents=True, exist_ok=True)

    lane_uses = DEMAND_LANE_USES
    period_keys = [period.upper() for period in time_period_list]

    for omx_path in demand_path.iterdir():
        file_name_lower = omx_path.name.lower()
        if omx_path.suffix.lower() != ".omx" or "transit" in file_name_lower:
            continue

        matching_periods = [period for period in period_keys if period in omx_path.stem.upper()]
        for time_period_upper in matching_periods:
            print(f"Processing file: {omx_path.name} for time period: {time_period_upper}")
            output_dir = output_root / time_period_upper.lower() if period_folder_output else output_root

            start = time.process_time()
            myfile = omx.open_file(str(omx_path))
            try:
                print("Shape:", myfile.shape())
                print("Number of tables:", len(myfile))
                print("Table names:", myfile.list_matrices())
                export_matrix_data(output_dir, time_period_upper, lane_uses, myfile)
            finally:
                myfile.close()

            end = time.process_time()
            print(f"Total running time for {time_period_upper}: {end - start} seconds")

# Example usage:
# demand_dir = '/path/to/demand_dir'
# time_period_list = ['am', 'md', 'pm', 'nt']
# get_gmns_demand_from_omx(demand_dir, time_period_list)
