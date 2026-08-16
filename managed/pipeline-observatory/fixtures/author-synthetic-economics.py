"""Author the SYNTHETIC IRAK4/RA economics inputs for the pipeline demo.

Run once (`uv run --no-project python .../author-synthetic-economics.py`, or any
python3) to regenerate the two fixtures next to this file:

  irak4-ra.SYNTHETIC.program.json
  irak4-ra.SYNTHETIC.comparables.json

WHAT THIS DOES, AND WHAT IT REFUSES TO DO. It reads the economics node's own
fictitious demo fixtures read-only, relabels the IDENTITY fields (programme
name, target, modality, route, indication, comparable names) to the IRAK4 /
rheumatoid-arthritis programme the rest of the pipeline demo is about, and
copies every NUMBER through untouched. It invents no price, no patient count
and no probability. The result is a subject-coherent demo input in which every
figure is still Vince's synthetic demo figure — which is exactly what the
committed files say about themselves, in `notes` fields the economics engine
carries into its own output as SYNTHETIC evidence.

Why relabel at all: with the economics node's own demo programme the last
station of the pipeline would be valuing a fictitious PEPTIDE against a
fictitious syndrome while every station before it was about an IRAK4 inhibitor
in RA. That mismatch reads as a broken chain. Relabelling makes the chain
coherent WITHOUT upgrading a single number's status.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SRC = REPO_ROOT / "managed" / "therapeutic-program-economics" / "fixtures"

PROGRAM_NOTE = (
    "SYNTHETIC. Derived from managed/therapeutic-program-economics/fixtures/"
    "demo_program.json by relabelling identity fields to the IRAK4 / rheumatoid-"
    "arthritis programme so the pipeline demo is subject-coherent. EVERY NUMBER IS "
    "INHERITED VERBATIM FROM THAT FICTITIOUS DEMO FIXTURE - not one of them is an RA "
    "estimate, an IRAK4 estimate, or an observed value."
)
COMPARABLE_NOTE = (
    "SYNTHETIC. Comparable identities relabelled to RA treatment CLASSES; every price "
    "amount is inherited verbatim from the fictitious demo catalogue. These are NOT the "
    "prices of any real RA product and must never be read as one."
)

ID_MAP = {
    "syn-comp-primary": "syn-ra-class-jaki-primary",
    "syn-comp-net-anchor": "syn-ra-class-jaki-net-anchor",
    "syn-comp-expansion-net": "syn-ra-class-il6-net",
    "syn-comp-secondary": "syn-ra-class-antitnf",
    "syn-comp-context": "syn-ra-class-context",
    "syn-comp-excluded": "syn-ra-class-excluded",
}
NAME_MAP = {
    "syn-ra-class-jaki-primary": "SYNTHETIC oral JAK-inhibitor class comparator (primary match)",
    "syn-ra-class-jaki-net-anchor": "SYNTHETIC oral JAK-inhibitor class, modelled-net scenario",
    "syn-ra-class-il6-net": "SYNTHETIC IL-6 pathway biologic class, modelled-net scenario",
    "syn-ra-class-antitnf": "SYNTHETIC anti-TNF biologic class comparator",
    "syn-ra-class-context": "SYNTHETIC RA context comparator (non-matching line of therapy)",
    "syn-ra-class-excluded": "SYNTHETIC excluded comparator (kept so the exclusion stays visible)",
}
RA_AREA = "Immunology / rheumatology (SYNTHETIC)"
RA_INDICATION = "Moderate-to-severe rheumatoid arthritis, MTX-inadequate response (SYNTHETIC)"
RA_POPULATION = (
    "Adults with seropositive moderate-to-severe RA, inadequate response to "
    "methotrexate (SYNTHETIC)"
)
PRIMARY_MATCH_IDS = {
    "syn-ra-class-jaki-primary",
    "syn-ra-class-jaki-net-anchor",
    "syn-ra-class-antitnf",
}


def relabel_comparables() -> dict:
    comparables = json.loads((SRC / "demo_comparables.json").read_text())
    for row in comparables["comparables"]:
        new_id = ID_MAP[row["comparable_id"]]
        row["comparable_id"] = new_id
        row["name"] = NAME_MAP[new_id]
        row["therapeutic_area"] = RA_AREA
        row["target_or_mechanism"] = "SYNTHETIC_RA_CLASS"
        if new_id in PRIMARY_MATCH_IDS:
            row["indication"] = RA_INDICATION
            row["target_population"] = RA_POPULATION
            row["route"] = "ORAL"
        else:
            row["indication"] = f"{RA_INDICATION} - adjacent context"
        row["notes"] = COMPARABLE_NOTE
        row["price"]["evidence"]["notes"] = COMPARABLE_NOTE
    comparables["synthetic"] = True
    comparables["warning"] = COMPARABLE_NOTE
    return comparables


def relabel_program() -> dict:
    program = json.loads((SRC / "demo_program.json").read_text())
    program["program_id"] = "SYNTHETIC-IRAK4-RA-001"
    program["program_name"] = (
        "SYNTHETIC IRAK4-inhibitor programme in rheumatoid arthritis "
        "(all numbers inherited from the economics demo fixture)"
    )
    program["target"] = "IRAK4"
    program["modality"] = "SMALL_MOLECULE"
    program["molecule_identifier"] = "SYNTHETIC_IRAK4_INHIBITOR_NOT_FOR_USE"
    program["route"] = "ORAL"

    indication = program["initial_indication"]
    indication["indication_id"] = "syn-ra-mtx-ir"
    indication["name"] = RA_INDICATION
    indication["therapeutic_area"] = RA_AREA
    indication["target_population"] = RA_POPULATION
    indication["line_of_therapy"] = "Second line"
    indication["biomarker"] = "Seropositive (anti-CCP and/or RF positive) - SYNTHETIC"
    indication["route"] = "ORAL"
    indication["comparator_ids"] = [
        "syn-ra-class-jaki-primary",
        "syn-ra-class-jaki-net-anchor",
        "syn-ra-class-antitnf",
        "syn-ra-class-context",
    ]
    indication.setdefault("assumptions", {})["note"] = PROGRAM_NOTE

    for expansion in program.get("expansion_indications", []):
        expansion["name"] = f"{RA_INDICATION} - adjacent expansion"
        expansion["therapeutic_area"] = RA_AREA
        expansion["route"] = "ORAL"
        expansion["comparator_ids"] = [
            ID_MAP.get(cid, cid) for cid in expansion.get("comparator_ids", [])
        ]
        expansion.setdefault("assumptions", {})["note"] = PROGRAM_NOTE

    program.setdefault("assumptions", {})["note"] = PROGRAM_NOTE
    return program


def main() -> None:
    (HERE / "irak4-ra.SYNTHETIC.comparables.json").write_text(
        json.dumps(relabel_comparables(), indent=2) + "\n"
    )
    (HERE / "irak4-ra.SYNTHETIC.program.json").write_text(
        json.dumps(relabel_program(), indent=2) + "\n"
    )
    print("wrote irak4-ra.SYNTHETIC.{program,comparables}.json")


if __name__ == "__main__":
    main()
