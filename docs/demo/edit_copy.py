"""Make one edit of task 6 of the L2 demonstration in a copy of the Bike Workload, and rewrite the copy's lock.

Standard library only; it imports nothing of Hypotrail and is not a command of the CLI. Run it with the Python
of the checkout:

    uv run python docs/demo/edit_copy.py --copy DIR --edit 6.1
"""

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

DATA_FILE = "data/day.csv"
LOCK_FILE = "data-sources.lock.json"
DATE_COLUMN = "dteday"
# The two columns an edit changes, by the same amount: `cnt` is checked to equal `casual + registered`.
COLUMNS = ("registered", "cnt")
AMOUNT = 100
# The day of each edit: 6.1 is a day of public_check, outside the assessed Partition; 6.2 a day of dev, inside it.
EDITS = {"6.1": "2012-12-31", "6.2": "2012-03-15"}
# The checkout this file is in: docs/demo/ is two folders below its root.
CHECKOUT = Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    made.add_argument("--copy", required=True, metavar="DIR", help="the Workload copy: the folder passed as --examples-dir")
    made.add_argument("--edit", required=True, choices=sorted(EDITS), help="which edit to make")
    return made


def inside_the_checkout(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == CHECKOUT or CHECKOUT in resolved.parents


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def edited(text: str, day: str) -> tuple:
    """(the text with `COLUMNS` of `day` raised by `AMOUNT`, {column: (old, new)}). Every other byte is kept, line endings included."""
    lines = text.splitlines(keepends=True)
    header = next(csv.reader([lines[0]]))
    date_at = header.index(DATE_COLUMN)
    [number] = [at for at, line in enumerate(lines[1:], 1) if next(csv.reader([line]))[date_at] == day]
    line = lines[number]
    cells = next(csv.reader([line]))
    changes = {}
    for column in COLUMNS:
        old = int(cells[header.index(column)])
        changes[column] = (old, old + AMOUNT)
        cells[header.index(column)] = str(old + AMOUNT)
    out = io.StringIO()
    csv.writer(out, lineterminator=line[len(line.rstrip("\r\n")):]).writerow(cells)
    lines[number] = out.getvalue()
    return "".join(lines), changes


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    copy = Path(args.copy)
    bike = copy / "bike_day"
    data_path, lock_path = bike / DATA_FILE, bike / LOCK_FILE
    if any(inside_the_checkout(path) for path in (copy, bike, data_path, lock_path)):
        print(
            f"refused: {copy} is inside the checkout {CHECKOUT}. This script edits a Workload copy made outside the checkout, "
            "so that no Reference of the repository changes. Nothing was written.",
            file=sys.stderr,
        )
        return 2
    for name, path in ((DATA_FILE, data_path), (LOCK_FILE, lock_path)):
        if not path.is_file():
            print(f"{name} was not found in {bike}: --copy takes the Workload copy passed as --examples-dir. Nothing was written.", file=sys.stderr)
            return 1
    day = EDITS[args.edit]
    old_bytes = data_path.read_bytes()
    text, changes = edited(old_bytes.decode("utf-8"), day)
    new_bytes = text.encode("utf-8")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    [entry] = [source for source in lock["sources"] if source["local_path"] == DATA_FILE]
    old_size = entry["size_bytes"]
    entry["sha256"], entry["size_bytes"] = digest(new_bytes), len(new_bytes)
    data_path.write_bytes(new_bytes)
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"edit {args.edit} of task 6, in {data_path}")
    print(f"day: {day}")
    for column, (old, new) in changes.items():
        print(f"{column}: {old} -> {new}")
    print(f"sha256 of {DATA_FILE}: {digest(old_bytes)} -> {entry['sha256']}")
    print(f"size_bytes of {DATA_FILE}: {old_size} -> {entry['size_bytes']}")
    print(f"rewritten: the sha256 and size_bytes of {DATA_FILE} in {lock_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
