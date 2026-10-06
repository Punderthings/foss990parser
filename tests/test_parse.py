import pytest

from foss990parser.parse import convert, parse_return
from tests.conftest import FIXTURES


def load(name: str) -> dict:
    return parse_return((FIXTURES / name).read_bytes())


def test_asf_header_handles_fiscal_year_and_bom():
    data = (FIXTURES / "asf_2024_990.xml").read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    result = load("asf_2024_990.xml")
    assert result["ein"] == "470825376"
    assert result["tax_year"] == 2024  # IRS: year the FY begins
    assert result["period_end"] == "2025-04-30"
    assert result["return_version"] == "2024v5.2"
    assert result["parsed"] is True
    assert result["amended"] is False


def test_asf_core_matches_return():
    core = load("asf_2024_990.xml")["core"]
    assert core["totrevenue"] == 2220257
    assert core["totfuncexpns"] == 2334727
    assert core["totnetassetend"] == 4206363


def test_asf_p1_fields():
    result = load("asf_2024_990.xml")
    assert result["fields"]["employees"] == 4
    assert result["fields"]["volunteers"] == 8200
    assert result["fields"]["contractors_over_100k"] == 3
    assert result["fields"]["government_grants"] is None  # not reported
    total = result["functional_expenses"]["total"]
    assert total == {
        "total": 2334727,
        "program": 2040778,
        "management": 185639,
        "fundraising": 108310,
    }
    assert result["balance_sheet"]["deferred_revenue"]["eoy"] == 1232912
    assert result["functional_expenses"]["grants_foreign"] is None


def test_repeating_groups():
    result = load("sfc_2024_990.xml")
    revenue = result["program_service_revenue"]
    assert revenue[0]["description"] == "Software Development Services"
    assert revenue[0]["total"] == 517741
    assert any(
        item["description"] == "Internships in FOSS"
        for item in result["other_expenses"]
    )


def test_2025_schema_version_parses():
    result = load("almalinux_2025_990.xml")
    assert result["return_version"] == "2025v4.0"
    assert result["tax_year"] == 2025
    assert result["fields"]["membership_dues"] == 250005


def test_990ez():
    result = load("minimal_990ez.xml")
    assert result["return_type"] == "990EZ"
    assert result["amended"] is True
    assert result["core"]["totrevenue"] == 1255
    assert result["core"]["totassetsend"] == 400
    assert result["core"]["totliabend"] == 45
    assert result["fields"] == {"membership_dues": 50}
    assert "functional_expenses" not in result


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("TotalAmt", "12", 12),
        ("Fundraising", "7", 7),
        ("SomeInd", "X", True),
        ("SomeInd", "false", False),
        ("Desc", " Hosting ", "Hosting"),
        ("TotalAmt", "", None),
        ("TotalAmt", None, None),
        ("OwnershipPct", "1.00000", 1.0),
    ],
)
def test_convert(name, text, expected):
    assert convert(name, text) == expected


def test_unknown_form_is_header_only():
    xml = (
        b'<Return xmlns="http://www.irs.gov/efile"><ReturnHeader>'
        b"<ReturnTypeCd>990PF</ReturnTypeCd></ReturnHeader>"
        b"<ReturnData><IRS990PF/></ReturnData></Return>"
    )
    result = parse_return(xml)
    assert result["parsed"] is False
    assert "core" not in result


def test_entities_are_not_expanded():
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "boom">]>'
        b"<Return><ReturnHeader><ReturnTypeCd>&x;</ReturnTypeCd>"
        b"</ReturnHeader></Return>"
    )
    assert parse_return(xml)["return_type"] in (None, "")
