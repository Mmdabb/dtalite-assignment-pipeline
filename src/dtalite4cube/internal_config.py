"""Internal DTALite assignment pipeline defaults.

These are implementation-level controls rather than project JSON settings.
Keep user-facing run choices in configs/*.json and keep compatibility,
diagnostic, and bookkeeping behavior here.
"""

import os


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"", "0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


USE_SEQUENTIAL_IDS_FOR_DTALITE = True
RENUMBER_LINK_IDS_IF_NEEDED = True
RUN_GMNS_READINESS_CHECK = True
BACKMAP_DTALITE_OUTPUTS = True
WRITE_ASSIGNMENT_SUMMARY = True
KEEP_SEQUENTIAL_WORK_DIR = _env_bool("DTALITE_KEEP_SEQ_DIR", default=False)
