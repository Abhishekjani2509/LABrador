# Contract Review Quality Rubric

This agent runs in `message` mode, so this rubric is not sent to an
automatic grader — it documents the bar a human should check a review
against. A complete review satisfies all of the following:

1. **Structure** — output contains exactly four top-level sections, in this
   order: Parties, Key Dates, Obligations, Red Flags. No other top-level
   sections.
2. **Parties** — a table with Role, Entity, Jurisdiction, Address for every
   contracting party; governing law and venue (or their absence) noted.
3. **Key Dates** — a table with Date/Deadline, Trigger, Section. Every
   relative offset ("60 days before X") is resolved to an actual calendar
   date where the anchor date is known. Includes effective date, term
   start/end, renewal-notice deadlines, fee-change notice deadlines, payment
   due dates and late-payment triggers, and cure periods, wherever present in
   the source.
4. **Obligations** — each party's obligations listed separately; every item
   cites its clause number(s).
5. **Red Flags — severity** — every finding has exactly one tier: Critical,
   High, Medium, or Low. No hybrid or compound labels (e.g. "Medium-High").
6. **Red Flags — ordering** — the list is sorted so severity is strictly
   non-increasing from top to bottom; the #1 item is the single
   highest-severity finding, not the first one noticed.
7. **Red Flags — citations and actions** — every finding cites clause
   number(s) and ends with a `Recommend:` line stating a concrete next
   action, not "review this further."
8. **Cross-reference integrity** — internal references between clauses are
   checked; contradictions (e.g., a liability cap excepted in one section but
   reasserted in another) are surfaced as findings in their own right.
9. **Closing summary** — the Red Flags section ends with a short "Summary
   for the client" naming the highest-severity item first and giving a clear
   sign/don't-sign threshold.
10. **Self-containedness of the reply** — the substantive findings (parties,
    key dates, top red flags) appear directly in the reply text, not only in
    a saved file.
