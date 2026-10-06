"""Download IRS e-file index CSVs and select our foundations' filings."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import requests

from foss990parser.config import IRS_XML_BASE, Settings
from foss990parser.net import get

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilingRef:
    """One e-filed return listed in an IRS index file.

    ``tax_period`` is ``YYYYMM`` of the fiscal year end; ``proc_year`` is
    the IRS processing year (the index/zip year), which is *not* the tax
    year. ``batch_id`` names the zip holding the XML (2024+ indexes).
    """

    ein: str
    tax_period: str
    return_type: str
    object_id: str
    return_id: str
    taxpayer_name: str
    sub_date: str
    proc_year: int
    batch_id: str = ""


def index_url(year: int) -> str:
    """Return the IRS URL of the index CSV for processing ``year``."""
    return f"{IRS_XML_BASE}/{year}/index_{year}.csv"


def download_index(
    year: int,
    settings: Settings,
    session: requests.Session,
    refresh: bool = False,
) -> Path | None:
    """Download ``index_<year>.csv`` into the cache (streamed).

    Returns the cached path, or None if the IRS has no file for ``year``.
    """
    path = settings.index_dir / f"index_{year}.csv"
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = get(session, index_url(year), settings, stream=True)
    if response.status_code != 200:
        log.warning("No index for %s (HTTP %s)", year, response.status_code)
        return None
    partial = path.with_suffix(".part")
    with partial.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1 << 20):
            handle.write(chunk)
    partial.replace(path)
    log.info("Downloaded %s", path)
    return path


def read_index(path: Path, year: int) -> Iterator[FilingRef]:
    """Yield every row of an IRS index CSV as a :class:`FilingRef`."""
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            row = {
                k.strip().upper(): (v or "").strip() for k, v in row.items()
            }
            yield FilingRef(
                ein=row.get("EIN", "").zfill(9),
                tax_period=row.get("TAX_PERIOD", ""),
                return_type=row.get("RETURN_TYPE", "").upper(),
                object_id=row.get("OBJECT_ID", ""),
                return_id=row.get("RETURN_ID", ""),
                taxpayer_name=row.get("TAXPAYER_NAME", ""),
                sub_date=row.get("SUB_DATE", ""),
                proc_year=year,
                batch_id=row.get("XML_BATCH_ID", ""),
            )


def select(
    refs: Iterable[FilingRef],
    eins: set[str],
    return_types: Iterable[str],
) -> list[FilingRef]:
    """Keep our EINs and return types; drop superseded duplicates.

    The IRS lists some returns more than once (e.g. amended or re-posted
    filings). For each ``(ein, tax_period, return_type)`` the most recently
    processed one wins, using processing year, then object id.
    """
    wanted = {t.upper() for t in return_types}
    best: dict[tuple[str, str, str], FilingRef] = {}
    for ref in refs:
        if ref.ein not in eins or ref.return_type not in wanted:
            continue
        key = (ref.ein, ref.tax_period, ref.return_type)
        current = best.get(key)
        if current is None or _recency(ref) > _recency(current):
            best[key] = ref
    return sorted(best.values(), key=lambda r: (r.ein, r.tax_period))


def _recency(ref: FilingRef) -> tuple[int, str]:
    """Sort key: later processing year, then larger object id, wins."""
    return (ref.proc_year, ref.object_id.zfill(20))


def write_csv(refs: list[FilingRef], path: Path) -> None:
    """Write selected filings to ``path`` as CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=[f.name for f in fields(FilingRef)]
        )
        writer.writeheader()
        for ref in refs:
            writer.writerow(asdict(ref))


def read_csv(path: Path) -> list[FilingRef]:
    """Read filings written by :func:`write_csv`."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            FilingRef(
                ein=row["ein"],
                tax_period=row["tax_period"],
                return_type=row["return_type"],
                object_id=row["object_id"],
                return_id=row["return_id"],
                taxpayer_name=row["taxpayer_name"],
                sub_date=row["sub_date"],
                proc_year=int(row["proc_year"]),
                batch_id=row["batch_id"],
            )
            for row in csv.DictReader(handle)
        ]
