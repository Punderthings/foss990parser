"""Parse one e-filed Form 990 / 990-EZ XML return into plain data."""

from __future__ import annotations

from typing import Any, cast

from lxml import etree
from lxml.etree import _Element as Element

from foss990parser import fields as fm

Value = int | float | bool | str | None

BOM = b"\xef\xbb\xbf"

# Older schemas used these column names without the "Amt" suffix.
_NUMERIC_NAMES = {
    "Total",
    "ProgramServices",
    "ManagementAndGeneral",
    "Fundraising",
}

# Safe parser: no entity expansion, no network access, no DTD loading.
_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
)


def local_name(element: Element) -> str:
    """Return the tag of ``element`` without its namespace."""
    return str(etree.QName(element).localname)


def child(element: Element | None, name: str) -> Element | None:
    """Return the first direct child of ``element`` with local name."""
    if element is None:
        return None
    for item in element.iterchildren(tag=etree.Element):
        if local_name(item) == name:
            return item
    return None


def children(element: Element | None, name: str) -> list[Element]:
    """Return all direct children of ``element`` with local name."""
    if element is None:
        return []
    return [
        item
        for item in element.iterchildren(tag=etree.Element)
        if local_name(item) == name
    ]


def find(element: Element | None, path: str) -> Element | None:
    """Follow a ``/``-separated path of local names below ``element``."""
    for name in path.split("/"):
        element = child(element, name)
    return element


def convert(name: str, text: str | None) -> Value:
    """Convert element text to int/bool/str based on the element name."""
    if text is None or not text.strip():
        return None
    text = text.strip()
    if name.endswith(("Pct", "Rt")):
        try:
            return float(text)
        except ValueError:
            return text
    if name.endswith(("Amt", "Cnt")) or name in _NUMERIC_NAMES:
        try:
            return int(text)
        except ValueError:
            return text
    if name.endswith("Ind"):
        return text.lower() in ("x", "true", "1")
    return text


def value_at(element: Element | None, path: str) -> Value:
    """Return the converted value at ``path`` below ``element``."""
    found = find(element, path)
    if found is None:
        return None
    return convert(path.rsplit("/", 1)[-1], found.text)


def load(data: bytes) -> Element:
    """Parse XML bytes (a leading UTF-8 BOM is allowed)."""
    root = etree.fromstring(data.removeprefix(BOM), parser=_PARSER)
    return cast(Element, root)


def _columns(
    group: Element | None, columns: dict[str, tuple[str, ...]]
) -> dict[str, Value] | None:
    """Read named columns of a line-item group; None if group absent."""
    if group is None:
        return None
    out: dict[str, Value] = {}
    for key, names in columns.items():
        out[key] = None
        for name in names:
            found = child(group, name)
            if found is not None:
                out[key] = convert(name, found.text)
                break
    return out


def parse_header(root: Element) -> dict[str, Any]:
    """Extract return metadata from ``Return/ReturnHeader``."""
    header = child(root, "ReturnHeader")
    tax_year = value_at(header, "TaxYr")
    return {
        "ein": value_at(header, "Filer/EIN"),
        "name": value_at(header, "Filer/BusinessName/BusinessNameLine1Txt"),
        "return_type": value_at(header, "ReturnTypeCd"),
        "return_version": root.get("returnVersion"),
        "tax_year": int(tax_year) if isinstance(tax_year, str) else None,
        "period_begin": value_at(header, "TaxPeriodBeginDt"),
        "period_end": value_at(header, "TaxPeriodEndDt"),
    }


def first_value(element: Element, paths: tuple[str, ...]) -> Value:
    """Return the value of the first of ``paths`` present in ``element``."""
    for path in paths:
        if find(element, path) is not None:
            return value_at(element, path)
    return None


def _address(row: Element, prefix: str) -> dict[str, Value]:
    """Return city, state/province and country of a row's address."""
    base = f"{prefix}/" if prefix else ""
    us_address = find(row, f"{base}USAddress")
    if us_address is not None:
        return {
            "city": value_at(us_address, "CityNm"),
            "state": value_at(us_address, "StateAbbreviationCd"),
            "country": "US",
        }
    foreign = find(row, f"{base}ForeignAddress")
    return {
        "city": value_at(foreign, "CityNm"),
        "state": value_at(foreign, "ProvinceOrStateNm"),
        "country": value_at(foreign, "CountryCd"),
    }


def parse_table(
    return_data: Element | None,
    table: fm.Table,
    include_person_names: bool = False,
) -> list[dict[str, Value]]:
    """Extract every row of one repeating group as a list of dicts.

    Rows naming an individual (``table.person_name``) are marked with
    ``name_type: "person"`` and their name is withheld unless
    ``include_person_names`` is True.
    """
    rows: list[dict[str, Value]] = []
    for parent in children(return_data, table.parent):
        for item in children(parent, table.group):
            row = {
                out: first_value(item, paths)
                for out, paths in table.columns.items()
            }
            if table.checkboxes:
                for out, paths in table.columns.items():
                    if row[out] is None and paths[0].endswith("Ind"):
                        row[out] = False
            if table.address is not None:
                row.update(_address(item, table.address))
            if table.person_name is not None:
                is_person = find(item, table.person_name) is not None
                row["name_type"] = "person" if is_person else "business"
                if is_person and not include_person_names:
                    row["name"] = None
            rows.append(row)
    return rows


def parse_return(
    data: bytes, include_person_names: bool = False
) -> dict[str, Any]:
    """Parse a whole return into header, core, field and table sections.

    Absent elements are reported as ``None`` ("not reported"), never 0.
    Form 990-PF returns get header data only (``parsed`` is False).
    Names of individuals (e.g. contractors paid as persons) are withheld
    unless ``include_person_names`` is True.
    """
    root = load(data)
    result: dict[str, Any] = parse_header(root)
    form_name = fm.FORM_ELEMENTS.get(str(result["return_type"]), "")
    return_data = child(root, "ReturnData")
    form = child(return_data, form_name) if form_name else None
    result["amended"] = bool(value_at(form, "AmendedReturnInd"))
    result["parsed"] = form is not None and form_name in fm.CORE
    if not result["parsed"]:
        return result
    result["core"] = {
        key: value_at(form, path) for key, path in fm.CORE[form_name].items()
    }
    result["fields"] = {
        key: value_at(form, path)
        for key, (_line, path) in fm.SCALARS.get(form_name, {}).items()
    }
    if form_name != fm.FORM_990:
        return result
    result["fields"].update(
        {
            key: value_at(return_data, path)
            for key, (_line, path) in fm.SCHEDULE_SCALARS.items()
        }
    )
    for schedule in fm.SCHEDULES:
        flag = "has_schedule_" + schedule.removeprefix("IRS990Schedule")
        result[flag.lower()] = child(return_data, schedule) is not None
    result["functional_expenses"] = {
        key: _columns(child(form, group), fm.FUNCTIONAL_COLUMNS)
        for key, (_line, group) in fm.FUNCTIONAL_EXPENSES.items()
    }
    result["balance_sheet"] = {
        key: _columns(child(form, group), fm.BALANCE_COLUMNS)
        for key, (_line, group) in fm.BALANCE_SHEET.items()
    }
    for key, table in fm.TABLES.items():
        result[key] = parse_table(return_data, table, include_person_names)
    return result
