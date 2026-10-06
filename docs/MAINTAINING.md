# Maintaining FOSS990Parser

Notes for maintainers on how FOSS990Parser works and why it is built this way.
Written by Claude Pro Max October 2026, after the first full data run (v0.1.0) 
and reviewed/tweaked by Shane Curcuru.

## 1. Purpose

[fossfoundation.info](https://fossfoundation.info/) tracks US 990 tax data
for FOSS foundations through ProPublica's Nonprofit Explorer API. ProPublica
only parses filings a year or more after the IRS publishes them, so recent tax
years (2024–2025) show up only as `filings_without_data` with PDF links.
ProPublica also exposes only about 70 summary fields.

FOSS990Parser reads the IRS's own **e-file XML** directly. That gives:

- recent years as soon as the IRS publishes them (monthly);
- the detail needed for research on how foundations fund themselves and spend
  their money: revenue breakdown, functional expenses, balance sheet, board,
  officer pay, contractors, grants (Schedule I) and related organizations
  (Schedule R).

## 2. How it was built (decision log)

| Step | Outcome |
|---|---|
| Tool survey | IRSx (Python) is stale (last release 2019, built for the retired AWS bucket). NODC `ef2` is current but written in R. NCCS parsed tables stop at 2022. **Decision:** a small new Python tool, using the NODC Master Concordance File as the field-name reference. Intent is to create a simple Apache-2.0 tool in python for ease of maintenance/integration. |
| Phase 1 spikes (`fossfoundation-research/fdn990_spikes`) | **S1:** the IRS indexes have `XML_BATCH_ID`, and 65 of 71 EINs were found. **S2:** `apps.irs.gov` supports HTTP Range, so a single return costs about 66 KB instead of a 100–500 MB zip. **S3:** the GivingTuesday data lake serves one file per return, including returns processed in 2026. **S4:** returns use schema versions newer than the concordance (2023v6.0–2025v4.0), but the element names we need are unchanged. All four were go. |
| Phase 2/3 (v0.1.0) | Index, fetch and parse of the priority (P1) fields; ProPublica-compatible core totals. |
| Tables | Contractors (VII-B), Schedule I, Schedule R, plus officer pay (VII-A, JSON only). |
| Fetch fix | Sibling parts of split months plus a full scan of the processing year, after 2 returns weren't found in their indexed zip. The sibling `05B` zip turned out to use Deflate64, so `inflate64` was added. |

## 3. Architecture

```
_foundations/*.md + _data/p990/*.json        (fossfoundation checkout)
        │  eins.py
        ▼
data/eins.csv ──► index.py ──► data/filings.csv
                  (IRS index_YYYY.csv, cached in cache/index/)
        │  fetch.py   GT lake → IRS zip (Range) → split-month parts → year scan
        ▼
cache/xml/<OBJECT_ID>_public.xml  (+ manifest.json: source per object)
        │  parse.py + fields.py
        ▼
export.py ──► data/irs990/<EIN>.json, irs990_core.csv, tables/*.csv
```

| Module | Responsibility |
|---|---|
| `config.py` | URLs, defaults, `Settings` (cache/data dirs, delay, retries) |
| `net.py` | requests session with User-Agent; `get()` with retries/backoff; `RangeFile` (seekable HTTP Range file for `zipfile`) |
| `eins.py` | Collect US EINs (non-US 9-digit IDs are skipped) |
| `index.py` | Download indexes; `select()` filters return types and keeps the most recently processed duplicate |
| `fetch.py` | Source fallback chain; caches XML and memoizes zip directories (including failures) |
| `fields.py` | **The field map**: `CORE`, `SCALARS`, `SCHEDULE_SCALARS`, `FUNCTIONAL_EXPENSES`, `BALANCE_SHEET`, `TABLES` |
| `parse.py` | Safe lxml parsing (no entity expansion or network access); namespace-agnostic local-name paths; type conversion |
| `export.py` | Per-EIN JSON, core CSV, cross-organization table CSVs |
| `cli.py` | `eins`, `index`, `fetch`, `parse`, `status`, `run` |

## 4. Data quirks to know

- **Cache data** Tools operate on a local cache, and should only be
  submitted as a PR to fossfoundation.info when needed/verified. 
- **Tax period vs. tax year.** Key on `tax_period` (`YYYYMM` of the fiscal year
  end). IRS `TaxYr` is the year the fiscal year *begins*; ProPublica's
  `tax_prd_yr` differs for non-calendar years (ASF, FSF, GNOME, SFC,
  Wikimedia...).
- **IRS folder year = processing year**, not tax year. A TY2025 return usually
  appears in the 2026 zips, often late in the year.
- **Duplicates and amendments.** The index lists some returns twice.
  `select()` keeps the most recently processed filing, so amended returns
  replace originals. This is the cause of every mismatch with ProPublica.
- **`SUB_DATE`** in recent indexes is only a year; recency is decided by
  processing year, then object id.
- **`XML_BATCH_ID`** case varies (`04a`), and big months are split (`05A`,
  `05B`), so `fetch.zip_urls()` tries case variants and sibling parts.
- **Deflate64 zips.** Some IRS zips (seen: `2026_TEOS_XML_05B`) use zip
  compression method 9, which Python's `zipfile` cannot read.
  `fetch.read_member()` reads those members raw and decompresses them with
  `inflate64`, checking the CRC. `inflate64` is LGPL, so it is an **optional
  extra** (`deflate64`) and is imported lazily; without it those returns are
  logged with an install hint and left `missing`.
- **UTF-8 BOM** at the start of IRS XML files; it is stripped before parsing.
- **Absent element means "not reported"**, stored as `null`, never 0. The
  exception is Part VII-A role checkboxes, where absent means False
  (`Table.checkboxes`).
- **Schedule R Part II** stores the organization's name in
  `DisregardedEntityName` (an IRS schema quirk). `fields.py` handles it.
- **Self-reported values** may look odd (e.g. a board of 371 "voting members"
  for AlmaLinux). They are kept exactly as filed.

## 5. Adding or changing fields

1. Find the element name in the NODC concordance (`xpath` column) and confirm
   it in a recent cached XML (`grep -o '<Name>' cache/xml/*.xml`).
2. Add it to the right structure in `fields.py`:
   - a single value goes in `SCALARS` (relative to the form) or
     `SCHEDULE_SCALARS` (relative to `ReturnData`);
   - a 4-column Part IX line goes in `FUNCTIONAL_EXPENSES`;
   - a beginning/end-of-year line goes in `BALANCE_SHEET`;
   - a repeating group becomes a `Table`, listing candidate paths per column
     (first one found wins).
3. Types come from the element-name suffix: `Amt`/`Cnt` become int, `Pct`/`Rt`
   become float, `Ind` becomes bool; everything else is text.
4. Add a test using a real fixture in `tests/fixtures/`. Add the table to
   `export.TABLE_CSVS` only if it should get a cross-organization CSV.

## 6. Licensing rules (keep these)

- Runtime dependencies must be permissively licensed (Apache, BSD, MIT).
- Copyleft libraries may be used only as optional extras that most users
  don't need, imported lazily, used unmodified and never vendored or bundled.
  This matches the ASF 3rd Party License Policy's treatment of Category X
  components.
- If you ever ship a bundled build (wheel with vendored code, PyInstaller,
  container image) that includes `inflate64`, include its LGPL text and
  source, and keep it replaceable.

## 7. Privacy rules (keep these)

- Addresses are reduced to city, state/province and country; street lines are
  never stored.
- Rows naming individuals (officers, contractors paid as persons) keep
  `name_type: "person"`, but the name is withheld unless
  `--include-person-names` is passed.
- Officer pay is in the per-EIN JSON only, never in a CSV.

## 8. Validation (first full run, Oct 2026)

- 398 filings selected for 65 of 71 EINs, all 398 fetched (GT lake 385, IRS
  zip 8, spike cache 5). The last 2 (Django Events TP 202512, OEGlobal TP
  202506) were indexed under `2026_TEOS_XML_05A` but found in the Deflate64
  `05B` zip. Parsed: 344 Form 990, 46 Form 990-EZ, plus 6 Form 990-PF
  (header only).
- 94 filings are new compared with ProPublica (TY2024 ×59, TY2025 ×24, ...).
- Against ProPublica on 296 overlapping filings, revenue, expenses, net
  assets and contributions match exactly for 289–291 of them. Every real
  difference is an amended return (FSF, Open Collective Foundation, Processing
  Foundation), plus a $1 rounding difference for Wikimedia.
- Officer rows add up exactly to the Part VII line 1d total on every filing
  (3,767 rows).
- The 6 EINs not in any 2019–2026 index (Haiku, Participatory Culture,
  Identity Commons, F# SF, Xiph, XMPP SF) are likely 990-N or inactive filers.

## 9. Routine operation

```sh
uv run foss990 run --repo ../fossfoundation   # monthly is enough
uv run foss990 status                          # coverage per foundation
uv run foss990 parse --out ../fossfoundation/_data/irs990   # publish
```

Re-runs only download new filings. Use `index --refresh` to pick up updated
IRS index files for the current year. Be polite: keep `--delay` at 0.5 s or
more and keep the User-Agent identifying the project.

Before a release:

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

Tests are fully offline (fake HTTP sessions and real XML fixtures).

## 10. Known limitations and roadmap

- Form 990-PF is not parsed (affects the Linux Kernel Organization).
- No Schedule A (public support test), B (contributor amounts), C, D, F, G or
  O parsing yet. Schedule A Part II and Schedule D Part V are the next most
  useful.
- Returns that are in no IRS zip and not in the GT lake stay `missing` until
  they are published. Re-run `fetch` later.
- Non-US foundations need a different source (budget model / national
  registries).
- Possible automation: a monthly GitHub Action that runs `run` and opens a PR
  against `fossfoundation/_data/irs990`.

## 11. Data sources and licenses

- IRS Form 990 Series Downloads: US government public data.
- GivingTuesday 990 Data Lake: see their Data Use License.
- NODC Master Concordance File (field names): ODC-By 1.0, attribution
  required.
- Code: Apache-2.0. Dependencies are listed with licenses in
  `DEPENDENCIES.md`.
