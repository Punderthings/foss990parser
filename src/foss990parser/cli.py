"""Command line interface: ``foss990 <command>``.

Typical use, from the project directory::

    uv run foss990 run --repo ../fossfoundation

which runs ``eins``, ``index``, ``fetch`` and ``parse`` in order.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from foss990parser import __version__, eins, export, index, publish
from foss990parser.config import DEFAULT_RETURN_TYPES, Settings, default_years
from foss990parser.fetch import Fetcher, xml_path
from foss990parser.net import make_session

log = logging.getLogger("foss990parser")


def cmd_eins(args: argparse.Namespace, settings: Settings) -> int:
    """Build ``data/eins.csv`` from a fossfoundation checkout."""
    orgs = eins.collect(Path(args.repo))
    eins.write_csv(orgs, settings.eins_csv)
    print(f"Wrote {len(orgs)} EINs to {settings.eins_csv}")
    return 0


def cmd_index(args: argparse.Namespace, settings: Settings) -> int:
    """Download IRS indexes and write ``data/filings.csv``."""
    orgs = eins.read_csv(settings.eins_csv)
    session = make_session()
    refs: list[index.FilingRef] = []
    for year in args.years:
        path = index.download_index(year, settings, session, args.refresh)
        if path is not None:
            refs.extend(index.read_index(path, year))
    selected = index.select(refs, set(orgs), args.types)
    index.write_csv(selected, settings.filings_csv)
    found = {ref.ein for ref in selected}
    print(
        f"Selected {len(selected)} filings for {len(found)} of "
        f"{len(orgs)} EINs -> {settings.filings_csv}"
    )
    for ein in sorted(set(orgs) - found):
        print(f"  not in indexes: {ein} {orgs[ein].name}")
    return 0


def cmd_fetch(args: argparse.Namespace, settings: Settings) -> int:
    """Download every selected return's XML into the cache."""
    refs = _filtered(index.read_csv(settings.filings_csv), args.ein)
    if args.limit:
        refs = refs[: args.limit]
    fetcher = Fetcher(settings, make_session())
    results = fetcher.fetch_all(refs)
    counts = Counter(result.source for result in results)
    print("Fetched:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0 if counts.get("missing", 0) == 0 else 1


def _grouped(
    settings: Settings, ein: str | None, include_person_names: bool
) -> dict[str, list[dict[str, Any]]]:
    """Parse the cached XML of the selected filings, grouped by EIN."""
    refs = _filtered(index.read_csv(settings.filings_csv), ein)
    fetcher = Fetcher(settings, make_session())
    sources: dict[str, tuple[Path | None, str]] = {}
    for ref in refs:
        path = xml_path(settings, ref.object_id)
        if path.exists():
            source = fetcher.manifest.get(ref.object_id, "cache")
            sources[ref.object_id] = (path, source)
    return export.group_by_ein(refs, sources, include_person_names)


def cmd_parse(args: argparse.Namespace, settings: Settings) -> int:
    """Parse cached XML into per-EIN JSON and a core CSV."""
    orgs = eins.read_csv(settings.eins_csv)
    grouped = _grouped(settings, args.ein, args.include_person_names)
    out_dir = Path(args.out)
    written = export.write_json(grouped, orgs, out_dir)
    export.write_core_csv(grouped, orgs, out_dir / export.CORE_CSV)
    tables = export.write_table_csvs(
        grouped, orgs, out_dir / export.TABLES_DIR
    )
    print(
        f"Wrote {len(written)} JSON files, {export.CORE_CSV} and "
        f"{len(tables)} table CSVs to {out_dir}"
    )
    return 0


def cmd_publish(args: argparse.Namespace, settings: Settings) -> int:
    """Write the published dataset layout into a fossfoundation checkout."""
    orgs = eins.read_csv(settings.eins_csv)
    grouped = _grouped(settings, None, include_person_names=False)
    out_dir = publish.publish(
        grouped,
        orgs,
        settings.eins_csv,
        settings.filings_csv,
        Path(args.repo),
    )
    site_csv = Path(args.repo) / publish.SITE_DATA_DIR / publish.CORE_CSV
    print(f"Published {len(grouped)} organizations to {out_dir}")
    print(f"Copied {publish.CORE_CSV} to {site_csv}")
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    """Show, per EIN, the latest indexed tax period and fetch status."""
    orgs = eins.read_csv(settings.eins_csv)
    refs = index.read_csv(settings.filings_csv)
    latest: dict[str, index.FilingRef] = {}
    fetched: Counter[str] = Counter()
    for ref in refs:
        if (
            ref.ein not in latest
            or ref.tax_period > latest[ref.ein].tax_period
        ):
            latest[ref.ein] = ref
        if xml_path(settings, ref.object_id).exists():
            fetched[ref.ein] += 1
    total: Counter[str] = Counter(ref.ein for ref in refs)
    print(f"{'EIN':9}  {'latest':6}  {'fetched':>7}  name")
    for ein, org in sorted(orgs.items(), key=lambda item: item[1].name):
        newest = latest.get(ein)
        period = newest.tax_period if newest else "-"
        print(
            f"{ein}  {period:6}  {fetched[ein]:>3}/{total[ein]:<3}  {org.name}"
        )
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    """Run eins, index, fetch and parse in sequence."""
    for step in (cmd_eins, cmd_index, cmd_fetch, cmd_parse):
        status = step(args, settings)
        if status != 0 and step is not cmd_fetch:
            return status
    return 0


def _filtered(
    refs: list[index.FilingRef], ein: str | None
) -> list[index.FilingRef]:
    """Optionally restrict filings to one EIN."""
    if ein is None:
        return refs
    wanted = ein.replace("-", "").zfill(9)
    return [ref for ref in refs if ref.ein == wanted]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for all sub-commands."""
    parser = argparse.ArgumentParser(
        prog="foss990",
        description="Extract IRS Form 990 e-file data for FOSS foundations.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--cache", default="cache", help="cache directory")
    parser.add_argument("--data", default="data", help="data directory")
    parser.add_argument(
        "--delay", type=float, default=0.5, help="seconds between requests"
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_repo(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--repo",
            default="../fossfoundation",
            help="path to a fossfoundation checkout",
        )

    def add_index_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--years",
            type=int,
            nargs="+",
            default=default_years(),
            help="IRS processing years (default: 2019 to this year)",
        )
        p.add_argument(
            "--types",
            nargs="+",
            default=list(DEFAULT_RETURN_TYPES),
            help="return types to keep",
        )
        p.add_argument(
            "--refresh",
            action="store_true",
            help="re-download index files already in the cache",
        )

    def add_ein(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ein", help="only process this EIN")

    def add_out(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--out",
            default="data/irs990",
            help="output directory for <EIN>.json files",
        )
        p.add_argument(
            "--include-person-names",
            action="store_true",
            help="keep names of individuals (e.g. contractors paid as "
            "persons); withheld by default",
        )

    p = sub.add_parser("eins", help="collect EINs from fossfoundation")
    add_repo(p)
    p.set_defaults(func=cmd_eins)

    p = sub.add_parser("index", help="download IRS indexes, select filings")
    add_index_opts(p)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("fetch", help="download selected XML returns")
    add_ein(p)
    p.add_argument("--limit", type=int, help="fetch at most N returns")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("parse", help="parse cached XML to JSON/CSV")
    add_ein(p)
    add_out(p)
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser(
        "publish",
        help="write the published dataset into a fossfoundation checkout "
        "(data/irs990 and _data/irs990/core.csv); person names withheld",
    )
    add_repo(p)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="show coverage per EIN")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="eins + index + fetch + parse")
    add_repo(p)
    add_index_opts(p)
    add_ein(p)
    add_out(p)
    p.set_defaults(func=cmd_run, limit=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``foss990`` command."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = Settings(
        cache_dir=Path(args.cache),
        data_dir=Path(args.data),
        delay=args.delay,
    )
    status: int = args.func(args, settings)
    return status


if __name__ == "__main__":
    sys.exit(main())
