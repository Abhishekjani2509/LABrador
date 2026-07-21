# Weekly metrics report — week ending 2026-07-19

Source: `data/weekly-metrics.csv` via `.claude/skills/weekly-metrics-report/scripts/compute-report.mjs` (35 days, 5 full weeks).

## Week-over-week growth

Growth = (this week's total − prior week's total) / prior week's total. For
MRR, "this week's total" is the end-of-week balance (the last day's
`mrr_usd`), not an average over the week's days.

| Week | Signups | Activations | Churned customers | MRR (end of week) | Trials started |
| --- | --- | --- | --- | --- | --- |
| 2026-06-15 | 137 (—) | 87 (—) | 5 (—) | $191,521 (—) | 186 (—) |
| 2026-06-22 | 150 (+9.5%) | 96 (+10.3%) | 3 (-40.0%) | $205,505 (+7.3%) | 200 (+7.5%) |
| 2026-06-29 | 157 (+4.7%) | 89 (-7.3%) | 4 (+33.3%) | $220,038 (+7.1%) | 185 (-7.5%) |
| 2026-07-06 | 140 (-10.8%) | 65 (-27.0%) | 33 (+725.0%) | $213,058 (-3.2%) | 165 (-10.8%) |
| 2026-07-13 | 184 (+31.4%) | 113 (+73.8%) | 8 (-75.8%) | $230,828 (+8.3%) | 209 (+26.7%) |

## Activation rate

Activation rate = that week's activations ÷ that same week's signups — not
a cohort followed across weeks (e.g. week of 07-06: 65 ÷ 140 = 46.4%).

| Week | Signups | Activations | Activation rate | Point change |
| --- | --- | --- | --- | --- |
| 2026-06-15 | 137 | 87 | 63.5% | — |
| 2026-06-22 | 150 | 96 | 64.0% | +0.5 |
| 2026-06-29 | 157 | 89 | 56.7% | -7.3 |
| 2026-07-06 | 140 | 65 | 46.4% | -10.3 |
| 2026-07-13 | 184 | 113 | 61.4% | +15.0 |

## Churn trend

The first three weeks (06-15, 06-22, 06-29) were unremarkable, steady-state
churn — 3-5 customers a week, spread thinly across the week with no single
day standing out. Week of 2026-07-06 broke that pattern hard: churn ran
elevated all week and peaked on **2026-07-12 (10 churned that day alone)**,
with 2026-07-09 (7) also well above baseline — together those two days
account for more than half the week's total of 33. The following week
(07-13) partially normalized: churn dropped to 8 for the week, still
somewhat above the pre-incident baseline but spread evenly (2 per day early
in the week, tapering to 0-1 by the weekend) rather than concentrated in a
spike — consistent with a tail of incident-driven cancellations rather than
a new, ongoing problem.

## Callouts

**Week of 2026-07-06 shows a single incident hitting three metrics at
once.** Churned customers jumped 725% week-over-week (4 → 33, driven by the
07-09 and 07-12 spikes above), activation rate dropped 10.3 points (56.7% →
46.4%), and MRR fell 3.2% (\$220,038 → \$213,058) — the only week-over-week
MRR decline anywhere in this 5-week window. These three moving together in
the same week, rather than independently, points to one underlying event
(a service incident or outage) rather than three unrelated metric wobbles:
the outage plausibly both pushed existing customers to churn and made new
signups less likely to complete onboarding in the same week.

The following week (07-13) recovered on every front — signups +31.4%,
activations +73.8%, activation rate back up to 61.4% (a 15-point rebound),
churn down 75.8%, and MRR growth back to +8.3%, the strongest week in the
window. That's consistent with a contained incident rather than a
sustained decline.

No other week in this window crossed the anomaly thresholds.

## What changed and why it matters

The week-over-week percentages above understate this because the two prior
weeks (06-22, 06-29) weren't flat — they were growing at +7.3% and +7.1%.
Projecting that average trend (+7.2%, `trend_growth_pct_basis`, based on
those 2 prior non-anomalous weeks) forward from the 06-29 closing balance of
\$220,038 implies an expected close of **\$235,881** for the week of 07-06
had the incident not happened. MRR actually closed that week at \$213,058 —
a shortfall of **\$22,823** versus trend, not the \$6,980 a naive
week-over-week diff (\$220,038 − \$213,058) would suggest, and well above
the -3.2% headline figure. This shortfall isn't churn alone — it also
reflects the week's activation-rate drop slowing new bookings, so it's a
combined-cause number, not a pure churn cost.

Separately, the 33 customers who churned that week represent real recurring
revenue lost, priced at the estimated average deal size across this
dataset's non-incident weeks (**\$130.88/month per customer**, a blended
estimate — net MRR added ÷ net customers added in normal weeks — not each
churned customer's actual contract value): **33 × \$130.88 ≈ \$4,319/month**
in recurring revenue walked out the door, or **≈\$51,828 annualized** if
those customers don't come back. That \$4,319 monthly figure and the
\$22,823 trend-shortfall above are two different cuts — the churned-customer
cost, and the total gap versus where the business was trending — and they
aren't expected to match.

Read together: a ~\$23K single-week dip against trend and ~\$52K in
annualized recurring revenue at risk from the churned cohort is a real but
contained hit, not a business-threatening one at this MRR base (~\$220K) —
worth a root-cause writeup on the incident, but the following week's full
recovery across every metric is the stronger signal than the dip itself.

---
*Generated from `data/weekly-metrics.csv` (mock fixture data) via
`.claude/skills/weekly-metrics-report/scripts/compute-report.mjs` — every growth percentage, activation rate,
and dollar figure above is taken directly from the script's JSON output
(`weeks`, `anomalies`, `avgDealSizeUsd`, `incidentImpact`), not recomputed
by hand.*
