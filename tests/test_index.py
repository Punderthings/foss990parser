from foss990parser import index
from tests.conftest import FakeSession

HEADER = (
    "RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,TAXPAYER_NAME,"
    "RETURN_TYPE,DLN,OBJECT_ID,XML_BATCH_ID\n"
)


def ref(**kw) -> index.FilingRef:
    base = dict(
        ein="470825376",
        tax_period="202504",
        return_type="990",
        object_id="1",
        return_id="1",
        taxpayer_name="ASF",
        sub_date="2026",
        proc_year=2026,
    )
    base.update(kw)
    return index.FilingRef(**base)


def test_read_index_handles_bom_and_padding(tmp_path):
    path = tmp_path / "index_2026.csv"
    path.write_text(
        "﻿" + HEADER + "1,EFILE,47825376,202504,2026,ASF,990,9,2026001,"
        "2026_TEOS_XML_03A\n",
        encoding="utf-8",
    )
    (row,) = index.read_index(path, 2026)
    assert row.ein == "047825376"
    assert row.batch_id == "2026_TEOS_XML_03A"
    assert row.proc_year == 2026


def test_select_filters_and_dedups():
    refs = [
        ref(object_id="100", proc_year=2025),
        ref(object_id="200", proc_year=2026),  # newer wins
        ref(return_type="990T", object_id="300"),  # type filtered
        ref(ein="999999999", object_id="400"),  # not our EIN
        ref(tax_period="202404", object_id="050"),
    ]
    selected = index.select(refs, {"470825376"}, ["990", "990EZ"])
    assert [r.object_id for r in selected] == ["050", "200"]


def test_csv_round_trip(tmp_path):
    refs = [ref(batch_id="2024_TEOS_XML_04a")]
    path = tmp_path / "filings.csv"
    index.write_csv(refs, path)
    assert index.read_csv(path) == refs


def test_download_index_caches(settings):
    session = FakeSession({index.index_url(2026): HEADER.encode()})
    path = index.download_index(2026, settings, session)
    assert path is not None and path.read_text() == HEADER
    index.download_index(2026, settings, session)
    assert len(session.calls) == 1


def test_download_index_missing_year(settings):
    assert index.download_index(2018, settings, FakeSession({})) is None
