"""Collect the US EINs of foundations listed in the fossfoundation repo."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

US_COUNTRIES = {"US", "USA"}


@dataclass
class Organization:
    """One US tax-exempt organization to collect 990 data for."""

    ein: str
    name: str = ""
    identifier: str = ""
    nonprofit_status: str = ""
    in_foundations: bool = False
    in_p990: bool = False


def normalize_ein(value: object) -> str | None:
    """Return a 9-digit EIN string, or None if ``value`` is not one."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(9) if 0 < len(digits) <= 9 else None


def _front_matter(path: Path) -> dict[str, Any]:
    """Parse the YAML front matter of a Jekyll ``.md`` file."""
    parts = path.read_text(encoding="utf-8").split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1])
    return data if isinstance(data, dict) else {}


def collect(repo: Path) -> list[Organization]:
    """Collect organizations from ``_foundations`` and ``_data/p990``.

    Foundations whose ``addressCountry`` is not the US are skipped even if
    their tax ID happens to be nine digits.
    """
    orgs: dict[str, Organization] = {}
    for path in sorted((repo / "_foundations").glob("*.md")):
        meta = _front_matter(path)
        country = str(meta.get("addressCountry", "US")).upper()
        digits = re.sub(r"\D", "", str(meta.get("taxID") or ""))
        if len(digits) != 9:
            continue
        ein = digits
        if country not in US_COUNTRIES:
            log.debug("Skipping non-US %s (%s)", path.stem, country)
            continue
        orgs[ein] = Organization(
            ein=ein,
            name=str(meta.get("commonName", "")),
            identifier=str(meta.get("identifier", path.stem)),
            nonprofit_status=str(meta.get("nonprofitStatus", "")),
            in_foundations=True,
        )
    for path in sorted((repo / "_data" / "p990").glob("*.json")):
        org_data = json.loads(path.read_text(encoding="utf-8"))
        info = org_data.get("organization", {})
        p990_ein = normalize_ein(info.get("ein"))
        if p990_ein is None:
            continue
        org = orgs.setdefault(
            p990_ein,
            Organization(
                ein=p990_ein,
                name=str(info.get("name", "")),
                nonprofit_status=f"501c{info.get('subsection_code', '')}",
            ),
        )
        org.in_p990 = True
    return sorted(orgs.values(), key=lambda org: org.ein)


def write_csv(orgs: list[Organization], path: Path) -> None:
    """Write organizations to ``path`` as CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f.name for f in fields(Organization)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for org in orgs:
            writer.writerow(asdict(org))


def read_csv(path: Path) -> dict[str, Organization]:
    """Read organizations written by :func:`write_csv`, keyed by EIN."""
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["ein"]: Organization(
                ein=row["ein"],
                name=row["name"],
                identifier=row["identifier"],
                nonprofit_status=row["nonprofit_status"],
                in_foundations=row["in_foundations"] == "True",
                in_p990=row["in_p990"] == "True",
            )
            for row in csv.DictReader(handle)
        }
