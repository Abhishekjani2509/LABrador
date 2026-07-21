---
name: weekly-metrics-report
description: Produce the weekly B2B SaaS metrics report from a daily CSV — week-over-week growth for signups, activations, churned customers, MRR, and trials, plus activation rate, churn trend, and callouts of any anomalies. Use whenever asked for the weekly metrics report, growth report, or "how are we doing this week."
---

# Weekly metrics report

This skill is self-contained: everything it needs — including the
aggregation script — lives under this skill directory
(`.claude/skills/weekly-metrics-report/`). It only reads the CSV fixture
from the project's `data/` directory; it depends on nothing else at the
top level of `managed/metrics-reporter/`.

**Read this before doing anything else, every time you run this skill:**

1. Run `scripts/compute-report.mjs` (path below) first, before writing a
   single word of the report.
2. Never hand-compute anything — not a growth %, not an activation rate,
   not a dollar figure, not even as a "quick sanity check." If a number the
   report needs isn't in the script's JSON, that's a gap in the script (see
   Step 0), not something to fill in by eyeballing the CSV.
3. Use the script's JSON output verbatim — copy figures directly into the
   report; don't re-derive, re-round, or "correct" them.
4. Follow the Output format section below exactly, including the inline
   formula prose at each metric's first appearance and the "What changed
   and why it matters" section.

Turns a daily metrics CSV into a week-over-week SaaS report.
`scripts/compute-report.mjs` (inside this skill directory) is the only
thing that ever touches these numbers — it buckets days into Monday-Sunday
weeks and computes every figure that appears in the report: growth,
activation rate, anomaly flags, the estimated average deal size, and the
dollar/customer cost of any MRR-anomaly week. The report's only job is
translating that JSON into prose, and every prose figure must be traceable
to a specific field in the script's output.

## Step 0 — If the script is missing a number, fix the script first

If the report needs a figure the script doesn't already emit, add it to
`scripts/compute-report.mjs` (in this skill's `scripts/` directory) and
rerun — never compute it by hand in the write-up, even "just this once."
The script is the only place these numbers get computed; the report only
reads its JSON.

## Step 1 — Run the compute script

From `managed/metrics-reporter/` (the skill's `scripts/` directory holds
the script; the CSV stays in the project's top-level `data/`):

```
node .claude/skills/weekly-metrics-report/scripts/compute-report.mjs data/weekly-metrics.csv
```

This prints JSON: one entry per Monday-Sunday week (`totals`, `mrr_usd_end`,
`activation_rate`, `growth` vs. the prior week, `daily_churn`), an
`anomalies` array, the estimated `avgDealSizeUsd`, an `incidentImpact`
array (one entry per MRR-anomaly week, with the trend-projected MRR, the
dollar shortfall versus that trend, and the monthly/annualized recurring
revenue value of that week's churned customers), and a `trends` array (one
entry per metric, covering the last 4 full weeks — see Step 3.5). Only full
weeks matter for the report — if the CSV's last week has fewer than 7 days,
treat it as in-progress and report on the last full week instead, noting
the partial week separately if it's still worth watching.

## Step 2 — Report week-over-week growth per metric

State the formula in plain prose the first time growth is introduced (right
before or above the table), e.g. "growth is each week's total vs. the prior
week's, `(this week − last week) / last week`; MRR growth is computed off
the end-of-week balance, not an average balance." Don't make the reader open
this skill file to know what a number means — the report must be
self-contained.

For every metric (`signups`, `activations`, `churned_customers`, `mrr_usd`,
`trials_started`), show each week's total (or, for `mrr_usd`, the
end-of-week balance) next to its growth % from the prior week, taken
directly from the script's `growth` field — don't re-derive the percentage
by hand. The first week in the window has no prior week to compare against;
show it with growth `—`, not `0%` or a blank that could be misread as no
change.

## Step 2.5 — Report the 4-week trend

Right after the Week-over-week growth table, add a `## 4-week trend`
section. For each metric, take its entry from the script's `trends` array
and print the `formatted` string verbatim (don't rebuild it from `values`
by hand) — it already contains the last-4-full-weeks values oldest-to-newest
reading right-to-left (e.g. `137 <- 125 <- 118 <- 121`, most recent week
first) plus the majority direction across those weeks' transitions (`up`,
`down`, or `flat`) and how many of the (up to 3) week-over-week transitions
went that way. The script only ever draws this window from full (7-day)
weeks — an in-progress trailing week is excluded from the trend the same
way it's excluded from the growth table, so you never need to check this
yourself. If fewer than 4 full weeks exist, the array still has one entry
per metric, just over however many full weeks are available — say so in a
lead-in sentence rather than treating it as an error.

**"Up" is not uniformly good news, so never print a bare `up`/`down` for
this section.** The script pairs every direction with an explicit
business-polarity word, and the report must always show that word, not
just the raw direction:

| Metric | Good direction | Up reads as | Down reads as |
| --- | --- | --- | --- |
| signups | up | growing | declining |
| activations | up | growing | declining |
| mrr_usd | up | growing | declining |
| trials_started | up | growing | declining |
| churned_customers | down | worsening | improving |

For example: `184 <- 140 <- 157 <- 150 (growing, up 2 of last 3)` for
signups, but `8 <- 33 <- 4 <- 3 (worsening, up 2 of last 3)` for churned
customers — same raw direction (`up`), opposite polarity word, because more
churn is bad. A flat trend reports as `(flat N of last M)` with no polarity
word (there's no good/bad direction to call out when nothing moved). This
polarity mapping lives in the script's `GOOD_DIRECTION` table and its
`polarity` field on each trend entry — if a new metric is ever added to
`TREND_METRICS`, it must get an entry there too, or its trend line will
silently read as a bare direction again.

## Step 3 — Report activation rate

State the formula in prose where this section starts: activation rate =
activations ÷ signups **for that same week** (not a cohort tracked across
weeks) — already computed per-week as `activation_rate`. Show it alongside
the point change from the prior week (`activation_rate_point_change`) — a
rate can hold steady while raw activations swing with signup volume, so the
point change is what actually says whether onboarding got better or worse.

## Step 4 — Report the churn trend

Don't just show the weekly `churned_customers` total — use `daily_churn` to
say *when within the week* churn happened. A flat total can hide a spike
concentrated in 2-3 days versus one spread evenly across the week, and
that's the difference between "a bad Tuesday" and "a slow bleed." Name the
specific day(s) with the highest daily churn count when a week's total is
notably elevated.

## Step 5 — Callouts

Take every entry in the script's `anomalies` array and turn it into a
callout — don't invent anomalies the script didn't flag, and don't drop ones
it did. For each callout, connect the dots across metrics if they land in
the same week (e.g. a churn spike and an MRR decline in the same week are
almost certainly the same underlying incident, not two coincidences) rather
than listing them as unrelated bullets. If `anomalies` is empty, say plainly
that nothing crossed the thresholds this week — do not manufacture a
callout to fill the section.

## Step 6 — "What changed and why it matters" (dollar cost of any incident)

If `incidentImpact` is non-empty, add this section after Callouts. It must
answer "should I be panicking or not" in dollars and customers, not
percentages — percentages don't tell a reader the stakes. For each entry:

- State the trend basis in prose: `trend_growth_pct_basis` is the average
  MRR growth % over the `trend_growth_basis_weeks` prior non-anomalous
  weeks, projected forward from `prev_week_mrr_usd_end` to get
  `expected_mrr_usd_end` — what MRR would have been if the incident week had
  simply continued the prior trend.
- Report `mrr_shortfall_vs_trend_usd` as the actual dollar cost: expected
  MRR minus actual MRR (`actual_mrr_usd_end`), not the week-over-week
  percent decline — the percent decline understates it here because prior
  weeks were still growing, not flat.
- Report the churned-customer cost: `churned_customers` at that week's
  `avg_deal_size_usd_per_month` (state this is a data-derived blended
  estimate — average revenue per net-new customer across non-anomalous
  weeks, not each customer's actual contract) works out to
  `monthly_recurring_revenue_lost_from_churn_usd` in monthly recurring
  revenue walking out the door, or `annualized_revenue_lost_from_churn_usd`
  annualized.
- Note that the MRR shortfall and the churn dollar cost are two different
  cuts (trend-shortfall vs. customers-lost-at-typical-value), not the same
  number twice, and they need not match — the shortfall also reflects
  slowed new bookings, not just churn.
- If `incidentImpact` is empty, omit this section entirely rather than
  including it with nothing to say.

## Output format

Produce exactly these sections, in this order:

```markdown
# Weekly metrics report — week ending <last full week's end date>

Source: `data/weekly-metrics.csv` via `.claude/skills/weekly-metrics-report/scripts/compute-report.mjs` (<N> days, <M> full weeks).

## Week-over-week growth

Growth = (this week's total − prior week's total) / prior week's total. For
MRR, "this week's total" is the end-of-week balance (the last day's
`mrr_usd`), not an average over the week's days.

| Week | Signups | Activations | Churned customers | MRR (end of week) | Trials started |
| --- | --- | --- | --- | --- | --- |
| <week start> | <n> (<±X.X%>) | ... | ... | $<n> (<±X.X%>) | ... |
(one row per full week, oldest first, growth vs. the row above)

## 4-week trend

<One line per metric, the `trends[i].formatted` string verbatim (it already
includes the good/bad polarity word — never substitute a bare `up`/`down`),
labeled with `trends[i].label`, e.g. "Signups: 184 <- 140 <- 157 <- 150
(growing, up 2 of last 3)".>

## Activation rate

Activation rate = that week's activations ÷ that same week's signups —
not a cohort followed across weeks.

| Week | Signups | Activations | Activation rate | Point change |
| --- | --- | --- | --- | --- |
(one row per full week)

## Churn trend

<1-2 sentences per week that had anything notable, naming the specific
day(s) that drove the week's total when it was elevated. Weeks with
unremarkable, steady-state churn can be grouped in one sentence rather than
given their own paragraph.>

## Callouts

<One paragraph per anomaly (or per related cluster of anomalies), citing
the exact numbers from the script output. If none: state that no metric
crossed the anomaly thresholds this week.>

## What changed and why it matters

(Only if `incidentImpact` is non-empty — omit the whole section otherwise.)

<Per incidentImpact entry: the trend basis in prose, the MRR shortfall vs.
trend in dollars, and the churned-customer cost in monthly/annualized
dollars — per Step 6.>
```

Report every growth percentage and activation rate to 1 decimal place,
matching the script's output — don't round further or add trailing zeros
the script didn't produce. Dollar figures in "What changed and why it
matters" come straight from the script's `incidentImpact` fields — do not
recompute, round differently, or hand-check them against the CSV.
