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
import shutil
import subprocess
import urllib.request
from pathlib import Path

import modal

# fpocket from conda-forge; proto-tools for the in-process CPU tools
# (vina-docking, foldseek-*, pyrosetta-*) that have no Proto Modal app.
# gemmi (0.7.5) arrives as a proto-tools dependency and is REQUIRED, not
# optional — the mmCIF parse is the whole input path now. If proto-tools ever
# stops depending on it this image needs an explicit `gemmi` pin.
image = (
    modal.Image.micromamba(python_version="3.12")
    .micromamba_install("fpocket", channels=["conda-forge"])
    .apt_install("git")
    .pip_install(
        # gemmi is a HARD requirement — mmCIF is the only structure format read.
        # It also arrives transitively via proto-tools, but pinning it directly
        # means a proto-tools dependency change cannot fail every structure at
        # stage "prepare".
        "gemmi>=0.7",
        "proto-tools[mcp] @ git+https://github.com/evo-design/proto-tools.git",
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

# Legal single-character PDB chain identifiers, in the order they get handed
# out when an mmCIF chain name will not fit column 22.
_PDB_CHAIN_POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _fetch(pdb_id: str, dest: Path) -> Path:
    """Fetch the mmCIF. Always the mmCIF, never the legacy PDB.

    Legacy PDB is not a subset of the truth, it is a lossy encoding of it, and
    three of its losses bite this module directly:

      * the chemical component ID has three columns. The PDB ran out of 3-char
        codes, so 2024+ depositions carry five-character comp_ids — 9SQX's
        ligand is `A1JPS`. Parsed out of columns 18-20 that reads as `A1J`,
        the ligand is never found, the ligand site comes back empty, and the
        run silently degrades to "most druggable pocket anywhere", which on
        9SQX picks a 3606 A^3 merge artifact. That was a real wrong answer on
        IL-17A, not a hypothetical.
      * chain IDs have one column, and >99999 atoms cannot be numbered.
      * RCSB no longer issues it at all for newer entries — verified, 9SQX.pdb
        is HTTP 404 while 9SQX.cif is 200. Recent structures are exactly where
        new chemistry lives, so a pdb-first fetcher fails on the most
        interesting targets.

    So mmCIF is the single source of truth for the whole per-structure pass,
    and the only PDB file in play is the one written for fpocket, which accepts
    nothing else.

    THE BIOLOGICAL ASSEMBLY, NOT THE ASYMMETRIC UNIT.

    The asymmetric unit is a crystallographic artifact. It may hold several
    copies of the biological unit, or only part of one, and both errors are
    silent and severe for pocket detection. Measured on our own runs:

      * 9SQX's preferred assembly is a DIMER, but its ASU holds two of them.
        Scoring all four chains fused them and produced a 3606 A^3 "pocket"
        that no molecule occupies.
      * 5HI3, the IL-17A macrocycle structure, has a HEPTAMER as its preferred
        assembly while the small-molecule site lies in the dimer groove.
      * 8USS's preferred assembly is a MONOMER, so a site that spans the
        IL-17A dimer interface is only half present — which is the likely
        reason it recovered 15 site residues at Jaccard 0.29 while 8DYG
        managed 0.69.

    So fetch `<ID>-assembly1.cif` first and record what was used. Falling back
    to the ASU is allowed but must be visible in the output, never silent.
    """
    cif = dest / f"{pdb_id}.cif"
    if cif.exists():
        return cif

    # Preferred biological assembly first.
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"https://files.rcsb.org/download/{pdb_id}-assembly1.cif", timeout=60
        ) as r:
            cif.write_bytes(r.read())
        (dest / f"{pdb_id}.source").write_text("assembly1")
        return cif
    except urllib.error.HTTPError:
        pass  # fall through to the asymmetric unit

    try:
        with urllib.request.urlopen(  # noqa: S310
            f"https://files.rcsb.org/download/{pdb_id}.cif", timeout=60
        ) as r:
            cif.write_bytes(r.read())
        (dest / f"{pdb_id}.source").write_text("asymmetric_unit")
    except urllib.error.HTTPError as exc:
        # Never let the raw HTTPError escape: it holds a BufferedReader, which
        # cannot pickle, so Modal reports an opaque SerializationError instead
        # of the 404 that actually happened.
        raise RuntimeError(f"{pdb_id}: no CIF at RCSB (HTTP {exc.code})") from None
    return cif


def _load(cif: Path) -> tuple[object, list[str], dict[str, str]]:
    """Parse the mmCIF ONCE into the object everything else is derived from.

    Returns (structure, missing_residues, chain_renaming).

    Cleaning happens here, not in each consumer, so that the ligand inventory,
    the ligand contact site and the file handed to fpocket can never disagree
    about which atoms exist:
      * hydrogens and deuteriums dropped (element symbol, not a name guess —
        mmCIF carries `type_symbol`, so HG the mercury is never a hydrogen);
      * altloc kept at blank or A, then blanked, so nothing downstream sees a
        partly occupied "A" as a distinct conformer.

    Chain names are forced to be single-character here as well, BEFORE anything
    reads them. This is the one place the mmCIF -> PDB round trip can silently
    corrupt a run, and it is worse than "gemmi renames the chain": measured on a
    2-character chain name, `make_pdb_string()` writes BOTH characters, into
    columns 21-22, eating the space after resName —

        ATOM      1  N   THRAA  44      -1.396  21.115   8.728

    so column 22 (the chain ID everything downstream slices) ends up holding the
    SECOND character. Two chains AA and BA would both come back as "A". fpocket
    reports pocket residues in the chain IDs of the file it was given, so those
    IDs would not match the site residues derived from the CIF, every Jaccard
    would be 0.0, and the module would report "no pocket overlapped the ligand
    site" on a structure where one plainly does. Renaming up front, once, with
    the map returned, makes the two sides consistent by construction; `_prep`
    re-reads the written file and asserts it.
    """
    import gemmi

    doc = gemmi.cif.read(str(cif))
    block = doc.sole_block()
    st = gemmi.make_structure_from_block(block)
    # `make_structure_from_block` emits one Chain per SUBCHAIN, so an entry with
    # polymer + ligand + waters under auth chain A comes back as three separate
    # Chain objects all called "A" — verified on 8DYG, six chains for a dimer.
    # `read_structure()` merges them and this must too, or the rename map below
    # would key several chains on one name.
    st.merge_chain_parts()
    st.setup_entities()
    st.remove_hydrogens()

    for chain in st[0]:
        for res in chain:
            for i in range(len(res) - 1, -1, -1):
                if res[i].altloc not in ("\x00", "A"):
                    del res[i]
                else:
                    res[i].altloc = "\x00"

    # Single-character chain IDs, keeping every name that already fits.
    used = {c.name for c in st[0] if len(c.name) == 1 and c.name != " "}
    pool = [c for c in _PDB_CHAIN_POOL if c not in used]
    renamed: dict[str, str] = {}
    for chain in st[0]:
        if (len(chain.name) == 1 and chain.name != " ") or chain.name in renamed:
            continue
        if not pool:
            raise RuntimeError(
                f"{cif.stem}: more chains than PDB chain IDs; cannot write "
                "an fpocket input without losing chain identity"
            )
        renamed[chain.name] = pool.pop(0)
    for old, new in renamed.items():
        st.rename_chain(old, new)

    # `_pdbx_unobs_or_zero_occ_residues` is the mmCIF category RCSB generates
    # REMARK 465 from — verified row-for-row against 6OIM's 16 REMARK 465 lines.
    missing: list[str] = []
    tab = block.find(
        "_pdbx_unobs_or_zero_occ_residues.",
        ["auth_asym_id", "auth_seq_id", "?PDB_model_num"],
    )
    for row in tab:
        if row.has(2) and row.str(2) not in ("", ".", "?", "1"):
            continue
        ch = row.str(0)
        missing.append(f"{renamed.get(ch, ch)}/{row.str(1)}")
    return st, missing, renamed


def _prep(st, dest: Path, stem: str, chains: list[str] | None) -> tuple[Path, list[str]]:
    """The fpocket input: polymer only, from the same object as everything else.

    Chain selection is per-target and deliberate: KRAS is a monomer, TNF-alpha's
    site sits on the trimer axis and disappears if you keep one chain.

    Polymer means het_flag == 'A', which is exactly what used to be selected by
    `line.startswith("ATOM")`. Modified residues (MSE and friends) are HETATM in
    both encodings and are dropped here as they always were.

    The written file's chain IDs are re-read and checked against the chains we
    think we wrote. fpocket's residue lists are only comparable to the ligand
    site because those two agree, so this is asserted rather than assumed.
    """
    import gemmi

    sel = gemmi.Structure()
    sel.name = st.name
    sel.cell = st.cell
    sel.spacegroup_hm = st.spacegroup_hm
    model = gemmi.Model("1")
    seen_chains = set()
    for chain in st[0]:
        if chains and chain.name not in chains:
            continue
        keep = gemmi.Chain(chain.name)
        for res in chain:
            if res.het_flag != "A" or not len(res):
                continue
            keep.add_residue(res)
        if len(keep):
            model.add_chain(keep)
            seen_chains.add(chain.name)
    sel.add_model(model)
    sel.setup_entities()

    # Only the coordinate records, as before — no CRYST1, no headers, nothing
    # for fpocket to have an opinion about.
    lines = [
        ln
        for ln in sel.make_pdb_string().splitlines()
        if ln.startswith(("ATOM", "TER", "END"))
    ]
    out = dest / f"{stem}_prep.pdb"
    out.write_text("\n".join(lines) + "\n")

    written = {ln[21] for ln in lines if ln.startswith("ATOM") and len(ln) >= 22}
    if written != seen_chains:
        raise RuntimeError(
            f"{stem}: chain IDs changed on PDB write ({sorted(seen_chains)} -> "
            f"{sorted(written)}); fpocket residues would not map to the "
            "ligand site"
        )
    return out, sorted(seen_chains)


def _ligands(st) -> list[dict]:
    """Nonpolymer ligands with heavy-atom counts, so 'holo' can be checked
    rather than assumed. A PEG or a cryoprotectant is not a holo ligand.

    comp_id comes from the mmCIF, so it is the FULL component ID: `A1JPS`, not
    the first three characters of it.
    """
    counts: dict[tuple[str, str, str], int] = {}
    for chain in st[0]:
        for res in chain:
            if res.het_flag != "H" or res.name in NON_LIGANDS or not len(res):
                continue
            key = (res.name, chain.name, str(res.seqid.num))
            counts[key] = counts.get(key, 0) + len(res)
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
    st,
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

    Same structure object as `_prep`, so the chain/resseq labels here are the
    ones fpocket will hand back.

    Returns (residues, "chain/resseq of the copy used").
    """
    copies: dict[tuple[str, str], list] = {}
    grid: dict[tuple[int, int, int], list] = {}
    for chain in st[0]:
        for res in chain:
            if res.het_flag == "H" and res.name == comp_id:
                copies.setdefault((chain.name, str(res.seqid.num)), []).extend(
                    (a.pos.x, a.pos.y, a.pos.z) for a in res
                )
            elif res.het_flag == "A":
                if chains and chain.name not in chains:
                    continue
                tag = f"{chain.name}/{res.seqid.num}"
                for a in res:
                    cell = (
                        int(a.pos.x // cutoff),
                        int(a.pos.y // cutoff),
                        int(a.pos.z // cutoff),
                    )
                    grid.setdefault(cell, []).append((a.pos.x, a.pos.y, a.pos.z, tag))
    c2 = cutoff * cutoff
    offsets = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]

    def contacts(lig: list) -> set:
        # Cell-hashed at the cutoff, so the 27 neighbouring cells hold every
        # atom that can possibly be within it. Same answer as all-pairs.
        hits = set()
        for lx, ly, lz in lig:
            base = (int(lx // cutoff), int(ly // cutoff), int(lz // cutoff))
            for di, dj, dk in offsets:
                for px, py, pz, tag in grid.get(
                    (base[0] + di, base[1] + dj, base[2] + dk), ()
                ):
                    if tag in hits:
                        continue
                    if (px - lx) ** 2 + (py - ly) ** 2 + (pz - lz) ** 2 <= c2:
                        hits.add(tag)
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
        # One unfetchable structure must not lose the whole ensemble, and the
        # reason must survive the trip back: exceptions holding open file
        # handles cannot pickle, so Modal replaces them with an opaque
        # SerializationError. Record the failure as data instead.
        stage = "fetch"
        try:
            cif = _fetch(pid, work)
            st, missing_res, renamed = _load(cif)
            # Everything below reads the one structure object loaded above, so
            # chain IDs and residue numbers are the same in the fpocket input,
            # the ligand list, the ligand site and the missing-residue list.
            stage = "prepare"
            want = (
                sorted({renamed.get(c, c) for c in chains[pid]})
                if chains.get(pid)
                else None
            )
            prepped, used_chains = _prep(st, work, pid, want)
            ligs = _ligands(st)
        except Exception as exc:  # noqa: BLE001
            results[pid] = {
                "error": f"{type(exc).__name__}: {exc}",
                "stage": stage,
                "tier": "none",
                "by_clustering": {},
            }
            continue

        if want:
            missing_res = [r for r in missing_res if r.split("/")[0] in want]
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
            _ligand_site(st, target_comp, used_chains)
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

        src_marker = work / f"{pid}.source"
        results[pid] = {
            "structure_source": (
                src_marker.read_text() if src_marker.exists() else "unknown"
            ),
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
        if renamed:
            # Only when an mmCIF chain name would not fit a PDB column. Present
            # so a caller comparing against the deposited entry can see that
            # the chain IDs in every residue list above are ours, not RCSB's.
            results[pid]["chain_renamed_from_cif"] = renamed

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
            # Provenance: legacy PDB truncates comp_ids to 3 characters and is
            # not issued at all for newer entries, so nothing here is derived
            # from it. The PDB written for fpocket comes out of the mmCIF.
            "source_format": "mmCIF (files.rcsb.org/download/<ID>.cif), parsed with gemmi",
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
