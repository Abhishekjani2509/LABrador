# Contract Review Quality Rubric

This agent runs in `message` mode, so this rubric is not sent to an
automatic grader — it documents the bar a human should check a review
against. A complete review satisfies all of the following:

1. **Structure** — output contains exactly five top-level sections, in this
   order: Bottom Line, Parties, Key Dates, Obligations, Red Flags. No other
   top-level sections.
2. **Bottom line** — a one-line verdict (Sign / Sign after fixes / Don't
   sign) plus up to three plain-language bullets, above the Parties table,
   written for a non-technical reader who won't read the Red Flags list —
   no clause citations, no legal jargon. Agrees with the closing "Summary
   for the client" paragraph in criterion 11.
3. **Parties** — a table with Role, Entity, Jurisdiction, Address for every
   contracting party; governing law and venue (or their absence) noted.
4. **Key Dates** — a table with Date/Deadline, Trigger, Section. Every
   relative offset ("60 days before X") is resolved to an actual calendar
   date where the anchor date is known. Includes effective date, term
   start/end, renewal-notice deadlines, fee-change notice deadlines, payment
   due dates and late-payment triggers, and cure periods, wherever present in
   the source.
5. **Obligations** — each party's obligations listed separately; every item
   cites its clause number(s).
6. **Red Flags — severity** — every finding has exactly one tier: Critical,
   High, Medium, or Low. No hybrid or compound labels (e.g. "Medium-High").
7. **Red Flags — ordering** — the list is sorted so severity is strictly
   non-increasing from top to bottom; the #1 item is the single
   highest-severity finding, not the first one noticed.
8. **Red Flags — citations and actions** — every finding cites clause
   number(s) and ends with a `Recommend:` line stating a concrete next
   action, not "review this further."
9. **Cross-reference integrity** — internal references between clauses are
   checked; contradictions (e.g., a liability cap excepted in one section but
   reasserted in another) are surfaced as findings in their own right.
10. **Type-appropriate lens** — the review identifies whether the contract
    is an NDA, an MSA/services agreement, or mixed, and states it as a
    `Review lens:` line in the preamble (not a sixth top-level section).
    The categories scrutinized hardest match the stated lens: NDAs get
    confidentiality-definition breadth, exclusions completeness,
    residuals/reuse-rights interaction, term proportionality, and remedies
    symmetry; MSAs get financial exposure and lock-in mechanics as before.
    A residuals or reuse-rights clause paired with a missing
    independent-development carve-out in an NDA is flagged Critical, not
    buried at a lower tier.
11. **Closing summary** — the Red Flags section ends with a short "Summary
    for the client" naming the highest-severity item first and giving a clear
    sign/don't-sign threshold.
12. **Self-containedness of the reply** — the substantive findings (parties,
    key dates, top red flags) appear directly in the reply text, not only in
    a saved file.
