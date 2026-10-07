"""Command line entry point:  python -m scrapers.maharera.cli {list,details} ...

  list     --district Palghar [--taluka X] [--max-pages N] --out data/rera/list.jsonl
  details  --in data/rera/list.jsonl --out data/rera/projects.jsonl [--limit N] [--skip-existing]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("scrapers.maharera")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scrapers.maharera.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests (default 3)")
    ap.add_argument("--timeout", type=float, default=180.0, help="per-request timeout in seconds")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="crawl the project search listing for a district")
    pl.add_argument("--district", required=True)
    pl.add_argument("--taluka", default=None, help="keep only rows whose location mentions this taluka")
    pl.add_argument("--max-pages", type=int, default=None)
    pl.add_argument("--out", required=True)
    pl.add_argument("--resume", action="store_true",
                    help="append to --out and continue after the last page already crawled")

    pd = sub.add_parser("details", help="fetch detail data for rows of a list.jsonl")
    pd.add_argument("--in", dest="inp", required=True)
    pd.add_argument("--out", required=True)
    pd.add_argument("--limit", type=int, default=None)
    pd.add_argument("--skip-existing", action="store_true")
    pd.add_argument("--prefer-talukas", default="Palghar,Dahanu,Talasari,Wada",
                    help="comma list; rows whose location matches are processed first")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .crawl import crawl_details, crawl_list  # noqa: E402  (keeps --help fast)
    from .client import MahaReraClient

    with MahaReraClient(delay=args.delay, timeout=args.timeout, retries=args.retries) as client:
        if args.cmd == "list":
            n = crawl_list(client, district=args.district, taluka=args.taluka, max_pages=args.max_pages,
                           out=Path(args.out), resume=args.resume)
            log.info("wrote %d listing rows to %s", n, args.out)
        else:
            prefer = [t.strip() for t in args.prefer_talukas.split(",") if t.strip()]
            n = crawl_details(client, inp=Path(args.inp), out=Path(args.out), limit=args.limit,
                              skip_existing=args.skip_existing, prefer_talukas=prefer)
            log.info("wrote %d project records to %s", n, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
