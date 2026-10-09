# FOSS990Parser

Extract IRS Form 990 e-file data for the US nonprofit FOSS foundations listed in
[fossfoundation.info](https://fossfoundation.info/), including recent tax years
(2024–2025) that ProPublica has not yet parsed.

It reads the IRS's own e-file XML, which is published monthly, instead of
waiting for third-party extracts.

## How it works

1. **eins**: collect US EINs from a local
   [fossfoundation](https://github.com/Punderthings/fossfoundation) checkout
   (`_foundations/*.md` `taxID`, plus `_data/p990/*.json`).
2. **index**: download the IRS yearly e-file indexes (`index_YYYY.csv`, about
   1M rows each, cached) and keep our EINs' 990/990-EZ/990-PF filings. For
   duplicates, the most recently processed filing wins.
3. **fetch**: download each return's XML from the
   [GivingTuesday 990 Data Lake](https://990data.givingtuesday.org/). If that
   fails, it reads the single member out of the IRS monthly zip using HTTP
   Range requests, so the 100–500 MB zip is never downloaded. Split months
   (`05A`/`05B`) and, finally, every zip for that year are searched if needed.
4. **parse**: write `<EIN>.json` (all filings, newest first) and
   `irs990_core.csv`.

## Quick start

```sh
uv sync --extra deflate64                  # create .venv (see note below)
uv run foss990 run --repo ../fossfoundation
uv run foss990 status                      # coverage per foundation
```

The `deflate64` extra adds the LGPL-licensed `inflate64` library, needed only
for the few IRS zips that use Deflate64 compression. Plain `uv sync` works too;
those returns are then reported as missing, with an install hint.

Commands can also be run one at a time (`eins`, `index`, `fetch`, `parse`,
`publish`, `status`); see `uv run foss990 --help`. Useful options:

- `--years 2024 2025 2026`: limit which IRS **processing** years are indexed.
- `--ein 470825376`: fetch or parse a single organization.
- `--out ../fossfoundation/_data/irs990`: write JSON somewhere else.
- `--delay 0.5`: seconds between network requests.

Downloads are cached under `cache/` (git-ignored). Outputs go to `data/`.

## Output

Each filing in `data/irs990/<EIN>.json` contains:

| Key | Meaning |
|---|---|
| `tax_period` | `YYYYMM` of the fiscal year end (from the IRS index); **use this as the key** |
| `tax_year` | IRS `TaxYr`, the year the fiscal year *begins* (ASF FY May 2024–Apr 2025 = 2024; ProPublica would say 2025) |
| `period_begin`, `period_end` | Exact fiscal year dates |
| `return_type`, `return_version`, `amended` | Form, IRS schema version, amended flag |
| `object_id`, `proc_year`, `source` | Provenance: IRS object id, processing year, `gt-lake` / `irs-zip` / `cache` |
| `core` | ProPublica-compatible totals (`totrevenue`, `totfuncexpns`, `totcntrbgfts`, `totprgmrevnue`, `invstmntinc`, `totassetsend`, `totliabend`, `totnetassetend`) |
| `fields` | Part I headcounts, Part VI board, Part VII-B contractor count, Part VIII contribution lines |
| `functional_expenses` | Part IX lines, each with `total` / `program` / `management` / `fundraising` |
| `balance_sheet` | Part X lines, each with `boy` / `eoy` |
| `program_service_revenue`, `other_expenses` | Part VIII line 2 and Part IX line 24 repeating rows |
| `officers` | Part VII Section A: officers, directors, trustees, key and highest-compensated employees (`title`, `hours_per_week`, role checkboxes, `comp_from_org`, `comp_from_related`, `other_comp`, `name_type`). Part VII totals (`officers_comp_from_org`, `individuals_over_100k`, ...) are in `fields`. **JSON only; no CSV is written** |
| `contractors` | Part VII-B: five highest-paid independent contractors over $100K (`name`, `services`, `compensation`, `city`/`state`/`country`, `name_type`) |
| `has_schedule_i`, `grants_to_orgs`, `grants_to_individuals` | Schedule I grants: Part II recipients (name, EIN, IRC section, cash/non-cash, purpose) and Part III grants to individuals (type, count, amounts). Counts of 501(c)(3)/other recipients are in `fields` |
| `has_schedule_r`, `related_disregarded`, `related_tax_exempt`, `related_partnerships`, `related_corporations` | Schedule R Parts I–IV related organizations (name, EIN, activity, legal domicile, controlling entity, plus part-specific columns) |
| `related_transactions` | Schedule R Part V line 2: transactions with related organizations (`transaction_type` is the Part V line 1 letter code a–s) |

A value of `null` means the line was **not reported** on the return; it is not
the same as 0. Tables are empty lists when the schedule wasn't filed (check the
`has_schedule_*` flags).

The `parse` command also writes one cross-organization CSV per table to
`data/irs990/tables/` (`contractors.csv`, `grants_to_orgs.csv`,
`related_corporations.csv` and so on), each row prefixed with the filer's EIN,
name and tax period. Table columns that repeat a filer column get the table
name as a prefix (e.g. `grants_to_orgs_ein` is the recipient's EIN).

## Publishing to fossfoundation.info

```sh
uv run foss990 publish --repo ../fossfoundation
```

`publish` parses the cached returns again and writes the public dataset:

| Path in the fossfoundation repo | Contents |
|---|---|
| `data/irs990/core.csv` | One row per filing with the core totals |
| `data/irs990/orgs/<EIN>.json` | Every filing of one organization (as above) |
| `data/irs990/tables/*.csv` | The cross-organization tables |
| `data/irs990/links.csv` | One row per link between organizations: Schedule I grants (`grant`), Schedule R related organizations and transactions. Transactions get the other organization's EIN when its name matches one of the filer's Schedule R related organizations. `*_identifier` is the fossfoundation.info id |
| `data/irs990/filings.csv`, `organizations.csv` | The selected filings and the organizations searched for |
| `data/irs990/datapackage.json` | [Frictionless Data](https://frictionlessdata.io/) description of every CSV and column type |
| `_data/irs990/core.csv` | Copy of `core.csv` for Jekyll pages (`site.data.irs990.core`) |

Names of individuals are always withheld by `publish`, and it stops with an
error if one would be written. A hand-written `data/irs990/README.md` is left
alone, and JSON files of organizations that no longer have filings are
removed.

**Privacy:** addresses are reduced to city, state/province and country, so
street lines are never stored. Rows naming individuals (officers and
contractors paid as persons) are kept with `name_type: "person"`, but the name
is withheld unless you pass `--include-person-names`. Officer pay is written
only to the per-EIN JSON, never to a cross-organization CSV. Form 990-PF returns are listed with header data only
(`parsed: false`). The field map lives in `src/foss990parser/fields.py`.

## Development

```sh
uv sync                        # installs dev tools too
uv run ruff check .            # PEP 8 lint (pycodestyle, pyflakes, naming, docstrings)
uv run ruff format --check .   # formatting
uv run mypy src                # static types (strict)
uv run pytest                  # tests (offline; no network needed)
```

Code follows PEP 8 (79-column lines) and PEP 257 docstrings, enforced by Ruff.
Tests use real public 990 XML fixtures (ASF, SFC, AlmaLinux) plus synthetic
files, and fake HTTP sessions, so they never touch the network.

## Data sources and licenses

- IRS Form 990 Series Downloads (public domain US government data).
- GivingTuesday 990 Data Lake (see their Data Use License).
- Field names were checked against the Nonprofit Open Data Collective
  [Master Concordance File](https://github.com/Nonprofit-Open-Data-Collective/irs-efile-master-concordance-file)
  (ODC-By 1.0).

See [DEPENDENCIES.md](DEPENDENCIES.md) for the Python libraries used and
[docs/MAINTAINING.md](docs/MAINTAINING.md) for design notes, data quirks and
maintenance procedures.
Licensed under the Apache License 2.0.
See [Propublica990](https://github.com/Punderthings/propublica990) for a similar but less functional library written in ruby.
