"""
Batched pocket scan on Modal — the computed-tractability half of the dossier.

Runs the whole ensemble in ONE invocation: every PDB entry, every clustering
value, and holo ligand-site derivation. One call, one cold start. Four separate
calls would pay four.

NOT IMPLEMENTED HERE — do not assume the output contains these:
  * the apo/holo cryptic comparison (superposition, C-alpha displacement, clash
    attribution). Those live only in the calibration scripts. Consequently, on
    an apo structure with no ligand site, `site_pocket` is simply the most
    druggable pocket ANYWHERE in the chain — for 4OBE at D 1.6 that is the
    nucleotide site, NOT the collapsed switch-II site the dossier's rule 3 is
    about. Read `site_pocket_selected_by` on every value before using it.
  * site transfer from a structural neighbour. Requires a residue-numbering
    equivalence policy; 6OIM and 4OBE happen to share numbering, which is not
    general.
Pooled ensemble volume/druggability may therefore span DIFFERENT sites; see
`_pooling_caveat` in the returned `ensemble` block.

Deploy (workspace MUST be rafwiewiora):
    MODAL_PROFILE=rafwiewiora modal deploy modal_app.py

Call from the eve tool handler:
    import modal
    fn = modal.Function.lookup("druggability-pocket-scan", "pocket_scan")
    result = fn.remote(pdb_ids=["6OIM", "4OBE"], ligand_codes=["MOV"])

Nothing here runs on the Anthropic sandbox or on a laptop; the agent only
decides to call it.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

import modal

# fpocket from conda-forge; proto-tools for the in-process CPU tools
# (vina-docking, foldseek-*, pyrosetta-*) that have no Proto Modal app.
image = (
    modal.Image.micromamba(python_version="3.12")
    .micromamba_install("fpocket", channels=["conda-forge"])
    .apt_install("git")
    .pip_install(
        "proto-tools[mcp] @ git+https://github.com/evo-design/proto-tools.git"
    )
)

app = modal.App("druggability-pocket-scan", image=image)

# Sweep, never pin — see the skill's failure modes. -D 1.6 gives a FALSE
# NEGATIVE (0.002) on TNF-alpha's co-crystallised site; -D 2.4 fuses KRAS's
# nucleotide and switch-II sites into one meaningless 1540 A^3 mega-pocket.
D_VALUES = (1.6, 2.4)

# Below this a "ligand" is a buffer component, cryoprotectant or ion, not
# evidence of drug-like binding.
DRUGLIKE_MIN_HEAVY_ATOMS = 18

# Buffer components, cryoprotectants, ions. Excluded by identity because they
# are noise in the ligand list even when they are too small to be drug-like.
NON_LIGANDS = frozenset(
    """HOH DOD SO4 PO4 GOL EDO PEG PG4 1PE P6G MPD ACT ACY CIT FLC TRS EPE MES
    IMD DMS BME DTT TLA FMT NO3 AZI IOD BR CL NA K CA MG MN ZN FE FE2 CU NI CD
    CO CS RB SR BA HG NH4 UNX UNL UNK""".split()
)

# Endogenous cofactors, nucleotides, sugars and lipids. These clear the
# heavy-atom threshold on SIZE ALONE — GDP is 28 heavy atoms — so a pure size
# cut calls apo KRAS (4OBE: GDP + Mg, no inhibitor) "holo", and the whole
# cryptic-pocket argument in the dossier depends on 4OBE being apo. Size cannot
# separate a cofactor from a drug; only identity can. A curated set is chosen
# over a runtime chemical-component lookup deliberately: the lookup adds a
# network dependency inside the Modal function and fails open, whereas this is
# deterministic and auditable. It is a denylist, so the failure mode is a
# never-seen cofactor slipping through as "drug-like" — visible in the reported
# comp_id, not silent.
COFACTORS = frozenset(
    """GDP GTP GNP GSP GCP G2P GGL GGZ ADP ATP AMP ANP ACP AGS APC ADX CDP CTP
    CMP UDP UTP UMP TTP TMP TDP IDP ITP NAD NAI NAP NDP NAJ FAD FMN FDA SAM SAH
    SFG COA ACO MCA HEM HEC HEA HDD BCL CLA PLP TPP B12 COB BTN MTA APR PRP 3PG
    F6P G6P G1P UPG NAG NDG BMA MAN GAL GLA GLC BGC FUC SIA XYS XYP SUC TRE
    MYR PLM OLA STE DAO D12 LDA LMT CHD CLR PEE PC1 PGV""".split()
)

# "REMARK 465     GLY A     0" — the data lines. The five legend lines above
# them also start with REMARK 465, which is why this is a match and not a slice.
_MISSING_RES_RE = re.compile(
    r"^REMARK 465\s+(?:\d+\s+)?([A-Z0-9]{1,3})\s+(\S)\s+(-?\d+[A-Z]?)\s*$"
)


def _is_hydrogen(line: str, name_fallback: bool = False) -> bool:
    """Element columns 77-78. `name_fallback` is for ATOM records only: in a
    protein an atom name starting with H is a hydrogen, but in a HETATM it
    could be HG (mercury), so the fallback must not be used there."""
    el = line[76:78].strip() if len(line) >= 78 else ""
    if el:
        return el in ("H", "D")
    if not name_fallback:
        return False
    return line[12:16].strip().lstrip("0123456789")[:1] in ("H", "D")


def _fetch(pdb_id: str, dest: Path) -> Path:
    path = dest / f"{pdb_id}.pdb"
    if not path.exists():
        url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
            path.write_bytes(r.read())
    return path


def _prep(
    src: Path, dest: Path, chains: list[str] | None
) -> tuple[Path, list[str], list[str]]:
    """Protein only, altloc A or blank, hydrogens stripped.

    Chain selection is per-target and deliberate: KRAS is a monomer, TNF-alpha's
    site sits on the trimer axis and disappears if you keep one chain.

    Missing residues (REMARK 465) are RETURNED, not just counted: a disordered
    loop is a hole in the surface, and fpocket will happily score the hole. The
    caller has to be able to see one at the site it is reporting.
    """
    kept, seen_chains, missing = [], set(), []
    for line in src.read_text().splitlines():
        if line.startswith("REMARK 465"):
            m = _MISSING_RES_RE.match(line.rstrip())
            if m:
                missing.append(f"{m.group(2)}/{m.group(3)}")
            continue
        if not line.startswith("ATOM") or len(line) < 54:
            continue
        if line[16] not in (" ", "A"):  # altloc
            continue
        if _is_hydrogen(line, name_fallback=True):  # hydrogens and deuteriums
            continue
        ch = line[21]
        if chains and ch not in chains:
            continue
        seen_chains.add(ch)
        # Blank the altloc indicator; nothing downstream should see a partly
        # occupied "A" and treat it as a distinct conformer.
        kept.append(line[:16] + " " + line[17:])
    out = dest / f"{src.stem}_prep.pdb"
    out.write_text("\n".join(kept) + "\nTER\nEND\n")
    if chains:
        missing = [r for r in missing if r.split("/")[0] in chains]
    return out, sorted(seen_chains), missing


def _ligands(src: Path) -> list[dict]:
    """Nonpolymer ligands with heavy-atom counts, so 'holo' can be checked
    rather than assumed. A PEG or a cryoprotectant is not a holo ligand."""
    counts: dict[tuple[str, str, str], int] = {}
    for line in src.read_text().splitlines():
        if not line.startswith("HETATM") or len(line) < 54:
            continue
        comp = line[17:20].strip()
        if comp in NON_LIGANDS:
            continue
        if line[16] not in (" ", "A"):  # altloc, or one copy counts twice
            continue
        if _is_hydrogen(line):
            continue
        key = (comp, line[21], line[22:26].strip())
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "comp_id": c,
            "chain": ch,
            "resseq": rs,
            "heavy_atoms": n,
            # Reported, not dropped: the dossier has to be able to say "apo,
            # but carrying GDP" rather than "apo" full stop.
            "cofactor": c in COFACTORS,
            "druglike": n >= DRUGLIKE_MIN_HEAVY_ATOMS and c not in COFACTORS,
        }
        for (c, ch, rs), n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _ligand_site(
    src: Path,
    comp_id: str,
    chains: list[str] | None = None,
    cutoff: float = 5.0,
) -> tuple[list[str], str | None]:
    """Residues within `cutoff` of ONE copy of the ligand — the only ground
    truth for whether the detected pocket is the pocket that matters.

    One copy, and only the chains that were actually scored. Both restrictions
    are load-bearing: 2AZ5 has two copies of ligand 307 across an A/B/C/D
    two-dimer asymmetric unit, and pooling them returns 43 residues spanning
    four chains instead of the 19-residue A/B site. Jaccard against that union
    is meaningless — a pocket found in the A/B dimer can never exceed ~0.44
    against it, so the wrong pocket wins.

    Returns (residues, "chain/resseq of the copy used").
    """
    copies: dict[tuple[str, str], list] = {}
    prot: list = []
    for line in src.read_text().splitlines():
        if len(line) < 54:
            continue
        if line.startswith("HETATM") and line[17:20].strip() == comp_id:
            if line[16] not in (" ", "A") or _is_hydrogen(line):
                continue
            bucket = copies.setdefault((line[21], line[22:26].strip()), [])
        elif line.startswith("ATOM"):
            if _is_hydrogen(line, name_fallback=True):
                continue
            if chains and line[21] not in chains:
                continue
            bucket = prot
        else:
            continue
        bucket.append(
            (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
                line[21],
                line[22:26].strip(),
            )
        )
    c2 = cutoff * cutoff

    def contacts(lig: list) -> set:
        hits = set()
        for px, py, pz, pch, prs in prot:
            for lx, ly, lz, _, _ in lig:
                if (px - lx) ** 2 + (py - ly) ** 2 + (pz - lz) ** 2 <= c2:
                    hits.add(f"{pch}/{prs}")
                    break
        return hits

    # The copy best engaged by the chains we kept. For a single-copy structure
    # this is a no-op; for a multi-copy one it picks the site we can score.
    best: set = set()
    best_key: tuple[str, str] | None = None
    for key, lig in copies.items():
        hits = contacts(lig)
        if len(hits) > len(best):
            best, best_key = hits, key
    return (
        sorted(best, key=lambda s: (s.split("/")[0], int(s.split("/")[1]))),
        f"{best_key[0]}/{best_key[1]}" if best_key else None,
    )


def _parse_pockets(out_dir: Path) -> list[dict]:
    # Verified against real output: fpocket writes <input_stem>_out/ and inside
    # it <input_stem>_info.txt. removesuffix, not replace — replace() would eat
    # an "_out" occurring anywhere in the stem.
    info = out_dir / f"{out_dir.name.removesuffix('_out')}_info.txt"
    if not info.exists():
        return []
    pockets, cur = [], None
    for line in info.read_text().splitlines():
        s = line.strip()
        if s.startswith("Pocket") and s.endswith(":"):
            if cur:
                pockets.append(cur)
            cur = {"rank": int(s.split()[1])}
        elif cur is not None and ":" in s:
            k, _, v = s.partition(":")
            k = k.strip().lower().replace(" ", "_")
            try:
                cur[k] = float(v.strip())
            except ValueError:
                pass
    if cur:
        pockets.append(cur)

    for p in pockets:
        # fpocket numbers the per-pocket files from 1, matching "Pocket N :" in
        # info.txt exactly — there is no pocket0_atm.pdb. Checked on every run
        # in the calibration set. The old rank-1 shifted every pocket's residues
        # onto its neighbour and silently gave rank 1 no residues at all.
        atm = out_dir / "pockets" / f"pocket{p['rank']}_atm.pdb"
        res = set()
        if not atm.exists():
            # Never expected. Say so rather than reporting an empty pocket.
            p["residues_unavailable"] = atm.name
        else:
            for line in atm.read_text().splitlines():
                if line.startswith(("ATOM", "HETATM")):
                    res.add(f"{line[21]}/{line[22:26].strip()}")
        p["residues"] = sorted(
            res, key=lambda s: (s.split("/")[0], int(s.split("/")[1]))
        )
    return pockets


def _jaccard(a: list[str], b: list[str]) -> float | None:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return None
    return round(len(sa & sb) / len(sa | sb), 3)


@app.function(cpu=4.0, timeout=1800)
def pocket_scan(
    pdb_ids: list[str],
    chains: dict[str, list[str]] | None = None,
    ligand_codes: list[str] | None = None,
) -> dict:
    """Scan an ensemble at every clustering value and report the spread.

    Returns volume with its across-structure spread as the PRIMARY number, and
    druggability only as a range. Measured on five apo TNF-alpha structures:
    volume varied +/-16%, druggability varied 650-fold over the same site.
    """
    work = Path("/tmp/pockets")
    work.mkdir(parents=True, exist_ok=True)
    chains = chains or {}
    results: dict[str, dict] = {}

    for pid in pdb_ids:
        raw = _fetch(pid, work)
        prepped, used_chains, missing_res = _prep(raw, work, chains.get(pid))
        ligs = _ligands(raw)
        druglike = [lig for lig in ligs if lig["druglike"]]
        cofactors = sorted({lig["comp_id"] for lig in ligs if lig["cofactor"]})

        # Ground-truth site, when a drug-like ligand is present.
        target_comp = None
        if ligand_codes:
            target_comp = next(
                (
                    lig["comp_id"]
                    for lig in ligs
                    if lig["comp_id"] in ligand_codes
                ),
                None,
            )
        elif druglike:
            target_comp = druglike[0]["comp_id"]
        true_site, site_copy = (
            _ligand_site(raw, target_comp, used_chains)
            if target_comp
            else ([], None)
        )

        per_d = {}
        for d in D_VALUES:
            run = work / f"{pid}_D{d}"
            run.mkdir(parents=True, exist_ok=True)
            tgt = run / prepped.name
            tgt.write_text(prepped.read_text())
            out_dir = run / f"{tgt.stem}_out"
            # A warm Modal container reuses /tmp. fpocket overwrites what it
            # rewrites but leaves everything else, so a failed rerun would be
            # parsed as a successful one off the previous run's files.
            shutil.rmtree(out_dir, ignore_errors=True)
            proc = subprocess.run(  # noqa: S603
                ["fpocket", "-f", str(tgt), "-D", str(d)],  # noqa: S607
                check=False,
                capture_output=True,
            )
            pockets = _parse_pockets(out_dir)
            for p in pockets:
                p["jaccard_vs_ligand_site"] = (
                    _jaccard(p.get("residues", []), true_site) if true_site else None
                )
            # Rank by overlap with the real site when we have one; by
            # druggability only when we do not.
            if true_site:
                best = max(
                    pockets,
                    key=lambda p: p.get("jaccard_vs_ligand_site") or 0.0,
                    default=None,
                )
                basis = "ligand_site_jaccard"
                if best and not (best.get("jaccard_vs_ligand_site") or 0.0):
                    # Nothing touched the real site at this D. Returning the
                    # arbitrary first pocket as "the site pocket" is worse than
                    # returning nothing — that is the false negative in rule 4.
                    best, basis = None, "no_pocket_overlapped_ligand_site"
            else:
                best = max(
                    pockets,
                    key=lambda p: p.get("druggability_score") or 0.0,
                    default=None,
                )
                basis = "max_druggability_no_ligand_site"
            per_d[str(d)] = {
                "n_pockets": len(pockets),
                "site_pocket": best,
                "site_pocket_selected_by": basis,
                "merge_suspected": bool(
                    best and best.get("volume", 0) > 1000
                ),
            }
            if not pockets:
                per_d[str(d)]["fpocket_failed"] = {
                    "returncode": proc.returncode,
                    "stderr": proc.stderr.decode(errors="replace")[-500:],
                }

        results[pid] = {
            "chains_used": used_chains,
            "missing_residues": missing_res,
            "ligands": ligs,
            "cofactors_present": cofactors,
            "tier": "holo" if druglike else "apo",
            "tier_note": (
                "no drug-like ligand (>=18 heavy atoms, endogenous cofactors "
                "excluded by identity)"
                + (f"; cofactors present: {', '.join(cofactors)}" if cofactors else "")
                if not druglike else
                f"drug-like ligand {target_comp or druglike[0]['comp_id']}"
            ),
            "ligand_site_residues": true_site,
            "ligand_site_copy": site_copy,
            "by_clustering": per_d,
        }

    # Ensemble spread — volume is the reproducible quantity, druggability is not.
    vols, drugs = [], []
    n_ligand_confirmed, n_pooled = 0, 0
    for r in results.values():
        for d in r["by_clustering"].values():
            sp = d["site_pocket"]
            if sp:
                n_pooled += 1
                if d["site_pocket_selected_by"] == "ligand_site_jaccard":
                    n_ligand_confirmed += 1
                if sp.get("volume"):
                    vols.append(sp["volume"])
                if sp.get("druggability_score") is not None:
                    drugs.append(sp["druggability_score"])

    return {
        "structures": results,
        "ensemble": {
            "n_structures": len(pdb_ids),
            "clustering_swept": list(D_VALUES),
            # Which of the pooled pockets are the site and which are a guess.
            "site_pockets_pooled": n_pooled,
            "site_pockets_ligand_confirmed": n_ligand_confirmed,
            "_pooling_caveat": (
                "Values are pooled across structures AND clustering values. "
                "For a structure with no drug-like ligand there is no ligand "
                "site to match against, so its 'site pocket' is only the "
                "most druggable pocket anywhere in the chain — it need not be "
                "the site the holo structures point at. Check "
                "site_pocket_selected_by per structure before quoting a "
                "spread as being about one site."
            ),
            "volume_a3": {
                "min": min(vols) if vols else None,
                "max": max(vols) if vols else None,
                "spread_pct": (
                    round(100 * (max(vols) - min(vols)) / max(vols), 1)
                    if vols and max(vols)
                    else None
                ),
            },
            "druggability": {
                "min": min(drugs) if drugs else None,
                "max": max(drugs) if drugs else None,
                "fold_range": (
                    round(max(drugs) / min(drugs), 1)
                    if drugs and min(drugs) > 0
                    else None
                ),
                "_warning": (
                    "Druggability is NOT reproducible across structures or "
                    "clustering values. Measured 650-fold spread over one "
                    "TNF-alpha site. Report as a range; never drive a verdict "
                    "from a single value. Volume is the reliable number."
                ),
            },
        },
        "method": {
            "tool": "fpocket 4.2.3 (conda-forge)",
            "clustering_swept": list(D_VALUES),
            "druglike_min_heavy_atoms": DRUGLIKE_MIN_HEAVY_ATOMS,
            "druglike_excludes_cofactors": True,
            "ligand_site": "5.0 A heavy-atom shell, single ligand copy, kept chains only",
            "prep": "protein only, altloc A/blank, hydrogens stripped",
        },
    }


@app.local_entrypoint()
def main(pdb_ids: str = "6OIM,4OBE", ligand_codes: str = "MOV"):
    """Smoke test: the KRAS holo/apo pair the calibration was built on.

    Expected: 6OIM's switch-II pocket recovers the MOV site with high Jaccard
    at one D; 4OBE shows the same site collapsed. If 6OIM comes back with a
    low-overlap site, the prep or the parse is broken, not the biology.
    """
    out = pocket_scan.remote(
        pdb_ids=[p.strip() for p in pdb_ids.split(",")],
        ligand_codes=[c.strip() for c in ligand_codes.split(",")] or None,
    )
    print(json.dumps(out, indent=2))
