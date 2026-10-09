# SPDX-License-Identifier: Apache-2.0
"""Write the published dataset layout used by fossfoundation.info.

``foss990 publish --repo ../fossfoundation`` writes::

    <repo>/data/irs990/
        core.csv             one row per filing with the core totals
        filings.csv          every selected filing (from the IRS index)
        organizations.csv    the organizations searched for
        links.csv            grants and related-organization links
        orgs/<EIN>.json      every parsed filing of one organization
        tables/<table>.csv   cross-organization Schedule I/R, VII-B tables
        datapackage.json     Frictionless Data description of the CSVs
    <repo>/_data/irs990/core.csv    copy of core.csv for Jekyll pages

A hand-written ``README.md`` in ``data/irs990`` is left alone. Names of
individuals are always withheld in the published layout.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import re
import shutil
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from foss990parser import __version__, export
from foss990parser.config import GT_LAKE_URL, IRS_DOWNLOADS_PAGE
from foss990parser.eins import Organization
from foss990parser.fields import TABLES
from foss990parser.index import FilingRef
from foss990parser.parse import element_type

log = logging.getLogger(__name__)

DATA_DIR = Path("data") / "irs990"
"""Published dataset directory, relative to the fossfoundation repo."""
SITE_DATA_DIR = Path("_data") / "irs990"
"""Jekyll data directory, relative to the fossfoundation repo."""
ORGS_DIR = "orgs"
CORE_CSV = "core.csv"
FILINGS_CSV = "filings.csv"
ORGANIZATIONS_CSV = "organizations.csv"
LINKS_CSV = "links.csv"
DATAPACKAGE = "datapackage.json"

LINK_COLUMNS = [
    "source_ein",
    "source_name",
    "source_identifier",
    "tax_period",
    "tax_year",
    "relation",
    "target_name",
    "target_ein",
    "target_identifier",
    "amount",
    "detail",
]
"""Columns of ``links.csv``: one row per link between two organizations."""

LINK_TABLES = {
    "grants_to_orgs": "grant",
    "related_disregarded": "disregarded_entity",
    "related_tax_exempt": "related_tax_exempt",
    "related_partnerships": "related_partnership",
    "related_corporations": "related_corporation",
    "related_transactions": "transaction",
}
"""Tables that become links, and the ``relation`` value of their rows."""

_RELATED_TABLES = [key for key in LINK_TABLES if key.startswith("related_")]

# Types of columns not derived from IRS element names.
_KNOWN_TYPES = {
    "tax_year": "integer",
    "amended": "boolean",
    "proc_year": "integer",
    "in_foundations": "boolean",
    "in_p990": "boolean",
    "amount": "integer",
    **{key: "integer" for key in export.CORE_KEYS},
}

_DESCRIPTIONS = {
    CORE_CSV: "One row per parsed Form 990/990-EZ filing with core totals "
    "(ProPublica-compatible names). tax_period (YYYYMM of the fiscal year "
    "end) is the key; an empty value means not reported, not 0.",
    FILINGS_CSV: "Every return selected from the IRS e-file indexes, "
    "including 990-PF returns and filings not yet parsed.",
    ORGANIZATIONS_CSV: "The US organizations searched for, from "
    "fossfoundation.info foundation pages and ProPublica data.",
    LINKS_CSV: "Links between organizations: Schedule I grants, Schedule R "
    "related organizations and transactions. target_ein is filled when "
    "reported, or for transactions when the other organization is listed "
    "in the filer's Schedule R; *_identifier is the fossfoundation.info id.",
}


_SUFFIXES = {"INC", "CORP", "CORPORATION", "LLC", "LTD", "LIMITED", "CO"}


def _normal_name(name: object) -> str:
    """Return an organization name reduced for matching.

    Only letters and digits are kept, and a leading "THE" and trailing
    legal suffixes (INC, CORP, LLC...) are dropped, so "Mozilla Corp."
    matches "MOZILLA CORPORATION".
    """
    words = re.sub(r"[^A-Z0-9 ]", "", str(name or "").upper()).split()
    if words[:1] == ["THE"]:
        words = words[1:]
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    return "".join(words)


def _eins_by_name(filing: dict[str, Any]) -> dict[str, str]:
    """Map normalized names of a filing's related orgs to their EINs.

    Names shared by organizations with different EINs are left out, so
    an ambiguous name is never linked to the wrong organization.
    """
    found: dict[str, set[str]] = {}
    for key in _RELATED_TABLES:
        for row in filing.get(key, []):
            if row.get("ein"):
                name = _normal_name(row.get("name"))
                found.setdefault(name, set()).add(str(row["ein"]))
    return {name: eins.pop() for name, eins in found.items() if len(eins) == 1}


def _amount(*values: object) -> int | None:
    """Return the sum of the integer ``values``, or None if none are."""
    numbers = [value for value in values if isinstance(value, int)]
    return sum(numbers) if numbers else None


def build_links(
    grouped: dict[str, list[dict[str, Any]]],
    orgs: dict[str, Organization],
) -> list[dict[str, Any]]:
    """Return one link row per grant, related organization or transaction.

    Schedule R transactions name the other organization but not its EIN,
    so the EIN is looked up by name among the filer's Schedule R related
    organizations for the same tax period.
    """
    identifiers = {ein: org.identifier for ein, org in orgs.items()}
    links: list[dict[str, Any]] = []
    for ein, filings in sorted(grouped.items()):
        org = orgs.get(ein)
        for filing in filings:
            related_eins = _eins_by_name(filing)
            base = {
                "source_ein": ein,
                "source_name": org.name if org else "",
                "source_identifier": identifiers.get(ein, ""),
                "tax_period": filing["tax_period"],
                "tax_year": filing.get("tax_year"),
            }
            for key, relation in LINK_TABLES.items():
                for row in filing.get(key, []):
                    if key == "grants_to_orgs":
                        name = row.get("name")
                        target = row.get("ein")
                        amount = _amount(row.get("cash"), row.get("noncash"))
                        detail = row.get("purpose")
                    elif key == "related_transactions":
                        name = row.get("other_org")
                        target = related_eins.get(_normal_name(name))
                        amount = _amount(row.get("amount"))
                        detail = row.get("transaction_type")
                    else:
                        name = row.get("name")
                        target = row.get("ein")
                        amount = None
                        detail = row.get("activity")
                    links.append(
                        {
                            **base,
                            "relation": relation,
                            "target_name": name,
                            "target_ein": target,
                            "target_identifier": identifiers.get(
                                str(target or ""), ""
                            ),
                            "amount": amount,
                            "detail": detail,
                        }
                    )
    return links


def write_links_csv(links: list[dict[str, Any]], path: Path) -> None:
    """Write link rows from :func:`build_links` to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LINK_COLUMNS)
        writer.writeheader()
        writer.writerows(links)


def check_no_person_names(grouped: dict[str, list[dict[str, Any]]]) -> None:
    """Raise ValueError if any row names an individual."""
    for ein, filings in grouped.items():
        for filing in filings:
            for key, table in TABLES.items():
                if table.person_name is None:
                    continue
                for row in filing.get(key, []):
                    if row.get("name_type") == "person" and row.get("name"):
                        raise ValueError(
                            f"{ein} {filing['tax_period']} {key}: "
                            "a person's name would be published"
                        )


def _table_types(key: str) -> dict[str, str]:
    """Return column -> field type for table ``key`` (unprefixed names)."""
    return {
        column: element_type(paths[0].rsplit("/", 1)[-1])
        for column, paths in TABLES[key].columns.items()
    }


def _schema(columns: list[str], types: dict[str, str]) -> dict[str, Any]:
    """Return a Frictionless Table Schema for CSV ``columns``."""
    return {
        "fields": [
            {
                "name": column,
                "type": types.get(column, _KNOWN_TYPES.get(column, "string")),
            }
            for column in columns
        ]
    }


def _resource(
    path: str, columns: list[str], types: dict[str, str] | None = None
) -> dict[str, Any]:
    """Return a Frictionless tabular data resource for one CSV file."""
    resource: dict[str, Any] = {
        "name": path.removesuffix(".csv").replace("/", "-"),
        "path": path,
        "profile": "tabular-data-resource",
        "format": "csv",
        "mediatype": "text/csv",
        "encoding": "utf-8",
        "schema": _schema(columns, types or {}),
    }
    if path in _DESCRIPTIONS:
        resource["description"] = _DESCRIPTIONS[path]
    return resource


def build_datapackage(created: str) -> dict[str, Any]:
    """Return the ``datapackage.json`` document for the published CSVs."""
    resources = [
        _resource(CORE_CSV, export.CORE_COLUMNS),
        _resource(FILINGS_CSV, [f.name for f in dataclass_fields(FilingRef)]),
        _resource(
            ORGANIZATIONS_CSV,
            [f.name for f in dataclass_fields(Organization)],
        ),
        _resource(LINKS_CSV, LINK_COLUMNS),
    ]
    for key in export.TABLE_CSVS:
        types = {
            (f"{key}_{c}" if c in export.FILER_COLUMNS else c): kind
            for c, kind in _table_types(key).items()
        }
        resource = _resource(
            f"{export.TABLES_DIR}/{key}.csv", export.table_header(key), types
        )
        resource["description"] = (
            f"Form 990 {TABLES[key].line} rows of every filer, prefixed "
            "with the filer's EIN, name and tax period."
        )
        resources.append(resource)
    return {
        "profile": "tabular-data-package",
        "name": "foss-foundations-irs990",
        "title": "IRS Form 990 data for FOSS foundations",
        "description": "Parsed IRS Form 990 e-file returns of the US "
        "nonprofit FOSS foundations listed on fossfoundation.info. "
        f"Every parsed filing of one organization is in {ORGS_DIR}/<EIN>"
        ".json. Names of individuals are withheld.",
        "homepage": "https://fossfoundation.info/",
        "version": __version__,
        "created": created,
        "sources": [
            {
                "title": "IRS Form 990 Series Downloads",
                "path": IRS_DOWNLOADS_PAGE,
            },
            {
                "title": "GivingTuesday 990 Data Lake",
                "path": GT_LAKE_URL.split("/EfileData", 1)[0],
            },
        ],
        "resources": resources,
    }


def publish(
    grouped: dict[str, list[dict[str, Any]]],
    orgs: dict[str, Organization],
    eins_csv: Path,
    filings_csv: Path,
    repo: Path,
) -> Path:
    """Write the published layout into ``repo``; return the data directory.

    Per-EIN JSON files in ``orgs/`` for EINs no longer present are
    removed, so the directory always matches the current filings.
    """
    check_no_person_names(grouped)
    out_dir = repo / DATA_DIR
    orgs_dir = out_dir / ORGS_DIR
    written = export.write_json(grouped, orgs, orgs_dir)
    for stale in set(orgs_dir.glob("*.json")) - set(written):
        log.warning("Removing %s: no filings for this EIN", stale)
        stale.unlink()
    export.write_core_csv(grouped, orgs, out_dir / CORE_CSV)
    export.write_table_csvs(grouped, orgs, out_dir / export.TABLES_DIR)
    write_links_csv(build_links(grouped, orgs), out_dir / LINKS_CSV)
    shutil.copyfile(filings_csv, out_dir / FILINGS_CSV)
    shutil.copyfile(eins_csv, out_dir / ORGANIZATIONS_CSV)
    created = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    (out_dir / DATAPACKAGE).write_text(
        json.dumps(build_datapackage(created), indent=2) + "\n",
        encoding="utf-8",
    )
    site_dir = repo / SITE_DATA_DIR
    site_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_dir / CORE_CSV, site_dir / CORE_CSV)
    return out_dir
