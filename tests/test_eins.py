import json
from pathlib import Path

from foss990parser import eins


def make_repo(root: Path) -> Path:
    fdn = root / "_foundations"
    fdn.mkdir(parents=True)
    (fdn / "asf.md").write_text(
        "---\nidentifier: asf\ncommonName: Apache\ntaxID: 47-0825376\n"
        "addressCountry: US\nnonprofitStatus: Nonprofit501c3\n---\nText\n"
    )
    (fdn / "eclipse.md").write_text(
        "---\nidentifier: eclipse\ncommonName: Eclipse\ntaxID: '123456789'\n"
        "addressCountry: BE\n---\n"
    )
    (fdn / "notax.md").write_text("---\nidentifier: notax\n---\n")
    p990 = root / "_data" / "p990"
    p990.mkdir(parents=True)
    (p990 / "470825376.json").write_text(
        json.dumps({"organization": {"ein": 470825376, "name": "Apache"}})
    )
    (p990 / "42888848.json").write_text(
        json.dumps(
            {
                "organization": {
                    "ein": 42888848,
                    "name": "FSF",
                    "subsection_code": 3,
                }
            }
        )
    )
    return root


def test_collect_merges_sources_and_skips_non_us(tmp_path):
    orgs = {o.ein: o for o in eins.collect(make_repo(tmp_path))}
    assert set(orgs) == {"470825376", "042888848"}
    assert orgs["470825376"].in_foundations and orgs["470825376"].in_p990
    assert orgs["042888848"].nonprofit_status == "501c3"


def test_csv_round_trip(tmp_path):
    orgs = eins.collect(make_repo(tmp_path))
    path = tmp_path / "out" / "eins.csv"
    eins.write_csv(orgs, path)
    assert eins.read_csv(path)["470825376"] == orgs[1]


def test_normalize_ein():
    assert eins.normalize_ein("47-0825376") == "470825376"
    assert eins.normalize_ein(42888848) == "042888848"
    assert eins.normalize_ein("") is None
