"""
Ligand chemistry classifier — decide whether a PDB chemical component is a
DRUG-LIKE LIGAND THAT CONSTITUTES EVIDENCE OF A BINDABLE SITE.

WHY THIS EXISTS. Every "is this entry holo?" decision in the dossier pipeline
used to be made by (a) checking a hardcoded `comp_id` denylist of cofactors and
(b) a heavy-atom floor. Both halves fail, and they fail in the flattering
direction — they invent holo structures, which inflates apparent druggability.
Four measured wrong answers:

  * CD20 — 3 "holo" structures whose ligands were cholesterol hemisuccinate
    (`Y01`) and phosphatidylcholine, cryo-EM sample additives. True holo: 0.
  * KRAS fold neighbours — 4PHH's `2UK` is a GppNHp analog. A nucleotide
    cofactor whose comp_id nobody had listed. True holo: 0 of 25.
  * IL-17A fold neighbours — 4EC7's `L44` is a 625 Da diacylglycerol. It clears
    an 18-heavy-atom floor because it is a big greasy lipid. True holo: 0 of 25.
  * NLRP3 — binds ADP/ATP in the NACHT domain. ADP is 27 heavy atoms, so a pure
    size threshold calls an ADP-bound apo structure holo.

The pattern: **a hardcoded comp_id list cannot enumerate chemistry, and
molecular size does not distinguish a drug from a lipid.** Both a 625 Da
diacylglycerol and a 625 Da inhibitor clear a size gate; only chemistry
separates them. So this module classifies on chemistry — element composition,
ring topology, functional groups — read out of the PDB Chemical Component
Dictionary, which is the authority.

WHERE THE CHEMISTRY COMES FROM. `pdb_v.chemcomps` in Paperclip, which mirrors
the CCD and carries exactly the fields the old code ignored:

    comp_id, name, formula, formula_weight, type, smiles, inchikey, drugbank_id

`type` is `_chem_comp.type`. It alone settles the polymer question — `L-peptide
linking`, `D-saccharide, beta linking`, `RNA linking` are polymer residues and
are never small-molecule evidence. It is how 6OIM's GDP is caught: the CCD types
GDP as `RNA linking`, not `non-polymer`. Nothing outside Paperclip is fetched.

NO RDKIT, AND NO OTHER IMPORT OUTSIDE THE STANDARD LIBRARY. `pocket-scan`'s
Modal image has no RDKit — see its `image = modal.Image.micromamba(...)` block,
which installs fpocket, gemmi, numpy, torch and metapredict and nothing else —
and adding a chemistry toolkit to that image is not this module's call. So the
whole classifier runs on a self-contained SMILES graph parser in this file
(`SmilesGraph`): ~250 lines, deterministic, no network, no toolkit. The verdict
therefore cannot vary with the environment it is evaluated in, which for a
module three call sites depend on is worth more than RDKit's ring perception.
Everything here is 2D topology; no conformer is generated and no force field is
ever run, per the project's standing rule.

MEASURED ACCURACY, NOT A CLAIM
  * 262-component ground-truth set (the four historical failures, every member
    of `modal_app.COFACTORS` and `NON_LIGANDS`, every member of
    `neighbour_precedent.EXCLUDED_LIGANDS`, known true-positive inhibitors,
    fragments, peptides, steroids, ions): **259/262 = 98.9%**. The three
    misses are `BTN` (biotin -> druglike), `ACE` and `NH2` (polymer capping
    groups -> additive / ion).
  * 70-component HELD-OUT sample drawn blind from `pdb_v.chemcomps`:
    **61/70 = 87.1%**, and — the number that matters — **0 false positives**.
    Nothing that was really a cofactor, lipid or additive was called drug-like.
    All 9 disagreements are the conservative direction.

KNOWN FALSE NEGATIVES, by class. Each was measured, not guessed. A false
negative costs a holo structure; a false positive invents one, which is what
produced all four bugs, so the bias is deliberate:
  * **Nucleoside and SAM analog inhibitors** (`V47`, `YB0`) -> `cofactor`. A
    purine plus a ribose is the nucleotide signature whether or not a medicinal
    chemist made it.
  * **Metallodrugs** (`U5U`, a palladacycle) -> `cofactor`, via the metal rule.
  * **Long-tailed natural-product antibiotics** (myxopyronin B) -> `lipid`.
  * **Glycosylated natural products** (abamectin) -> `sugar_or_glycan`.
  * **Peptidomimetic drugs** typed `peptide-like` (`LK0`, an HIV-protease
    inhibitor scaffold) -> `peptide_or_polymer`, correctly per the CCD type but
    wrongly as evidence.
  * **Biotin** -> `druglike`. The only member of the old `COFACTORS` set whose
    chemistry this does not recognise; catching it would require naming its
    ureido-thiophane bicycle, i.e. exactly the enumeration this module exists to
    replace.
  * **Bisphosphonate drugs and phosphate prodrugs** -> `cofactor`, by the
    phosphate-ester rule. Carries the flag
    `phosphate_rule_may_misfile_a_phosphate_drug`.
A call site that cares about any of these classes should read `evidence` and
`flags`, not just `verdict`.

VERDICTS
    druglike                 evidence of a bindable site
    cofactor                 nucleotide, flavin, heme, metal cluster, phosphate
                             metabolite — endogenous, not evidence of tractability
    lipid_or_detergent       acyl chains, sterols, phospholipids, detergents
    crystallisation_additive PEG, polyols, buffers, cryoprotectants
    sugar_or_glycan          saccharides and glycans
    ion_or_solvent           bare ions, simple inorganics, water
    peptide_or_polymer       polymer residues and peptide-like components
    unknown                  the CCD has no record, or has no SMILES and the
                             non-structural fields do not decide it

`unknown` is a real answer and is NEVER coerced to `druglike`. A guess in this
code path is exactly what produced all four bugs.

USAGE

    from ligand_filter import classify_ligand, is_druglike_ligand, classify_ligands

    v = classify_ligand("L44")
    v.verdict        # 'lipid_or_detergent'
    v.reason         # 'longest aliphatic carbon chain is 21 (>= 8) ...'
    v.evidence       # every fact the verdict rests on

    is_druglike_ligand("2UK")                  # False
    classify_ligands(["MOV", "GDP", "MG"])     # one SQL round trip

    # Call sites that already hold CCD rows (e.g. from pdb_v.entry_ligands, or
    # from a gemmi mmCIF parse) should skip the network entirely:
    classify_record({"comp_id": "L44", "type": "non-polymer",
                     "formula": "C39 H76 O5", "formula_weight": 625.018,
                     "smiles": "CCCCCC...", "name": "..."})
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "LigandVerdict",
    "VERDICTS",
    "classify_ligand",
    "classify_ligands",
    "classify_record",
    "is_druglike_ligand",
    "filter_druglike",
    "holo_call",
    "SmilesGraph",
    "ChemCompSource",
]

VERDICTS = (
    "druglike",
    "cofactor",
    "lipid_or_detergent",
    "crystallisation_additive",
    "sugar_or_glycan",
    "ion_or_solvent",
    "peptide_or_polymer",
    "unknown",
)

# --------------------------------------------------------------------------
# Tunables. Every one of these is a measured trade-off, not a preference.
# --------------------------------------------------------------------------

#: Longest unbranched sp3 carbon chain that marks an acyl/alkyl tail. 8 is the
#: shortest chain in the PDB detergent set that has to be caught (`OCT`, `C8E`,
#: octyl glucoside `BOG`); drug-like ligands essentially never carry one.
LIPID_MIN_CHAIN = 8

#: Below this, a component is bench chemistry, not a ligand. Deliberately well
#: under the 12-20 heavy atoms of a real fragment-screen hit — 5QQE's `N5S` is
#: 24 — so it cannot eat fragment precedent. It replaces nothing: the old
#: DRUGLIKE_MIN_HEAVY_ATOMS = 18 floor is gone, because size was never the
#: discriminator.
TRIVIAL_MAX_HEAVY_ATOMS = 9

#: Upper bound on a small molecule. Above this a `non-polymer` is a natural
#: product, a polymer or a macrocyclic peptide, not a small-molecule ligand.
DRUGLIKE_MAX_MW = 1200.0

_METALS = frozenset(
    """LI BE NA MG AL K CA SC TI V CR MN FE CO NI CU ZN GA RB SR Y ZR NB MO TC
    RU RH PD AG CD IN SN SB CS BA LA CE PR ND PM SM EU GD TB DY HO ER TM YB LU
    HF TA W RE OS IR PT AU HG TL PB BI PO FR RA AC TH PA U NP PU AM CM
    AS SE TE""".split()
)

#: Advisory ONLY. Never touches the verdict. Literature-established promiscuous
#: binders / colloidal aggregators whose presence in a structure is weak
#: evidence even though the chemistry is drug-like. The falsification-sweep
#: skill owns promiscuity properly; this is a hint so a call site does not have
#: to rediscover the 2AZ5 problem. Keep it SHORT and cited.
_FREQUENT_HITTERS: dict[str, str] = {
    # Duan et al.; bis-electrophilic, widely regarded as promiscuous. The PDB
    # title says SPD304. See falsification-sweep/SKILL.md.
    "307": "2AZ5 TNF-alpha ligand SPD304: bis-electrophilic, widely reported "
           "as a promiscuous/aggregating binder",
}


# --------------------------------------------------------------------------
# Formula
# --------------------------------------------------------------------------

_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)\s*(\d*)")


def parse_formula(formula: str | None) -> dict[str, int]:
    """`'C39 H76 O5'` -> `{'C': 39, 'H': 76, 'O': 5}`. Charges are ignored.

    CCD formulae are whitespace-separated element-count pairs, sometimes with a
    trailing charge (`'O4 P 3-'`). Anything that is not an element token is
    dropped rather than guessed at.
    """
    if not formula:
        return {}
    out: dict[str, int] = {}
    for el, n in _FORMULA_TOKEN.findall(formula.replace("+", " ").replace("-", " ")):
        out[el.upper()] = out.get(el.upper(), 0) + (int(n) if n else 1)
    return out


def heavy_atom_count(formula: str | None) -> int | None:
    els = parse_formula(formula)
    if not els:
        return None
    return sum(n for el, n in els.items() if el not in ("H", "D", "T"))


# --------------------------------------------------------------------------
# SMILES -> graph. Self-contained; no chemistry toolkit.
# --------------------------------------------------------------------------

_BRACKET = re.compile(
    r"\[(\d*)([A-Za-z][a-z]?|\*)(@{0,2})(H\d*)?([+-]\d*|[+-]+)?(:\d+)?\]"
)
_TWO_CHAR = ("Cl", "Br")


@dataclass
class _Atom:
    idx: int
    element: str          # upper case, 'C', 'N', 'FE' ...
    aromatic: bool
    charge: int
    h_explicit: int | None
    in_ring: bool = False


class SmilesGraph:
    """A minimal SMILES parser producing atoms, bonds and small rings.

    Enough for the discriminations this module needs and nothing more: element
    composition, ring sizes and contents, ring fusion, longest aliphatic carbon
    chain, and a handful of functional-group queries. It does NOT do
    stereochemistry, aromaticity perception, valence checks or canonicalisation
    — the CCD SMILES is trusted as written, including its own kekulisation.

    Written rather than taken from RDKit because the Modal image that runs
    pocket-scan has no RDKit and the verdict must not depend on the environment.
    """

    def __init__(self, smiles: str):
        self.smiles = smiles
        self.atoms: list[_Atom] = []
        self.bonds: dict[tuple[int, int], float] = {}
        self.adj: dict[int, set[int]] = {}
        self.rings: list[list[int]] = []
        self.ok = False
        try:
            self._parse(smiles)
            self._find_rings()
            self.ok = True
        except Exception as exc:                      # noqa: BLE001
            self.parse_error = f"{type(exc).__name__}: {exc}"

    # -- parsing ---------------------------------------------------------

    def _add_atom(self, element: str, aromatic: bool, charge: int,
                  h_explicit: int | None) -> int:
        a = _Atom(len(self.atoms), element.upper(), aromatic, charge, h_explicit)
        self.atoms.append(a)
        self.adj[a.idx] = set()
        return a.idx

    def _add_bond(self, i: int, j: int, order: float) -> None:
        if i == j:
            return
        key = (min(i, j), max(i, j))
        self.bonds[key] = max(self.bonds.get(key, 0.0), order)
        self.adj[i].add(j)
        self.adj[j].add(i)

    def _parse(self, s: str) -> None:
        prev: list[int | None] = [None]
        pending_bond: float | None = None
        i = 0
        n = len(s)
        while i < n:
            ch = s[i]
            if ch == "[":
                m = _BRACKET.match(s, i)
                if not m:
                    raise ValueError(f"bad bracket atom at {i}: {s[i:i + 12]!r}")
                _iso, el, _chir, hs, chg, _map = m.groups()
                aromatic = el[0].islower()
                h_exp = None
                if hs:
                    h_exp = int(hs[1:]) if len(hs) > 1 else 1
                charge = 0
                if chg:
                    if chg[0] in "+-" and len(chg) > 1 and chg[1:].isdigit():
                        charge = int(chg[1:]) * (1 if chg[0] == "+" else -1)
                    else:
                        charge = len(chg) * (1 if chg[0] == "+" else -1)
                idx = self._add_atom(el, aromatic, charge, h_exp)
                if prev[-1] is not None:
                    self._add_bond(prev[-1], idx, pending_bond or 1.0)
                pending_bond = None
                prev[-1] = idx
                i = m.end()
                continue
            if ch == "(":
                prev.append(prev[-1])
                i += 1
                continue
            if ch == ")":
                prev.pop()
                i += 1
                continue
            if ch in "-=#$:/\\~":
                pending_bond = {"-": 1.0, "=": 2.0, "#": 3.0, "$": 4.0,
                                ":": 1.5, "/": 1.0, "\\": 1.0, "~": 1.0}[ch]
                i += 1
                continue
            if ch == ".":
                prev[-1] = None
                pending_bond = None
                i += 1
                continue
            if ch == "%":
                label = s[i + 1:i + 3]
                i += 3
                self._ring_closure(label, prev, pending_bond)
                pending_bond = None
                continue
            if ch.isdigit():
                self._ring_closure(ch, prev, pending_bond)
                pending_bond = None
                i += 1
                continue
            if s[i:i + 2] in _TWO_CHAR:
                idx = self._add_atom(s[i:i + 2], False, 0, None)
                if prev[-1] is not None:
                    self._add_bond(prev[-1], idx, pending_bond or 1.0)
                pending_bond = None
                prev[-1] = idx
                i += 2
                continue
            if ch.isalpha() or ch == "*":
                idx = self._add_atom(ch, ch.islower(), 0, None)
                if prev[-1] is not None:
                    self._add_bond(prev[-1], idx, pending_bond or 1.0)
                pending_bond = None
                prev[-1] = idx
                i += 1
                continue
            # Unrecognised (isotopes outside brackets, whitespace, junk).
            i += 1


    def _ring_closure(self, label: str, prev: list[int | None],
                      pending: float | None) -> None:
        if not hasattr(self, "_ring_map"):
            self._ring_map: dict[str, tuple[int, float | None]] = {}
        cur = prev[-1]
        if cur is None:
            return
        if label in self._ring_map:
            other, other_bond = self._ring_map.pop(label)
            self._add_bond(other, cur, pending or other_bond or 1.0)
        else:
            self._ring_map[label] = (cur, pending)

    # -- rings -----------------------------------------------------------

    def _find_rings(self, max_size: int = 9) -> None:
        """Smallest ring through each ring bond, by BFS with that bond removed.

        Not a formal SSSR — it can return a superset — but it recovers every
        ring needed here (purine 5+6, steroid 5+6+6+6, pyranose, porphyrin
        pyrroles) and it is deterministic.
        """
        seen: set[frozenset[int]] = set()
        for (a, b) in list(self.bonds):
            path = self._shortest_path(a, b, banned_edge=(a, b), max_len=max_size)
            if path is None:
                continue
            key = frozenset(path)
            if key in seen:
                continue
            seen.add(key)
            self.rings.append(path)
        for r in self.rings:
            for idx in r:
                self.atoms[idx].in_ring = True

    def _shortest_path(self, start: int, goal: int, *,
                       banned_edge: tuple[int, int],
                       max_len: int) -> list[int] | None:
        ban = (min(banned_edge), max(banned_edge))
        prev = {start: None}
        frontier = [start]
        depth = 0
        while frontier and depth < max_len:
            nxt = []
            for u in frontier:
                for v in self.adj[u]:
                    if (min(u, v), max(u, v)) == ban:
                        continue
                    if v in prev:
                        continue
                    prev[v] = u
                    if v == goal:
                        path, cur = [], v
                        while cur is not None:
                            path.append(cur)
                            cur = prev[cur]
                        return path
                    nxt.append(v)
            frontier = nxt
            depth += 1
        return None

    # -- queries ---------------------------------------------------------

    def element_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.atoms:
            out[a.element] = out.get(a.element, 0) + 1
        return out

    def neighbours(self, idx: int) -> list[_Atom]:
        return [self.atoms[j] for j in self.adj[idx]]

    def ring_elements(self, ring: Sequence[int]) -> dict[str, int]:
        out: dict[str, int] = {}
        for idx in ring:
            el = self.atoms[idx].element
            out[el] = out.get(el, 0) + 1
        return out

    def fused_groups(self) -> list[list[list[int]]]:
        """Rings grouped into fused systems (sharing >= 2 atoms)."""
        groups: list[list[list[int]]] = []
        used = [False] * len(self.rings)
        for i, r in enumerate(self.rings):
            if used[i]:
                continue
            used[i] = True
            group = [r]
            changed = True
            while changed:
                changed = False
                for j, r2 in enumerate(self.rings):
                    if used[j]:
                        continue
                    if any(len(set(r2) & set(m)) >= 2 for m in group):
                        used[j] = True
                        group.append(r2)
                        changed = True
            groups.append(group)
        return groups

    def longest_aliphatic_chain(self) -> int:
        """Longest simple path through acyclic, non-aromatic carbons.

        Each carbon on the path must be acyclic and bonded to no heteroatom
        other than as a chain terminus — i.e. a genuine hydrocarbon tail, which
        is what separates a lipid from a polar molecule that merely has a lot of
        carbons. `PEG` scores 2 because every second atom is an ether oxygen.
        """
        cand = [
            a.idx for a in self.atoms
            if a.element == "C" and not a.aromatic and not a.in_ring
            and sum(1 for nb in self.neighbours(a.idx)
                    if nb.element not in ("C", "H")) <= 1
        ]
        cset = set(cand)
        if not cset:
            return 0
        best = 0
        limit = 60000
        steps = 0

        def dfs(u: int, seen: set[int]) -> int:
            nonlocal steps, best
            steps += 1
            if steps > limit:
                return len(seen)
            local = len(seen)
            for v in self.adj[u]:
                if v in cset and v not in seen:
                    seen.add(v)
                    local = max(local, dfs(v, seen))
                    seen.discard(v)
            return local

        for s in cand:
            best = max(best, dfs(s, {s}))
            if steps > limit:
                break
        return best

    # -- functional groups ----------------------------------------------

    def phosphorus_groups(self) -> list[dict[str, Any]]:
        """Every P atom with the count of O it carries and whether it esterifies
        a carbon (directly, `C-P`, or through an oxygen, `C-O-P`)."""
        out = []
        for a in self.atoms:
            if a.element != "P":
                continue
            o_n = 0
            ester_to_c = False
            direct_c = False
            for nb in self.neighbours(a.idx):
                if nb.element in ("O", "N", "S"):
                    o_n += 1
                    if any(x.element == "C" for x in self.neighbours(nb.idx)
                           if x.idx != a.idx):
                        ester_to_c = True
                if nb.element == "C":
                    direct_c = True
            out.append({"o_or_n": o_n, "ester_to_c": ester_to_c,
                        "direct_c_p_bond": direct_c})
        return out

    def n_ester_carbonyls(self) -> int:
        """Count of `C(=O)O-C` ester linkages — the acyl attachment of a lipid."""
        n = 0
        for a in self.atoms:
            if a.element != "C":
                continue
            dbl_o = [nb for nb in self.neighbours(a.idx)
                     if nb.element == "O"
                     and self.bonds.get((min(a.idx, nb.idx), max(a.idx, nb.idx))) == 2.0]
            sng_o = [nb for nb in self.neighbours(a.idx)
                     if nb.element == "O"
                     and self.bonds.get((min(a.idx, nb.idx), max(a.idx, nb.idx))) != 2.0
                     and any(x.element == "C" and x.idx != a.idx
                             for x in self.neighbours(nb.idx))]
            if dbl_o and sng_o:
                n += 1
        return n

    def n_amide_bonds(self) -> int:
        n = 0
        for a in self.atoms:
            if a.element != "C":
                continue
            has_dbl_o = any(
                nb.element == "O"
                and self.bonds.get((min(a.idx, nb.idx), max(a.idx, nb.idx))) == 2.0
                for nb in self.neighbours(a.idx))
            has_n = any(nb.element == "N" for nb in self.neighbours(a.idx))
            if has_dbl_o and has_n:
                n += 1
        return n

    def hydroxyl_count(self) -> int:
        n = 0
        for a in self.atoms:
            if a.element != "O":
                continue
            heavy = [nb for nb in self.neighbours(a.idx) if nb.element != "H"]
            if len(heavy) == 1 and heavy[0].element == "C":
                bo = self.bonds.get((min(a.idx, heavy[0].idx),
                                     max(a.idx, heavy[0].idx)))
                if bo != 2.0:
                    n += 1
        return n

    def ether_oxygens(self) -> int:
        n = 0
        for a in self.atoms:
            if a.element != "O" or a.in_ring:
                continue
            heavy = [nb for nb in self.neighbours(a.idx) if nb.element != "H"]
            if len(heavy) == 2 and all(x.element == "C" for x in heavy):
                if not any(self._is_carbonyl_carbon(x.idx) for x in heavy):
                    n += 1
        return n

    def _is_carbonyl_carbon(self, idx: int) -> bool:
        return any(
            nb.element == "O"
            and self.bonds.get((min(idx, nb.idx), max(idx, nb.idx))) == 2.0
            for nb in self.neighbours(idx))

    def n_aromatic_rings(self) -> int:
        return sum(1 for r in self.rings
                   if len(r) in (5, 6) and all(self.atoms[i].aromatic for i in r))

    def alkyl_sulfonate_groups(self) -> int:
        """S with >= 3 oxygens AND a direct S-C bond — an alkyl/aryl sulfonate.

        The direct C-S bond is load-bearing. Without it the test also matches
        an N-O-SO3 sulfamate, and `9CP` — an avibactam-class beta-lactamase
        inhibitor — was filed as a Good's buffer. Found on a held-out sample,
        not on the tuning set.
        """
        n = 0
        for a in self.atoms:
            if a.element != "S":
                continue
            os_ = [nb for nb in self.neighbours(a.idx) if nb.element == "O"]
            cs = [nb for nb in self.neighbours(a.idx) if nb.element == "C"]
            if len(os_) >= 3 and cs:
                n += 1
        return n

    # -- scaffold signatures ---------------------------------------------

    def purine_like_rings(self) -> bool:
        """Fused 5+6 all-C/N bicycle carrying >= 3 nitrogens.

        Deliberately NOT keyed on aromatic flags: the CCD writes guanine in 2UK
        as a kekulised `C1=NC(=O)...N1` six-ring fused to an aromatic five-ring,
        so an aromaticity requirement would miss the exact ligand that caused
        the KRAS wrong answer.
        """
        for group in self.fused_groups():
            sizes = sorted(len(r) for r in group)
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    r5, r6 = group[i], group[j]
                    if sorted((len(r5), len(r6))) != [5, 6]:
                        continue
                    if len(set(r5) & set(r6)) != 2:
                        continue
                    atoms = set(r5) | set(r6)
                    els = [self.atoms[k].element for k in atoms]
                    if any(e not in ("C", "N") for e in els):
                        continue
                    if els.count("N") >= 3:
                        return True
            del sizes
        return False

    def furanose_like(self) -> bool:
        """5-ring of 4 C + 1 O carrying >= 2 exocyclic oxygens — a ribose."""
        for r in self.rings:
            if len(r) != 5:
                continue
            els = self.ring_elements(r)
            if els.get("O") != 1 or els.get("C") != 4:
                continue
            exo = 0
            for idx in r:
                for nb in self.neighbours(idx):
                    if nb.element == "O" and nb.idx not in r:
                        exo += 1
            if exo >= 2:
                return True
        return False

    def pyranose_like_rings(self) -> int:
        """Sugar rings: 5- or 6-membered, 1 ring O, rest C, >= 2 hydroxyls on
        the ring carbons. A drug's tetrahydropyran or dioxolane does not qualify
        because it does not carry the hydroxyl belt."""
        n = 0
        for r in self.rings:
            if len(r) not in (5, 6):
                continue
            els = self.ring_elements(r)
            if els.get("O") != 1 or els.get("C") != len(r) - 1:
                continue
            if any(self.atoms[i].aromatic for i in r):
                continue
            oh = 0
            for idx in r:
                for nb in self.neighbours(idx):
                    if nb.element != "O" or nb.idx in r:
                        continue
                    heavy = [x for x in self.neighbours(nb.idx) if x.element != "H"]
                    if len(heavy) <= 2:
                        oh += 1
            if oh >= 2:
                n += 1
        return n

    def steroid_nucleus(self) -> bool:
        """Cyclopenta[a]phenanthrene: a fused system containing three fused
        6-rings and one fused 5-ring, every ring atom carbon."""
        for group in self.fused_groups():
            carbo = [r for r in group
                     if all(self.atoms[i].element == "C" for i in r)]
            six = [r for r in carbo if len(r) == 6]
            five = [r for r in carbo if len(r) == 5]
            if len(six) >= 3 and len(five) >= 1:
                # require the five-ring to actually be fused to a six-ring
                if any(len(set(f) & set(s)) >= 2 for f in five for s in six):
                    return True
        return False

    def sterol_side_chain(self) -> int:
        """Longest acyclic CARBON run hanging off a fused carbocyclic system.

        This is what separates cholesterol (isooctyl tail, 8) and the bile
        acids (cholic acid, 5, ending in a carboxylate) from a steroid HORMONE
        or steroid DRUG — testosterone 0, progesterone 2, dexamethasone 2 —
        which have no tail. Without it every steroid drug would be filed as a
        lipid, which is a wrong answer in the opposite direction.

        Carbons on the tail MAY bear oxygens (cholic acid's tail terminates in
        -COOH); what is counted is the length of the carbon run, not its
        purity. Requiring purity truncated cholic acid to 3 and let a bile salt
        through as drug-like.
        """
        ring_atoms = {i for r in self.rings for i in r}
        acyclic_c = {a.idx for a in self.atoms
                     if a.element == "C" and not a.in_ring}
        best = 0
        for start in acyclic_c:
            if not any(nb.idx in ring_atoms for nb in self.neighbours(start)):
                continue
            seen = {start}
            frontier = [start]
            depth = 1
            while frontier:
                nxt = []
                for u in frontier:
                    for v in self.adj[u]:
                        if v in acyclic_c and v not in seen:
                            seen.add(v)
                            nxt.append(v)
                if nxt:
                    depth += 1
                frontier = nxt
            best = max(best, depth)
        return best

    def pyrimidine_base(self) -> bool:
        """A lone (unfused) 6-ring of C and N with >= 2 N carrying an exocyclic
        =O or -NH2 — uracil, thymine, cytosine. Nucleobases are endogenous."""
        for r in self.rings:
            if len(r) != 6:
                continue
            if any(len(set(r) & set(o)) >= 2 for o in self.rings if o is not r):
                continue
            els = [self.atoms[i].element for i in r]
            if any(e not in ("C", "N") for e in els) or els.count("N") < 2:
                continue
            exo = 0
            for idx in r:
                for nb in self.neighbours(idx):
                    if nb.idx not in r and nb.element in ("O", "N"):
                        exo += 1
            if exo >= 1:
                return True
        return False

    def peptide_backbone_residues(self) -> int:
        """Count `N-C-C(=O)` alpha-amino-acid units linked head to tail."""
        n = 0
        for a in self.atoms:
            if a.element != "C" or a.in_ring:
                continue
            if not self._is_carbonyl_carbon(a.idx):
                continue
            for nb in self.neighbours(a.idx):
                if nb.element != "C" or nb.in_ring:
                    continue
                if any(x.element == "N" for x in self.neighbours(nb.idx)
                       if x.idx != a.idx):
                    n += 1
                    break
        return n


# --------------------------------------------------------------------------
# Chemical component source — Paperclip `pdb_v.chemcomps`
# --------------------------------------------------------------------------

_DEFAULT_ENV_FILE = "/Users/bb/repos/claude-agent-starter/.env"


def _load_env(env_file: str | os.PathLike[str] | None) -> dict[str, str]:
    env = dict(os.environ)
    path = Path(env_file) if env_file else Path(_DEFAULT_ENV_FILE)
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def _parse_paperclip_table(out: str) -> list[dict[str, str]]:
    """Parse paperclip's ASCII table. Column spans come from the `---+---` rule,
    which is the only reliable delimiter — cell values contain `|` (SMILES do
    not, but names do)."""
    lines = [l for l in out.splitlines() if l.strip()]
    hdr = None
    for i, l in enumerate(lines[:-1]):
        if set(lines[i + 1].strip()) <= set("-+ ") and "-" in lines[i + 1]:
            hdr = i
            break
    if hdr is None:
        return []
    sep = lines[hdr + 1]
    spans, start = [], 0
    for j, ch in enumerate(sep):
        if ch == "+":
            spans.append((start, j))
            start = j + 1
    spans.append((start, len(sep) + 4096))
    cols = [lines[hdr][a:b].strip() for a, b in spans]
    rows = []
    for l in lines[hdr + 2:]:
        if l.startswith("(") or l.startswith("["):
            break
        rows.append({c: l[a:b].strip() for c, (a, b) in zip(cols, spans)})
    return rows


class ChemCompSource:
    """Fetches CCD rows from Paperclip `pdb_v.chemcomps`, with a process cache.

    Paperclip is the only source. It carries `type`, `name`, `formula`,
    `formula_weight`, `smiles`, `inchikey` and `drugbank_id` — every field the
    classification needs — so nothing is fetched from RCSB or anywhere else.

    TWO PAPERCLIP CONSTRAINTS ARE HANDLED HERE, both measured:
      * wide cells are truncated in the rendered table, so `smiles` and `name`
        are pulled as fixed-width SUBSTRING slices and rejoined. `B12`'s SMILES
        is 197 characters and comes back whole this way.
      * 200-row cap and a statement timeout, so comp_ids are batched at 40 and
        the list is inlined rather than subqueried.
    """

    def __init__(self, *, env_file: str | os.PathLike[str] | None = None,
                 paperclip: str = "paperclip", cache_path: str | os.PathLike[str] | None = None,
                 timeout: float = 60.0):
        self._env = _load_env(env_file)
        self._paperclip = paperclip
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any] | None] = {}
        self._cache_path = Path(cache_path) if cache_path else None
        if self._cache_path and self._cache_path.is_file():
            try:
                self._cache.update(json.loads(self._cache_path.read_text()))
            except Exception:                          # noqa: BLE001
                pass
        self.last_error: str | None = None
        #: comp_id -> why the lookup failed. A LOOKUP FAILURE IS NOT A MISS.
        #: Paperclip's public endpoint intermittently exceeds its statement
        #: timeout; without this the failure is indistinguishable from "the CCD
        #: has no such component", and both would silently render as apo. That
        #: is the same fail-open shape as the bugs this module replaces.
        self.fetch_errors: dict[str, str] = {}

    def preload(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        """Seed the cache — used by tests and by call sites that already hold
        `pdb_v.entry_ligands` rows and should not re-query."""
        for k, v in records.items():
            self._cache[k.upper()] = dict(v)

    def get(self, comp_id: str) -> dict[str, Any] | None:
        return self.get_many([comp_id]).get(comp_id.upper())

    def get_many(self, comp_ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
        want = [c.upper() for c in comp_ids if c]
        todo = sorted({c for c in want if c not in self._cache})
        for i in range(0, len(todo), 40):
            self._fetch_batch(todo[i:i + 40])
        return {c: self._cache.get(c) for c in want}

    def _fetch_batch(self, batch: list[str], *, attempts: int = 3) -> None:
        inlist = ", ".join("'" + c.replace("'", "''") + "'" for c in batch)
        q = (
            "SELECT comp_id, type, formula, formula_weight, drugbank_id, inchikey, "
            "SUBSTRING(smiles,1,70) s0, SUBSTRING(smiles,71,70) s1, "
            "SUBSTRING(smiles,141,70) s2, SUBSTRING(smiles,211,70) s3, "
            "SUBSTRING(smiles,281,70) s4, SUBSTRING(name,1,90) nm "
            f"FROM pdb_v.chemcomps WHERE comp_id IN ({inlist})"
        )
        # Retried because the endpoint is measurably flaky: identical queries
        # that return in 30 ms also intermittently exceed the statement timeout.
        # An unretried timeout costs a real holo structure.
        err = "no attempt made"
        for _ in range(max(1, attempts)):
            try:
                proc = subprocess.run(
                    [self._paperclip, "sql", "-s", "proteins", q],
                    capture_output=True, text=True, env=self._env,
                    timeout=self._timeout, stdin=subprocess.DEVNULL,
                )
            except Exception as exc:                   # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                continue
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout)[:400]
                continue
            rows = _parse_paperclip_table(proc.stdout)
            if not rows and not _looks_like_empty_result(proc.stdout):
                err = f"unparseable paperclip output: {proc.stdout[:200]!r}"
                continue
            break
        else:
            # Every attempt failed. Mark the WHOLE batch as errored; do NOT
            # leave it looking like a clean CCD miss.
            self.last_error = err
            for c in batch:
                self.fetch_errors[c] = err
            return

        for c in batch:
            self._cache.setdefault(c, None)
        for r in rows:
            cid = (r.get("comp_id") or "").strip()
            if not cid:
                continue
            smi = "".join(r.get(f"s{i}") or "" for i in range(5)).strip()
            self._cache[cid.upper()] = {
                "comp_id": cid,
                "type": _nn(r.get("type")),
                "formula": _nn(r.get("formula")),
                "formula_weight": _nf(r.get("formula_weight")),
                "drugbank_id": _nn(r.get("drugbank_id")),
                "inchikey": _nn(r.get("inchikey")),
                "smiles": _nn(smi),
                "name": _nn(r.get("nm")),
            }

    def save_cache(self) -> None:
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache, sort_keys=True))


def _looks_like_empty_result(out: str) -> bool:
    """A genuine zero-row answer, as opposed to an error or a hang."""
    return "(0 rows" in out


def _nn(v: Any) -> Any:
    return None if v in (None, "", "NULL") else v


def _nf(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_DEFAULT_SOURCE: ChemCompSource | None = None


def _default_source() -> ChemCompSource:
    global _DEFAULT_SOURCE
    if _DEFAULT_SOURCE is None:
        _DEFAULT_SOURCE = ChemCompSource()
    return _DEFAULT_SOURCE


def set_default_source(src: ChemCompSource) -> None:
    """Swap the module-level source. Tests and offline callers use this."""
    global _DEFAULT_SOURCE
    _DEFAULT_SOURCE = src


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LigandVerdict:
    comp_id: str
    name: str | None
    formula: str | None
    heavy_atoms: int | None
    mw: float | None
    verdict: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    comp_type: str | None = None
    smiles: str | None = None
    drugbank_id: str | None = None
    confidence: str = "high"
    source: str = "paperclip:pdb_v.chemcomps"

    @property
    def is_druglike(self) -> bool:
        return self.verdict == "druglike"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["flags"] = list(self.flags)
        d["is_druglike"] = self.is_druglike
        return d


def _v(comp_id, rec, verdict, reason, evidence, *, flags=(), confidence="high",
       source="paperclip:pdb_v.chemcomps") -> LigandVerdict:
    rec = rec or {}
    extra = list(flags)
    if comp_id.upper() in _FREQUENT_HITTERS:
        extra.append("promiscuity_advisory")
        evidence = dict(evidence)
        evidence["promiscuity_advisory"] = _FREQUENT_HITTERS[comp_id.upper()]
    return LigandVerdict(
        comp_id=comp_id.upper(),
        name=rec.get("name"),
        formula=rec.get("formula"),
        heavy_atoms=evidence.get("heavy_atoms"),
        mw=rec.get("formula_weight"),
        verdict=verdict,
        reason=reason,
        evidence=evidence,
        flags=tuple(extra),
        comp_type=rec.get("type"),
        smiles=rec.get("smiles"),
        drugbank_id=rec.get("drugbank_id"),
        confidence=confidence,
        source=source,
    )


# --------------------------------------------------------------------------
# The rules
# --------------------------------------------------------------------------


def classify_record(rec: Mapping[str, Any] | None, comp_id: str | None = None
                    ) -> LigandVerdict:
    """Classify from a CCD record already in hand. No I/O.

    `rec` needs `type`, `formula`, `formula_weight`, `smiles`, `name` — the
    exact column set of `pdb_v.chemcomps` and (bar `type` vs `comp_type`) of
    `pdb_v.entry_ligands`, so a call site that already selected either can
    classify without a second round trip.
    """
    cid = (comp_id or (rec or {}).get("comp_id") or "?").upper()
    if not rec:
        return _v(cid, None, "unknown",
                  "no record for this comp_id in pdb_v.chemcomps; refusing to "
                  "guess (an unclassified ligand is not evidence of a site)",
                  {"heavy_atoms": None, "ccd_hit": False},
                  confidence="low", source="paperclip:pdb_v.chemcomps (miss)")

    # Accept a `pdb_v.entry_ligands` row verbatim as well as a
    # `pdb_v.chemcomps` one: the two views spell the same two fields
    # differently, and a call site should not have to rename them.
    rec = dict(rec)
    if not rec.get("type") and rec.get("comp_type"):
        rec["type"] = rec["comp_type"]
    if not rec.get("name") and rec.get("ligand_name"):
        rec["name"] = rec["ligand_name"]

    ctype = (rec.get("type") or "").strip().lower()
    formula = rec.get("formula")
    mw = _nf(rec.get("formula_weight"))
    smiles = rec.get("smiles")
    els = parse_formula(formula)
    heavy = heavy_atom_count(formula)

    ev: dict[str, Any] = {
        "ccd_hit": True,
        "chem_comp_type": rec.get("type"),
        "formula": formula,
        "formula_weight": mw,
        "heavy_atoms": heavy,
        "elements": els or None,
        "has_nitrogen": bool(els.get("N")),
        "has_phosphorus": bool(els.get("P")),
        "metals": sorted(e for e in els if e in _METALS) or None,
        "smiles_present": bool(smiles),
    }

    # ---- R0. The CCD's own placeholder components. `UNK`, `UNL`, `UNX` and
    # friends are density that was never identified. Keyed on the CCD `name`
    # field, not on a hardcoded id list, so a new placeholder code is caught.
    name_l = (rec.get("name") or "").strip().lower()
    if name_l.startswith("unknown") or name_l.startswith("unidentified"):
        return _v(cid, rec, "unknown",
                  f"the CCD names this component {rec.get('name')!r}: "
                  "unidentified density, not a characterised ligand", ev,
                  confidence="high")

    # ---- R1. `_chem_comp.type`: polymer residues are never small-molecule
    # evidence. This is the field the old code ignored and it is decisive on
    # its own. 6OIM's GDP is typed `RNA linking`.
    if ctype:
        is_sacch = ("saccharide" in ctype)
        if is_sacch:
            # A saccharide carrying a phosphate is a sugar phosphate / metabolite;
            # a saccharide carrying an alkyl tail is an alkyl-glycoside detergent
            # (BOG, HTG, LMT). Neither is "a sugar" in the sense a call site
            # cares about, and both are still not drug-like.
            if parse_formula(formula).get("P"):
                return _v(cid, rec, "cofactor",
                          f"CCD type {rec['type']!r} plus phosphorus: a sugar "
                          "phosphate / nucleotide-sugar metabolite", ev)
            gg = SmilesGraph(smiles) if smiles else None
            if gg is not None and gg.ok:
                ch = gg.longest_aliphatic_chain()
                ev["longest_aliphatic_chain"] = ch
                if ch >= 6:
                    return _v(cid, rec, "lipid_or_detergent",
                              f"CCD type {rec['type']!r} with an unbranched alkyl "
                              f"chain of {ch} carbons: an alkyl-glycoside "
                              "detergent (octyl glucoside / dodecyl maltoside "
                              "class), not a glycan", ev)
            return _v(cid, rec, "sugar_or_glycan",
                      f"CCD _chem_comp.type is {rec['type']!r}", ev)
        if "linking" in ctype or "terminus" in ctype:
            if "peptide" in ctype:
                return _v(cid, rec, "peptide_or_polymer",
                          f"CCD _chem_comp.type is {rec['type']!r}: a peptide "
                          "polymer residue (modified/standard amino acid)", ev)
            if "dna" in ctype or "rna" in ctype:
                return _v(cid, rec, "cofactor",
                          f"CCD _chem_comp.type is {rec['type']!r}: a nucleotide "
                          "polymer residue — a nucleotide cofactor when it "
                          "appears free (this is how GDP in 6OIM is typed)", ev)
        if ctype == "peptide-like":
            return _v(cid, rec, "peptide_or_polymer",
                      f"CCD _chem_comp.type is {rec['type']!r}: a peptide-like "
                      "component. It may be a genuine binder, but it is not "
                      "small-molecule evidence", ev,
                      flags=("standalone_peptide_ligand",))

    # ---- R2. Elemental / size floor. No SMILES needed.
    n_c = els.get("C", 0)
    metals = [e for e in els if e in _METALS]
    n_metal_atoms = sum(els[e] for e in metals)

    if heavy is not None:
        # Metal clusters (Fe2S2, Fe4S4, Mo-pterin) are cofactors, not ions.
        if n_metal_atoms >= 2 and n_c == 0:
            return _v(cid, rec, "cofactor",
                      f"inorganic metal cluster ({''.join(sorted(metals))}, "
                      f"{n_metal_atoms} metal atoms, no carbon): an "
                      "iron-sulfur / metal-cluster cofactor", ev)
        if heavy <= 9 and n_c == 0:
            return _v(cid, rec, "ion_or_solvent",
                      f"no carbon and {heavy} heavy atoms: a bare ion or simple "
                      "inorganic species (sulfate, phosphate, pyrophosphate, "
                      "halide, metal)", ev)
        # One carbon and essentially no hydrogen is an inorganic oxyanion
        # (carbonate, bicarbonate, thiocyanate). The hydrogen bound keeps
        # formic acid and urea out — they are bench additives, not ions.
        if heavy <= 5 and n_c <= 1 and els.get("H", 0) <= 1:
            return _v(cid, rec, "ion_or_solvent",
                      f"{heavy} heavy atoms, {n_c} carbon and "
                      f"{els.get('H', 0)} hydrogen: a simple inorganic "
                      "oxyanion (carbonate / thiocyanate class)", ev)
        if heavy <= 2:
            return _v(cid, rec, "ion_or_solvent",
                      f"{heavy} heavy atom(s)", ev)

    # ---- R3. Metal-containing organic cofactors: heme, chlorophyll, B12.
    if metals and heavy and heavy >= 10:
        return _v(cid, rec, "cofactor",
                  f"organometallic component carrying {'/'.join(sorted(metals))} "
                  f"over {heavy} heavy atoms: a metalloporphyrin/corrin-class "
                  "cofactor, not a synthetic ligand", ev)

    # ---- Beyond here the topology matters.
    g = SmilesGraph(smiles) if smiles else None
    if g is not None and not g.ok:
        ev["smiles_parse_error"] = getattr(g, "parse_error", "unknown")
        g = None

    if g is None:
        return _classify_without_smiles(cid, rec, ev, heavy, els, ctype)

    ev.update({
        "n_rings": len(g.rings),
        "n_aromatic_rings": g.n_aromatic_rings(),
        "longest_aliphatic_chain": g.longest_aliphatic_chain(),
        "phosphorus_groups": g.phosphorus_groups(),
        "n_ester_carbonyls": g.n_ester_carbonyls(),
        "n_amide_bonds": g.n_amide_bonds(),
        "hydroxyls": g.hydroxyl_count(),
        "ether_oxygens": g.ether_oxygens(),
        "purine_like": g.purine_like_rings(),
        "furanose_like": g.furanose_like(),
        "sugar_rings": g.pyranose_like_rings(),
        "steroid_nucleus": g.steroid_nucleus(),
        "sterol_side_chain": g.sterol_side_chain(),
        "peptide_residues": g.peptide_backbone_residues(),
        "alkyl_sulfonates": g.alkyl_sulfonate_groups(),
        "pyrimidine_base": g.pyrimidine_base(),
    })

    chain = ev["longest_aliphatic_chain"]
    pgroups = ev["phosphorus_groups"]
    phospho_ester = any(p["ester_to_c"] and p["o_or_n"] >= 2 for p in pgroups)
    aromatic = ev["n_aromatic_rings"]

    # ---- R4. Free nucleobases. Endogenous, and checked BEFORE the size floor
    # because uracil is 8 heavy atoms and would otherwise be swallowed by it.
    # Note the purine test does not require aromatic flags — the CCD kekulises
    # several of these, uracil among them.
    if ev["purine_like"] and heavy is not None and heavy <= 12:
        return _v(cid, rec, "cofactor",
                  f"bare purine base ({heavy} heavy atoms, no ribose or "
                  "phosphate): adenine/guanine-class nucleobase", ev)
    if ev["pyrimidine_base"] and heavy is not None and heavy <= 10:
        return _v(cid, rec, "cofactor",
                  f"bare pyrimidine base ({heavy} heavy atoms): "
                  "uracil/thymine/cytosine-class nucleobase", ev)

    # ---- R5. Below the reporting floor. Two exemptions, both measured:
    #   * an aromatic ring — `LZ1` (1H-indazole) is 9 heavy atoms and IS a real
    #     fragment hit, whereas `DEP` (diethyl phosphonate, 8, no ring) is bench
    #     chemistry. Without it the floor eats fragment-screen precedent, which
    #     is the same class of error the old 18-heavy-atom floor made.
    #   * a long alkyl chain — `OCT` is n-octane, 8 heavy atoms and unambiguously
    #     greasy; it belongs with the lipids, not the buffers.
    if heavy is not None and heavy <= TRIVIAL_MAX_HEAVY_ATOMS \
            and not (aromatic >= 1 and heavy >= 8) \
            and chain < LIPID_MIN_CHAIN:
        return _v(cid, rec, "crystallisation_additive",
                  f"only {heavy} heavy atoms, no aromatic ring and no alkyl "
                  "chain: below anything a fragment screen reports; a buffer "
                  "component, cryoprotectant or solvent", ev)

    # ---- R6. Sterol. Cholesterol and its hemisuccinate — the CD20 bug.
    # The side chain is what separates a membrane sterol from a steroid DRUG.
    if ev["steroid_nucleus"]:
        if ev["sterol_side_chain"] >= 4:
            return _v(cid, rec, "lipid_or_detergent",
                      "cyclopenta[a]phenanthrene (steroid) nucleus carrying an "
                      f"aliphatic side chain of {ev['sterol_side_chain']} carbons: "
                      "a membrane sterol or bile salt, not a drug. This is the "
                      "cholesterol / cholesteryl-hemisuccinate class that "
                      "produced the CD20 wrong answer", ev)
        return _v(cid, rec, "druglike",
                  "steroid nucleus with no aliphatic side chain "
                  f"({ev['sterol_side_chain']} carbons): a steroid hormone or "
                  "steroid drug, which IS evidence of a bindable site. Reported "
                  "separately from sterols on purpose — filing every steroid as "
                  "a lipid is the same failure in the other direction", ev,
                  flags=("steroid_nucleus",))

    # ---- R7. Nucleotide / nucleoside. The 2UK bug, and ADP/ATP on NLRP3.
    if ev["purine_like"] and (ev["furanose_like"] or phospho_ester):
        return _v(cid, rec, "cofactor",
                  "purine (adenine/guanine-class) base fused bicycle plus "
                  + ("a ribose/deoxyribose furanose" if ev["furanose_like"]
                     else "a phosphate ester")
                  + ": a nucleotide/nucleoside cofactor. Catches ADP, ATP, GDP, "
                    "GTP, GNP and non-hydrolysable analogs such as 2UK "
                    "(GppNHp) without naming any of them", ev)
    if ev["furanose_like"] and phospho_ester:
        return _v(cid, rec, "cofactor",
                  "ribofuranose bearing a phosphate ester: a nucleotide-class "
                  "cofactor or sugar phosphate", ev)

    # ---- R6. Phospholipid: phospho head group + acyl chains. CD20's PC.
    if phospho_ester and (chain >= LIPID_MIN_CHAIN or ev["n_ester_carbonyls"] >= 2):
        return _v(cid, rec, "lipid_or_detergent",
                  f"phosphate ester head group with an aliphatic chain of "
                  f"{chain} carbons and {ev['n_ester_carbonyls']} acyl esters: a "
                  "phospholipid/detergent (phosphatidylcholine class)", ev)

    # ---- R7. Any other phosphate ester on a small molecule. Free phosphates
    # are the signature of endogenous metabolites and cofactors (FMN, FAD, PLP,
    # TPP, CoA, sugar phosphates), not of drugs.
    if phospho_ester:
        return _v(cid, rec, "cofactor",
                  "carries a phosphate/phosphonate ester. Free phosphates are "
                  "the signature of endogenous cofactors and metabolites; drugs "
                  "essentially never carry one (bisphosphonate drugs and "
                  "phosphate prodrugs are the known exception — see flags)", ev,
                  flags=("phosphate_rule_may_misfile_a_phosphate_drug",))

    # ---- R8. Lipid / detergent by acyl or alkyl chain. The L44 bug.
    #
    # The chain must DOMINATE the molecule (>= 30% of its heavy atoms) or the
    # molecule must be essentially ring-free. A bare `chain >= 8` test filed
    # abamectin, myxopyronin B and other long-tailed natural-product ANTIBIOTICS
    # as lipids — found on a held-out sample. A fatty acid, an acylglycerol and
    # a detergent are mostly chain; a macrolide is mostly ring.
    chain_frac = (chain / heavy) if (heavy and chain) else 0.0
    ev["chain_fraction_of_heavy_atoms"] = round(chain_frac, 3)
    if chain >= LIPID_MIN_CHAIN and (len(g.rings) <= 1 or chain_frac >= 0.30):
        return _v(cid, rec, "lipid_or_detergent",
                  f"longest unbranched aliphatic carbon chain is {chain} "
                  f"(>= {LIPID_MIN_CHAIN}) and accounts for {chain_frac:.0%} of "
                  f"{heavy} heavy atoms across {len(g.rings)} ring(s): a fatty "
                  "acid, acylglycerol or alkyl detergent. This is the 625 Da "
                  "diacylglycerol class (L44) that cleared the old "
                  "18-heavy-atom floor", ev)

    # ---- R9. Sugars not caught by `type`.
    if ev["sugar_rings"] >= 1 and not ev["has_nitrogen"] and not ev["n_aromatic_rings"]:
        return _v(cid, rec, "sugar_or_glycan",
                  f"{ev['sugar_rings']} pyranose/furanose ring(s) with a "
                  "hydroxyl belt and no aromatic ring or nitrogen: a sugar or "
                  "glycan", ev)
    if ev["sugar_rings"] >= 2:
        return _v(cid, rec, "sugar_or_glycan",
                  f"{ev['sugar_rings']} linked pyranose/furanose rings: an "
                  "oligosaccharide/glycan", ev)

    # ---- R10. Peptides written as one component.
    if ev["peptide_residues"] >= 3:
        return _v(cid, rec, "peptide_or_polymer",
                  f"{ev['peptide_residues']} alpha-amino-acid backbone units: a "
                  "peptide. May be a real binder but it is not small-molecule "
                  "evidence", ev, flags=("standalone_peptide_ligand",))

    # ---- R11. Bench chemistry: PEGs, polyols, buffers, cryoprotectants.
    if ev["ether_oxygens"] >= 3 and not ev["has_nitrogen"] and not g.rings \
            and set(els) <= {"C", "H", "O"}:
        return _v(cid, rec, "crystallisation_additive",
                  f"acyclic C/H/O chain with {ev['ether_oxygens']} ether "
                  "oxygens: a polyethylene glycol", ev)
    # Good's buffers. An ALKYL sulfonate (S with >=3 O, on an sp3 carbon) with
    # no aromatic ring is MES/HEPES/MOPS/PIPES/CHES chemistry. Aryl sulfonamide
    # drugs are not touched: their sulfur carries two oxygens and a nitrogen.
    if ev["alkyl_sulfonates"] >= 1 and aromatic == 0 and heavy is not None \
            and heavy <= 20:
        return _v(cid, rec, "crystallisation_additive",
                  f"{ev['alkyl_sulfonates']} alkyl sulfonate group(s) (direct "
                  f"C-S bond), no aromatic ring, {heavy} heavy atoms: a Good's "
                  "buffer (MES/HEPES/MOPS/PIPES/CHES class)", ev)
    # Nothing a screen reports as a hit is both ring-free and this small. Catches
    # polyamines (spermidine, spermine), N-oxalylglycine, small polyacids.
    if heavy is not None and heavy <= 14 and not g.rings:
        return _v(cid, rec, "crystallisation_additive",
                  f"{heavy} heavy atoms and no ring system at all: an additive, "
                  "polyamine or small metabolite, not a reported screening hit", ev)
    if heavy is not None and heavy <= 18 and ev["n_aromatic_rings"] == 0 \
            and (ev["hydroxyls"] + ev["ether_oxygens"] + ev["alkyl_sulfonates"]) >= 3 \
            and ev["n_amide_bonds"] == 0:
        return _v(cid, rec, "crystallisation_additive",
                  f"{heavy} heavy atoms, no aromatic ring, "
                  f"{ev['hydroxyls']} hydroxyls / {ev['ether_oxygens']} ethers / "
                  f"{ev['alkyl_sulfonates']} sulfonates and no amide: a polyol, "
                  "sulfonate buffer (MES/HEPES class) or cryoprotectant", ev)

    # ---- R12. Size ceiling.
    if mw is not None and mw > DRUGLIKE_MAX_MW:
        return _v(cid, rec, "unknown",
                  f"{mw:.0f} Da exceeds the {DRUGLIKE_MAX_MW:.0f} Da "
                  "small-molecule ceiling and no cofactor/lipid/peptide "
                  "signature fired; not classified rather than assumed", ev,
                  confidence="low")

    # ---- R13. Drug-like by exclusion of every endogenous signature, with a
    # positive check: drug-like ligands are overwhelmingly N-containing or at
    # least aromatic. A pure C/H/O acyclic molecule that got this far is greasy
    # bench chemistry, not a drug.
    if not ev["has_nitrogen"] and ev["n_aromatic_rings"] == 0 and set(els) <= {"C", "H", "O"}:
        return _v(cid, rec, "crystallisation_additive",
                  "pure C/H/O, no nitrogen and no aromatic ring: not drug-like "
                  "chemistry", ev, confidence="medium")

    bits = []
    if els.get("N"):
        bits.append(f"{els['N']} nitrogen(s)")
    bits.append(f"{ev['n_aromatic_rings']} aromatic ring(s)")
    bits.append(f"{heavy} heavy atoms")
    if mw is not None:
        bits.append(f"{mw:.0f} Da")
    return _v(cid, rec, "druglike",
              "no cofactor, lipid, sugar, peptide, polymer or additive "
              "signature fired; " + ", ".join(bits), ev)


def _classify_without_smiles(cid, rec, ev, heavy, els, ctype) -> LigandVerdict:
    """Degraded path: the CCD row exists but carries no usable SMILES.

    Only the checks that need nothing but the formula and `type` are allowed to
    fire. Everything else returns `unknown` — deliberately, because this is the
    exact code path where a guess becomes a fabricated holo structure.
    """
    ev = dict(ev)
    ev["degraded_no_smiles"] = True
    if heavy is not None and heavy <= TRIVIAL_MAX_HEAVY_ATOMS and not els.get("N"):
        return _v(cid, rec, "crystallisation_additive",
                  f"no SMILES in the CCD row; {heavy} heavy atoms and no "
                  "nitrogen is bench chemistry on formula alone", ev,
                  confidence="medium")
    return _v(cid, rec, "unknown",
              "the CCD row has no SMILES, so no chemistry test can run. "
              "Reported as unknown rather than assumed drug-like — an "
              "unclassified ligand must not become a holo structure", ev,
              confidence="low")


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def classify_ligand(comp_id: str, *, source: str = "pdb",
                    chemcomps: ChemCompSource | None = None) -> LigandVerdict:
    """Classify one chemical component.

    `comp_id` is the FULL component ID from the mmCIF — `A1JPS`, not the first
    three characters of it. Five-character codes have been issued since 2023 and
    the legacy PDB format cannot hold them; that truncation is a separate,
    already-documented wrong answer on IL-17A.

    `source` currently accepts only `'pdb'` (the PDB Chemical Component
    Dictionary via Paperclip). It exists so a future CCD mirror can be selected
    without changing call sites.
    """
    if source != "pdb":
        raise ValueError(f"unsupported source {source!r}; only 'pdb' is implemented")
    return classify_ligands([comp_id], source=source, chemcomps=chemcomps)[comp_id.upper()]


def classify_ligands(comp_ids: Iterable[str], *, source: str = "pdb",
                     chemcomps: ChemCompSource | None = None
                     ) -> dict[str, LigandVerdict]:
    """Batch form — ONE Paperclip round trip per 40 comp_ids.

    Call sites process whole entries, and an entry has 1-15 components. Looping
    `classify_ligand` would be one subprocess each.
    """
    if source != "pdb":
        raise ValueError(f"unsupported source {source!r}; only 'pdb' is implemented")
    ids = [c.upper() for c in comp_ids if c]
    src = chemcomps or _default_source()
    recs = src.get_many(ids)
    out: dict[str, LigandVerdict] = {}
    for c in ids:
        rec = recs.get(c)
        if rec is None and c in src.fetch_errors:
            # A LOOKUP FAILURE, NOT A CCD MISS. Distinct verdict text and a
            # distinct flag, so a call site can retry or refuse to report
            # rather than quietly counting the entry as apo.
            out[c] = _v(c, None, "unknown",
                        "the chemical-component lookup FAILED (not: the "
                        f"component is absent). {src.fetch_errors[c]}. This "
                        "entry's holo/apo state is undetermined and must not "
                        "be reported as apo",
                        {"heavy_atoms": None, "ccd_hit": None,
                         "lookup_error": src.fetch_errors[c]},
                        flags=("lookup_failed",), confidence="none",
                        source="paperclip:pdb_v.chemcomps (lookup failed)")
        else:
            out[c] = classify_record(rec, c)
    return out


def is_druglike_ligand(comp_id: str, *, chemcomps: ChemCompSource | None = None) -> bool:
    """True only for `druglike`. `unknown` is False — an unclassified ligand is
    not evidence of a bindable site."""
    return classify_ligand(comp_id, chemcomps=chemcomps).verdict == "druglike"


def filter_druglike(comp_ids: Iterable[str], *,
                    chemcomps: ChemCompSource | None = None) -> list[str]:
    verdicts = classify_ligands(comp_ids, chemcomps=chemcomps)
    return [c for c, v in verdicts.items() if v.verdict == "druglike"]


def holo_call(comp_ids: Iterable[str], *,
              chemcomps: ChemCompSource | None = None) -> dict[str, Any]:
    """Entry-level holo/apo call with the full reasoning attached.

    Returns `is_holo`, the drug-like ligands that justify it, and every other
    ligand bucketed by verdict — so a dossier can say "apo, but carrying GDP"
    rather than "apo" full stop, and can show WHY a rejected ligand was
    rejected.
    """
    verdicts = classify_ligands(comp_ids, chemcomps=chemcomps)
    buckets: dict[str, list[str]] = {}
    for c, v in verdicts.items():
        buckets.setdefault(v.verdict, []).append(c)
    dl = sorted(buckets.get("druglike", []))
    failed = sorted(c for c, v in verdicts.items() if "lookup_failed" in v.flags)
    return {
        "is_holo": bool(dl),
        "druglike_ligands": dl,
        "by_verdict": {k: sorted(v) for k, v in sorted(buckets.items())},
        "unknown_ligands": sorted(buckets.get("unknown", [])),
        # `is_holo=False` with a non-empty `undetermined` is NOT an apo call.
        # A caller that reports it as apo has reintroduced the original bug in
        # a new place.
        "undetermined": failed,
        "determined": not failed,
        "verdicts": {c: v.to_dict() for c, v in verdicts.items()},
        "flags": sorted({f for v in verdicts.values() for f in v.flags}),
    }
