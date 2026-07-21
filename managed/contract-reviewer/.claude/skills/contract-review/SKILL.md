---
name: contract-review
description: Review a client contract (MSA or similar) and produce a structured extraction of parties, key dates, obligations, and severity-ranked red flags. Use whenever asked to review, redline-scout, or summarize risk in a contract document.
---

# Contract review

You are reviewing a contract on behalf of the party who received it (usually
the "Client" or "Customer" side of an MSA sent by a vendor/counterparty).
The goal is a structured extraction plus a risk read a founder or ops lead
can act on without reading the underlying legalese themselves. This is not
a substitute for outside counsel — flag when something needs a lawyer's
sign-off (e.g. enforceability of a liquidated-damages clause), don't try to
resolve it yourself.

## Step 1 — Read the whole document, not just the obvious sections

Gotchas are routinely placed away from where a skimming reader would look
for them:

- Renewal and cancellation terms often live in "General Provisions,"
  "Miscellaneous," or "Term" — check all three, not just the one titled
  "Term."
- Fee-adjustment mechanics may be tucked into a payment section subclause
  rather than given their own heading.
- IP ownership and liability/indemnification clauses interact with each
  other (a cap in one section can be silently excepted or re-imposed by
  another) — cross-check every cross-reference ("subject to Section X")
  actually says what the referencing clause implies it says.

Read every section once before extracting anything. Note every internal
cross-reference (e.g. "as defined in Section 11.7") and verify it resolves
to a real section that says what's implied.

## Step 2 — Extract parties

Identify every contracting party: legal name, entity type/jurisdiction,
address, and its role (e.g. "Provider," "Client"). Note the governing law
clause and whether a venue/forum-selection clause exists — if governing law
is specified but venue isn't (or vice versa), that's a gap worth naming.

## Step 3 — Extract key dates

Every clause that starts a clock is a key date, including ones stated only
as a relative offset. Convert every relative offset to a real calendar date
when the anchor date is known (e.g. "60 days before the Term end" → an
actual date), so the reader never has to do date arithmetic themselves.
Include at minimum, where present:

- Effective date and term start/end
- Renewal-notice deadlines (and what happens if missed)
- Fee-change notice deadlines
- Payment due dates, late-payment triggers (interest, suspension,
  acceleration)
- Cure periods for breach
- Any other deadline that, if missed, changes either party's rights

## Step 4 — Extract obligations

List each party's obligations separately, each citing the clause number(s)
it comes from. Include payment, cooperation/access, confidentiality,
indemnification, and notice obligations at minimum — anything the party
must affirmatively do or refrain from doing.

## Step 5 — Identify and rank red flags

Look across the whole document for issues in these recurring categories
(not an exhaustive list — read for anything that shifts risk or cost onto
the reviewing party):

- **Lock-in mechanics**: auto-renewal, notice windows, evergreen terms
- **Financial exposure**: unilateral/uncapped fee changes, unusual payment
  windows paired with harsh consequences (interest, suspension,
  acceleration), one-sided termination penalties
- **Ownership**: IP assignment scope — does the reviewing party keep rights
  to what it pays for or contributes, including feedback/data?
- **Liability and indemnification**: caps, carve-outs, and whether they're
  internally consistent across sections
- **Gaps**: missing SLA/uptime commitments, missing venue clause, anything
  a comparable contract would normally include but this one omits

Assign every finding exactly one severity tier — no hybrid labels:

- **Critical** — permanently gives away a core asset or right (e.g. IP
  ownership), or otherwise can't be undone by later action. No trigger
  event required; it applies by default.
- **High** — uncapped or largely automatic financial/operational exposure
  that does not require the reviewing party to make a mistake to trigger.
- **Medium** — bounded or conditional exposure: a capped amount, or one
  that only triggers if the reviewing party affirmatively acts (e.g.
  chooses to terminate early).
- **Low** — a gap or drafting ambiguity, not an active claw-back.

Assign the tier first, independent of how interesting or novel the finding
is to write up. Only after every finding has a tier, sort the list so tier
order is strictly non-increasing from top to bottom. The first item in the
list must be the single highest-severity finding — never the first one
noticed, never the one with the best narrative. Before publishing, re-read
the list top to bottom and confirm severity never increases going down the
list; if it does, fix the order, don't relabel a tier just to justify the
position it's already in.

Every red flag must cite the clause number(s) it comes from and end with a
`Recommend:` line — one concrete redline or next action, not "review this
further."

## Output format

Produce exactly these four sections, in this order, and no others:

```markdown
## Parties

| Role | Entity | Jurisdiction | Address |
| --- | --- | --- | --- |

(Note governing law and venue, or their absence, below the table.)

## Key Dates

| Date / Deadline | Trigger | Section |
| --- | --- | --- |

## Obligations

**[Reviewing party]:**
- ... (each item cites clause number(s))

**[Counterparty]:**
- ... (each item cites clause number(s))

## Red Flags

### 1. [Finding title] — **[Severity]** (§[clause])
[1-3 sentences: what the clause says and why it matters.]
**Recommend:** [concrete action]

### 2. ...
```

Close the Red Flags section with a short **Summary for the client**
paragraph that names the highest-severity item first and states a clear
sign/don't-sign threshold (e.g. "don't sign until items 1–4 are
addressed").
