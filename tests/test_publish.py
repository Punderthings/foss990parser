import csv
import json

import pytest

from foss990parser import eins, export, index, publish
from foss990parser.cli import main
from foss990parser.eins import Organization
from foss990parser.index import FilingRef
from tests.conftest import FIXTURES

ORGS = {
    "460503801": Organization(
        ein="460503801", name="Linux Foundation", identifier="lf"
    ),
    "743183459": Organization(
        ein="743183459", name="Linux Kernel Organization", identifier="kernel"
    ),
    "200097189": Organization(
        ein="200097189", name="Mozilla", identifier="mozilla"
    ),
}


def ref(ein: str, object_id: str) -> FilingRef:
    return FilingRef(
        ein=ein,
        tax_period="202412",
        return_type="990",
        object_id=object_id,
        return_id="1",
        taxpayer_name="X",
        sub_date="2025",
        proc_year=2025,
    )


def grouped_fixtures() -> dict:
    refs = [ref("460503801", "lf"), ref("200097189", "moz")]
    sources = {
        "lf": (FIXTURES / "lf_2024_990.xml", "cache"),
        "moz": (FIXTURES / "mozilla_2024_990.xml", "cache"),
    }
    return export.group_by_ein(refs, sources)


def links_of(links, ein, relation):
    return [
        row
        for row in links
        if row["source_ein"] == ein and row["relation"] == relation
    ]


def test_normal_name():
    assert publish._normal_name("Mozilla Corp.") == "MOZILLA"
    assert publish._normal_name("MOZILLA CORPORATION") == "MOZILLA"
    assert publish._normal_name("The Linux Kernel Organization") == (
        "LINUXKERNELORGANIZATION"
    )
    assert publish._normal_name("LF Labs, Inc.") == "LFLABS"
    assert publish._normal_name("CO") == "CO"  # never empties a name
    assert publish._normal_name(None) == ""


def test_links_related_orgs_and_identifiers():
    links = publish.build_links(grouped_fixtures(), ORGS)
    exempt = links_of(links, "460503801", "related_tax_exempt")
    assert len(exempt) == 4
    kernel = exempt[0]
    assert kernel["target_name"] == "THE LINUX KERNEL ORGANIZATION"
    assert kernel["target_ein"] == "743183459"
    assert kernel["target_identifier"] == "kernel"
    assert kernel["source_identifier"] == "lf"
    assert kernel["tax_period"] == "202412" and kernel["amount"] is None
    assert len(links_of(links, "460503801", "related_corporation")) == 3
    assert len(links_of(links, "200097189", "related_partnership")) == 2


def test_links_transactions_resolve_ein_by_name():
    links = publish.build_links(grouped_fixtures(), ORGS)
    lf = links_of(links, "460503801", "transaction")
    assert [row["target_ein"] for row in lf] == ["743183459", "841730246"]
    assert lf[0]["target_identifier"] == "kernel"
    assert all(isinstance(row["amount"], int) for row in lf)
    assert all(row["detail"] for row in lf)  # Part V line 1 letter code
    moz = links_of(links, "200097189", "transaction")
    assert len(moz) == 9
    corp = [row for row in moz if row["target_name"] == "MOZILLA CORP"]
    assert corp and {row["target_ein"] for row in corp} == {"203226186"}


def test_ambiguous_related_name_is_not_resolved():
    filing = {
        "related_tax_exempt": [{"name": "Acme Inc", "ein": "111111111"}],
        "related_corporations": [{"name": "ACME LLC", "ein": "222222222"}],
        "related_disregarded": [{"name": "Beta LLC", "ein": "333333333"}],
    }
    assert publish._eins_by_name(filing) == {"BETA": "333333333"}


def test_links_grants_sum_cash_and_noncash():
    links = publish.build_links(grouped_fixtures(), ORGS)
    grants = links_of(links, "200097189", "grant")
    assert len(grants) == 18
    access = grants[0]
    assert access["target_name"] == "ACCESS NOW INC"
    assert access["target_ein"] == "270597430"
    assert access["amount"] == 15000
    assert access["target_identifier"] == ""
    assert publish._amount(5, None, 7) == 12
    assert publish._amount(None, "x") is None


def test_check_no_person_names():
    grouped = grouped_fixtures()
    publish.check_no_person_names(grouped)
    grouped["460503801"][0]["officers"][0].update(
        name="JANE DOE", name_type="person"
    )
    with pytest.raises(ValueError, match="officers"):
        publish.check_no_person_names(grouped)


def read_header(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def test_publish_layout(tmp_path):
    repo = tmp_path / "repo"
    data_dir = repo / "data" / "irs990"
    (data_dir / "orgs").mkdir(parents=True)
    (data_dir / "README.md").write_text("hand written\n")
    (data_dir / "orgs" / "999999999.json").write_text("{}")
    eins_csv, filings_csv = tmp_path / "eins.csv", tmp_path / "filings.csv"
    eins.write_csv(list(ORGS.values()), eins_csv)
    index.write_csv([ref("460503801", "lf")], filings_csv)

    out = publish.publish(
        grouped_fixtures(), ORGS, eins_csv, filings_csv, repo
    )

    assert out == data_dir
    assert (data_dir / "README.md").read_text() == "hand written\n"
    assert sorted(p.name for p in (data_dir / "orgs").iterdir()) == [
        "200097189.json",
        "460503801.json",
    ]
    site_core = repo / "_data" / "irs990" / "core.csv"
    assert site_core.read_text() == (data_dir / "core.csv").read_text()
    assert (data_dir / "filings.csv").read_text() == filings_csv.read_text()
    assert (data_dir / "organizations.csv").read_text() == (
        eins_csv.read_text()
    )
    package = json.loads((data_dir / "datapackage.json").read_text())
    assert package["name"] == "foss-foundations-irs990"
    paths = [resource["path"] for resource in package["resources"]]
    assert len(paths) == 4 + len(export.TABLE_CSVS)
    for resource in package["resources"]:
        header = read_header(data_dir / resource["path"])
        names = [field["name"] for field in resource["schema"]["fields"]]
        assert header == names, resource["path"]
        assert len(names) == len(set(names)), resource["path"]
    with (data_dir / "links.csv").open(newline="") as handle:
        links = list(csv.DictReader(handle))
    assert len(links) == len(publish.build_links(grouped_fixtures(), ORGS))


def test_datapackage_field_types():
    package = publish.build_datapackage("2026-01-01T00:00:00+00:00")
    types = {
        resource["path"]: {
            field["name"]: field["type"]
            for field in resource["schema"]["fields"]
        }
        for resource in package["resources"]
    }
    assert types["core.csv"]["totrevenue"] == "integer"
    assert types["core.csv"]["amended"] == "boolean"
    assert types["core.csv"]["tax_period"] == "string"
    grants = types["tables/grants_to_orgs.csv"]
    assert grants["grants_to_orgs_ein"] == "string"
    assert grants["cash"] == "integer"
    assert types["tables/related_partnerships.csv"]["ownership_pct"] == (
        "number"
    )
    assert types["tables/related_tax_exempt.csv"]["controlled"] == ("boolean")
    assert types["organizations.csv"]["in_p990"] == "boolean"
    assert types["filings.csv"]["proc_year"] == "integer"


def test_publish_command(tmp_path, capsys):
    data, cache, repo = tmp_path / "data", tmp_path / "cache", tmp_path / "r"
    eins.write_csv(list(ORGS.values()), data / "eins.csv")
    index.write_csv([ref("460503801", "lfobj")], data / "filings.csv")
    (cache / "xml").mkdir(parents=True)
    (cache / "xml" / "lfobj_public.xml").write_bytes(
        (FIXTURES / "lf_2024_990.xml").read_bytes()
    )
    argv = ["--cache", str(cache), "--data", str(data)]
    assert main([*argv, "publish", "--repo", str(repo)]) == 0
    assert "Published 1 organizations" in capsys.readouterr().out
    document = json.loads(
        (repo / "data/irs990/orgs/460503801.json").read_text()
    )
    officers = document["filings"][0]["officers"]
    assert officers and all(o["name"] is None for o in officers)
    assert (repo / "_data/irs990/core.csv").exists()
