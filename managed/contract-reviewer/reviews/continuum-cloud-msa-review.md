# Contract Review — Continuum Cloud Systems MSA

**Source document:** `fixtures/continuum-cloud-msa.txt`
**Document type:** Master Services Agreement (vendor-drafted, standard form)
**Reviewed for:** Solano Bio Analytics, Inc. (Client / prospective signatory)

## Parties

| Role | Entity | Jurisdiction | Address |
| --- | --- | --- | --- |
| Provider (vendor) | Continuum Cloud Systems, Inc. | Delaware corp. | 900 Congress Avenue, Suite 500, Austin, TX 78701 |
| Client | Solano Bio Analytics, Inc. | Delaware corp. | 4400 Bayshore Parkway, Suite 200, San Mateo, CA 94403 |

Governing law: Delaware (§11.6). No venue/forum-selection clause is present.

## Key Dates

| Date / Deadline | Trigger | Section |
| --- | --- | --- |
| Effective Date | Date of last signature (unsigned as of review) | Preamble |
| August 1, 2026 | Initial Term commences (per Order Form OF-2044) | Order Form OF-2044 |
| July 31, 2027 | Initial Term ends (12 months from Aug 1, 2026) | §3.1, OF-2044 |
| June 1, 2027 | Deadline to send written non-renewal notice — 60 days before Term end. Miss this and the contract auto-renews for another 12 months. | §11.7 |
| 30 days before each Renewal Term | Provider's deadline to notice a fee increase (no cap) | §4.4 |
| Net 90 days from invoice | Payment due date for undisputed invoices | §4.2 |
| Invoice due date + 30 days | Full remaining Term fees accelerate if unpaid | §4.2 |
| Invoice due date + 10 days' notice | Provider may suspend Services for nonpayment | §4.2 |
| 30 days from breach notice | Cure period before either party may terminate for cause | §9.1 |

## Obligations

**Client (Solano):**
- Pay Fees per Order Form; undisputed invoices due net-90 (§4.2).
- Provide reasonable cooperation, data access, and personnel to Provider (§2.2).
- Bear sales/use taxes, excluding Provider's income taxes (§4.3).
- Defend/indemnify Provider for claims arising from Client's data, breach, or unlawful use (§10.2).
- Give 60 days' written notice to avoid auto-renewal (§11.7); give 30 days' notice for termination-for-convenience, and pay a 50% early termination fee if it exits mid-term (§9.2).

**Provider (Continuum):**
- Perform Services in a "professional and workmanlike manner" per industry standards (§2.1) — no specific SLA or uptime commitment appears in the MSA body.
- Defend Client against third-party IP infringement claims tied to authorized use of the Services (§10.1).
- Warrant material conformance to documentation (§7.1), disclaim everything else (§7.2).
- Give 30 days' notice before raising fees at renewal (§4.4); give 60 days' notice to avoid auto-renewal (§11.7 — a mutual mechanism on paper, but Provider has no real incentive to invoke it).

## Red Flags

Severity scale: **Critical** (loss of a core asset or right) > **High** (uncapped or automatic financial/operational exposure) > **Medium** (bounded or conditional exposure) > **Low** (gap or drafting ambiguity, not an active claw-back). Listed highest severity first.

### 1. Broad IP assignment — Client's own commissioned work product belongs to the vendor — **Critical** (§6.2, §6.3)
Under §6.2, any Deliverable Continuum creates while performing the Services — custom configurations, integrations, dashboards, data models — is Continuum's exclusive property, even where it incorporates Solano's own Background IP (business logic, schemas, specs). Solano only gets a revocable, non-transferable license to use what it paid to have built. §6.3 goes further: any feedback or configuration data Solano provides is assigned to Continuum outright, with no compensation, for Continuum to build into its product for other customers. This is the only issue in the document that permanently gives away an asset rather than creating a financial or scheduling risk — it doesn't require any trigger event to bite, it applies to every Deliverable by default.
**Recommend:** Carve out Solano's own Background IP from the assignment in §6.2; narrow §6.3 to a license rather than an assignment, or strike it. Push back hardest here.

### 2. Unilateral, uncapped fee-increase right — **High** (§4.4)
Provider may raise Fees at every renewal with just 30 days' notice, and there's no cap — no CPI ceiling, no percentage limit. "Continued use... constitutes acceptance." This is guaranteed to recur at every renewal cycle with unbounded magnitude.
**Recommend:** Cap increases (e.g., greater of 5% or CPI), and/or make an increase above the cap a termination trigger without the §9.2 early-termination fee.

### 3. Auto-renewal with a 60-day cancellation window, buried in General Provisions — **High** (§11.7)
The Term section (§3) never mentions renewal — it just says the Agreement runs for the "Initial Term" and points forward to §9 and §11. The actual auto-renewal mechanism doesn't appear until §11.7, deep in boilerplate "General Provisions," after confidentiality, IP, warranties, liability, termination, and indemnification. This is the gating mechanism for #2: miss the June 1, 2027 deadline and Solano is locked into another 12 months at whatever price Continuum sets at renewal.
**Recommend:** Calendar the notice deadline now. Redline to move renewal language into §3, or require Provider to send an advance reminder before the notice deadline.

### 4. Net-90 payment terms stacked with suspension and full acceleration on late payment — **High** (§4.2)
Ninety days to pay looks generous, but the downside is severe and largely automatic: if payment slips past net-90, Continuum can suspend access on 10 days' notice, and if the invoice is still unpaid 30 days past its due date, the entire remainder of the Term's fees becomes immediately due. A single AP delay — not a real dispute — can trigger a bill for the full remaining contract value in one shot, which is a bigger single-event exposure than the capped early-termination fee in #5.
**Recommend:** Flag to Solano's finance team as a hard deadline. Extend the suspension cure period and strike or soften the acceleration clause.

### 5. Early-termination penalty on Client only — **Medium** (§9.2)
Client-initiated termination for convenience costs 50% of the remaining Term's fees, framed as "not a penalty." There is no symmetrical right for Client to terminate for convenience without penalty. Unlike #2–#4, this only triggers if Client affirmatively chooses to terminate early — it is within Solano's control to avoid, and the exposure is capped at a known 50% rather than open-ended.
**Recommend:** Negotiate the percentage down or to a declining schedule tied to months remaining, or trade it against #2's fee-increase cap.

### 6. Internal contradiction on whether indemnification is capped — **Medium** (§8.1, §10.1)
§8.1 explicitly excepts "either Party's indemnification obligations" from the liability cap, meaning indemnity claims should be uncapped. But §10.1 says Provider's IP-infringement indemnity is "subject to Section 8," which reads as capping it. These can't both be right, and it materially changes Solano's protection on an IP infringement claim.
**Recommend:** Get Continuum to confirm which provision controls before signature.

### 7. No SLA or uptime commitment in the MSA body — **Low** (§2.1)
§2.1 only commits to a "professional and workmanlike manner" standard — no uptime, response time, or credit terms.
**Recommend:** Confirm an SLA exists in Order Form OF-2044 or the Implementation SOW; if not, request one.

### 8. No forum/venue selection — **Low** (§11.6)
Governing law (Delaware) is specified, but no venue or forum for disputes.
**Recommend:** Add a venue clause for dispute-resolution clarity; low priority relative to items 1–6.

## Summary for the client

Highest-severity item first: **(1) IP assignment (§6.2/§6.3)** is Critical — it gives away ownership of Solano's own commissioned work by default, with no trigger required. Three **High** items follow and interact with each other: **(2)** uncapped fee increases **(3)** gated by a buried 60-day auto-renewal window, and **(4)** a net-90 payment term stacked with suspension and full-balance acceleration. **(5)** and **(6)** are Medium — a one-sided but capped early-termination fee, and a genuine drafting contradiction over whether indemnification is capped. **(7)** and **(8)** are Low — gaps to close, not active claw-backs. Recommend Solano not sign until at minimum items 1–4 are addressed.
