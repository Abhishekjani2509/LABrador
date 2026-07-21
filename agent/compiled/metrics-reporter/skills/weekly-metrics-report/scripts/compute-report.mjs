#!/usr/bin/env node
// Reads a daily metrics CSV and prints per-week aggregates, week-over-week
// growth, activation rate, and anomaly flags as JSON. No write-up here —
// that's the skill's job; this script only owns the arithmetic.
//
// Usage: node .claude/skills/weekly-metrics-report/scripts/compute-report.mjs <csv-path>

import { readFileSync } from "node:fs";

const METRICS = ["signups", "activations", "churned_customers", "mrr_usd", "trials_started"];

function mondayOf(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  const day = d.getUTCDay(); // 0=Sun..6=Sat
  const offset = day === 0 ? 6 : day - 1;
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}

function parseCSV(path) {
  const text = readFileSync(path, "utf8").trim();
  const [header, ...lines] = text.split("\n");
  const cols = header.split(",").map((c) => c.trim());
  return lines.map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const row = {};
    cols.forEach((c, i) => {
      row[c] = METRICS.includes(c) ? Number(cells[i]) : cells[i];
    });
    return row;
  });
}

function round(n, places = 1) {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}

function pctChange(curr, prev) {
  if (prev === 0) return curr === 0 ? 0 : null; // undefined growth off a zero base
  return round(((curr - prev) / prev) * 100, 1);
}

const path = process.argv[2];
if (!path) {
  console.error("Usage: node .claude/skills/weekly-metrics-report/scripts/compute-report.mjs <csv-path>");
  process.exit(1);
}

const rows = parseCSV(path).sort((a, b) => (a.date < b.date ? -1 : 1));

const weekMap = new Map();
for (const row of rows) {
  const weekStart = mondayOf(row.date);
  if (!weekMap.has(weekStart)) weekMap.set(weekStart, []);
  weekMap.get(weekStart).push(row);
}

const weekStarts = [...weekMap.keys()].sort();
const weeks = weekStarts.map((weekStart) => {
  const days = weekMap.get(weekStart);
  const sums = Object.fromEntries(METRICS.map((m) => [m, days.reduce((s, d) => s + d[m], 0)]));
  const weekEnd = days[days.length - 1].date;
  return {
    weekStart,
    weekEnd,
    days: days.length,
    totals: {
      signups: sums.signups,
      activations: sums.activations,
      churned_customers: sums.churned_customers,
      trials_started: sums.trials_started,
    },
    // mrr is a balance, not a flow — the week's value is its closing balance.
    mrr_usd_end: days[days.length - 1].mrr_usd,
    mrr_usd_start: days[0].mrr_usd,
    activation_rate: sums.signups === 0 ? null : round((sums.activations / sums.signups) * 100, 1),
    daily_churn: days.map((d) => ({ date: d.date, churned_customers: d.churned_customers })),
  };
});

const withGrowth = weeks.map((w, i) => {
  const prev = weeks[i - 1];
  if (!prev) return { ...w, growth: null };
  return {
    ...w,
    growth: {
      signups: pctChange(w.totals.signups, prev.totals.signups),
      activations: pctChange(w.totals.activations, prev.totals.activations),
      churned_customers: pctChange(w.totals.churned_customers, prev.totals.churned_customers),
      mrr_usd: pctChange(w.mrr_usd_end, prev.mrr_usd_end),
      trials_started: pctChange(w.totals.trials_started, prev.totals.trials_started),
    },
    activation_rate_point_change:
      prev.activation_rate == null || w.activation_rate == null
        ? null
        : round(w.activation_rate - prev.activation_rate, 1),
  };
});

// Anomaly flags: thresholds are deliberately loose heuristics for a first pass,
// not a statistical model — tune against more history once it exists.
const anomalies = [];
withGrowth.forEach((w, i) => {
  if (!w.growth) return;
  if (w.growth.mrr_usd !== null && w.growth.mrr_usd < 0) {
    anomalies.push({
      week: w.weekStart,
      metric: "mrr_usd",
      detail: `MRR fell ${Math.abs(w.growth.mrr_usd)}% week-over-week (${weeks[i - 1].mrr_usd_end} -> ${w.mrr_usd_end}), the only week-over-week MRR decline in the window.`,
    });
  }
  if (w.growth.churned_customers !== null && w.growth.churned_customers >= 100) {
    anomalies.push({
      week: w.weekStart,
      metric: "churned_customers",
      detail: `Churned customers jumped ${w.growth.churned_customers}% week-over-week (${weeks[i - 1].totals.churned_customers} -> ${w.totals.churned_customers}).`,
    });
  }
  if (w.activation_rate_point_change !== null && w.activation_rate_point_change <= -8) {
    anomalies.push({
      week: w.weekStart,
      metric: "activation_rate",
      detail: `Activation rate dropped ${Math.abs(w.activation_rate_point_change)} points week-over-week (${weeks[i - 1].activation_rate}% -> ${w.activation_rate}%).`,
    });
  }
});

// Average revenue per net-new customer, estimated from weeks NOT flagged as an
// MRR anomaly: sum(mrr_end - mrr_start) / sum(activations - churned_customers)
// across those weeks. This is a blended, data-derived estimate of monthly
// deal size — not a hardcoded number — used below to price out churn in
// dollar terms. Weeks with an MRR anomaly are excluded so an incident's own
// distorted flows don't contaminate the baseline they're being measured against.
function estimateAvgDealSizeUsd(weeks, anomalies) {
  const mrrAnomalyWeeks = new Set(anomalies.filter((a) => a.metric === "mrr_usd").map((a) => a.week));
  let flowSum = 0;
  let netCustomerSum = 0;
  for (const w of weeks) {
    if (mrrAnomalyWeeks.has(w.weekStart)) continue;
    flowSum += w.mrr_usd_end - w.mrr_usd_start;
    netCustomerSum += w.totals.activations - w.totals.churned_customers;
  }
  return netCustomerSum === 0 ? null : flowSum / netCustomerSum;
}

// For every week flagged with an MRR anomaly, quantify it in dollars and
// customers rather than just percent: (1) the MRR trend the prior
// (non-anomalous) weeks were on, projected forward, versus what actually
// happened — the "shortfall vs trend" — and (2) the recurring-revenue value
// of that week's churned customers at the estimated average deal size.
function computeIncidentImpact(weeks, anomalies, avgDealSizeUsd) {
  const impacts = [];
  for (const a of anomalies.filter((a) => a.metric === "mrr_usd")) {
    const idx = weeks.findIndex((w) => w.weekStart === a.week);
    const w = weeks[idx];
    const priorGrowths = weeks
      .slice(0, idx)
      .filter(
        (pw) =>
          pw.growth &&
          pw.growth.mrr_usd !== null &&
          !anomalies.some((x) => x.week === pw.weekStart && x.metric === "mrr_usd")
      )
      .map((pw) => pw.growth.mrr_usd);
    if (priorGrowths.length === 0) continue; // no established trend to compare against

    const trendGrowthPct = round(priorGrowths.reduce((s, g) => s + g, 0) / priorGrowths.length, 2);
    const prevWeek = weeks[idx - 1];
    const expectedMrrUsdEnd = Math.round(prevWeek.mrr_usd_end * (1 + trendGrowthPct / 100));
    const mrrShortfallVsTrendUsd = expectedMrrUsdEnd - w.mrr_usd_end;
    const churnedCustomers = w.totals.churned_customers;
    const monthlyRecurringRevenueLostFromChurnUsd =
      avgDealSizeUsd === null ? null : Math.round(churnedCustomers * avgDealSizeUsd);
    const annualizedRevenueLostFromChurnUsd =
      monthlyRecurringRevenueLostFromChurnUsd === null ? null : monthlyRecurringRevenueLostFromChurnUsd * 12;

    impacts.push({
      week: w.weekStart,
      trend_growth_pct_basis: trendGrowthPct,
      trend_growth_basis_weeks: priorGrowths.length,
      prev_week_mrr_usd_end: prevWeek.mrr_usd_end,
      expected_mrr_usd_end: expectedMrrUsdEnd,
      actual_mrr_usd_end: w.mrr_usd_end,
      mrr_shortfall_vs_trend_usd: mrrShortfallVsTrendUsd,
      churned_customers: churnedCustomers,
      avg_deal_size_usd_per_month: avgDealSizeUsd === null ? null : round(avgDealSizeUsd, 2),
      monthly_recurring_revenue_lost_from_churn_usd: monthlyRecurringRevenueLostFromChurnUsd,
      annualized_revenue_lost_from_churn_usd: annualizedRevenueLostFromChurnUsd,
    });
  }
  return impacts;
}

const avgDealSizeUsd = estimateAvgDealSizeUsd(withGrowth, anomalies);
const incidentImpact = computeIncidentImpact(withGrowth, anomalies, avgDealSizeUsd);

// Last-4-full-weeks trajectory per metric, for spotting trends a single
// week-over-week comparison can't show. Values are oldest-to-newest
// internally; direction is the majority of the (up to 3) week-over-week
// transitions among them (ties, including all-flat, report as "flat").
//
// "up" isn't uniformly good news — it's good for signups/activations/mrr/
// trials but bad for churned_customers — so every trend line is tagged with
// an explicit business-polarity word (growing/declining for up-is-good
// metrics, worsening/improving for churned_customers) alongside the raw
// up/down/flat, rather than leaving a bare "up"/"down" for a skimming
// reader to misjudge.
const GOOD_DIRECTION = {
  signups: "up",
  activations: "up",
  churned_customers: "down",
  mrr_usd: "up",
  trials_started: "up",
};

const TREND_METRICS = [
  { key: "signups", label: "Signups" },
  { key: "activations", label: "Activations" },
  { key: "churned_customers", label: "Churned customers" },
  { key: "mrr_usd", label: "MRR (end of week)" },
  { key: "trials_started", label: "Trials started" },
];

function trendValue(week, key) {
  return key === "mrr_usd" ? week.mrr_usd_end : week.totals[key];
}

function formatTrendValue(key, value) {
  return key === "mrr_usd" ? `$${value.toLocaleString("en-US")}` : `${value}`;
}

function polarityWord(key, direction) {
  if (direction === "flat") return "flat";
  const isGood = direction === GOOD_DIRECTION[key];
  return direction === "up" ? (isGood ? "growing" : "worsening") : isGood ? "improving" : "declining";
}

function computeTrend(weeks, { key, label }) {
  // Only full (7-day) weeks belong in the trend, same as the growth table —
  // an in-progress trailing week would otherwise silently skew both the
  // trajectory and its direction.
  const fullWeeks = weeks.filter((w) => w.days === 7);
  const window = fullWeeks.slice(-4);
  const values = window.map((w) => trendValue(w, key));
  let up = 0;
  let down = 0;
  for (let i = 1; i < values.length; i++) {
    if (values[i] > values[i - 1]) up++;
    else if (values[i] < values[i - 1]) down++;
  }
  const transitions = values.length - 1;
  const direction = up > down ? "up" : down > up ? "down" : "flat";
  const count = direction === "up" ? up : direction === "down" ? down : transitions - up - down;
  const polarity = polarityWord(key, direction);
  const trajectory = [...values]
    .reverse()
    .map((v) => formatTrendValue(key, v))
    .join(" <- ");
  const parenthetical =
    direction === "flat" ? `flat ${count} of last ${transitions}` : `${polarity}, ${direction} ${count} of last ${transitions}`;
  return {
    metric: key,
    label,
    weekStarts: window.map((w) => w.weekStart),
    values,
    direction,
    polarity,
    formatted: `${trajectory} (${parenthetical})`,
  };
}

const trends = TREND_METRICS.map((m) => computeTrend(withGrowth, m));

console.log(JSON.stringify({ weeks: withGrowth, anomalies, avgDealSizeUsd: avgDealSizeUsd === null ? null : round(avgDealSizeUsd, 2), incidentImpact, trends }, null, 2));
