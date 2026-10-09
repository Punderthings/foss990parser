import csv

from foss990parser import export, fields
from foss990parser.eins import Organization
from foss990parser.index import FilingRef
from foss990parser.parse import load, parse_return, parse_table
from tests.conftest import FIXTURES


def load_fixture(name: str, **kw) -> dict:
    return parse_return((FIXTURES / name).read_bytes(), **kw)


def test_contractors_lf():
    rows = load_fixture("lf_2024_990.xml")["contractors"]
    assert len(rows) == 5
    assert rows[0] == {
        "name": "PSI SERVICES INC",
        "services": "EXAM DEVELOPMENT",
        "compensation": 1633254,
        "city": "GLENDALE",
        "state": "CA",
        "country": "US",
        "name_type": "business",
    }


def test_schedule_i_mozilla():
    result = load_fixture("mozilla_2024_990.xml")
    assert result["has_schedule_i"] is True
    assert result["fields"]["grants_501c3_org_count"] == 16
    assert result["fields"]["grants_other_org_count"] == 3
    orgs = result["grants_to_orgs"]
    assert len(orgs) == 18
    assert orgs[0]["name"] == "ACCESS NOW INC"
    assert orgs[0]["ein"] == "270597430"
    assert orgs[0]["cash"] == 15000
    individuals = result["grants_to_individuals"]
    assert individuals[0] == {
        "grant_type": "FELLOWSHIP",
        "recipients": 1,
        "cash": 20000,
        "noncash": None,
        "noncash_description": None,
        "valuation_method": None,
    }


def test_schedule_r_lf():
    result = load_fixture("lf_2024_990.xml")
    assert result["has_schedule_r"] is True
    assert result["has_schedule_i"] is False
    japan = result["related_disregarded"][0]
    assert japan["name"] == "LINUX FOUNDATION JAPAN LLC"
    assert japan["country"] == "JA" and japan["city"] == "TOKYO"
    assert japan["domicile_country"] == "JA"
    kernel = result["related_tax_exempt"][0]
    assert kernel["name"] == "THE LINUX KERNEL ORGANIZATION"
    assert kernel["controlled"] is True
    labs = result["related_corporations"][0]
    assert labs["ownership_pct"] == 1.0
    assert result["related_transactions"][0]["amount"] == 265300


def test_schedule_r_partnerships_mozilla():
    rows = load_fixture("mozilla_2024_990.xml")["related_partnerships"]
    assert rows[0]["name"] == "MOZILLA VENTURES I LP"
    assert rows[0]["general_partner"] is True
    assert rows[0]["share_of_eoy_assets"] == 32328929


def test_no_schedules_gives_empty_tables():
    result = load_fixture("asf_2024_990.xml")
    assert result["has_schedule_i"] is False
    assert result["grants_to_orgs"] == []
    assert result["fields"]["grants_501c3_org_count"] is None


PERSON_XML = b"""<Return xmlns="http://www.irs.gov/efile"><ReturnData>
<IRS990><ContractorCompensationGrp>
  <ContractorName><PersonNm>JANE DOE</PersonNm></ContractorName>
  <ContractorAddress><ForeignAddress>
  <AddressLine1Txt>1 Street</AddressLine1Txt>
  <CityNm>BERLIN</CityNm><CountryCd>GM</CountryCd></ForeignAddress>
  </ContractorAddress>
  <ServicesDesc>SYSADMIN</ServicesDesc><CompensationAmt>120000</CompensationAmt>
</ContractorCompensationGrp></IRS990></ReturnData></Return>"""


def test_person_names_withheld_by_default():
    return_data = load(PERSON_XML)[0]
    table = fields.TABLES["contractors"]
    (row,) = parse_table(return_data, table)
    assert row["name"] is None and row["name_type"] == "person"
    assert row["country"] == "GM" and row["city"] == "BERLIN"
    assert "AddressLine1Txt" not in str(row) and "1 Street" not in str(row)
    (row,) = parse_table(return_data, table, include_person_names=True)
    assert row["name"] == "JANE DOE"


OFFICER_XML = b"""<Return xmlns="http://www.irs.gov/efile"><ReturnData>
<IRS990><Form990PartVIISectionAGrp>
  <BusinessName><BusinessNameLine1Txt>JOHN ROE</BusinessNameLine1Txt>
  </BusinessName><TitleTxt>CHAIR</TitleTxt>
  <IndividualTrusteeOrDirectorInd>X</IndividualTrusteeOrDirectorInd>
</Form990PartVIISectionAGrp><Form990PartVIISectionAGrp>
  <BusinessName><BusinessNameLine1Txt>TRUST BANK NA</BusinessNameLine1Txt>
  </BusinessName><TitleTxt>TRUSTEE</TitleTxt>
  <InstitutionalTrusteeInd>X</InstitutionalTrusteeInd>
</Form990PartVIISectionAGrp></IRS990></ReturnData></Return>"""


def test_officer_business_name_without_institution_is_person():
    # Some filers (e.g. Apereo 2023) list directors under BusinessName.
    return_data = load(OFFICER_XML)[0]
    table = fields.TABLES["officers"]
    director, bank = parse_table(return_data, table)
    assert director["name"] is None and director["name_type"] == "person"
    assert director["title"] == "CHAIR"
    assert bank["name"] == "TRUST BANK NA"
    assert bank["name_type"] == "business"
    director, _ = parse_table(return_data, table, include_person_names=True)
    assert director["name"] == "JOHN ROE"


def test_contractor_business_name_stays_business():
    assert fields.TABLES["contractors"].business_flag is None


def test_table_csvs(tmp_path):
    ref = FilingRef(
        ein="460503801",
        tax_period="202412",
        return_type="990",
        object_id="x",
        return_id="1",
        taxpayer_name="LF",
        sub_date="2025",
        proc_year=2025,
    )
    grouped = export.group_by_ein(
        [ref], {"x": (FIXTURES / "lf_2024_990.xml", "cache")}
    )
    orgs = {"460503801": Organization(ein="460503801", name="LF")}
    paths = export.write_table_csvs(grouped, orgs, tmp_path)
    assert {p.name for p in paths} >= {
        "contractors.csv",
        "related_tax_exempt.csv",
    }
    with (tmp_path / "contractors.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert rows[0]["contractors_name"] == "PSI SERVICES INC"
    assert rows[0]["tax_period"] == "202412"
    with (tmp_path / "related_tax_exempt.csv").open() as handle:
        header = next(csv.reader(handle))
    assert len(header) == len(set(header))
    assert header[0] == "ein" and "related_tax_exempt_ein" in header


def test_officers_lf_json_only():
    result = load_fixture("lf_2024_990.xml")
    officers = result["officers"]
    assert len(officers) == 32
    top = officers[-1]
    assert top["name"] is None and top["name_type"] == "person"
    assert top["title"] == "VP STRATEGIC AND DEVELOPER"
    assert top["hours_per_week"] == 40.0
    assert top["highest_compensated"] is True
    assert top["officer"] is False  # unchecked box, not "unknown"
    assert top["comp_from_org"] == 651592
    assert top["other_comp"] == 64491
    fields_ = result["fields"]
    assert fields_["officers_comp_from_org"] == 7694152
    assert fields_["individuals_over_100k"] == 199
    assert fields_["any_comp_over_150k"] is True
    # Part VII line 1d total equals the sum of the listed rows.
    assert sum(o["comp_from_org"] for o in officers) == 7694152
    assert "officers" not in export.TABLE_CSVS


def test_officer_names_on_request():
    result = load_fixture("lf_2024_990.xml", include_person_names=True)
    assert all(o["name"] for o in result["officers"])
