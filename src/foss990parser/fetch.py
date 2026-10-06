"""Fetch e-filed 990 XML returns into the local cache.

Sources are tried in order:

1. GivingTuesday 990 Data Lake: one small XML file per return (fastest).
2. IRS Form 990 Series Downloads: the single member is read out of the
   monthly zip with HTTP Range requests, so the zip is never downloaded.
   The index's ``XML_BATCH_ID`` names the zip, but large months are split
   (``05A``, ``05B``...) and the index does not always name the right part,
   so sibling parts of the same month are tried next.
3. As a last resort, every zip listed on the IRS downloads page for the
   processing year is searched (each zip's directory is read only once).
"""

from __future__ import annotations

import io
import json
import logging
import re
import struct
import time
import zipfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import requests

from foss990parser.config import (
    GT_LAKE_URL,
    IRS_DOWNLOADS_PAGE,
    IRS_XML_BASE,
    Settings,
)
from foss990parser.index import FilingRef
from foss990parser.net import RangeFile, get

log = logging.getLogger(__name__)

BOM = b"\xef\xbb\xbf"
MANIFEST = "manifest.json"


@dataclass
class FetchResult:
    """Outcome of fetching one return."""

    object_id: str
    source: str
    path: Path | None


def looks_like_xml(data: bytes) -> bool:
    """Return True if ``data`` starts like an XML document (BOM allowed)."""
    return data.lstrip(BOM + b" \t\r\n").startswith(b"<")


def xml_path(settings: Settings, object_id: str) -> Path:
    """Return the cache path for one return's XML."""
    return settings.xml_dir / f"{object_id}_public.xml"


SPLIT_PARTS = "ABCDEF"
"""Part letters tried for a split month (e.g. ``2026_TEOS_XML_05B``)."""

_BATCH = re.compile(r"^(?P<month>\d{4}_TEOS_XML_\d{2})(?P<part>[A-Za-z])$")


def zip_urls(ref: FilingRef) -> list[str]:
    """Return candidate IRS zip URLs for ``ref``, most likely first.

    The named batch comes first (in its own, upper and lower case), then
    the other parts of the same month, since the IRS splits large months
    into several zips.
    """
    if not ref.batch_id:
        return []
    names = [ref.batch_id, ref.batch_id.upper(), ref.batch_id.lower()]
    match = _BATCH.match(ref.batch_id)
    if match:
        names += [match["month"] + part for part in SPLIT_PARTS]
        names += [match["month"] + part.lower() for part in SPLIT_PARTS]
    base = f"{IRS_XML_BASE}/{ref.proc_year}"
    return [f"{base}/{name}.zip" for name in dict.fromkeys(names)]


DEFLATE64 = 9
"""Zip compression method 9 ("Enhanced Deflate"), which the standard
library cannot read. Some IRS zips (e.g. ``2026_TEOS_XML_05B``) use it."""

_LOCAL_HEADER = struct.Struct("<4s5H3L2H")


def read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Return the uncompressed bytes of one zip member.

    Standard methods are read with :mod:`zipfile`. Deflate64 members are
    read raw from the archive and decompressed with the optional
    ``inflate64`` package (LGPL; install the ``deflate64`` extra); the
    CRC-32 is then checked.
    """
    if info.compress_type != DEFLATE64:
        return archive.read(info)
    try:
        import inflate64  # optional extra: foss990parser[deflate64]
    except ImportError as error:
        raise ImportError(
            "Deflate64 zip member; install the optional extra with "
            "'uv sync --extra deflate64' to read it"
        ) from error

    handle = archive.fp
    if handle is None:
        raise OSError("zip archive is closed")
    handle.seek(info.header_offset)
    header = _LOCAL_HEADER.unpack(handle.read(_LOCAL_HEADER.size))
    if header[0] != b"PK\x03\x04":
        raise zipfile.BadZipFile(f"Bad local header for {info.filename}")
    name_len, extra_len = header[-2], header[-1]
    handle.seek(info.header_offset + _LOCAL_HEADER.size + name_len + extra_len)
    raw = handle.read(info.compress_size)
    data: bytes = inflate64.Inflater().inflate(raw)
    if zlib.crc32(data) != info.CRC:
        raise zipfile.BadZipFile(f"CRC mismatch for {info.filename}")
    return data


def listed_zip_urls(page_html: str, year: int) -> list[str]:
    """Return the zip URLs for ``year`` linked from the IRS downloads page."""
    pattern = re.escape(f"{IRS_XML_BASE}/{year}/") + r"[\w.-]+\.zip"
    return list(dict.fromkeys(re.findall(pattern, page_html)))


class Fetcher:
    """Fetch and cache XML returns, remembering where each came from."""

    def __init__(self, settings: Settings, session: requests.Session):
        """Load the fetch manifest from the cache directory."""
        self.settings = settings
        self.session = session
        self.manifest_path = settings.xml_dir / MANIFEST
        self.manifest: dict[str, str] = {}
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text())
        self._zips: dict[str, zipfile.ZipFile | None] = {}
        self._listed: dict[int, list[str]] = {}

    def save_manifest(self) -> None:
        """Persist which source each cached return came from."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True)
        )

    def fetch(self, ref: FilingRef) -> FetchResult:
        """Return the cached XML for ``ref``, downloading it if needed."""
        path = xml_path(self.settings, ref.object_id)
        if path.exists():
            source = self.manifest.get(ref.object_id, "cache")
            return FetchResult(ref.object_id, source, path)
        for source, method in (
            ("gt-lake", self._from_gt_lake),
            ("irs-zip", self._from_irs_zip),
            ("irs-zip", self._from_irs_year_scan),
        ):
            try:
                data = method(ref)
            except (
                OSError,
                zipfile.BadZipFile,
                KeyError,
                NotImplementedError,
            ) as error:
                log.warning(
                    "%s failed for %s: %s", source, ref.object_id, error
                )
                data = None
            if data is not None and looks_like_xml(data):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                self.manifest[ref.object_id] = source
                return FetchResult(ref.object_id, source, path)
        log.error("Could not fetch %s (%s)", ref.object_id, ref.taxpayer_name)
        return FetchResult(ref.object_id, "missing", None)

    def fetch_all(self, refs: Iterable[FilingRef]) -> list[FetchResult]:
        """Fetch every return in ``refs``; save the manifest at the end."""
        results = []
        try:
            for ref in refs:
                cached = xml_path(self.settings, ref.object_id).exists()
                results.append(self.fetch(ref))
                if not cached:
                    time.sleep(self.settings.delay)
        finally:
            self.save_manifest()
        return results

    def _from_gt_lake(self, ref: FilingRef) -> bytes | None:
        """Download one XML from the GivingTuesday data lake."""
        url = GT_LAKE_URL.format(object_id=ref.object_id)
        response = get(self.session, url, self.settings)
        return response.content if response.status_code == 200 else None

    def _from_irs_zip(self, ref: FilingRef) -> bytes | None:
        """Read one member out of the named (or sibling) monthly zip."""
        return self._search_zips(ref, zip_urls(ref))

    def _from_irs_year_scan(self, ref: FilingRef) -> bytes | None:
        """Search every zip listed for the processing year (last resort)."""
        tried = set(zip_urls(ref))
        urls = [u for u in self._year_zips(ref.proc_year) if u not in tried]
        return self._search_zips(ref, urls)

    def _search_zips(self, ref: FilingRef, urls: list[str]) -> bytes | None:
        """Return the return's XML from the first zip containing it."""
        member = f"{ref.object_id}_public.xml"
        for url in urls:
            archive = self._open_zip(url)
            if archive is None:
                continue
            for info in archive.infolist():
                if info.filename.rsplit("/", 1)[-1] != member:
                    continue
                log.info("Found %s in %s", ref.object_id, url)
                try:
                    return read_member(archive, info)
                except (NotImplementedError, ImportError) as error:
                    log.error(
                        "Cannot decompress %s from %s (method %s): %s",
                        member,
                        url,
                        info.compress_type,
                        error,
                    )
        return None

    def _year_zips(self, year: int) -> list[str]:
        """Return (and memoize) zip URLs listed on the IRS page for year."""
        if year not in self._listed:
            response = get(self.session, IRS_DOWNLOADS_PAGE, self.settings)
            page = response.text if response.status_code == 200 else ""
            self._listed[year] = listed_zip_urls(page, year)
        return self._listed[year]

    def _open_zip(self, url: str) -> zipfile.ZipFile | None:
        """Open (and memoize) a remote zip's central directory.

        Failures are memoized too, so a missing zip is probed only once.
        """
        if url not in self._zips:
            try:
                remote = RangeFile(self.session, url, self.settings)
                buffered = io.BufferedReader(remote, buffer_size=1 << 16)
                self._zips[url] = zipfile.ZipFile(buffered)
            except (OSError, KeyError, zipfile.BadZipFile) as error:
                log.debug("Cannot open %s: %s", url, error)
                self._zips[url] = None
        return self._zips[url]
