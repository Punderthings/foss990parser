"""Write parsed returns as per-EIN JSON files and a flat core CSV."""

from __future__ import annotations

import csv
import datetime
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from foss990parser import __version__
from foss990parser.eins import Organization
from foss990parser.fields import CORE, FORM_990, TABLES
from foss990parser.index import FilingRef
from foss990parser.parse import parse_return

log = logging.getLogger(__name__)

CORE_KEYS = list(CORE[FORM_990])
CORE_CSV = "irs990_core.csv"
TABLES_DIR = "tables"
TABLE_CSVS = [
    "contractors",
    "grants_to_orgs",
    "grants_to_individuals",
    "related_disregarded",
    "related_tax_exempt",
    "related_partnerships",
    "related_corporations",
    "related_transactions",
]
"""Tables also written as one cross-organization CSV each."""


def build_filing(
    ref: FilingRef,
    xml: Path | None,
    source: str,
    include_person_names: bool = False,
) -> dict[str, Any]:
    """Combine index metadata, provenance and parsed XML for one return."""
    filing: dict[str, Any] = {
        "tax_period": ref.tax_period,
        "return_type": ref.return_type,
        "object_id": ref.object_id,
        "proc_year": ref.proc_year,
        "source": source,
    }
    if xml is None:
        filing["parsed"] = False
        return filing
    parsed = parse_return(xml.read_bytes(), include_person_names)
    parsed.pop("ein", None)
    parsed.pop("name", None)
    parsed.pop("return_type", None)
    filing.update(parsed)
    return filing


def group_by_ein(
    refs: Iterable[FilingRef],
    sources: dict[str, tuple[Path | None, str]],
    include_person_names: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Build filings for every ref, grouped by EIN, newest first."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in refs:
        xml, source = sources.get(ref.object_id, (None, "missing"))
        try:
            filing = build_filing(ref, xml, source, include_person_names)
        except Exception as error:  # keep going; report the bad file
            log.error("Failed to parse %s: %s", ref.object_id, error)
            filing = build_filing(ref, None, f"error: {error}")
        grouped[ref.ein].append(filing)
    for filings in grouped.values():
        filings.sort(key=lambda f: (f["tax_period"], f["return_type"]))
        filings.reverse()
    return grouped


def write_json(
    grouped: dict[str, list[dict[str, Any]]],
    orgs: dict[str, Organization],
    out_dir: Path,
) -> list[Path]:
    """Write ``<out_dir>/<EIN>.json`` for every EIN with filings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    written = []
    for ein, filings in sorted(grouped.items()):
        org = orgs.get(ein)
        document = {
            "ein": ein,
            "name": org.name if org else "",
            "identifier": org.identifier if org else "",
            "generated_by": f"foss990parser {__version__}",
            "generated_at": stamp,
            "filings": filings,
        }
        path = out_dir / f"{ein}.json"
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def write_core_csv(
    grouped: dict[str, list[dict[str, Any]]],
    orgs: dict[str, Organization],
    path: Path,
) -> None:
    """Write one CSV row per parsed filing with the core totals."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "ein",
        "name",
        "tax_period",
        "tax_year",
        "return_type",
        "return_version",
        "amended",
        "source",
        *CORE_KEYS,
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for ein, filings in sorted(grouped.items()):
            org = orgs.get(ein)
            for filing in filings:
                if not filing.get("parsed"):
                    continue
                row = {key: filing.get(key) for key in columns}
                row.update(filing.get("core", {}))
                row["ein"] = ein
                row["name"] = org.name if org else ""
                writer.writerow(row)


def write_table_csvs(
    grouped: dict[str, list[dict[str, Any]]],
    orgs: dict[str, Organization],
    out_dir: Path,
) -> list[Path]:
    """Write one CSV per table in :data:`TABLE_CSVS`, across all EINs.

    Each row is prefixed with the filer's EIN, name and tax period.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for key in TABLE_CSVS:
        table = TABLES[key]
        columns = ["ein", "name", "tax_period", "tax_year"]
        extra = list(table.columns)
        if table.address is not None:
            extra += ["city", "state", "country"]
        if table.person_name is not None:
            extra.append("name_type")
        header = columns + [f"{key}_{c}" if c == "name" else c for c in extra]
        path = out_dir / f"{key}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for ein, filings in sorted(grouped.items()):
                org = orgs.get(ein)
                for filing in filings:
                    for row in filing.get(key, []):
                        writer.writerow(
                            [
                                ein,
                                org.name if org else "",
                                filing["tax_period"],
                                filing.get("tax_year"),
                            ]
                            + [row.get(c) for c in extra]
                        )
        written.append(path)
    return written
