# Weekly Metrics Report Quality Rubric

This agent runs in `outcome` mode: this rubric is sent directly to the
platform's grader via `user.define_outcome`. The grader inspects the
**deliverable file** the agent writes to `/mnt/session/outputs/weekly-metrics-report.md`
in its sandbox — not the agent's chat reply — so every criterion below must
be satisfied by that file's content. The grader iterates (up to
`manifest.max_iterations`) until it is.

1. **Script-derived arithmetic only** — every growth percentage, activation
   rate, and dollar figure in the report is arithmetically consistent with
   running `scripts/compute-report.mjs` (from this skill's bundle) against
   the CSV the task provided. No figure is invented, hand-adjusted, or
   rounds differently than the script's own output.
2. **Formulas stated in prose, inline** — the growth formula and MRR's
   end-of-week-balance convention are stated in plain prose at or
   immediately above the Week-over-week growth table; the activation-rate
   formula (that same week's activations ÷ that same week's signups, not a
   cohort tracked across weeks) is stated in prose at or immediately above
   the Activation rate table. A reader must never need to consult the skill
   file to know what a number means.
3. **Section structure and order** — exactly these top-level sections, in
   this order: Week-over-week growth, Activation rate, Churn trend,
   Callouts, and (only if the script's `incidentImpact` array is
   non-empty) What changed and why it matters. No other top-level sections;
   the last section is omitted entirely — not included empty — when there
   is no incident to report.
4. **Precision** — growth % and activation rate are reported to 1 decimal
   place, matching the script's own rounding; the first week in the window
   shows growth as `—`, never `0%` or blank.
5. **Churn trend names days, not just totals** — any week with an elevated
   churn total names the specific day(s) (from `daily_churn`) that drove
   it; steady-state weeks can be grouped into one sentence.
6. **Callouts match `anomalies` exactly** — one callout per entry in the
   script's `anomalies` array, no invented anomalies and none dropped;
   anomalies landing in the same week are connected as one likely incident
   rather than listed as unrelated bullets. If `anomalies` is empty, the
   section says so plainly rather than manufacturing a callout.
7. **Dollar-quantified incident impact** — for every entry in
   `incidentImpact`: (a) the trend basis is stated in prose (the average
   growth % over the prior non-anomalous weeks, projected forward to an
   expected MRR balance), (b) the MRR shortfall vs. that trend is reported
   in dollars — not the raw week-over-week % decline, which understates it
   whenever the prior trend was still growing — and (c) the
   churned-customer cost is reported in monthly and annualized dollars at
   the script's estimated `avg_deal_size_usd_per_month`, explicitly labeled
   as a data-derived blended estimate rather than each customer's actual
   contract value. The report notes these are two different cuts of cost
   that are not expected to match each other.
8. **Self-contained** — every number in the report file is traceable and
   explainable from that file's text alone, without the reader opening the
   skill, the script, or the raw CSV.
