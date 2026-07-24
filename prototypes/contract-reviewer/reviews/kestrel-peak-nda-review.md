# Contract Review — Kestrel Peak Holdings NDA

**Source document:** `fixtures/kestrel-peak-nda.txt`
**Document type:** Mutual Non-Disclosure Agreement (client-drafted, sent in place of an expected MSA)
**Review lens:** NDA / confidentiality agreement — no services, deliverables, or fees appear anywhere in the document, so the categories weighted here are confidentiality-definition scope, exclusions completeness, reuse/residuals rights, term proportionality, and remedies symmetry (not the financial-exposure/lock-in categories an MSA review leads with).
**Reviewed for:** Brightloom Data, Inc. (recipient / prospective signatory)

## Bottom line

**Sign after fixes**

- This isn't actually mutual: as drafted, Kestrel's people can freely reuse whatever they remember from your technical materials — forever, without paying you — while you get no equivalent right over anything of theirs.
- If there's ever a dispute, only Kestrel can run to court to stop you; you don't get that same emergency power over them.
- The 5-year confidentiality window is longer than a "let's explore working together" NDA needs — not dangerous by itself, but combined with the other two it tilts every asymmetry the same direction. Don't sign until the redlines below go in.

## Parties

| Role | Entity | Jurisdiction | Address |
| --- | --- | --- | --- |
| Counterparty (client) | Kestrel Peak Holdings, LLC | Delaware LLC | 1201 Third Avenue, Suite 2200, Seattle, WA 98101 |
| Recipient | Brightloom Data, Inc. | Delaware corp. | 228 Park Avenue South, PMB 100482, New York, NY 10003 |

Governing law: Washington (§9.1). No venue/forum-selection clause is present.

## Key Dates

| Date / Deadline | Trigger | Section |
| --- | --- | --- |
| Effective Date | Date of last signature (unsigned as of review) | Preamble |
| Effective Date + 5 years (e.g., July 21, 2031 if executed today) | Term ends; confidentiality obligations under §2 lapse entirely at this point, regardless of when a given piece of information was disclosed | §4 |

No renewal, fee, or payment mechanics — this is a standalone NDA, not the MSA you were expecting.

## Obligations

**Brightloom (you):**
- When acting as Receiving Party: hold Kestrel's Confidential Information in confidence with reasonable care, use it only to evaluate/pursue the Purpose, and restrict access to need-to-know personnel/advisors under equivalent confidentiality terms (§2.1–2.2).
- Return or destroy Kestrel's materials on written request, with a legal-file retention exception (§6).
- Exposed, as "Recipient," to Kestrel's unilateral injunctive-relief right on any breach — no bond required (§7.2).

**Kestrel:**
- When acting as Receiving Party: same confidentiality and use restrictions apply to Brightloom's information — mutual on paper (§2.1–2.2, §6).
- Free to use "Residuals" — ideas, concepts, know-how, or techniques retained in employees' memory from exposure to Brightloom's Confidential Information — for any purpose, with no accounting or royalty (§5).
- Sole named beneficiary of the injunctive-relief right in §7.2, despite §1.2's mutual Disclosing/Receiving Party framework.

## Red Flags

Severity scale: **Critical** (loss of a core asset or right) > **High** (uncapped or automatic financial/operational exposure) > **Medium** (bounded or conditional exposure) > **Low** (gap or drafting ambiguity, not an active claw-back). Listed highest severity first.

### 1. Residuals clause plus no independent-development carve-out — together they gut confidentiality — **Critical** (§3, §5, §6)
Working the confidentiality-scope chain end to end: the "Confidential Information" definition (§1.1) is broad — business plans, financial information, product designs, technical data, source code, customer lists, pricing — but that breadth is appropriate for an NDA and not itself a problem; a narrow definition would be the flag. The exclusions list (§3) is where it breaks down. Of the four standard NDA carve-outs, it has three — public availability, prior possession, rightful third-party receipt — and is missing the fourth: independent development without reference to the other Party's Confidential Information. That gap only matters because of §5: the Residuals clause lets anyone at Kestrel who has seen Brightloom's Confidential Information freely use any "ideas, concepts, know-how, or techniques" they retain in memory, "for any purpose," with no accounting or royalty, even if not intentionally memorized. On its own, an aggressive but not unheard-of clause. Combined with the missing carve-out, it's decisive: if Kestrel's team absorbs Brightloom's technical approach during due diligence and later builds something similar, Brightloom has no textual basis to argue Kestrel "independently developed" it — Kestrel doesn't need that defense, because §5 already gives it blanket cover. §6 compounds this further: the return/destroy obligation explicitly carves out anything retained under §5. Definition breadth, exclusions, and residuals interact to make the confidentiality promise in §2 — the entire reason this document exists — nearly unenforceable against Kestrel, and it applies by default with no breach or trigger event required.
**Recommend:** Narrow §5 to the standard formulation (residuals usable only if not consciously retained/copied, and excluding anything that would constitute use of a trade secret), and add an independent-development carve-out to §3. Both are common redlines a counterparty sending a boilerplate NDA will typically accept.

### 2. Injunctive relief runs one way only, contradicting the Agreement's own mutual framing — **High** (§7.2, §1.2)
§1.2 defines Disclosing Party and Receiving Party symmetrically — "a Party may act as both ... under this Agreement" — and §2's confidentiality obligations are written generically to apply to whichever Party is the Receiving Party at a given time. §7.2 breaks that pattern: instead of granting injunctive relief to "the Disclosing Party," it names "Kestrel Peak Holdings, LLC" specifically. Read literally, only Kestrel can go to court for an emergency injunction if Brightloom breaches; if Kestrel breaches (e.g., by misusing Brightloom's technical information beyond the Purpose), Brightloom has no equivalent fast-track remedy under this Agreement, only ordinary damages claims. That's a real asymmetry in leverage, not a drafting slip you can assume was accidental — every other operative clause in the Agreement is genuinely mutual.
**Recommend:** Replace "Kestrel Peak Holdings, LLC" in §7.2 with "the Disclosing Party" so the remedy runs both ways, consistent with §1.2.

### 3. Flat 5-year confidentiality term for a pre-engagement NDA, with a hard cutoff regardless of disclosure timing — **Medium** (§4)
Five years is long for an NDA signed before any engagement even exists — the stated Purpose (§ Recitals) is just to "explore a potential business relationship." A more typical range for this stage is 2–3 years. Worse, §4 ties confidentiality to a fixed Term rather than to each disclosure: information shared in year 4 only gets one year of protection before the obligation lapses entirely, and information shared right before expiration gets almost none. This is bounded (a known 5-year ceiling, not indefinite) and doesn't by itself create financial exposure, which is why it's Medium rather than High — but it's a real gap for whatever gets disclosed late in the Term.
**Recommend:** Shorten the Term to 2–3 years, or better, decouple confidentiality duration from the Term and instead run it a fixed period (e.g., 3 years) from each individual disclosure.

### 4. No venue or forum-selection clause — **Low** (§9.1)
Governing law (Washington) is specified, but no venue clause states where a dispute would actually be litigated.
**Recommend:** Add a venue clause (e.g., state or federal courts in King County, WA, or a neutral/mutually convenient forum) — low priority relative to items 1–3.

## Summary for the client

Highest-severity item first: **(1) the Residuals clause combined with the missing independent-development carve-out (§3/§5/§6)** is Critical — together they let Kestrel absorb and reuse Brightloom's technical know-how with no real confidentiality backstop, and it applies automatically, no breach required. **(2)** is High: the injunctive-relief right in §7.2 only protects Kestrel, breaking the mutual framing the rest of the Agreement sets up. **(3)** is Medium: a 5-year flat term is longer than this stage of the relationship warrants and creates a coverage gap for late-Term disclosures. **(4)** is Low: no venue clause. None of these are unusual or hard to fix — this reads like a client's boilerplate NDA template rather than a deliberately hostile draft — but as written it is not actually mutual despite the title. Recommend not signing until items 1–3 are addressed.
