"""cofold-check — the four GPU proto-tools, called in process, each returning
its numbers together with the provenance needed to judge them.

Run this under the proto-tools python (it imports ``proto_tools`` directly —
plain Python import, in-process; not MCP, not a CLI). Modal credentials come
from the environment / ``~/.modal.toml``; nothing here reads a hard-coded
dotenv path.

    from predict import cofold_complex, cofold_affinity, esmfold_predict, bioemu_ensemble

WHAT THIS MODULE WILL AND WILL NOT DO
-------------------------------------
It computes, per run, the things that are measurable per run:

* seed dispersion, and WHICH SITE the seeds converged on (``cofold_complex``);
* a rank ordering plus a positive-control log error (``cofold_affinity``);
* the model's own confidence and the inter-chain contact count
  (``esmfold_predict``);
* the linker that had to be inserted to reach a multimer (``bioemu_ensemble``).

It does NOT ship a calibration constant for any of these tools, and it does not
declare any of them unreliable. We have single-case observations that look like
they should generalise — one compound, one complex, one target — and the whole
point of this project is to refuse conclusions drawn from one example. Those
observations are carried in ``OBSERVATIONS`` with their sample size stated and
``benchmarked: False`` on every one, so a reader can weigh them. A proper
benchmark is running separately; when it lands, ``OBSERVATIONS`` is what needs
re-checking, and nothing downstream will need un-picking because no correction
was ever applied to a returned number.
"""

from __future__ import annotations

import math
import os
import statistics
import time
from itertools import combinations
from pathlib import Path
from typing import Any

__all__ = [
    "OBSERVATIONS",
    "bioemu_ensemble",
    "cofold_affinity",
    "cofold_complex",
    "esmfold_predict",
]

# ---------------------------------------------------------------------------
# OBSERVATIONS
#
# Things we have actually seen on our own targets. Every entry states its
# sample size and carries ``benchmarked: False``. NONE of these is applied to a
# returned number as a correction, a gate or a downweighting. They are attached
# to the payload so a caller can weigh them, and that is all.
#
# The distinction that matters: "n=1 target" observations describe one thing
# that happened. Per-run quantities (seed dispersion, the positive-control log
# error, the contact count) are recomputed fresh on every call and are the
# numbers you should actually act on.
# ---------------------------------------------------------------------------
OBSERVATIONS: dict[str, Any] = {
    "kras_sealed_pocket_confidence": {
        "what_was_measured": (
            "Whether any Boltz-2 output signal reports that a binding site has "
            "been destroyed."
        ),
        "how": (
            "KRAS switch-II pocket sealed shut with nine phenylalanine "
            "substitutions (physically undruggable by construction), folded, "
            "and compared against wild type."
        ),
        "sample_size": {"targets": 1, "target": "KRAS", "mutants": 1, "seeds": 2},
        "replicated_on_other_targets": False,
        "benchmarked": False,
        "generalises": "UNKNOWN — one target, one mutant. Not tested elsewhere.",
        "result": {
            "complex_plddt_wild_type": 0.940,
            "complex_plddt_nine_phe_mutant": 0.957,
            "confidence_wild_type": 0.919,
            "confidence_nine_phe_mutant": 0.927,
            "mutant_scored_higher_on": "every pLDDT-family metric",
            "ca_rmsd_mutant_vs_wild_type_a": 0.73,
            "ca_rmsd_wild_type_vs_wild_type_baseline_a": 1.02,
            "only_metric_that_moved": "average PAE",
        },
        "what_it_shows": (
            "On THIS target, the confidence numbers did not notice that the "
            "pocket was gone — the sealed mutant scored higher than wild type "
            "and its backbone landed closer to wild type than two wild-type "
            "seeds landed to each other."
        ),
        "what_it_does_not_show": (
            "That cofolding confidence is anti-diagnostic for druggability in "
            "general. That is a claim about the method drawn from one target, "
            "and this module does not make it."
        ),
    },
    "tofacitinib_affinity_error": {
        "what_was_measured": (
            "How far the Boltz-2 affinity value head landed from a measured "
            "potency, for one compound."
        ),
        "how": "JAK1 kinase domain vs tofacitinib, plus two unrelated negatives.",
        "sample_size": {"targets": 1, "target": "JAK1", "compounds": 1, "compound": "tofacitinib", "decoys": 2},
        "replicated_on_other_compounds": False,
        "benchmarked": False,
        "generalises": (
            "UNKNOWN — ONE COMPOUND. A per-compound offset measured once is a "
            "data point, not a bias term. It is deliberately NOT applied as a "
            "correction anywhere in this module."
        ),
        "result": {
            "ligand": "tofacitinib",
            "measured_nm": 0.50,
            "predicted_nm": 46.4,
            "signed_log_error": 1.97,
            "error_direction": "predicted weaker than measured",
            "separation_active_vs_decoys_log_units": 2.36,
            "ordering_correct": True,
            "binder_probability_active": 0.75,
            "binder_probability_decoys": [0.37, 0.11],
        },
        "what_it_shows": (
            "On this one compound the ordering was right and the separation "
            "from decoys was large, while the absolute value was far from the "
            "measured potency."
        ),
        "what_it_does_not_show": (
            "A calibration. One compound cannot establish a bias, a direction "
            "that holds, or a magnitude that transfers to another chemotype or "
            "another target."
        ),
    },
    "il17a_esmfold_dimer": {
        "what_was_measured": "ESMFold's inter-chain geometry on one homodimer.",
        "how": "IL-17A mature chain (24-155) folded as a 2-chain input, compared to deposited 8DYG.",
        "sample_size": {"complexes": 1, "complex": "IL-17A homodimer"},
        "replicated_on_other_complexes": False,
        "benchmarked": False,
        "generalises": "UNKNOWN — one complex.",
        "result": {
            "inter_chain_contacts_predicted": 1,
            "inter_chain_contacts_reference": 97,
            "contact_definition": "CA-CA pairs within 8.0 A between the two chains",
            "contact_definition_note": (
                "Re-verified here: 8DYG gives 97 CA-CA PAIRS but only 29 "
                "residues-in-contact. The 97 is a PAIR count. A residue count "
                "is a different, smaller number and is not comparable to it."
            ),
            "min_inter_chain_ca_predicted_a": 7.30,
            "min_inter_chain_ca_reference_a": 4.04,
            "com_separation_predicted_a": 24.73,
            "com_separation_reference_a": 12.81,
            "dimer_tm_score": 0.328,
            "monomer_tm_score": 0.446,
            "ptm_dimer": 0.399,
            "ptm_monomer": 0.905,
            "avg_pae_dimer": 18.26,
            "avg_pae_monomer": 3.66,
        },
        "what_it_shows": (
            "On this one dimer the predicted chains barely touched, AND the "
            "model's own pTM and PAE moved sharply between the monomer and the "
            "dimer — i.e. the per-run self-report tracked the per-run outcome."
        ),
        "what_it_does_not_show": (
            "That ESMFold is unreliable at interfaces as a general property. "
            "One complex. ``esmfold_predict`` therefore returns the self-report "
            "and the contact count and does not gate, flag or downweight on "
            "this basis."
        ),
    },
    "seed_dispersion_and_site_convergence": {
        "what_was_measured": (
            "How far apart reseeded cofolds land, and whether they land on the "
            "site that was asked about."
        ),
        "how": "Eight seeds of one probe; 24 probe runs across the seed sweep, on KRAS.",
        "sample_size": {"targets": 1, "target": "KRAS", "runs": 24, "seeds_one_probe": 8},
        "replicated_on_other_targets": False,
        "benchmarked": False,
        "generalises": (
            "The seed statistics within this target are sound; whether the "
            "magnitude transfers to other targets is UNKNOWN. This is why "
            "dispersion is RECOMPUTED on every call rather than assumed."
        ),
        "result": {
            "median_pairwise_centroid_dispersion_a": 0.21,
            "seeds_within_0.2_a": "7 of 8",
            "runs_converging_on_one_site": "21 of 24",
            "site_converged_on": "SI/II-P",
            "site_asked_about": "switch-II",
        },
        "what_it_shows": (
            "Tight seed-to-seed agreement coexisted with the runs landing on a "
            "real site that was NOT the site the question was about. So "
            "agreement between seeds is not by itself evidence that the site is "
            "the right one — which is why ``cofold_complex`` returns the "
            "contact residues and makes the caller check them."
        ),
    },
    "bioemu_frame_format": {
        "what_was_measured": "The literal content of BioEmu output frames.",
        "how": "Inspection of a 169-residue KRAS ensemble.",
        "sample_size": {"ensembles": 1, "frames": 16},
        "benchmarked": False,
        "generalises": (
            "This one is a FORMAT property of the tool's output, not a "
            "performance claim, and it is re-checkable on any run: count the "
            "atoms and read the B-factor column."
        ),
        "result": {
            "atoms_per_frame": 835,
            "residues": 169,
            "side_chains_present": False,
            "frames_pre_superposed": True,
            "max_com_spread_a": 0.045,
            "optimal_rotation_from_identity_a": 5e-8,
            "residue_indexing": "zero-indexed",
            "b_factors": "all zero — there is no per-frame confidence",
        },
        "consequence": (
            "Repack side chains before any fpocket / mdpocket run: those tools "
            "define pockets from side-chain atoms, so unrepacked frames inflate "
            "every volume. No alignment step is needed — frames arrive "
            "superposed."
        ),
    },
    "generative_ensembles_on_apo_LITERATURE": {
        "source": "external literature, NOT measured by us",
        "benchmarked_by_us": False,
        "result": {
            "cryptic_pocket_recovery_from_holo_seed": 0.86,
            "cryptic_pocket_recovery_from_apo_seed": 0.56,
            "also_reported": (
                "over-population of partially unfolded and over-extended "
                "conformations; no method reliably predicts the absolute "
                "probability that a pocket is open; all fail below 1% occupancy"
            ),
        },
        "consequence": (
            "Filter frames on radius of gyration, SASA and secondary-structure "
            "sanity before scoring, and do not report a sampled open-state "
            "population as a measurement. Apo is our normal case."
        ),
    },
}

# Contact definition reused everywhere so numbers are comparable across calls
# and comparable to the IL-17A reference figures.
_CA_CONTACT_CUTOFF_A = 8.0
_LIGAND_CONTACT_CUTOFF_A = 4.5

# BioEmu multimer linker. The tool itself rejects >1 chain, so a linker is the
# only route to a multimer ensemble; 5-10 glycines is the working range.
_BIOEMU_LINKER_MIN = 5
_BIOEMU_LINKER_MAX = 10
_BIOEMU_LINKER_DEFAULT = 8

# Rule 12: a predictor that cannot recover a known potent binder within one log
# is uninformative for absolute values on this target. This is a threshold the
# caller applies to a FRESHLY MEASURED control, not a stored correction.
_CONTROL_LOG_THRESHOLD = 1.0


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def _require_proto_tools() -> None:
    """Fail loudly and usefully if we are not under the proto-tools python."""
    try:
        import proto_tools  # noqa: F401, PLC0415
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "proto_tools is not importable. This module must run under the "
            "proto-tools python interpreter (the venv that has proto_tools "
            "installed); set PROTO_PY to it and invoke `$PROTO_PY predict.py`. "
            "It is a plain in-process import — there is no MCP server and no "
            "CLI to call instead."
        ) from exc


def _require_modal(device: str) -> None:
    """Check Modal credentials are reachable from the ENVIRONMENT.

    Deliberately does NOT read any dotenv file by path: this module is
    expected to run in sandboxes where no such path exists.
    """
    if device != "modal":
        return
    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return
    if (Path.home() / ".modal.toml").is_file():
        return
    raise RuntimeError(
        "device='modal' but no Modal credentials found. Set MODAL_TOKEN_ID and "
        "MODAL_TOKEN_SECRET in the environment, or set MODAL_PROFILE with a "
        "~/.modal.toml present. Credentials are read from the environment only; "
        "this module never reads a dotenv file by path. Pass device='cpu' to "
        "run locally instead (slow)."
    )


def _prov(
    tool_key: str,
    config: Any,
    *,
    device: str,
    wall_s: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Provenance block. Every returned dict carries one."""
    out: dict[str, Any] = {
        "tool": tool_key,
        "invocation": "proto_tools python import, in-process",
        "device": device,
        "wall_clock_s": round(wall_s, 1),
        "config": {
            k: getattr(config, k, None)
            for k in (
                "seed",
                "use_msa",
                "recycling_steps",
                "sampling_steps",
                "diffusion_samples",
                "diffusion_samples_affinity",
                "num_recycles",
                "chain_linker",
                "num_samples",
                "model_name",
                "filter_samples",
                "denoiser_type",
            )
            if hasattr(config, k)
        },
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Geometry helpers (gemmi, via the Structure entity's CIF/PDB text)
# ---------------------------------------------------------------------------
def _gemmi_model(structure: Any) -> Any:
    import gemmi  # noqa: PLC0415

    st = gemmi.read_structure_string(structure.structure_cif)
    st.setup_entities()
    return st[0]


def _ca_by_chain(structure: Any) -> dict[str, list[tuple[float, float, float]]]:
    model = _gemmi_model(structure)
    out: dict[str, list[tuple[float, float, float]]] = {}
    for chain in model:
        pts = []
        for res in chain:
            atom = res.find_atom("CA", "*")
            if atom is not None:
                pts.append((atom.pos.x, atom.pos.y, atom.pos.z))
        if pts:
            out[chain.name] = pts
    return out


def _het_atoms(structure: Any) -> dict[str, list[tuple[float, float, float]]]:
    """Non-polymer (ligand) heavy atoms, keyed by chain name."""
    import gemmi  # noqa: PLC0415

    model = _gemmi_model(structure)
    out: dict[str, list[tuple[float, float, float]]] = {}
    for chain in model:
        pts = []
        for res in chain:
            info = gemmi.find_tabulated_residue(res.name)
            if info is not None and info.is_amino_acid():
                continue
            if res.name in ("HOH", "WAT"):
                continue
            for atom in res:
                if atom.element.name != "H":
                    pts.append((atom.pos.x, atom.pos.y, atom.pos.z))
        if pts:
            out[chain.name] = pts
    return out


def _centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float] | None:
    if not points:
        return None
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _inter_chain_ca_contacts(structure: Any, cutoff: float = _CA_CONTACT_CUTOFF_A) -> dict[str, Any]:
    """Inter-chain CA contacts between the first two protein chains.

    ``contacts`` is the CA-CA PAIR count under ``cutoff``. That is the exact
    definition behind the IL-17A reference figures (1 predicted vs 97
    deposited), verified by re-running the original comparison: 8DYG gives 97
    pairs but only 29 residues-in-contact, so a residue count is NOT the
    documented number. Both are returned; ``contacts`` is the comparable one.
    """
    ca = _ca_by_chain(structure)
    names = [n for n in ca if len(ca[n]) > 1]
    if len(names) < 2:
        return {
            "n_protein_chains": len(names),
            "contacts": None,
            "residues_in_contact": None,
            "min_inter_chain_ca_a": None,
            "com_separation_a": None,
            "definition": None,
            "note": "single protein chain — no interface to measure",
        }
    a, b = ca[names[0]], ca[names[1]]
    dists = [[_dist(pa, pb) for pb in b] for pa in a]
    n_pairs = sum(1 for row in dists for d in row if d < cutoff)
    n_res = sum(1 for row in dists if min(row) < cutoff)
    ca_a, ca_b = _centroid(a), _centroid(b)
    return {
        "n_protein_chains": len(names),
        "chains_compared": [names[0], names[1]],
        "contacts": n_pairs,
        "residues_in_contact": n_res,
        "min_inter_chain_ca_a": round(min(min(row) for row in dists), 2),
        "com_separation_a": round(_dist(ca_a, ca_b), 2) if ca_a and ca_b else None,
        "definition": (
            f"CA-CA pairs within {cutoff} A between chains {names[0]} and "
            f"{names[1]}"
        ),
    }


def _ligand_contact_residues(structure: Any, cutoff: float = _LIGAND_CONTACT_CUTOFF_A) -> list[str]:
    """Protein residues (as 'CHAIN:NUM:RESNAME') within `cutoff` of any ligand heavy atom."""
    import gemmi  # noqa: PLC0415

    het = _het_atoms(structure)
    lig_pts = [p for pts in het.values() for p in pts]
    if not lig_pts:
        return []
    model = _gemmi_model(structure)
    hits: list[str] = []
    for chain in model:
        for res in chain:
            info = gemmi.find_tabulated_residue(res.name)
            if info is None or not info.is_amino_acid():
                continue
            for atom in res:
                if atom.element.name == "H":
                    continue
                p = (atom.pos.x, atom.pos.y, atom.pos.z)
                if any(_dist(p, lp) < cutoff for lp in lig_pts):
                    hits.append(f"{chain.name}:{res.seqid.num}:{res.name}")
                    break
    return hits


def _res_sort_key(label: str) -> tuple[str, int]:
    chain, num, _ = label.split(":", 2)
    return (chain, int(num))


def _pairwise_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n_pairs": 0, "median_a": None, "min_a": None, "max_a": None}
    return {
        "n_pairs": len(values),
        "median_a": round(statistics.median(values), 3),
        "min_a": round(min(values), 3),
        "max_a": round(max(values), 3),
    }


def _kabsch(mobile: list[tuple], target: list[tuple]) -> tuple[Any, Any, Any]:
    """Rotation + centroids superposing `mobile` onto `target`."""
    import numpy as np  # noqa: PLC0415

    p = np.asarray(mobile, dtype=float)
    q = np.asarray(target, dtype=float)
    pc, qc = p.mean(0), q.mean(0)
    h = (p - pc).T @ (q - qc)
    u, _s, vt = np.linalg.svd(h)
    d = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(vt.T @ u.T)))])
    return vt.T @ d @ u.T, pc, qc


def _ligand_centroids_common_frame(structures: list[Any]) -> list[tuple[float, float, float]]:
    """Ligand centroids after superposing every structure's protein CA onto the first.

    WHY: Boltz-2 emits each sample in its own arbitrary coordinate frame. Taking
    ligand centroids straight off the raw CIFs measured 15.57 A of "dispersion"
    between two seeds whose ligand-contact residue sets were IDENTICAL — a
    number produced entirely by the frames not being aligned. Superpose first,
    always. Verified with a rigid-body control: a rotated and translated copy of
    one structure now returns 0.000 A.
    """
    import numpy as np  # noqa: PLC0415

    ref_ca = _ca_by_chain(structures[0])
    out: list[tuple[float, float, float]] = []
    for i, st in enumerate(structures):
        pts = [p for chain_pts in _het_atoms(st).values() for p in chain_pts]
        c = _centroid(pts)
        if c is None:
            continue
        if i == 0:
            out.append(c)
            continue
        ca = _ca_by_chain(st)
        shared = [k for k in ref_ca if k in ca and len(ref_ca[k]) == len(ca[k])]
        if not shared:
            continue  # cannot superpose -> refuse to emit a number
        mob = [p for k in shared for p in ca[k]]
        tgt = [p for k in shared for p in ref_ca[k]]
        rot, pc, qc = _kabsch(mob, tgt)
        moved = rot @ (np.asarray(c) - pc) + qc
        out.append((float(moved[0]), float(moved[1]), float(moved[2])))
    return out


def _load_reference(reference: Any) -> Any:
    """Accept a Structure, a file path, or raw PDB/CIF text."""
    from proto_tools.entities.structures import Structure  # noqa: PLC0415

    if hasattr(reference, "structure_cif"):
        return reference
    text = str(reference)
    if "\n" not in text and Path(text).is_file():
        return Structure.from_file(text)
    return Structure(structure=text)


def _cofold_control(structures: list[Any], reference: Any) -> dict[str, Any]:
    """CA RMSD of each cofold seed against a supplied reference structure.

    Fills the dossier's ``structure.cofold_control`` block. Scores the cofold
    against the crystal so a reader can see whether cofolding reproduces a
    KNOWN answer for THIS target — the same discipline as the affinity
    positive control, and a per-target measurement rather than a stored claim.

    Residue matching is deliberately strict: if the reference and the
    prediction do not have the same number of CA atoms in the compared chain,
    NO number is emitted and the reason is returned instead. A silently
    mis-paired RMSD is worse than a null.
    """
    import numpy as np  # noqa: PLC0415

    try:
        ref = _load_reference(reference)
    except Exception as exc:  # noqa: BLE001
        return {"reference_loaded": False, "cofold_rmsd_a": None, "reason": f"could not load reference: {exc}"}

    ref_ca = _ca_by_chain(ref)
    if not ref_ca:
        return {"reference_loaded": False, "cofold_rmsd_a": None, "reason": "reference has no CA atoms"}
    ref_chain = max(ref_ca, key=lambda k: len(ref_ca[k]))
    ref_pts = ref_ca[ref_chain]

    rmsds: list[float] = []
    reasons: list[str] = []
    for st in structures:
        ca = _ca_by_chain(st)
        cand = [k for k in ca if len(ca[k]) == len(ref_pts)]
        if not cand:
            reasons.append(
                f"no chain with {len(ref_pts)} CA atoms to match reference chain "
                f"{ref_chain} (prediction has {[(k, len(v)) for k, v in ca.items()]})"
            )
            continue
        mob = ca[cand[0]]
        rot, pc, qc = _kabsch(mob, ref_pts)
        moved = (rot @ (np.asarray(mob) - pc).T).T + qc
        diff = moved - np.asarray(ref_pts)
        rmsds.append(float(np.sqrt((diff**2).sum(1).mean())))

    if not rmsds:
        return {
            "reference_loaded": True,
            "reference_chain": ref_chain,
            "reference_ca_count": len(ref_pts),
            "cofold_rmsd_a": None,
            "reason": (
                "residue counts do not match, so no RMSD was computed. Trim "
                "the reference to the modelled residues and retry. Details: "
                + "; ".join(reasons[:2])
            ),
        }
    return {
        "reference_loaded": True,
        "reference_chain": ref_chain,
        "reference_ca_count": len(ref_pts),
        "cofold_rmsd_a": round(statistics.median(rmsds), 3),
        "cofold_rmsd_a_per_seed": [round(r, 3) for r in rmsds],
        "method": "Kabsch superposition on all CA atoms, 1:1 by index",
        "reproduces_reference": None,
        "trusted": None,
        "_why_null": (
            "reproduces_reference and trusted are judgements, not "
            "measurements, and this module does not make them. There is no "
            "calibrated RMSD threshold here — one would have to come from a "
            "benchmark across targets, and we do not have one. Report the "
            "RMSD and let the reader weigh it."
        ),
    }


def _seed_dispersion(structures: list[Any]) -> dict[str, Any]:
    """Dispersion ACROSS SEEDS — recomputed fresh on every call.

    This is a per-run uncertainty measure, not a stored claim about the method.
    Small dispersion is NOT evidence of correctness: on KRAS, 24 runs at a
    median 0.21 A dispersion converged on a real site that was not the site the
    question was about. Read ``converged_site`` alongside this.
    """
    lig_centroids = _ligand_centroids_common_frame(structures) if structures else []
    lig_pairs = [_dist(a, b) for a, b in combinations(lig_centroids, 2)]

    bb_pairs: list[float] = []
    for a, b in combinations(structures, 2):
        try:
            bb_pairs.append(float(a.backbone_rmsd(b)))
        except Exception:  # noqa: BLE001 - RMSD needs matched chains; report absence, don't crash
            pass

    return {
        "n_seeds": len(structures),
        "ligand_centroid_dispersion_a": {
            **_pairwise_stats(lig_pairs),
            "frame": "protein-CA superposed onto seed 0 before measuring",
            "_why": (
                "Measured off raw un-superposed CIFs this returned 15.57 A for "
                "two seeds whose contact-residue sets were identical. Boltz-2 "
                "emits every sample in its own frame."
            ),
        },
        "backbone_ca_rmsd_across_seeds_a": _pairwise_stats(bb_pairs),
        "interpretation": (
            "Dispersion across seeds is a per-run uncertainty measure and it is "
            "measured, not assumed. It does NOT measure correctness — see "
            "converged_site, and OBSERVATIONS["
            "'seed_dispersion_and_site_convergence'] for the case where tight "
            "agreement accompanied the wrong site."
        ),
    }


def _converged_site(structures: list[Any]) -> dict[str, Any]:
    """Which site did the seeds land on, and did they agree?

    Per-run, and the reason multi-seed is not optional: a caller must be able to
    see that the model answered a different question from the one asked.
    """
    per_seed = [set(_ligand_contact_residues(st)) for st in structures]
    per_seed = [s for s in per_seed if s]
    if not per_seed:
        return {
            "has_ligand": False,
            "consensus_contact_residues": None,
            "seed_agreement_fraction": None,
            "caution": "no ligand in the complex — there is no site to converge on",
        }
    counts: dict[str, int] = {}
    for s in per_seed:
        for r in s:
            counts[r] = counts.get(r, 0) + 1
    n = len(per_seed)
    consensus = sorted([r for r, c in counts.items() if c == n], key=_res_sort_key)
    union = sorted(counts, key=_res_sort_key)
    return {
        "has_ligand": True,
        "n_seeds_with_ligand": n,
        "consensus_contact_residues": consensus,
        "union_contact_residues": union,
        "seed_agreement_fraction": round(len(consensus) / len(union), 3) if union else None,
        "contact_definition": (
            f"protein residue with any heavy atom within {_LIGAND_CONTACT_CUTOFF_A} A "
            f"of a ligand heavy atom"
        ),
        "caution": (
            "THIS IS THE SITE THE MODEL CHOSE, NOT NECESSARILY THE SITE YOU "
            "ASKED ABOUT. On KRAS, 21 of 24 runs converged on SI/II-P when the "
            "question was switch-II — a real site, and the wrong one. Check "
            "these residues against your intended site before using anything "
            "downstream of this call. High seed agreement does not settle it."
        ),
    }


def _metrics_dict(structure: Any) -> dict[str, Any]:
    m = structure.metrics
    d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
    return {k: v for k, v in d.items() if not isinstance(v, list)}


def _as_chain_list(sequences: str | list[str]) -> list[str]:
    return [sequences] if isinstance(sequences, str) else list(sequences)


# ---------------------------------------------------------------------------
# 1. Boltz-2 structure prediction  (proto-tools key: boltz2-prediction)
# ---------------------------------------------------------------------------
def cofold_complex(
    sequences: str | list[str],
    ligand_smiles: str | list[str] | None = None,
    *,
    n_seeds: int = 3,
    reference_structure: Any = None,
    seed: int = 42,
    device: str = "modal",
    use_msa: bool = True,
    recycling_steps: int = 3,
    sampling_steps: int = 200,
    diffusion_samples: int = 1,
    timeout: int = 3600,
    verbose: bool = False,
) -> dict[str, Any]:
    """Fold a protein, a multimer, or a protein-ligand complex with Boltz-2.

    Multi-seed by default. The confidence numbers are returned under
    ``structural_confidence`` and labelled for what they are — metrics about
    the geometry the model drew. They are not gated, corrected or downweighted
    here; ``single_target_observations`` carries the KRAS sealed-pocket result
    with its sample size so a reader can weigh it.

    Args:
        sequences: one protein sequence, or a list for a multimer.
        ligand_smiles: optional ligand SMILES (str or list) to cofold in.
        n_seeds: independent seeds. Seeds are ``seed, seed+1, ...`` — this is
            how the tool itself distinguishes duplicate complexes.

    Returns:
        dict with ``structural_confidence``, ``seed_dispersion``,
        ``converged_site``, ``interface``, ``structures_cif`` and
        ``provenance``.
    """
    _require_proto_tools()
    _require_modal(device)
    if n_seeds < 1:
        raise ValueError("n_seeds must be >= 1")

    from proto_tools.tools.structure_prediction.boltz2.boltz2 import (  # noqa: PLC0415
        Boltz2Config,
        Boltz2Input,
        run_boltz2,
    )

    protein_chains = _as_chain_list(sequences)
    chains: list[dict[str, Any]] = [{"sequence": s, "entity_type": "protein"} for s in protein_chains]
    ligs = [] if ligand_smiles is None else _as_chain_list(ligand_smiles)
    chains += [{"smiles": s, "entity_type": "ligand"} for s in ligs]

    inputs = Boltz2Input(complexes=[{"chains": chains}] * n_seeds)
    config = Boltz2Config(
        device=device,
        seed=seed,
        use_msa=use_msa,
        recycling_steps=recycling_steps,
        sampling_steps=sampling_steps,
        diffusion_samples=diffusion_samples,
        timeout=timeout,
        verbose=verbose,
    )

    t0 = time.time()
    result = run_boltz2(inputs, config)
    wall = time.time() - t0

    per_seed = [_metrics_dict(st) for st in result.structures]

    def _spread(key: str) -> dict[str, Any]:
        vals = [m[key] for m in per_seed if m.get(key) is not None]
        if not vals:
            return {"values": [], "min": None, "max": None}
        return {"values": [round(v, 4) for v in vals], "min": round(min(vals), 4), "max": round(max(vals), 4)}

    payload: dict[str, Any] = {
        "tool": "boltz2-prediction",
        "primary_output": "structures_cif",
        "n_protein_chains": len(protein_chains),
        "n_ligands": len(ligs),
        "is_multimer": len(protein_chains) > 1,
        "seeds": [seed + i for i in range(n_seeds)],
        "structural_confidence": {
            "_what_this_is": (
                "Structural-confidence metrics: how sure the model is about the "
                "geometry it drew. pTM, ipTM and pLDDT are defined as measures "
                "of geometric confidence — they are not binding scores, pocket "
                "scores or druggability scores, and nothing downstream should "
                "read them as such."
            ),
            "per_seed": per_seed,
            "confidence_score": _spread("confidence_score"),
            "complex_plddt": _spread("complex_plddt"),
            "ptm": _spread("ptm"),
            "iptm": _spread("iptm"),
            "ligand_iptm": _spread("ligand_iptm"),
            "avg_pae": _spread("avg_pae"),
        },
        "single_target_observations": {
            "_read_this_first": (
                "One observation, one target, not benchmarked, NOT applied to "
                "anything above. Weigh it yourself."
            ),
            "kras_sealed_pocket": OBSERVATIONS["kras_sealed_pocket_confidence"],
        },
        "seed_dispersion": _seed_dispersion(result.structures),
        "converged_site": _converged_site(result.structures),
        "cofold_control": _cofold_control(result.structures, reference_structure)
        if reference_structure is not None
        else {
            "reference_loaded": False,
            "cofold_rmsd_a": None,
            "reason": (
                "no reference_structure supplied. When a crystal structure of "
                "this target exists, pass it — scoring the cofold against the "
                "known answer is the only per-target check available here."
            ),
        },
        "interface": _inter_chain_ca_contacts(result.structures[0]),
        "structures_cif": [st.structure_cif for st in result.structures],
        "provenance": _prov("boltz2-prediction", config, device=device, wall_s=wall),
    }
    if n_seeds == 1:
        payload["seed_dispersion"]["warning"] = (
            "n_seeds=1: no dispersion was measured. The uncertainty on this "
            "structure is UNKNOWN, not zero."
        )
    return payload


# ---------------------------------------------------------------------------
# 2. Boltz-2 affinity  (proto-tools key: boltz2-affinity)
# ---------------------------------------------------------------------------
def _log10_um_from_nm(nm: float) -> float:
    return math.log10(nm / 1000.0)


def _exception_chain_text(exc: BaseException, limit: int = 8) -> str:
    """Full text of an exception and everything it was raised from.

    Needed because proto-tools re-raises the interesting error as a pydantic
    validation TypeError whose message TRUNCATES the payload — the actual cause
    string ('_unphysical.xtc') only survives further down the __cause__ /
    __context__ chain.
    """
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and len(parts) < limit and id(cur) not in seen:
        seen.add(id(cur))
        parts.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__
    return "\n".join(parts)


def cofold_affinity(
    protein: str | list[str],
    ligand_smiles: str | list[str],
    *,
    ligand_names: list[str] | None = None,
    positive_control_smiles: str | None = None,
    positive_control_name: str | None = None,
    positive_control_measured_nm: float | None = None,
    seed: int = 42,
    device: str = "modal",
    use_msa: bool = True,
    diffusion_samples_affinity: int = 5,
    timeout: int = 3600,
    verbose: bool = False,
) -> dict[str, Any]:
    """Rank ligands against a protein with the Boltz-2 affinity head.

    The primary output is ``ranking``. Absolute values are returned under
    ``absolute`` marked ``is_a_kd: False`` and ``benchmarked: False`` — the
    reason being simply that this head has not been benchmarked against
    measured affinities here, so nothing it emits is quotable as a potency. No
    correction, offset or calibration is applied to any returned value.

    Supply ``positive_control_smiles`` + ``positive_control_measured_nm`` to run
    the rule-12 control in the same call. That control is a FRESH per-run
    measurement on your own target, and it is the number to act on.
    """
    _require_proto_tools()
    _require_modal(device)

    from proto_tools.tools.structure_prediction.boltz2.boltz2_affinity import (  # noqa: PLC0415
        Boltz2AffinityConfig,
        Boltz2AffinityInput,
        run_boltz2_affinity,
    )

    ligs = _as_chain_list(ligand_smiles)
    names = list(ligand_names) if ligand_names else [f"ligand_{i}" for i in range(len(ligs))]
    if len(names) != len(ligs):
        raise ValueError("ligand_names must be the same length as ligand_smiles")

    control_idx: int | None = None
    if positive_control_smiles is not None:
        control_idx = 0
        ligs = [positive_control_smiles, *ligs]
        names = [positive_control_name or "positive_control", *names]

    protein_chains = [{"sequence": s, "entity_type": "protein"} for s in _as_chain_list(protein)]
    inputs = Boltz2AffinityInput(
        complexes=[
            {"chains": [*protein_chains, {"smiles": smi, "entity_type": "ligand"}]} for smi in ligs
        ]
    )
    config = Boltz2AffinityConfig(
        device=device,
        seed=seed,
        use_msa=use_msa,
        diffusion_samples_affinity=diffusion_samples_affinity,
        timeout=timeout,
        verbose=verbose,
    )

    t0 = time.time()
    result = run_boltz2_affinity(inputs, config)
    wall = time.time() - t0

    rows: list[dict[str, Any]] = []
    for i, (name, smi, st) in enumerate(zip(names, ligs, result.structures, strict=True)):
        m = _metrics_dict(st)
        v = m.get("affinity_pred_value")
        rows.append(
            {
                "name": name,
                "smiles": smi,
                "is_positive_control": i == control_idx,
                "_sort_key": v,
                "binder_probability": m.get("affinity_probability_binary"),
                "absolute": {
                    "affinity_pred_value_log10_ic50_um": v,
                    "unit": "log10(IC50 in micromolar), lower = predicted stronger",
                    "is_a_kd": False,
                    "is_a_potency_measurement": False,
                    "benchmarked_against_measured_affinities": False,
                    "correction_applied": None,
                    "warning": (
                        "Do NOT report this as a Kd, IC50 or potency and do NOT "
                        "compare it against a nanomolar threshold. This head has "
                        "not been benchmarked against measured affinities here, "
                        "so the relationship between this number and a real "
                        "potency is unknown. Use the ranking, and use the "
                        "positive control you ran on THIS target."
                    ),
                },
                "raw_metrics": m,
            }
        )

    ranked = sorted([r for r in rows if r["_sort_key"] is not None], key=lambda r: r["_sort_key"])
    for rank, r in enumerate(ranked, start=1):
        r["rank"] = rank
    best = ranked[0]["_sort_key"] if ranked else None
    for r in ranked:
        r["relative_score_log_units_vs_best"] = round(r["_sort_key"] - best, 4) if best is not None else None
    for r in rows:
        r.pop("_sort_key", None)

    span = ranked[-1]["relative_score_log_units_vs_best"] if len(ranked) >= 2 else None

    control: dict[str, Any] = {
        "run": False,
        "reliable": None,
        "note": (
            "Rule 12: a prediction without its control is not a measurement. "
            "Pass positive_control_smiles and positive_control_measured_nm to "
            "measure, on THIS target, how far the predictor lands from a known "
            "binder. That per-run number is worth more than any stored one."
        ),
    }
    if control_idx is not None and positive_control_measured_nm is not None:
        crow = next(r for r in rows if r["is_positive_control"])
        pred = crow["absolute"]["affinity_pred_value_log10_ic50_um"]
        if pred is not None:
            err = pred - _log10_um_from_nm(positive_control_measured_nm)
            control = {
                "run": True,
                "ligand": crow["name"],
                "measured_nm": positive_control_measured_nm,
                "predicted_log10_ic50_um": pred,
                "log_error": round(err, 3),
                "log_error_direction": "predicted weaker than measured"
                if err > 0
                else "predicted stronger than measured",
                "threshold_log_units": _CONTROL_LOG_THRESHOLD,
                "reliable": bool(abs(err) <= _CONTROL_LOG_THRESHOLD),
                "scope": (
                    "ONE compound on THIS target, measured in this run. It is a "
                    "check, not a calibration: it is not applied to the other "
                    "ligands' values and must not be used as an offset."
                ),
                "note": (
                    "reliable=False means the predictor did not recover this "
                    "known binder within one log here, so its absolute values "
                    "for novel chemotypes on this target are uninformative. The "
                    "RANKING may still be usable — read ranking_span_log_units "
                    "and whether the control ranked where you expected."
                ),
            }

    return {
        "tool": "boltz2-affinity",
        "primary_output": "ranking",
        "ranking": [
            {
                "rank": r["rank"],
                "name": r["name"],
                "relative_score_log_units_vs_best": r["relative_score_log_units_vs_best"],
                "binder_probability": r["binder_probability"],
                "is_positive_control": r["is_positive_control"],
            }
            for r in ranked
        ],
        "ranking_span_log_units": span,
        "ranking_usable": len(ranked) >= 2,
        "ranking_caveat": (
            "A ranking of one ligand is not a ranking. Pass more ligands, or a "
            "positive control, so there is something to rank against."
        )
        if len(ranked) < 2
        else (
            "Ranks are within-target only. Do not compare ranks or scores "
            "across different protein targets."
        ),
        "control": control,
        "per_ligand": rows,
        "single_compound_observations": {
            "_read_this_first": (
                "ONE compound, not benchmarked, NOT applied to anything above."
            ),
            "tofacitinib_on_jak1": OBSERVATIONS["tofacitinib_affinity_error"],
        },
        "provenance": _prov("boltz2-affinity", config, device=device, wall_s=wall),
    }


# ---------------------------------------------------------------------------
# 3. ESMFold  (proto-tools key: esmfold-prediction)
# ---------------------------------------------------------------------------
def esmfold_predict(
    sequence: str | list[str],
    *,
    seed: int = 42,
    device: str = "modal",
    num_recycles: int = 4,
    chain_linker: str | None = None,
    timeout: int | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Fold with ESMFold and return its own confidence alongside the geometry.

    ``self_report`` carries the model's pTM, average PAE and average pLDDT.
    ``interface`` carries the measured inter-chain CA contact count, the
    residues in contact, the closest inter-chain CA approach and the
    centre-of-mass separation. Both are per-run measurements. This function
    does not gate, flag or downweight its output — the caller judges.
    """
    _require_proto_tools()
    _require_modal(device)

    from proto_tools.tools.structure_prediction.esmfold.esmfold import (  # noqa: PLC0415
        ESMFoldConfig,
        ESMFoldInput,
        run_esmfold,
    )

    chains = _as_chain_list(sequence)
    kwargs: dict[str, Any] = {
        "device": device,
        "seed": seed,
        "num_recycles": num_recycles,
        "verbose": verbose,
    }
    if chain_linker is not None:
        kwargs["chain_linker"] = chain_linker
    if timeout is not None:
        kwargs["timeout"] = timeout
    config = ESMFoldConfig(**kwargs)

    inputs = ESMFoldInput(
        complexes=[{"chains": [{"sequence": s, "entity_type": "protein"} for s in chains]}]
    )

    t0 = time.time()
    result = run_esmfold(inputs, config)
    wall = time.time() - t0

    st = result.structures[0]
    m = _metrics_dict(st)
    is_multimer = len(chains) > 1

    return {
        "tool": "esmfold-prediction",
        "primary_output": "structure_cif",
        "n_chains": len(chains),
        "is_multimer": is_multimer,
        "structure_cif": st.structure_cif,
        "self_report": {
            "avg_plddt": m.get("avg_plddt"),
            "ptm": m.get("ptm"),
            "avg_pae": m.get("avg_pae"),
            "_what_this_is": (
                "The model's own confidence for THIS run. Returned unmodified "
                "and ungated — it is a real per-run signal and the caller "
                "judges it."
            ),
            "for_scale_il17a_case": {
                "monomer": {"ptm": 0.905, "avg_pae": 3.66},
                "dimer": {"ptm": 0.399, "avg_pae": 18.26},
                "caveat": "one complex, for scale only — not a threshold",
            },
        },
        "interface": _inter_chain_ca_contacts(st)
        if is_multimer
        else {"n_protein_chains": 1, "note": "single chain — no interface to measure"},
        "multimer_note": (
            "ESMFold folds multiple chains by joining them with an internal "
            f"linker ({len(config.chain_linker)} glycines by default), which it "
            "strips from the output. Read the contact count and the model's own "
            "pTM/PAE above before relying on the inter-chain geometry."
        )
        if is_multimer
        else None,
        "single_complex_observations": {
            "_read_this_first": (
                "ONE complex, not benchmarked, NOT applied to anything above."
            ),
            "il17a_homodimer": OBSERVATIONS["il17a_esmfold_dimer"],
        },
        "provenance": _prov(
            "esmfold-prediction",
            config,
            device=device,
            wall_s=wall,
            extra={"chain_linker_used": config.chain_linker if is_multimer else None},
        ),
    }


# ---------------------------------------------------------------------------
# 4. BioEmu  (proto-tools key: bioemu-sample)
# ---------------------------------------------------------------------------
def bioemu_ensemble(
    sequence: str | list[str],
    n_samples: int = 32,
    *,
    linker_length: int = _BIOEMU_LINKER_DEFAULT,
    seed: int = 42,
    device: str = "modal",
    model_name: str = "bioemu-v1.1",
    filter_samples: bool = True,
    denoiser_type: str = "dpm",
    timeout: int = 3600,
    verbose: bool = False,
) -> dict[str, Any]:
    """Sample a conformational ensemble with BioEmu.

    BioEmu's own validator rejects any complex with more than one chain, so a
    multimer is only reachable by concatenating the chains through a
    poly-glycine linker. When that happens the returned dict carries
    ``linker.inserted = True`` with the exact residue range of every linker and
    of every original chain, because a linker changes what the ensemble means.

    Frames are backbone + C-beta only, zero-indexed, all B-factors zero — see
    ``frame_caveats``, and check them against the run: they are re-verifiable.
    """
    _require_proto_tools()
    _require_modal(device)
    if not (_BIOEMU_LINKER_MIN <= linker_length <= _BIOEMU_LINKER_MAX):
        raise ValueError(
            f"linker_length must be {_BIOEMU_LINKER_MIN}-{_BIOEMU_LINKER_MAX} "
            f"glycines (got {linker_length})"
        )

    from proto_tools.tools.structure_dynamics.bioemu.bioemu_sample import (  # noqa: PLC0415
        BioEmuConfig,
        BioEmuInput,
        run_bioemu,
    )

    chains = _as_chain_list(sequence)
    linker = "G" * linker_length

    if len(chains) > 1:
        folded = linker.join(chains)
        segments: list[dict[str, Any]] = []
        linkers: list[dict[str, Any]] = []
        pos = 0
        for i, ch in enumerate(chains):
            segments.append(
                {
                    "chain_index": i,
                    "length": len(ch),
                    "residue_range_0indexed": [pos, pos + len(ch) - 1],
                }
            )
            pos += len(ch)
            if i < len(chains) - 1:
                linkers.append(
                    {
                        "after_chain_index": i,
                        "length": linker_length,
                        "sequence": linker,
                        "residue_range_0indexed": [pos, pos + linker_length - 1],
                    }
                )
                pos += linker_length
        linker_record: dict[str, Any] = {
            "inserted": True,
            "reason": (
                "BioEmu's input validator rejects any complex with more than "
                "one chain ('BioEmu only supports single-chain proteins "
                "(monomers)'). Concatenating through a poly-glycine linker is "
                "the only route to a multimer ensemble."
            ),
            "linker_sequence": linker,
            "linker_length": linker_length,
            "n_linkers": len(linkers),
            "linkers": linkers,
            "chain_segments": segments,
            "folded_length": len(folded),
            "what_it_changes": (
                "The ensemble is of a COVALENTLY TETHERED construct, not of the "
                "biological assembly. Inter-chain distances are constrained by "
                "the tether, the relative-orientation distribution is not the "
                "free one, and the linker residues are not part of the protein. "
                "Strip the linker residue ranges above before any pocket "
                "detection or RMSD, and do not report an inter-chain "
                "measurement off these frames as if it were free-solution."
            ),
        }
    else:
        folded = chains[0]
        linker_record = {
            "inserted": False,
            "reason": "single chain — no linker needed",
            "linker_sequence": None,
            "linker_length": None,
            "n_linkers": 0,
            "linkers": [],
            "chain_segments": [
                {"chain_index": 0, "length": len(folded), "residue_range_0indexed": [0, len(folded) - 1]}
            ],
            "folded_length": len(folded),
        }

    config = BioEmuConfig(
        device=device,
        num_samples=n_samples,
        seed=seed,
        model_name=model_name,
        filter_samples=filter_samples,
        denoiser_type=denoiser_type,
        timeout=timeout,
        verbose=verbose,
    )
    inputs = BioEmuInput(complexes=[{"chains": [{"sequence": folded, "entity_type": "protein"}]}])

    # UPSTREAM BUG, reproduced: when the physical-sanity filter actually rejects
    # frames, BioEmu writes a `*_unphysical.xtc` alongside the kept frames and
    # then dies parsing its own filename —
    #   ValueError: Invalid suffix '_unphysical.xtc'
    # It surfaces as a BioEmuOutput validation error ("ensembles Field
    # required"). Hit reproducibly on a glycine-linked 2x60 construct with
    # filter_samples=True; the same call with filter_samples=False succeeds.
    # A linked construct is exactly the input most likely to produce rejectable
    # frames, so the multimer path walks into it. Retry once unfiltered and say
    # so loudly — this CHANGES WHAT THE ENSEMBLE IS.
    filter_fallback: dict[str, Any] | None = None
    t0 = time.time()
    try:
        result = run_bioemu(inputs, config)
    except Exception as exc:  # noqa: BLE001 - narrowed by the message check below
        chain = _exception_chain_text(exc)
        # The proto-tools wrapper re-raises as a BioEmuOutput validation error
        # whose message truncates the payload, so match on the whole chain and
        # fall back to the output-shape signature.
        looks_like_filter_crash = "_unphysical" in chain or (
            "BioEmuOutput" in chain and "ensembles" in chain and "Field required" in chain
        )
        if not (filter_samples and looks_like_filter_crash):
            raise
        config = BioEmuConfig(
            device=device,
            num_samples=n_samples,
            seed=seed,
            model_name=model_name,
            filter_samples=False,
            denoiser_type=denoiser_type,
            timeout=timeout,
            verbose=verbose,
        )
        result = run_bioemu(inputs, config)
        filter_fallback = {
            "triggered": True,
            "requested_filter_samples": True,
            "actual_filter_samples": False,
            "upstream_error": chain[:600],
            "matched_on": "_unphysical" if "_unphysical" in chain else "BioEmuOutput-shape",
            "what_this_means": (
                "The physical-sanity filter REJECTED frames, and upstream then "
                "crashed parsing the '_unphysical.xtc' file it had just "
                "written. The rerun kept ALL frames, including the ones the "
                "filter wanted to discard. These frames are NOT sanity-checked: "
                "steric clashes and chain breaks may be present. Filter them "
                "yourself on radius of gyration, SASA and secondary-structure "
                "sanity before scoring anything."
            ),
        }
    wall = time.time() - t0

    frames = result.ensembles[0].structures

    rgs: list[float] = []
    for f in frames:
        try:
            rgs.append(float(f.gyration_radius()))
        except Exception:  # noqa: BLE001 - a bad frame is a finding, not a crash
            pass
    pair_rmsd: list[float] = []
    for a, b in combinations(frames[: min(len(frames), 8)], 2):
        try:
            pair_rmsd.append(float(a.backbone_rmsd(b)))
        except Exception:  # noqa: BLE001
            pass

    # Re-verify the frame format on THIS run rather than asserting it.
    first_atoms = None
    if frames:
        try:
            first_atoms = sum(
                1 for line in frames[0].structure_pdb.splitlines() if line.startswith(("ATOM", "HETATM"))
            )
        except Exception:  # noqa: BLE001
            pass

    return {
        "tool": "bioemu-sample",
        "primary_output": "frames_pdb",
        "n_frames_returned": len(frames),
        "n_samples_requested": n_samples,
        "frames_filtered_out": n_samples - len(frames),
        "sequence_folded": folded,
        "linker": linker_record,
        "filter_fallback": filter_fallback
        or {"triggered": False, "actual_filter_samples": filter_samples},
        "ensemble_spread": {
            "radius_of_gyration_a": {
                "min": round(min(rgs), 3) if rgs else None,
                "max": round(max(rgs), 3) if rgs else None,
                "median": round(statistics.median(rgs), 3) if rgs else None,
            },
            "pairwise_backbone_rmsd_a": _pairwise_stats(pair_rmsd),
            "pairwise_rmsd_note": "computed on the first 8 frames only (O(n^2))",
        },
        "frame_caveats": {
            "atoms_in_first_frame_THIS_RUN": first_atoms,
            "residues_folded": len(folded),
            "side_chains_present": False,
            "must_repack_before_pocket_detection": True,
            "repack_reason": (
                "Frames are backbone + C-beta only. fpocket and mdpocket define "
                "pockets from side-chain atoms, so scoring these frames "
                "unrepacked inflates every volume. Divide "
                "atoms_in_first_frame_THIS_RUN by residues_folded to confirm — "
                "roughly 5 atoms per residue means no side chains."
            ),
            "residue_indexing": "zero-indexed",
            "per_frame_confidence_available": False,
            "b_factors": "all zero — there is no per-frame confidence to read",
            "pre_superposed": True,
            "alignment_needed_downstream": False,
            "filter_before_scoring_on": ["radius_of_gyration", "SASA", "secondary_structure_sanity"],
        },
        "frames_pdb": [f.structure_pdb for f in frames],
        "observations": {
            "frame_format": OBSERVATIONS["bioemu_frame_format"],
            "apo_degradation_literature": OBSERVATIONS["generative_ensembles_on_apo_LITERATURE"],
        },
        "provenance": _prov("bioemu-sample", config, device=device, wall_s=wall),
    }
