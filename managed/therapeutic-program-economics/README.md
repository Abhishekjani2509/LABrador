# Therapeutic Program Economics

Therapeutic Program Economics is an interpretable, screening-grade simulator for therapeutic program economics. It
connects a provenance-aware program brief and comparable-price evidence to value, access,
affordability, protected cash flow, and seeded uncertainty. It is designed for a human analyst
and an AI agent to reach the same result from the same files.

> **Decision boundary:** LABrador is decision support, not medical, reimbursement, investment,
> legal, or patent advice. The bundled demo is **SYNTHETIC** and
> **NOT_DECISION_GRADE**. Public prices or comparable products do not reveal an actual
> confidential manufacturer net price.

## What it does

- Keeps list, public reimbursement, estimated net, and observed net price bases distinct.
- Separates clinical value from health-system access and patient out-of-pocket affordability.
- Models an eligible/prevalent population and incident flow without calling the result a market
  forecast.
- Applies the original asset patent clock to both an initial indication and any label expansion;
  an expansion does not restart the 20-year term.
- Produces annual patient, revenue, cost, free-cash-flow, and protected/post-LOE views.
- Runs deterministic Monte Carlo scenarios for a fixed seed.
- Returns assumptions, calculation steps, provenance, evidence grades, and warnings in JSON.
- Marks unsupported critical inputs or any synthetic demonstration as
  `NOT_DECISION_GRADE`.

## Quick start

Requires Python 3.11 or 3.12. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[dev]'

labrador example
labrador validate fixtures/demo_program.json \
  --comparables fixtures/demo_comparables.json
labrador analyze fixtures/demo_program.json \
  --comparables fixtures/demo_comparables.json \
  --simulations 1000 --seed 42 \
  --output analysis.json
```

The CLI prints JSON by default. `--compact` produces one-line JSON for agent pipelines. A CSV
version of the comparable fixture is included to exercise the upload/import path:

```bash
labrador compare fixtures/demo_comparables.csv --compact
labrador example --output-dir ./starter-inputs
labrador portfolio fixtures/demo_program.json fixtures/demo_program_b.json \
  --comparables fixtures/demo_comparables.json \
  --simulations 1000 --seed 42 --sort-by p50_rnpv --descending
```

Launch the dashboard:

```bash
streamlit run app.py
```

The dashboard provides five coordinated views:

1. **Executive** — screening recommendation, primary metrics, and material warnings.
2. **Price & Comparables** — explicit price bases, matched evidence, and provenance.
3. **Access & Affordability** — eligible and treated patients, payer budget impact, and PMPM.
4. **Cash Flow** — protected versus post-LOE revenue, costs, and discounted cash flow.
5. **Sensitivity / Audit** — uncertainty drivers and the complete reproducible JSON record.

## Input contract

The Pydantic contracts in `src/labrador_roi/models.py` are authoritative. A `ProgramInput`
contains:

- asset identity, modality, route, valuation/base years, and currency;
- an initial indication and optional expansion indications;
- population stock/flow, health-system access gates, and separately labeled income bands;
- patent filing term and any explicitly assumed extension;
- stage costs, durations, success probabilities, evidence, and analyst assumptions.

A comparable keeps product context and `PriceObservation` together. Every observation specifies
amount, currency, period, price year, price basis, and evidence metadata. Course or unit prices
also require annualization units. CSV upload is a transport convenience; it is normalized into
the same nested validated contract before analysis.

Start from the bundled files:

- `fixtures/demo_program.json`
- `fixtures/demo_program_b.json` (a second synthetic program for portfolio comparison)
- `fixtures/demo_comparables.json`
- `fixtures/demo_comparables.csv`

Every value in these files is fictitious. Replace the values and the `SYNTHETIC` evidence records;
changing only the label is not sufficient to make an analysis decision-grade.

## Output contract for agents

Successful CLI commands emit JSON. Validation failures also return structured JSON and exit with
code `2`:

```json
{
  "status": "error",
  "operation": "validate",
  "error_type": "ValidationError",
  "errors": [
    {"type": "missing", "loc": ["initial_indication"], "msg": "Field required"}
  ]
}
```

For reproducibility, persist the validated inputs, simulation count, seed, package version, full
result JSON, and source-access dates together. Do not scrape a displayed KPI and discard its
warnings or provenance.

`labrador portfolio` accepts two or more program JSON paths plus one shared comparable catalog.
It returns standardized P10/P50/P90 rNPV, probability-positive, cash-at-risk, protected-years,
launch-delay-cost, decision-grade, and recommendation rows. Its explicit numeric sort is a
screening convenience, not an investment ranking. Programs must share one currency and valuation
year; LABrador will not silently perform FX or time-basis conversions. `NOT_DECISION_GRADE`
programs still require evidence replacement and review.

## Core assumptions and interpretation rules

- A comparable is evidence, not proof that two therapies deserve the same price.
- Public reimbursement, acquisition cost, wholesale/list price, and estimated net price answer
  different questions and are never silently pooled.
- Net-price scenarios are analyst inputs unless backed by authorized observed-net evidence. The
  repository contains no actual confidential manufacturer net-price data.
- Patient income can constrain coverage, initiation, cost sharing, and access. It cannot
  mechanically reduce clinical benefit or a QALY gain.
- For nonzero cost sharing, a decision-grade affordability result requires an explicit annual
  patient out-of-pocket amount and evidence. A manufacturer-net percentage is retained only as
  a labeled screening proxy and cannot clear the evidence gate.
- When income-band coverage is incomplete, any `patient_affordability_rate` is an explicit
  analyst fallback scenario, not evidence about patient wealth; the synthetic expansion fixture
  demonstrates this path and remains `NOT_DECISION_GRADE`.
- Cost-effectiveness, payer budget impact, patient affordability, and manufacturer cash flow are
  separate outputs. A favorable result in one does not establish another.
- Population estimates separate prevalent launch backlog from incident flow and apply explicit
  coverage, authorization, initiation, provider-capacity, adoption, persistence, overlap, and
  cannibalization assumptions.
- The simplified patent calculation is a screening model: base term starts at filing, not launch,
  and does not substitute for a product-specific legal/FDA exclusivity review.
- Results should be reported as ranges and scenarios. Synthetic demo precision is interface
  precision, not evidentiary precision.
- Route is an explicit stratification field, not a hidden adherence multiplier. Encode
  route-specific administration burden, persistence, capacity, and costs as sourced assumptions.

## Source policy

Use bounded, auditable evidence lanes:

- FDA labels and Drugs@FDA for approved indication and regulatory context—not price.
- Orange Book records for listed patent/exclusivity context—not a legal conclusion or price.
- CMS Part B/Part D public data and NADAC for public reimbursement, utilization, formulary, or
  acquisition-cost signals—not confidential manufacturer net price.
- NICE appraisals for public HTA reasoning and disclosed prices, while preserving any
  confidential-discount caveat.
- Census/household-survey income bands or explicit user inputs for patient affordability.
- World Bank income groups only as country context, never as a mechanical WTP or price multiplier.
- Paperclip for bounded literature retrieval, followed by primary-source verification.

The complete rules and authoritative links are in [docs/source-policy.md](docs/source-policy.md).

## Build and verification plan

The implementation is intentionally layered:

1. **Typed contracts and provenance** — reject invalid or unlabeled precision at ingestion.
2. **Comparable and pricing analysis** — rank relevant evidence without collapsing price bases.
3. **Access, cash flow, and uncertainty** — deterministic engine plus seeded simulations.
4. **Human and agent surfaces** — the same validated inputs and engine behind CLI and Streamlit.
5. **Regression gates** — economic invariants, CLI contracts, lint, and deterministic smoke tests.

Run the local verification suite:

```bash
pytest
ruff check .
labrador analyze fixtures/demo_program.json \
  --comparables fixtures/demo_comparables.json --simulations 100 --seed 7 --compact
```

## Repository map

```text
app.py                         Streamlit dashboard
fixtures/                      Explicitly synthetic demo inputs
src/labrador_roi/cli.py        JSON/CSV adapters and CLI commands
src/labrador_roi/models.py     Validated domain contracts
src/labrador_roi/engine.py     Analysis orchestrator
docs/source-policy.md          Evidence and price-basis rules
tests/                         Economic, provenance, and CLI regression tests
```

## Residual limitations

LABrador does not itself establish clinical efficacy, perform legal patent analysis, negotiate
coverage, retrieve confidential rebate contracts, predict competitor behavior, or replace a
jurisdiction-specific HEOR model. Missing, synthetic, low-grade, or internally asserted inputs
must remain visible in the output and may keep the result `NOT_DECISION_GRADE`.

No repository license has been selected yet. The repository owner should choose one before
redistribution or external reuse.
