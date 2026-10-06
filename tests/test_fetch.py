import io
import zipfile

from foss990parser.config import GT_LAKE_URL
from foss990parser.fetch import Fetcher, looks_like_xml, zip_urls
from foss990parser.index import FilingRef
from foss990parser.net import RangeFile
from tests.conftest import FIXTURES, FakeSession

XML = (FIXTURES / "minimal_990ez.xml").read_bytes()


def ref(batch: str = "2026_TEOS_XML_01A") -> FilingRef:
    return FilingRef(
        ein="123456789",
        tax_period="202412",
        return_type="990EZ",
        object_id="2026000",
        return_id="1",
        taxpayer_name="EX",
        sub_date="2026",
        proc_year=2026,
        batch_id=batch,
    )


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_looks_like_xml():
    assert looks_like_xml(b"\xef\xbb\xbf<Return/>")
    assert not looks_like_xml(b"Not Found")


def test_zip_urls_cover_case_variants():
    urls = zip_urls(ref("2024_TEOS_XML_04a"))
    assert urls[0].endswith("/2026/2024_TEOS_XML_04a.zip")
    assert any(u.endswith("2024_TEOS_XML_04A.zip") for u in urls)
    assert zip_urls(ref("")) == []


def test_fetch_from_gt_lake_then_cache(settings):
    url = GT_LAKE_URL.format(object_id="2026000")
    session = FakeSession({url: b"\xef\xbb\xbf" + XML})
    fetcher = Fetcher(settings, session)
    result = fetcher.fetch_all([ref()])[0]
    assert result.source == "gt-lake" and result.path is not None
    again = Fetcher(settings, session).fetch(ref())
    assert again.source == "gt-lake"
    assert len(session.calls) == 1


def test_fallback_to_irs_zip_with_range(settings):
    archive = make_zip(
        {"other_public.xml": b"<x/>", "2026000_public.xml": XML}
    )
    session = FakeSession({zip_urls(ref())[0]: archive})
    result = Fetcher(settings, session).fetch(ref())
    assert result.source == "irs-zip"
    assert result.path is not None and result.path.read_bytes() == XML


def test_missing_everywhere(settings):
    result = Fetcher(settings, FakeSession({})).fetch(ref())
    assert result.source == "missing" and result.path is None


def test_range_file_reads_slices(settings):
    data = bytes(range(256)) * 10
    rf = RangeFile(FakeSession({"u": data}), "u", settings)
    assert rf.size == len(data)
    rf.seek(-4, io.SEEK_END)
    assert rf.read(10) == data[-4:]


def irs_zip(name: str, year: int = 2026) -> str:
    return f"https://apps.irs.gov/pub/epostcard/990/xml/{year}/{name}.zip"


def test_zip_urls_include_split_month_parts():
    urls = zip_urls(ref("2026_TEOS_XML_05A"))
    assert urls[0] == irs_zip("2026_TEOS_XML_05A")
    assert irs_zip("2026_TEOS_XML_05B") in urls
    assert irs_zip("2026_TEOS_XML_05c") in urls
    assert len(urls) == len(set(urls))


def test_found_in_sibling_part_of_split_month(settings):
    archive = make_zip({"2026000_public.xml": XML})
    session = FakeSession({irs_zip("2026_TEOS_XML_05B"): archive})
    result = Fetcher(settings, session).fetch(ref("2026_TEOS_XML_05A"))
    assert result.source == "irs-zip"
    assert result.path is not None and result.path.read_bytes() == XML


def test_year_scan_from_downloads_page(settings):
    from foss990parser.config import IRS_DOWNLOADS_PAGE

    page = (
        f'<a href="{irs_zip("2026_TEOS_XML_01A")}">Jan</a>'
        f'<a href="{irs_zip("2026_TEOS_XML_07A")}">Jul</a>'
        f'<a href="{irs_zip("2025_TEOS_XML_07A", 2025)}">old</a>'
    )
    archive = make_zip({"2026000_public.xml": XML})
    session = FakeSession(
        {
            IRS_DOWNLOADS_PAGE: page.encode(),
            irs_zip("2026_TEOS_XML_07A"): archive,
        }
    )
    fetcher = Fetcher(settings, session)
    result = fetcher.fetch(ref("2026_TEOS_XML_05A"))
    assert result.source == "irs-zip"
    assert fetcher._year_zips(2026) == [
        irs_zip("2026_TEOS_XML_01A"),
        irs_zip("2026_TEOS_XML_07A"),
    ]


def test_missing_zips_probed_once(settings):
    session = FakeSession({})
    fetcher = Fetcher(settings, session)
    fetcher.fetch(ref())
    calls = len(session.calls)
    other = FilingRef(**{**ref().__dict__, "object_id": "2026001"})
    fetcher.fetch(other)
    zip_calls = [c for c in session.calls[calls:] if c.endswith(".zip")]
    assert zip_calls == []


def as_deflate64(archive: bytes) -> bytes:
    """Relabel ZIP_DEFLATED members as method 9 (Deflate64).

    A plain deflate stream is also a valid Deflate64 stream for small
    inputs, so this exercises the raw-read path with a fake inflater.
    """
    data = bytearray(archive)
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        start = 0
        while (start := data.find(signature, start)) != -1:
            data[start + offset : start + offset + 2] = (9).to_bytes(
                2, "little"
            )
            start += 4
    return bytes(data)


class FakeInflater:
    def inflate(self, raw: bytes) -> bytes:
        import zlib

        return zlib.decompressobj(-15).decompress(raw)


def test_deflate64_member_is_decompressed(settings, monkeypatch):
    import sys
    import types

    fake = types.ModuleType("inflate64")
    fake.Inflater = FakeInflater
    monkeypatch.setitem(sys.modules, "inflate64", fake)
    archive = as_deflate64(
        make_zip({"other_public.xml": b"<x/>", "2026000_public.xml": XML})
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as check:
        assert check.getinfo("2026000_public.xml").compress_type == 9
    session = FakeSession({irs_zip("2026_TEOS_XML_05B"): archive})
    result = Fetcher(settings, session).fetch(ref("2026_TEOS_XML_05A"))
    assert result.source == "irs-zip"
    assert result.path is not None and result.path.read_bytes() == XML


def test_missing_optional_extra_is_reported(settings, monkeypatch, caplog):
    import sys

    monkeypatch.setitem(sys.modules, "inflate64", None)  # extra not installed
    archive = as_deflate64(make_zip({"2026000_public.xml": XML}))
    session = FakeSession({irs_zip("2026_TEOS_XML_05B"): archive})
    result = Fetcher(settings, session).fetch(ref("2026_TEOS_XML_05A"))
    assert result.source == "missing"
    assert "uv sync --extra deflate64" in caplog.text
