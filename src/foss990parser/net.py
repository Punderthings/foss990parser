"""HTTP helpers: a polite session, retries and an HTTP Range file."""

from __future__ import annotations

import io
import logging
import time

import requests

from foss990parser.config import USER_AGENT, Settings

log = logging.getLogger(__name__)


def make_session() -> requests.Session:
    """Create a requests session that identifies this tool."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def get(
    session: requests.Session,
    url: str,
    settings: Settings,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> requests.Response:
    """GET ``url`` with retries and exponential backoff.

    Server errors (5xx) and connection errors are retried; other HTTP
    status codes are returned to the caller unchanged.
    """
    last_error: Exception | None = None
    for attempt in range(settings.retries):
        try:
            response = session.get(
                url,
                headers=headers,
                stream=stream,
                timeout=settings.timeout,
            )
            if response.status_code < 500:
                return response
            last_error = requests.HTTPError(
                f"HTTP {response.status_code} for {url}"
            )
        except requests.RequestException as error:
            last_error = error
        wait = settings.delay * (2**attempt) + 1
        log.warning("Retrying %s in %.1fs (%s)", url, wait, last_error)
        time.sleep(wait)
    raise ConnectionError(f"Giving up on {url}: {last_error}")


class RangeFile(io.RawIOBase):
    """Read-only, seekable file backed by HTTP Range requests.

    ``zipfile.ZipFile`` can open this to list a remote archive and read
    single members without downloading the whole (multi-GB) zip.
    """

    def __init__(
        self,
        session: requests.Session,
        url: str,
        settings: Settings,
    ) -> None:
        """Probe ``url`` for its size and Range support."""
        super().__init__()
        self._session = session
        self._settings = settings
        self.url = url
        self.position = 0
        self.requests_made = 0
        self.bytes_read = 0
        probe = get(session, url, settings, headers={"Range": "bytes=0-0"})
        if probe.status_code != 206:
            raise OSError(
                f"Range requests not supported: HTTP {probe.status_code}"
            )
        self.size = int(probe.headers["Content-Range"].rsplit("/", 1)[1])

    def readable(self) -> bool:
        """Return True; this file can be read."""
        return True

    def seekable(self) -> bool:
        """Return True; this file supports random access."""
        return True

    def tell(self) -> int:
        """Return the current position."""
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move to ``offset`` relative to ``whence``."""
        base = {
            io.SEEK_SET: 0,
            io.SEEK_CUR: self.position,
            io.SEEK_END: self.size,
        }[whence]
        self.position = base + offset
        return self.position

    def readinto(self, buffer: memoryview | bytearray) -> int:  # type: ignore[override]
        """Fill ``buffer`` from the current position using one request."""
        if self.position >= self.size or len(buffer) == 0:
            return 0
        end = min(self.position + len(buffer), self.size) - 1
        response = get(
            self._session,
            self.url,
            self._settings,
            headers={"Range": f"bytes={self.position}-{end}"},
        )
        if response.status_code != 206:
            raise OSError(f"Range request failed: {response.status_code}")
        data = response.content
        buffer[: len(data)] = data
        self.position += len(data)
        self.requests_made += 1
        self.bytes_read += len(data)
        return len(data)
