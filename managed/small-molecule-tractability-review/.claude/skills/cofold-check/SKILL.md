---
name: cofold-check
description: >
  Runs the four GPU structure tools — Boltz-2 cofolding, Boltz-2 affinity,
  ESMFold and BioEmu — through one callable module, returning each tool's
  numbers with its provenance, its per-run controls (seed dispersion, the site
  the seeds converged on, a positive-control log error, inter-chain contact
  counts) and the sample size behind every observation carried alongside. It
  does NOT find pockets, does NOT score druggability, does NOT rank targets,
  and does NOT apply a calibration or correction to any predicted value.
---

# cofold-check

One module, four functions, all in `predict.py` next to this file:

| function | proto-tools key | what it is for |
| --- | --- | --- |
| `cofold_complex(sequences, ligand_smiles=None, ...)` | `boltz2-prediction` | pose and geometry for a site you already found |
| `cofold_affinity(protein, ligand_smiles, ...)` | `boltz2-affinity` | **ranking** ligands within one target |
| `esmfold_predict(sequence, ...)` | `esmfold-prediction` | fast monomer fold + the model's own confidence |
| `bioemu_ensemble(sequence, n_samples, ...)` | `bioemu-sample` | backbone conformational ensemble |

Every function returns a `dict` carrying the numbers, a `provenance` block, and
the per-run controls. None of them returns a bare score.

## How these are invoked — read this before writing any call

**Plain Python import, in process. Not MCP. Not a CLI.** The prose elsewhere
implies a tool-server; there isn't one. This is the same pattern as
`structure-select`'s Foldseek call.

```python
from predict import cofold_complex, cofold_affinity, esmfold_predict, bioemu_ensemble

result = cofold_affinity(
    protein=JAK1_KINASE_DOMAIN,
    ligand_smiles=[candidate_smiles],
    positive_control_smiles=TOFACITINIB,
    positive_control_measured_nm=0.50,
)
```

Run it under the **proto-tools python** — the venv that has `proto_tools`
installed. Set `PROTO_PY` to that interpreter and invoke `$PROTO_PY your.py`.
Importing under any other interpreter raises with that instruction.

Execution is on Modal (`device="modal"`, the default), workspace `rafwiewiora`,
environment `proto-env`, apps `proto-tools-boltz2`, `proto-tools-esmfold`,
`proto-tools-bioemu`.

**Credentials come from the environment only.** `MODAL_TOKEN_ID` +
`MODAL_TOKEN_SECRET`, or `MODAL_PROFILE` with a `~/.modal.toml`. The module
never reads a dotenv file by path — it will run in sandboxes where no such path
exists — and it raises a named error when credentials are absent rather than
failing deep inside a dispatch.

## The verbatim signatures these wrap

Recorded from the proto-tools source, not from documentation:

```python
# proto_tools/tools/structure_prediction/boltz2/boltz2.py
run_boltz2(inputs: Boltz2Input, config: Boltz2Config, instance: Any = None) -> Boltz2Output

# proto_tools/tools/structure_prediction/boltz2/boltz2_affinity.py
run_boltz2_affinity(inputs: Boltz2AffinityInput, config: Boltz2AffinityConfig, instance: Any = None) -> Boltz2AffinityOutput

# proto_tools/tools/structure_prediction/esmfold/esmfold.py
run_esmfold(inputs: ESMFoldInput, config: ESMFoldConfig, instance: Any = None) -> ESMFoldOutput

# proto_tools/tools/structure_dynamics/bioemu/bioemu_sample.py
run_bioemu(inputs: BioEmuInput, config: BioEmuConfig, instance: Any = None) -> BioEmuOutput
```

Complexes are built as `{"chains": [{"sequence": ..., "entity_type": "protein"},
{"smiles": ..., "entity_type": "ligand"}]}`. Boltz-2 advances the seed per
complex (`base_seed + dispatch_idx`), which is how `n_seeds` is implemented:
the same complex is submitted N times in one call and comes back on N seeds
through one container warm-up.

## What is a measurement here and what is an anecdote

This is the distinction the whole module is built around, so it is worth
stating before the failure modes.

**Per-run measurements** — recomputed on every call, safe to act on:

- `seed_dispersion` — ligand-centroid and backbone spread across seeds;
- `converged_site` — which residues the ligand actually contacted, and whether
  the seeds agreed;
- `control` in `cofold_affinity` — the log error against a known binder **on
  your target, in this run**;
- `interface` — inter-chain CA contact count, closest approach, COM separation;
- `cofold_control` — CA RMSD of the cofold against a crystal structure you
  supply;
- `frame_caveats.atoms_in_first_frame_THIS_RUN` — re-verifies the BioEmu frame
  format instead of asserting it.

**Single-case observations** — carried in the payload under
`single_target_observations` / `single_compound_observations` /
`single_complex_observations`, every one stating its sample size and
`benchmarked: False`. They are **not** applied to any returned number, as a
correction, a gate or a downweighting:

| observation | n | what it is |
| --- | --- | --- |
| KRAS sealed-pocket confidence | **1 target, 1 mutant** | the nine-phenylalanine mutant scored *higher* than wild type on every pLDDT-family metric (complex pLDDT 0.940 → 0.957) and landed 0.73 Å from wild type against a 1.02 Å wild-type-vs-wild-type baseline |
| tofacitinib affinity error | **1 compound** | predicted 46.4 nM against 0.50 nM measured — 1.97 log units — with correct ordering and 2.36 log separation from decoys |
| IL-17A ESMFold dimer | **1 complex** | 1 inter-chain CA-CA pair against 97 deposited, TM 0.328, and pTM/PAE moved sharply (0.905/3.66 → 0.399/18.26) |
| seed dispersion / site convergence | 1 target, 24 runs | median 0.21 Å dispersion, and 21 of 24 runs on a real site that was **not the one asked about** |

**Why they are not baked in.** Each is a conclusion about a tool drawn from one
example, and this project exists to refuse exactly that reasoning. One compound
does not establish a bias term; one complex does not establish that a method
fails at interfaces; one target does not establish that confidence is
anti-diagnostic in general. A reader who sees "one compound, 1.97 log, not
benchmarked" can use it. A reader who sees a correction constant will trust it.
A cross-target benchmark is running separately — when it lands, `OBSERVATIONS`
in `predict.py` is the only thing that needs revisiting, because no returned
number was ever adjusted by any of it.

The seed statistics **within** a target are sound; whether the magnitude
transfers is unknown, which is why dispersion is recomputed every call rather
than assumed.

## Failure modes

### 1. Un-superposed frames fabricate a dispersion number

Boltz-2 emits every diffusion sample in **its own arbitrary coordinate frame**.
Taking ligand centroids straight off the raw CIFs measured **15.57 Å** of
"seed dispersion" between two seeds whose ligand-contact residue sets were
**identical** — a number produced entirely by the frames not being aligned. The
same pair after protein-CA superposition: **0.045 Å**.

This is the single most dangerous thing in this module, because 15.57 Å is a
plausible-looking answer to "how much do the seeds disagree" and it is pure
artifact. `_ligand_centroids_common_frame` superposes first, always, and a
rigid-body control (rotate + translate one structure by 40 Å) returns 0.000.

If you compute any cross-seed or cross-frame geometry yourself, superpose
first, and verify with a rigid-body control before believing the number.

### 2. High seed agreement is not evidence the site is right

`converged_site` returns a `caution` string on every call for this reason. On
KRAS, 21 of 24 runs landed on SI/II-P at a median 0.21 Å dispersion when the
question was about switch-II. A real site, tight agreement, wrong question.

**So always read `converged_site.consensus_contact_residues` against the site
you intended, and never treat `seed_agreement_fraction` as validation.** In the
JAK1 test the consensus was 21 residues at agreement 1.0 covering the ATP site
— hinge Glu93/Leu95, gatekeeper Met92, catalytic Lys44 in kinase-domain
numbering (offset +864 to UniProt) — which is correct, and it is correct
because the residues were checked, not because the seeds agreed.

### 3. Cofolding runs from SEQUENCE, so it cannot see your structure

Apo and holo structures of one protein usually share a sequence, so a
sequence-only cofold cannot distinguish them. This is not a pocket finder and
it is not a way to test a collapsed pocket. Use it downstream of a site you
already have.

### 4. The "97 contacts" figure is a PAIR count, not a residue count

Re-verified here against 8DYG: **97 CA-CA pairs** within 8 Å, but only **29
residues-in-contact**. Quoting a residue count against the 97 compares two
different quantities and understates the reference by 3.3×. `_inter_chain_ca_contacts`
returns both and labels which is which; `contacts` is the comparable one.

### 5. BioEmu rejects multimers outright — the linker is the only route

`BioEmuInput` validates `comp.num_chains() != 1` and raises *"BioEmu only
supports single-chain proteins (monomers)"*. `bioemu_ensemble` therefore joins
chains with a poly-glycine linker (default 8, range 5–10) and records in
`linker`: that one was inserted, its sequence and length, the **0-indexed
residue range of every linker**, and the range of every original chain.

Verified on a 2×60 construct: linker at residues **60–67**, chains at **0–59**
and **68–127**.

**A linker changes what the ensemble means.** It is a covalently tethered
construct, not the biological assembly: inter-chain distances are constrained
by the tether and the relative-orientation distribution is not the free one.
Strip the recorded linker ranges before any pocket detection or RMSD, and never
report an inter-chain measurement off these frames as free-solution.

### 6. BioEmu's sanity filter crashes when it actually rejects a frame

Reproduced, twice. When the physical filter rejects frames, upstream writes a
`*_unphysical.xtc` and then dies parsing its own filename:

```
ValueError: Invalid suffix '_unphysical.xtc'
```

It surfaces as `TypeError: Tool 'bioemu-sample' result does not conform to
BioEmuOutput: ... ensembles Field required` — and **the `_unphysical` string
does not survive into that message**, even down the `__cause__` chain, so a
naive `except` matching on it will not fire. `bioemu_ensemble` walks the whole
exception chain and also matches the output-shape signature.

A glycine-linked construct is exactly the input most likely to produce
rejectable frames, so **the multimer path walks into this every time**. The
module retries once with `filter_samples=False` and records
`filter_fallback.triggered = True`. When it fires, **the returned frames were
not sanity-checked** — clashes and chain breaks may be present. Filter on
radius of gyration, SASA and secondary-structure sanity before scoring.

The monomer path (KRAS 169, 8 samples) did **not** trigger it.

### 7. BioEmu frames have no side chains and no confidence

Confirmed again on both test runs: **835 atoms / 169 residues** (monomer) and
**628 atoms / 128 residues** (linked multimer) — about 4.9 atoms per residue,
i.e. backbone + C-beta only. Residues are zero-indexed and all B-factors are
zero, so there is **no per-frame confidence to read**.

fpocket and mdpocket define pockets from side-chain atoms, so **these frames
must be repacked before pocket detection** or every volume is inflated. Frames
arrive pre-superposed, so no alignment step is needed.
`frame_caveats.atoms_in_first_frame_THIS_RUN` re-checks this per run — divide
by `residues_folded` and confirm it is ~5.

### 8. Nothing here emits a potency

`cofold_affinity`'s primary output is `ranking`. The absolute value is returned
under `absolute` as `affinity_pred_value_log10_ic50_um`, marked `is_a_kd:
False`, `is_a_potency_measurement: False`, `benchmarked_against_measured_affinities:
False` and `correction_applied: None`.

The reason is that **this head has not been benchmarked against measured
affinities here**, so the relationship between its output and a real potency is
unknown. Do not compare it against a nanomolar threshold and do not quote it as
a Kd or an IC50.

Ranks are **within-target only**. A ranking of one ligand is not a ranking, and
`ranking_usable` is `False` when fewer than two ligands scored.

### 9. Run the positive control, and read it as a check not a calibration

Pass `positive_control_smiles` + `positive_control_measured_nm` and the control
runs in the same call. It reports `log_error` and sets `reliable` against a
1-log threshold (dossier rule 12).

Measured on JAK1 / tofacitinib: predicted −1.333 log10(IC50 µM) against 0.50 nM
measured, **log_error 1.968, reliable: False** — while the ranking put
tofacitinib first with **2.43 log units** of separation from an ibuprofen
decoy and binder probabilities 0.754 vs 0.107.

`reliable: False` means the absolute values are uninformative **for this
target**. It does not by itself condemn the ranking. The control's `scope`
field says plainly that it is one compound and is not applied as an offset to
the other ligands.

### 10. `cofold_control` refuses rather than mis-pairs

Pass `reference_structure` to `cofold_complex` (a `Structure`, a file path, or
raw PDB/CIF text) and it returns CA RMSD of each seed against that reference,
filling the dossier's `structure.cofold_control`.

Residue matching is strict: **if the CA counts do not match, no number is
emitted** and the reason is returned instead, because a silently mis-paired
RMSD is worse than a null. Verified — self-reference 0.0, rigid-body copy 0.0,
0.5 Å isotropic noise 0.905 (expected 0.866), mismatched chain `None` with a
reason.

`reproduces_reference` and `trusted` are returned **null on purpose**. They are
judgements, and there is no calibrated RMSD threshold to make them from —
one would have to come from a cross-target benchmark that does not exist yet.

## Cost

GPU time on Modal, warm containers, from the test runs:

| call | wall clock |
| --- | --- |
| ESMFold monomer (KRAS 169 aa) | 25.4 s |
| ESMFold dimer (IL-17A 2×132) | 3.1 s |
| Boltz-2 cofold, 1 protein + ligand, 2 seeds (JAK1 290 aa) | 64.7 s |
| Boltz-2 cofold, 2 protein chains, 1 seed (IL-17A) | 15.8 s |
| Boltz-2 affinity, 2 ligands (JAK1 290 aa) | 77.9 s |
| BioEmu, 169 aa, 8 samples | 23.9 s |
| BioEmu, 128 aa linked, 4 samples, incl. filter retry | 40.7 s |

Cold starts are much worse — the first affinity call of a session took ~250 s,
most of it container connect. MSA generation (MMseqs2) is a separate remote
service and costs no GPU, but it is a large part of first-call latency.

**Keep `n_seeds` and `n_samples` low while iterating.** `n_seeds` multiplies GPU
time roughly linearly; `diffusion_samples_affinity` defaults to 5 internally
already.

## What these four tools are actually for

Stated bluntly, because the honest answer is narrower than the tool list
suggests:

- **`cofold_affinity` — the most useful of the four.** Ranking candidates within
  one target, with a positive control run in the same call. That is a real job
  and nothing else here does it.
- **`cofold_complex` — a pose and geometry step downstream of a site you already
  found.** Its per-run value is `converged_site` (where did the ligand actually
  go) and `cofold_control` (does it reproduce a crystal structure you have). Its
  confidence numbers are structural-confidence metrics and answer "how sure is
  the model about the geometry it drew", which is not the dossier's question.
- **`esmfold_predict` — a fast monomer folder** that reports its own confidence.
  Cheap enough to run as a triage step.
- **`bioemu_ensemble` — the weakest link in the pipeline as it stands.** Its
  frames cannot be scored without a repacking step this module does not
  provide, it has no per-frame confidence, and the literature figure for
  generative ensembles on apo input (56% cryptic-pocket recovery, against 86%
  from holo) applies to our normal case. Treat anything downstream of it as
  triage, and say so.
