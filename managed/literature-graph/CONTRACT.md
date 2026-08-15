# literature-graph — deliverables contract

Nothing gets built until this is agreed. Every row below is a thing someone can
pick up and own.

Contract for the data itself is `managed/literature-graph/SCHEMA.md` (input JSON,
output JSON, guarantees, memory layout). Not repeated here.

---

## 1. System I/O

| | |
|---|---|
| **In** | `{graph_id?, ask, target, depth, reason}` — `SCHEMA.md` §Request |
| **Out** | full graph JSON — `SCHEMA.md` §Output |
| **State** | `/mnt/memory/literature-graph/` — Stage 1 owns it, Stage 2 never sends a graph |
| **Invocation** | `message` mode, `session_policy: "fresh"` |

Request arrives as the task string. One ask per request, one round per request.

---

## 2. Paperclip — a CLI, not an MCP server

> **Voided 2026-08-15 by spike run `sesn_01TsJ1p4AfH7zd9Msbe12ArF`.** This section
> previously read "MCP — Paperclip only" and framed the open question as a
> transport fork between *remote-HTTP MCP* and *stdio MCP*. Both branches were
> wrong: Paperclip exposes no MCP server at all. There is nothing to put in
> `manifest.mcp_servers`, and `vault_ids` is still needed but not for MCP OAuth.
> Ignore any earlier text or discussion describing "Paperclip MCP".

Paperclip is a Python CLI (`gxl-paperclip`, 0.7.36) over a REST API at
`https://paperclip.gxl.ai`. The deployed agent installs it into its own sandbox
and shells out to it. No MCP, and no host-side relay.

**Install, proven in the deployed sandbox:**

```bash
# NOT `pip install https://paperclip.gxl.ai/paperclip.whl` — the server serves the
# file under a name that violates PEP 427, and pip rejects it on the filename
# before downloading. Fetch first, rename from the archive's own .dist-info.
curl -sL -o /tmp/gxl_paperclip-0.7.36-py3-none-any.whl https://paperclip.gxl.ai/paperclip.whl
pip install /tmp/gxl_paperclip-0.7.36-py3-none-any.whl
```

`pip install gxl-paperclip` does **not** work — the PyPI simple index returns 200
for that name but carries no distributions.

**Auth:** a vault credential of type `environment_variable`, `secret_name:
"PAPERCLIP_API_KEY"`, `networking` limited to `paperclip.gxl.ai`,
`injection_location: {header: true}` — the CLI sends the key as an `X-API-Key`
header. The sandbox holds only a placeholder; the platform substitutes the real
value on outbound requests to that host. The credential id goes in
`manifest.vault_ids`. Provisioning is manual (`client.beta.vaults.create` then
`client.beta.vaults.credentials.create`); nothing in `scripts/` automates it.

**`literature-search` remains the only component that touches Paperclip** —
everything downstream consumes our normalized record. That seam was designed for
an unknown MCP tool surface and is worth keeping for an unknown CLI surface.

| capability | command |
|---|---|
| search | `paperclip search -s pmc,biorxiv,medrxiv "<query>"` |
| metadata | `paperclip cat /papers/<id>/meta.json` |
| full text | `paperclip cat /papers/<id>/...` — exact path TBD from `paperclip skill` |

Fallback if a capability is missing: Europe PMC REST via built-in `web_fetch`
(egress to `ebi.ac.uk` confirmed working in the sandbox).

---

## 3. Skills — three

Each: frontmatter `name` + `description` (description states what it does **and
what it does not decide**), failure-modes section is the longest part.

### `literature-search`
- **In** ask type, target, depth · **Out** normalized `papers[]` + raw text per paper
- Owns: query construction per ask type, tier→budget, pagination, Paperclip seam, normalization
- Failure modes: page 1 is not the corpus · `quick` may never report absence · query variants returning the same set · relevance ranking ≠ quality · preprint vs published

### `claim-extraction`
- **In** papers + text · **Out** `findings[]` with verbatim quotes
- Two modes: abstract-batch (5/pass, broad asks) · full-text-targeted (`resolve_link`, `test_gap`)
- Failure modes: hedging read as assertion · background citation read as new result · mechanism inferred from co-occurrence · effect sizes lost in normalization · figure captions asserting what the text hedges · Methods conditions not matching Results claims

### `graph-assembly`
- **In** new findings + papers + prior graph · **Out** merged scored graph
- SKILL.md is thin — it says run `assemble.py`, what it does, what breaks
- Everything deterministic lives in the script, not prose. Arithmetic described in
  prose does not reproduce.

---

## 4. `assemble.py` — spec

Stdlib only. No classes; plain dicts and pure functions, so every piece is
testable alone.

```
main(prior_dir, new_findings, new_papers, round_n, ask) -> graph dict
```

**Identity + dedup**
```
normalize_doi(s)                     -> str        strip https://doi.org/, lowercase
paper_key(paper)                     -> str        doi > pmid > normalized title+year
dedupe_papers(new, existing)         -> merged, id_map
normalize_name(s)                    -> str        lowercase, strip punct, greek→latin, singularize
resolve_entities(new, existing)      -> merged, id_map
```
`resolve_entities` matches a normalized name against every existing name **and
alias across the whole graph**, not just this round. Unmatched → new node. The
model proposes merges upstream; the script only applies them, so it stays
deterministic.

**Integrity**
```
verify_quote(quote, source_text)     -> bool       normalized-whitespace substring
```
Called before a finding is written. False → dropped, `no_quote_discarded += 1`.
This is the guarantee the whole system rests on; it must be a check, not a prompt.

**Scoring**
```
evidence_quality(findings, papers)   -> float      mean of study_type table, ×0.8 preprint
agreement(yes, no)                   -> float      0.5 + (yes-no)/(2*(yes+no)); 1 source → 0.5
independence(findings, papers)       -> float      (distinct first_authors - 1)/(papers - 1)
score_link(findings, papers)         -> dict       0.4*agreement + 0.4*quality + 0.2*independence
link_state(yes, no, no_effect)       -> str        agreed|disagreed|single_source|no_effect
link_basis(findings)                 -> str        primary|hedged_only|background_only|mixed
```
Findings with `is_own_result: false` are excluded from `agreement` and
`independence` — one review restating 40 studies is one paper.

**The boundary-condition detector** (the demo moment)
```
explain_disagreement(yes_f, no_f)    -> str | None
```
Partition the two camps, compare `where` / `section` values. Disjoint non-empty
sets → `"conditions differ: {A} vs {B}"`. Otherwise `None`. Populates `links.why`.

**Gaps**
```
find_gaps(links, things, cap=50)     -> list
```
Open triangles: for each node B, each neighbour pair (A,C) with no A–C link → a
gap. Rank by `min(confidence of the two supporting links)`, truncate to `cap`.
Degree-capped to keep it near-linear; growth is quadratic otherwise.

**Rounds**
```
round_outcome(prior_links, new_links) -> str       new_evidence|nothing_new|promoted|contradicted
mark_changed(prior_links, new_links, round_n)      sets changed_in_round
save_state(graph, dir)                             splits at 80KB, findings/r<N>.json
load_state(dir)                                    reassembles; missing dir → empty graph
```

Verification for the script: run it twice on the same inputs, byte-identical
output. Non-determinism here silently corrupts every score.

---

## 5. Artifacts

| artifact | source or compiled |
|---|---|
| `SCHEMA.md`, `BUILD.md` | done |
| `CLAUDE.md` | source — role, 4 asks, pipeline, tiers, memory layout, JSON skeleton |
| 3 × `SKILL.md` | source |
| `assemble.py` | source, bundled in `graph-assembly/` |
| `fixtures/` ×3 | source — well-studied, sparse, genuinely disputed |
| `manifest.json` | compiled — sonnet-5, message, fresh, Paperclip, `memory` block |
| `acl.ts` | compiled — `{ public: true }` |
| `agent/tools/literature-graph.ts` | compiled — eve wrapper |
| `render.html` | deferred until real data exists |

---

## 6. Steps to a running agent

| # | step | done when |
|---|---|---|
| 0 | ~~Spike~~ — **DONE 2026-08-15** | all four checks answered; see "Spike result" below |
| 1 | fixtures | 3 questions, each with a stated reason it's in the set |
| 2 | `CLAUDE.md` + 3 skills + `assemble.py` | `assemble.py` twice-run byte-identical on a fixture |
| 3 | hand-run in session on largest fixture | output validates against `SCHEMA.md` |
| 4 | `/managed-agent-deploy literature-graph` | deploy succeeds |
| 5 | smoke, blocking | six facts below |
| 6 | render | deferred |

### Spike result — agent `spike` v2, session `sesn_01TsJ1p4AfH7zd9Msbe12ArF`

| check | result |
|---|---|
| bundled script executes in sandbox | **yes** — skills materialize at `/workspace/skills/<name>/`, non-`SKILL.md` files included |
| `python3` present | **yes** — 3.11.15 at `/usr/local/bin/python3` |
| `/mnt/memory` writable | **yes** — mounts at `/mnt/memory/<store>/`, write→read roundtrip OK |
| Paperclip usable | **install and run yes; auth outstanding** — wheel installs clean including the compiled `rookiepy`, `--help` RC 0, `search` RC 1 `Not authenticated` |

Also observed: `/mnt/session/outputs` exists · `curl`, `jq`, `pip`, `pip3`, `uv`
present · **`sqlite3` ABSENT** (already ruled out by design, now confirmed) ·
egress open to `ebi.ac.uk`, `paperclip.gxl.ai` and `pypi.org`.

One unknown remains: whether the vault-injected `PAPERCLIP_API_KEY` placeholder
survives the CLI's local handling and gets substituted onto the outbound
`X-API-Key` header. It needs a real key to settle. Everything else is green, so
steps 1–3 are no longer gated.

**Smoke facts** (`bun run console literature-graph -- --once "$(cat fixtures/q-disputed.txt)"`):
1. Paperclip called at event level, not claimed in prose
2. reply carries full graph JSON, not a summary
3. disputed fixture yields ≥1 `state: "disagreed"` — zero is failure, not cleanliness
4. a low-confidence finding survives into output
5. second request loads round 1 from memory, `round` increments
6. three quotes spot-checked verbatim against their DOIs

---

## 7. Open, non-blocking

- ~~Paperclip transport → decided on sight~~ → **settled**: CLI installed
  in-sandbox, not MCP. See §2.
- ~~Bundled-script execution → spike step 0~~ → **settled**: works.
  `assemble.py` stays a bundled script; no host-side custom tool is needed, so
  `tools.ts` does not get built.
- **Paperclip API key — the one blocking item.** Needs minting from
  paperclip.gxl.ai. The local credentials are OAuth (`refresh_token` /
  `id_token`) and expire, so they cannot back a long-lived vault entry.
- `read_write` memory + fetched papers = injection surface. `CLAUDE.md` must state
  memory holds data, never instructions.
- `bun run console <name>` does **not** attach memory — test via `--once` only
