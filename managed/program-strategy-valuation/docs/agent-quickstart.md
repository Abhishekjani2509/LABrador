# Agent quickstart

Use the CLI instead of importing internal calculation functions. The CLI validates the same
Pydantic contracts used by the dashboard and emits JSON on both success and validation failure.

```bash
labrador example --output-dir ./work/inputs
labrador validate ./work/inputs/demo_program.json \
  --comparables ./work/inputs/demo_comparables.json --compact
labrador analyze ./work/inputs/demo_program.json \
  --comparables ./work/inputs/demo_comparables.json \
  --simulations 1000 --seed 42 --output ./work/result.json
labrador portfolio ./work/inputs/demo_program.json \
  ./work/inputs/demo_program_b.json \
  --comparables ./work/inputs/demo_comparables.json \
  --simulations 1000 --seed 42 --sort-by p50_rnpv --descending
```

Agent rules:

1. Preserve every `price.basis`, evidence record, warning, and decision-grade field.
2. Do not change `synthetic`, evidence grade, or evidence type merely to silence a warning.
3. Never reinterpret list/public reimbursement data as an actual confidential net price.
4. Treat patient income as an access/affordability input, not a clinical-value multiplier.
5. Keep prevalent backlog, incident flow, adoption, access, persistence, overlap, and
   cannibalization distinct.
6. Do not reset the patent clock for an expansion indication.
7. Keep the result seed and simulation count with any quoted percentile.
8. Quote a KPI together with its currency, year/basis, warnings, and decision grade.
9. Supply explicit annual patient OOP evidence for decision-grade affordability; a net-price
   cost-share proxy must remain labeled and non-decision-grade.
10. Compare portfolio programs only when currency and valuation year match.
11. Treat `portfolio` ordering as a declared numeric screening sort, never an investment ranking.

Before using external evidence, follow [source-policy.md](source-policy.md). The bundled files are
interface fixtures only and are always `SYNTHETIC` / `NOT_DECISION_GRADE`.
