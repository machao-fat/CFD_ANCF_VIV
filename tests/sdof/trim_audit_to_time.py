from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    args = parser.parse_args()
    with args.csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = [row for row in reader if float(row["time_s"]) <= args.end_time + 1.0e-12]
        fields = reader.fieldnames or []
    temporary = args.csv.with_suffix(args.csv.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(args.csv)
    print({"path": str(args.csv), "end_time_s": args.end_time, "rows": len(rows)})


if __name__ == "__main__":
    main()
