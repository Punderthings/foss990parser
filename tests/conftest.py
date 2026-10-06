from pathlib import Path

import pytest

from foss990parser.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        delay=0.0,
        retries=1,
    )


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(
        self,
        status_code: int,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def iter_content(self, chunk_size: int = 1):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]


class FakeSession:
    """Serve URLs from a dict; supports single HTTP Range requests."""

    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url, headers=None, stream=False, timeout=None):
        self.calls.append(url)
        if url not in self.routes:
            return FakeResponse(404)
        data = self.routes[url]
        if headers and "Range" in headers:
            start, end = headers["Range"][6:].split("-")
            first, last = int(start), min(int(end), len(data) - 1)
            return FakeResponse(
                206,
                data[first : last + 1],
                {"Content-Range": f"bytes {first}-{last}/{len(data)}"},
            )
        return FakeResponse(200, data)
