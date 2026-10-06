# Dependencies

All dependencies are open source and managed with
[uv](https://docs.astral.sh/uv/) (`pyproject.toml` plus the `uv.lock` lockfile).

## Runtime

| Package | License | Why it is used |
|---|---|---|
| [requests](https://requests.readthedocs.io/) | Apache-2.0 | HTTP client for the IRS index/zip downloads and the GivingTuesday data lake, including HTTP Range requests |
| [lxml](https://lxml.de/) | BSD-3-Clause | Fast, safe XML parsing of 990 returns (entity expansion and network access disabled) |
| [PyYAML](https://pyyaml.org/) | MIT | Reads the YAML front matter of `fossfoundation/_foundations/*.md` |

## Optional extra: `deflate64`

| Package | License | Why it is used |
|---|---|---|
| [inflate64](https://github.com/miurahr/inflate64) | LGPL-2.1-or-later | Decompresses "Deflate64" (zip method 9) members, which Python's `zipfile` cannot read. A few IRS monthly zips use it (e.g. `2026_TEOS_XML_05B`; 2 of 398 returns in the first full run) |

Install with `uv sync --extra deflate64` (or
`pip install "foss990parser[deflate64]"`). Without it, everything else works.
Returns that need Deflate64 are logged with an install hint and recorded as
`missing`. The extra keeps the default install free of LGPL code; under the
[ASF third-party license policy](https://www.apache.org/legal/resolved.html#optional), LGPL (Category X) is acceptable only for
optional features. `inflate64` is used unmodified, as a separately installed
library, and is not redistributed by this project. The `dev` group includes it
so the test suite covers the Deflate64 path.

The standard library covers everything else: `zipfile` (remote zip members),
`csv`, `json`, `argparse` and `logging`.

## Development (`[dependency-groups] dev`)

| Package | License | Why it is used |
|---|---|---|
| [Ruff](https://docs.astral.sh/ruff/) | MIT | PEP 8 linter (pycodestyle E/W, pyflakes F, pep8-naming N, pydocstyle D, isort I) and formatter |
| [mypy](https://mypy-lang.org/) | MIT | Static type checking in strict mode |
| [pytest](https://pytest.org/) | MIT | Test runner |
| [lxml-stubs](https://github.com/lxml/lxml-stubs) | Apache-2.0 | Type hints for lxml (for mypy) |
| [types-requests](https://pypi.org/project/types-requests/) | Apache-2.0 | Type hints for requests (typeshed) |
| [types-PyYAML](https://pypi.org/project/types-PyYAML/) | Apache-2.0 | Type hints for PyYAML (typeshed) |

## Build

| Package | License | Why it is used |
|---|---|---|
| [hatchling](https://hatch.pypa.io/) | MIT | PEP 517 build backend so `uv` can install the `foss990` command |
