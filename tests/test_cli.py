import json
import shutil

from foss990parser import index
from foss990parser.cli import main
from tests.conftest import FIXTURES
from tests.test_eins import make_repo


def test_eins_then_parse_offline(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo")
    cache, data = tmp_path / "cache", tmp_path / "data"
    assert (
        main(
            [
                "--cache",
                str(cache),
                "--data",
                str(data),
                "eins",
                "--repo",
                str(repo),
            ]
        )
        == 0
    )
    refs = [
        index.FilingRef(
            ein="470825376",
            tax_period="202504",
            return_type="990",
            object_id="202630689349301933",
            return_id="1",
            taxpayer_name="ASF",
            sub_date="2026",
            proc_year=2026,
        )
    ]
    index.write_csv(refs, data / "filings.csv")
    (cache / "xml").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "asf_2024_990.xml",
        cache / "xml" / "202630689349301933_public.xml",
    )
    out = tmp_path / "out"
    assert (
        main(
            [
                "--cache",
                str(cache),
                "--data",
                str(data),
                "parse",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    document = json.loads((out / "470825376.json").read_text())
    filing = document["filings"][0]
    assert document["name"] == "Apache"
    assert filing["tax_period"] == "202504"
    assert filing["core"]["totrevenue"] == 2220257
    assert "470825376" in (out / "irs990_core.csv").read_text()
    contractors = (out / "tables" / "contractors.csv").read_text()
    assert "TABLE 2 CONSULTING" in contractors
    assert main(["--cache", str(cache), "--data", str(data), "status"]) == 0
    assert "202504" in capsys.readouterr().out
