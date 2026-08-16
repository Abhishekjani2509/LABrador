"""The command line: parameter patching, the keyless path, and failure modes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hyp_gen.cli import _overrides, main

GRAPH = Path(__file__).resolve().parents[1] / "data" / "example_graph.json"


def test_overrides_parse_json_values() -> None:
    parsed = _overrides(
        ["traversal.max_hops=4", "framing.mode=closed", "loop.enabled=true",
         'framing.anchors=["metformin"]']
    )
    assert parsed["traversal"]["max_hops"] == 4
    assert parsed["framing"]["mode"] == "closed"      # bare strings stay strings
    assert parsed["loop"]["enabled"] is True
    assert parsed["framing"]["anchors"] == ["metformin"]


def test_overrides_reject_malformed_pairs() -> None:
    with pytest.raises(SystemExit):
        _overrides(["max_hops=4"])  # no group


def test_dry_run_needs_no_credentials(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["--graph", str(GRAPH), "--dry-run", "--out", str(tmp_path)])
    assert code == 0

    out = capsys.readouterr().out
    assert "No model calls made." in out

    slate = json.loads((tmp_path / "slate.json").read_text())
    assert slate["graph_id"] == "g_demo1"
    assert slate["counts"]["model_calls"] == 0
    assert (tmp_path / "report.md").read_text().startswith("# Hypotheses")


def test_the_full_report_is_recoverable_from_a_saved_slate(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """The short report.md is only safe as a default if the long one can be got
    back without paying for the model stages again."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--graph", str(GRAPH), "--dry-run", "--out", str(tmp_path)]) == 0
    capsys.readouterr()

    slate = tmp_path / "slate.json"
    later = tmp_path / "later"
    assert main(["--report-from", str(slate), "--full-report", "--out", str(later)]) == 0

    full = (later / "report-full.md").read_text()
    assert full.startswith("# Hypotheses")
    # The audit trail is what distinguishes it, and it is back.
    assert "**Scores**" in full
    assert len(full) > len((tmp_path / "report.md").read_text())


def test_missing_credentials_fail_clearly(tmp_path: Path, capsys, monkeypatch) -> None:
    """A stack trace forty frames deep is not an error message."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    code = main(["--graph", str(GRAPH), "--out", str(tmp_path)])
    assert code == 2

    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "--dry-run" in err
    assert not (tmp_path / "report.md").exists()


def test_profile_and_set_compose(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(
        [
            "--graph", str(GRAPH),
            "--profile", "repurposing",
            "--set", "selection.top_k=2",
            "--dry-run",
            "--out", str(tmp_path),
        ]
    )
    assert code == 0
    slate = json.loads((tmp_path / "slate.json").read_text())
    # The patch applied on top of the profile, and the profile survived it.
    assert slate["params"]["selection"]["top_k"] == 2
    assert slate["params"]["traversal"]["seed_kinds"] == ["small_molecule"]
    assert len(slate["hypotheses"]) == 2


def test_params_travel_with_the_slate(tmp_path: Path, monkeypatch) -> None:
    """A slate whose parameters are not attached cannot be reproduced."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["--graph", str(GRAPH), "--dry-run", "--out", str(tmp_path)])
    slate = json.loads((tmp_path / "slate.json").read_text())
    for group in ("framing", "traversal", "motifs", "evidence", "novelty",
                  "selection", "ranking", "loop", "budget"):
        assert group in slate["params"]


FRAME = Path(__file__).resolve().parents[1] / "data" / "example_frame.json"


def test_emit_programs_refuses_without_a_frame(tmp_path: Path, capsys) -> None:
    """The refusal is the feature. A default filing year would look sourced."""
    code = main(
        ["--graph", str(GRAPH), "--dry-run", "--emit-programs", str(tmp_path / "p")]
    )
    assert code == 2
    assert "will not guess" in capsys.readouterr().err


def test_frame_template_is_written_and_is_not_yet_usable(tmp_path: Path) -> None:
    target = tmp_path / "frame.json"
    assert main(["--emit-frame-template", str(target)]) == 0

    template = json.loads(target.read_text())
    assert template["filing_year"] is None

    target.write_text(json.dumps(template))
    assert main(
        ["--graph", str(GRAPH), "--dry-run", "--emit-programs",
         str(tmp_path / "p"), "--frame", str(target)]
    ) == 2


def test_emit_programs_writes_briefs_and_an_empty_catalogue(tmp_path: Path) -> None:
    out = tmp_path / "p"
    code = main(
        ["--graph", str(GRAPH), "--profile", "valuation", "--dry-run",
         "--emit-programs", str(out), "--frame", str(FRAME)]
    )
    assert code == 0

    briefs = sorted(out.glob("*.program.json"))
    assert briefs
    # An empty catalogue rather than none: it makes LABrador's missing-anchor
    # warning fire instead of hiding that no price was ever supplied.
    assert json.loads((out / "comparables.json").read_text()) == []
    assert json.loads((out / "emission.json").read_text())["graph_id"] == "g_demo1"


def test_emit_from_an_existing_slate_matches_the_report_the_caller_read(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    assert main(["--graph", str(GRAPH), "--profile", "valuation", "--dry-run",
                 "--out", str(run)]) == 0

    out = tmp_path / "p"
    assert main(["--emit-programs-from", str(run / "slate.json"),
                 "--frame", str(FRAME), "--emit-programs", str(out)]) == 0
    assert sorted(p.name for p in out.glob("*.program.json"))


def test_emit_from_slate_needs_a_destination(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--emit-programs-from", str(tmp_path / "slate.json")])
