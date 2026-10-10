"""Refresh the local ASN routing table and AS names from public BGP data.

The scoring service resolves validator IPs to providers with a pyasn table
checked into ``data/asn/``. Prefix allocations move, so a table that is
months old leaves recently reallocated IPs without a provider; under
diversity formula v1 that scores the provider axis as unknown. This script
downloads the latest RouteViews snapshot, converts it, refreshes the AS
names, swaps the dated table file in, and points every reference at it.

Usage:
    python scripts/refresh_asn_table.py [--work-dir DIR]

Prints the new table's file name on success. Run by the monthly
``refresh-asn-table.yml`` workflow, which opens a pull request with the
result; also usable by hand.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "asn"
NAMES_FILE = DATA_DIR / "asnames.json"
TABLE_PATTERN = re.compile(r"ipasn_\d{8}\.dat")
# Files that name the table; the date is part of the file name so each
# reference moves with the refresh.
TABLE_REFERENCES = (
    REPO_ROOT / ".dockerignore",
    REPO_ROOT / "Dockerfile",
    REPO_ROOT / "scripts" / "lookup_asn.py",
    REPO_ROOT / "scoring_service" / "clients" / "asn.py",
)


def current_table() -> Path:
    tables = sorted(DATA_DIR.glob("ipasn_*.dat"))
    if len(tables) != 1:
        raise SystemExit(f"expected exactly one table in {DATA_DIR}, found {tables}")
    return tables[0]


def _run(command: list[str], **kwargs) -> None:
    # The pyasn tools chatter on stdout; keep stdout for the result only.
    subprocess.run(command, check=True, stdout=sys.stderr, **kwargs)


def download_rib(work_dir: Path) -> Path:
    _run(["pyasn_util_download.py", "--latest"], cwd=work_dir)
    ribs = sorted(work_dir.glob("rib.*.bz2"))
    if not ribs:
        raise SystemExit("pyasn_util_download.py produced no rib.*.bz2 file")
    return ribs[-1]


def rib_date(rib: Path) -> date:
    match = re.search(r"rib\.(\d{8})\.", rib.name)
    if not match:
        raise SystemExit(f"cannot read the snapshot date from {rib.name}")
    return datetime.strptime(match.group(1), "%Y%m%d").date()


def refresh(work_dir: Path) -> Path:
    old_table = current_table()
    references = {path: path.read_text() for path in TABLE_REFERENCES}
    for path, text in references.items():
        if not TABLE_PATTERN.search(text):
            raise SystemExit(f"{path} does not reference the ASN table")

    rib = download_rib(work_dir)
    snapshot = rib_date(rib)
    new_table = DATA_DIR / f"ipasn_{snapshot:%Y%m%d}.dat"
    if new_table == old_table:
        print(f"table {old_table.name} is already the latest snapshot", file=sys.stderr)
        return old_table

    # Convert next to the final location so the swap is a same-filesystem
    # rename, and touch the repository only once every download succeeded.
    converted = DATA_DIR / f"{new_table.name}.tmp"
    _run(["pyasn_util_convert.py", "--single", str(rib), str(converted)])
    names = DATA_DIR / f"{NAMES_FILE.name}.tmp"
    _run(["pyasn_util_asnames.py", "-o", str(names)])

    converted.replace(new_table)
    names.replace(NAMES_FILE)
    old_table.unlink()
    for path, text in references.items():
        path.write_text(TABLE_PATTERN.sub(new_table.name, text))
    return new_table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="where to download and convert (default: a temporary directory)",
    )
    args = parser.parse_args()
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        table = refresh(args.work_dir)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            table = refresh(Path(tmp))
    print(table.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
