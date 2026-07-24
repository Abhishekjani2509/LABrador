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

## Step 2 — Classify the contract and pick a review lens

Determine what kind of contract this is from its title, recitals/purpose
clause, and structure, then use that to decide which categories in Step 6
to weight most heavily. Two named types, plus a catch-all — don't build
out a longer taxonomy:

- **NDA / confidentiality agreement** — the only real obligation is not to
  disclose or misuse information; no services, deliverables, or fees are
  described.
- **MSA / services agreement** (or similar — subscription, SOW, license
  with ongoing fees) — describes services, deliverables, pricing, or a
  subscription relationship.
- **Other / mixed** — doesn't clearly fit either, or an NDA is embedded
  inside a larger commercial agreement. Apply both lenses below without
  narrowing.

Each type sets a primary question the rest of the review has to answer —
not just a checklist to skim past:

- **NDA → "Does the confidentiality obligation actually protect
  anything?"** Chase this through the full chain: how broad is the
  "Confidential Information" definition; does the exclusions/carve-outs
  list include all four standard exceptions (public domain, prior
  possession, independently developed without reference to the disclosing
  party's information, and rightful receipt from a third party) — a
  missing one is a red flag by itself; is there a residuals or
  memory-retention/reuse clause, and if so, does it interact with a
  missing independent-development carve-out? That specific combination —
  broad rights to reuse retained know-how plus no independent-development
  exception — is the single most common way an NDA gets gutted. Treat it
  as Critical whenever both are present, regardless of how tidy the rest
  of the document reads, because it undermines the confidentiality
  promise that is the entire point of the agreement, not just one clause.
  Also check: is the term proportionate to how sensitive the information
  is and how long the relationship actually needs protecting, and do
  remedies (injunctive relief, etc.) run to both parties symmetrically or
  only one.
- **MSA → "Where does this contract quietly move risk or cost onto the
  reviewing party?"** This is what the category list in Step 6 covers:
  lock-in mechanics, financial exposure, ownership, liability/
  indemnification, gaps.
- **Other/mixed → ask both questions**, applying whichever categories are
  relevant to the sections actually present.

Naming the lens doesn't change the severity-tier definitions in Step 6 —
tiers still track actual exposure, not document type. It changes where
you look hardest and what you refuse to wave through as "probably fine."

State the classification in the reply itself — a `Review lens:` line in
the preamble, above `## Bottom line` (see Output format). Don't leave it
as a silent judgment call; the whole point is that the next reviewer, or
a client reading over your shoulder, can see which categories you leaned
on and why.

## Step 3 — Extract parties

Identify every contracting party: legal name, entity type/jurisdiction,
address, and its role (e.g. "Provider," "Client"). Note the governing law
clause and whether a venue/forum-selection clause exists — if governing law
is specified but venue isn't (or vice versa), that's a gap worth naming.

## Step 4 — Extract key dates

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

## Step 5 — Extract obligations

List each party's obligations separately, each citing the clause number(s)
it comes from. Include payment, cooperation/access, confidentiality,
indemnification, and notice obligations at minimum — anything the party
must affirmatively do or refrain from doing.

## Step 6 — Identify and rank red flags

Look across the whole document for issues in these recurring categories
(not an exhaustive list — read for anything that shifts risk or cost onto
the reviewing party). Which group to weight most heavily follows the lens
picked in Step 2; still skim the other group in case it applies:

For **NDAs**, weight these most heavily:

- **Confidentiality scope**: breadth of the "Confidential Information"
  definition, and whether the exclusions list is missing any of the four
  standard carve-outs (public domain, prior possession, independent
  development, third-party rightful receipt)
- **Reuse/residuals rights**: any clause letting a party keep using
  retained know-how, ideas, or techniques after the engagement — check it
  against the exclusions list above; broad reuse rights plus a missing
  independent-development carve-out together gut the agreement (see the
  Critical tier below)
- **Term proportionality**: is the confidentiality period sized to the
  sensitivity of the information and the length of the relationship, not
  just copy-pasted from a template
- **Remedies symmetry**: do injunctive relief and other remedies run to
  both parties, or only whichever party drafted the agreement

For **MSAs / services agreements**, weight these most heavily:

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
  ownership in an MSA; in an NDA, a residuals/reuse clause paired with no
  independent-development carve-out, since together they leave the
  confidentiality obligation with nothing actually enforceable behind
  it), or otherwise can't be undone by later action. No trigger event
  required; it applies by default.
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

## Step 7 — Decide the executive verdict

Reviews are routinely forwarded to a non-technical reader who will not read
the Red Flags list item by item. Before the Parties table, give them a
one-line verdict plus up to three plain-language bullets — no clause
citations, no legal jargon, just what it means for them:

- **Sign** — no Critical or High findings.
- **Sign after fixes** — Critical and/or High findings are present, but
  they're standard for a first-draft contract and fixable via redline
  before signature (the common case).
- **Don't sign** — a Critical finding that's structural to the document as
  drafted (unlikely to be removable by redline) or a pattern across
  findings that signals bad-faith drafting rather than a normal first
  draft.

The verdict must agree with the detailed "Summary for the client"
paragraph that closes the Red Flags section — the two are the same
judgment at different altitudes, not independent opinions.

## Output format

Before the five sections below, include a short preamble with the source
document, document type, the `Review lens:` classification from Step 2 (one
line — the type and the one or two categories it's driving emphasis
toward), and who the review is for — formatted as bold-label lines exactly
like the template below. The preamble is not one of the five top-level
sections: no `##` heading, no title line, nothing above it but the reply
itself starts directly with `**Source document:**`.

Then produce exactly these five sections, in this order, and no others:

```markdown
**Source document:** [file name or "pasted text"]
**Document type:** [e.g. Mutual Non-Disclosure Agreement, Master Services Agreement]
**Review lens:** [NDA / MSA / mixed — one line naming the type and the categories it drives emphasis toward]
**Reviewed for:** [the recipient party]

## Bottom line

**[Sign / Sign after fixes / Don't sign]**

- [plain-language consequence, no clause citations]
- [plain-language consequence]
- [plain-language consequence — 3 bullets max]

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
