# Methodology

Capitol Gains turns public trade **ranges** into a league table. The math is
deliberately simple. It is a size-weighted average of holding-period returns,
not a broker statement and not a claim about what anyone actually earned.

## What a disclosure is

Periodic transaction reports list an amount **range**, not a share count and
not a fill price. This project uses the **midpoint** of that range as the
position size:

```
midpoint = (amount_min + amount_max) / 2
```

`$1,001 – $15,000` becomes `$8,000.50`. When a bucket is open-ended and only
one side is present, that single side is used and the trade is flagged
`open_ended` in the export. Ranges are estimates. Treat every dollar figure
here as an estimate.

## Which trades count

Included:

- Equities and ETFs. Alpha Vantage `asset_type_code` values `ST`, `Stock`,
  and `ETF` (any capitalization) are included. A blank type is included only
  when the asset name still says stock or ETF and the ticker looks like a
  ticker.

Excluded and counted, never silently dropped from the member page:

- Options (`OP`, `Stock Option`, or the word "option" in the asset name).
- Other non-stocks (bonds, notes, treasuries, crypto, and anything else).
- Unknown tickers: no close on file within 7 calendar days of the date we need.
- Transaction types other than a buy or a sell (`OTHER`, exchanges).
- Sells with no earlier buy in the feed. Those shares were acquired before the
  data we have. They are **unmatched sells**, not invented short positions.

Same-day round trips have no close-to-close move, so they do not enter the
return. They still count toward the trade total.

## Two ways to keep score

Both views use the same exits. They differ only in the entry.

1. **Their returns.** Shares = `midpoint / close on the transaction date`.
   The position starts that day.
2. **Copycat returns.** The same midpoint dollars are deployed at the close on
   the **disclosure date** (`filed_date`, or `notification_date` when the
   filing date is missing). You cannot copy a position that was already closed
   before it was disclosed. Those lots are counted as uncopyable and left out
   of the copycat return.

Buys open a lot. Sales close lots **FIFO**, per ticker. A disclosed sale is a
dollar amount, so shares sold = `midpoint / close on the sale date`. A partial
sale splits the oldest lot. Whatever is still open is marked to market at the
latest close on or before the scoreboard date.

## Alpha versus the S&P 500

The benchmark is SPY over **exactly the same dates** as each lot.

For a lot that is open between `t0` and `t1` (see windows below):

```
weight        = shares * price(t0)
pnl           = shares * (price(t1) - price(t0))
spy_return    = SPY(t1) / SPY(t0) - 1
benchmark_pnl = weight * spy_return
```

Across every lot that overlaps the window:

```
member return     = sum(pnl) / sum(weight)
benchmark return  = sum(benchmark_pnl) / sum(weight)
alpha vs S&P 500  = member return - benchmark return
```

This is a **capital-weighted average excess holding-period return**. It is not
a time-weighted portfolio, it ignores commissions, and overlapping lots are
weighted by the dollars tied up at the start of each measured span. When two
members are compared, the benchmark each faces is their own set of dates, not
one shared buy-and-hold of SPY.

The equity curve chains those same period returns. On dates with no open
position, both lines stay flat: no exposure, no benchmark exposure.

## Windows

| Window | Start |
| --- | --- |
| Last 30 days | scoreboard date minus 30 calendar days |
| YTD | January 1 of the scoreboard year |
| Last 12 months | scoreboard date minus 365 calendar days |
| All available data | first priced lot in the cache |

A lot is measured from `max(entry, window start)` through `min(exit or window end, window end)`. A span that does not cover at least one calendar day is skipped. Clipping is what makes a 30-day number describe those 30 days, while the S&P comparison still uses that same clipped span.

The trade-count gate uses the **transaction date**. Filing-lag stats use the **disclosure date**, so a report that shows up this month is part of this month even when the trade is older.

## Filing lag

```
lag = disclosure date - transaction date
```

A lag above **45 days** is flagged late. That is the public STOCK Act shorthand this project uses; it is a timing stat, not a legal finding. Negative lags (a filing date before the trade) are shown and left out of the average.

## Who gets ranked

A member is ranked in a window when they have at least **3** priced equity trades whose transaction date falls in that window. Everyone else is **benched**. Benched members still show their stats and badges. They do not take a rank, so they do not move the arrows.

Default order is alpha versus SPY, highest first. Ties break on their return, then name.

Rank change is `yesterday's rank - today's rank` for the same window. A positive number is a climb. The streak counts consecutive snapshots where the rank number got strictly better. Three or more is "on fire." Snapshots are stored in `rank-history.json`, so a fresh machine can still see yesterday.

## Badges

Computed from the window you are looking at. Humor is about the stats only.

| Badge | Rule |
| --- | --- |
| Beat the Market | Alpha above zero |
| The Market Beat You | Alpha below zero |
| Index Hugger | Alpha within ±2 percentage points |
| One Big Bet | At least three trades, and the biggest one or two are 70% or more of midpoint dollars |
| Tech Bro | At least half of midpoint dollars are in the bundled technology list |
| Punctual Pro | At least one filing in the window and none of them late |
| Diamond Hands | Longest average holding period in the field |
| Paper Hands | Shortest average holding period |
| Fashionably Late | Highest average filing lag |
| Buy High Sell Low | Worst capital-weighted return on positions that were actually closed |

Superlatives (the last four) go to one member. Ties break alphabetically by name.

## Prices

Closes come from Alpha Vantage daily series. The free plan includes
`TIME_SERIES_DAILY` (raw closes, not split-adjusted) and, for `outputsize=compact`,
about the latest 100 sessions. `TIME_SERIES_DAILY_ADJUSTED` and `outputsize=full`
are premium. The job records which series it used. Raw closes are wrong across
splits; adjusted closes are used automatically when the configured function
returns them. A cached series that already contains the latest weekday is not
requested again.

## What this is not

It is not financial advice, not a statement of net worth, and not an accusation.
Party is a data label. It is not an input to returns, badges, ranks, or the
ticker tape.
