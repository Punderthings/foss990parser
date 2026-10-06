"""Shared constants and runtime settings."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from foss990parser import __version__

IRS_XML_BASE = "https://apps.irs.gov/pub/epostcard/990/xml"
"""Base URL of the IRS Form 990 Series Downloads (index CSVs and zips)."""

IRS_DOWNLOADS_PAGE = (
    "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
)
"""IRS page listing every monthly zip; scanned as a last resort."""

GT_LAKE_URL = (
    "https://gt990datalake-rawdata.s3.amazonaws.com"
    "/EfileData/XmlFiles/{object_id}_public.xml"
)
"""GivingTuesday 990 Data Lake: one public XML file per e-filed return."""

FIRST_INDEX_YEAR = 2019
"""Earliest processing year published on the IRS downloads page."""

DEFAULT_RETURN_TYPES = ("990", "990EZ", "990PF")
"""Return types kept from the IRS index (990T etc. are dropped)."""

USER_AGENT = (
    f"FOSS990Parser/{__version__} "
    "(+https://github.com/Punderthings/fossfoundation)"
)


def default_years() -> list[int]:
    """Return every IRS processing year from 2019 through this year."""
    return list(range(FIRST_INDEX_YEAR, datetime.date.today().year + 1))


@dataclass
class Settings:
    """Runtime settings shared by all commands.

    Attributes:
        cache_dir: Where downloaded index CSVs and XML returns are kept.
        data_dir: Where derived files (EIN list, filings list) are written.
        delay: Seconds to wait between network requests (be polite).
        timeout: Per-request timeout in seconds.
        retries: Attempts per request before giving up.

    """

    cache_dir: Path = field(default_factory=lambda: Path("cache"))
    data_dir: Path = field(default_factory=lambda: Path("data"))
    delay: float = 0.5
    timeout: float = 60.0
    retries: int = 3

    @property
    def index_dir(self) -> Path:
        """Directory holding cached ``index_YYYY.csv`` files."""
        return self.cache_dir / "index"

    @property
    def xml_dir(self) -> Path:
        """Directory holding cached ``<OBJECT_ID>_public.xml`` files."""
        return self.cache_dir / "xml"

    @property
    def eins_csv(self) -> Path:
        """Path of the EIN list written by the ``eins`` command."""
        return self.data_dir / "eins.csv"

    @property
    def filings_csv(self) -> Path:
        """Path of the selected filings written by the ``index`` command."""
        return self.data_dir / "filings.csv"
