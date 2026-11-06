# Alpha Vantage fields this project reads

Checked against the public demo key on 2026-11-06.

`TIME_SERIES_DAILY` (raw closes) is on the free plan. `outputsize=compact` is the latest ~100 sessions and is also on the free plan. `outputsize=full` and `TIME_SERIES_DAILY_ADJUSTED` are premium. The job starts on the free-plan endpoint and switches to raw daily closes if an adjusted request is rejected as premium.

## `POLITICIAN_METADATA`

One call returns the roster. Top-level key: `politicians`. Each person:

| Field | Use |
| --- | --- |
| `bioguide_id` | Primary key |
| `display_name` | Name on the board |
| `aliases` | Stored, not shown |
| `chamber` | `house` or `senate` |
| `state` | Two-letter state |
| `district` | House district, or null in the Senate |
| `party` | Code such as `D`, `R`, or `I`. A label only |
| `terms[]` | `chamber`, `state`, `district`, `start_date`, `end_date` |

The demo roster that day had 1,146 people, 537 of them seated (439 House, 98 Senate).

## `CONGRESS_TRADES`

Query with `bioguide_id` (or `symbol`). Top-level keys: `symbol`, `bioguide_id`, `trades`.

Each trade in the demo response:

| Field | Use |
| --- | --- |
| `chamber` | `HOUSE` or `SENATE` |
| `politician` | As written on the filing, sometimes with "Hon." |
| `bioguide_id` | Member key |
| `politician_canonical` | Display name when metadata is missing |
| `party` | Code. Not used in copy or badges |
| `state` | State |
| `state_district` | Compact district such as `TX17` |
| `symbol` | Ticker the feed resolved |
| `ticker_reported` | Ticker as filed |
| `ticker_source` | How the ticker was chosen, often `reported` |
| `asset_name` | Description, often ending in `[ST]` |
| `asset_type_code` | `ST`, `Stock`, `OP`, `Stock Option`, sometimes null |
| `transaction_type` | `BUY`, `SELL`, or `OTHER` |
| `transaction_date` | Trade date. Entry for "their returns" |
| `notification_date` | Stored. Used as the disclosure date only if `filed_date` is missing |
| `amount_min` / `amount_max` | Dollar strings. The midpoint is the position size |
| `owner_code` | `SELF`, `SPOUSE`, `JOINT`, `DEPENDENT_CHILD`, `OTHER` |
| `filing_status` | `NEW`, `AMENDED`, `INITIAL REPORT`, or null |
| `filed_date` | Disclosure date for copycat returns and filing lag |
| `extraction_method` | Parser note, often null |
| `extraction_confidence` | Parser note, often null |
| `extraction_flags` | Parser note, often null |
| `source_page` | Often null |
| `source_row` | Often null |
| `extraction_artifact_sha256` | Often null |

`source_url` was **not** in either demo payload (`symbol=AAPL`, 729 trades, and `bioguide_id=S000510`). The loader still keeps `source_url` when a row has one of: `source_url`, `sourceUrl`, `disclosure_url`, `filing_url`, `ptr_url`, `link`, `url`. When it does not, the member page links to the House Clerk or Senate EFD search instead of inventing a PDF.

Asset codes seen on the AAPL pull: `ST`, `Stock`, null, `OP`, `sT`, `Stock Option`. Transaction types: `BUY`, `SELL`, `OTHER`.

## Daily prices

`Time Series (Daily)` rows use numbered keys (`4. close`, and `5. adjusted close` on the adjusted endpoint). The cache stores both. Scoring prefers the adjusted close when it is present.

A symbol that already has a bar on the latest weekday is not requested again.
