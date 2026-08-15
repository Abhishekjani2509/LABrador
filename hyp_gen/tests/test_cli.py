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
