"""Command-line interface and file adapters for LABrador.

The CLI is deliberately thin: validation belongs to the Pydantic domain models and
economic calculations belong to :mod:`labrador_roi.engine`.  Keeping file parsing
here gives humans and agents one stable JSON-oriented interface without duplicating
model logic.
"""

from __future__ import annotations

import csv
import importlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Annotated, Any, Literal

import typer

from labrador_roi.provenance import redact

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Interpretable, screening-grade therapeutic program strategy analysis.",
)

PACKAGE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
REPOSITORY_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE_DIR = PACKAGE_FIXTURE_DIR if PACKAGE_FIXTURE_DIR.is_dir() else REPOSITORY_FIXTURE_DIR
DEMO_PROGRAM = FIXTURE_DIR / "demo_program.json"
DEMO_PROGRAM_B = FIXTURE_DIR / "demo_program_b.json"
DEMO_COMPARABLES_JSON = FIXTURE_DIR / "demo_comparables.json"
DEMO_COMPARABLES_CSV = FIXTURE_DIR / "demo_comparables.csv"


@dataclass(frozen=True)
class DomainAPI:
    """Resolved engine symbols, loaded lazily to keep CLI errors actionable."""

    ProgramInput: type[Any]
    ComparableTherapy: type[Any]
    ComparableSet: type[Any]


def _domain_api() -> DomainAPI:
    """Resolve the intentionally small public engine contract.

    During development the comparable models may live alongside the program model
    or in a dedicated module.  Supporting both layouts is harmless and lets the CLI
    remain stable while the public package exports settle.
    """

    models = importlib.import_module("labrador_roi.models")
    comparable_module = importlib.import_module("labrador_roi.comparables")
    return DomainAPI(
        ProgramInput=models.ProgramInput,
        ComparableTherapy=models.ComparableTherapy,
        ComparableSet=comparable_module.ComparableSet,
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return redact(str(value))


def _as_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _as_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_data(item) for item in value]
    return value


def _emit(payload: Any, *, pretty: bool, output: Path | None = None) -> None:
    safe_payload = redact(_as_data(payload))
    rendered = json.dumps(
        safe_payload,
        default=_json_default,
        indent=2 if pretty else None,
        sort_keys=pretty,
    )
    if output is None:
        typer.echo(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{rendered}\n", encoding="utf-8")
    typer.echo(
        json.dumps(
            {"status": "ok", "output": str(output.resolve())},
            indent=2 if pretty else None,
        )
    )


def _error_payload(exc: Exception, *, operation: str) -> dict[str, Any]:
    errors: Any
    if hasattr(exc, "errors"):
        try:
            errors = exc.errors(include_url=False)  # type: ignore[call-arg]
        except TypeError:
            errors = exc.errors()  # type: ignore[operator]
    else:
        errors = [{"message": str(exc), "type": type(exc).__name__}]
    return {
        "status": "error",
        "operation": operation,
        "error_type": type(exc).__name__,
        "errors": errors,
    }


def _fail(exc: Exception, *, operation: str, pretty: bool = True) -> None:
    _emit(_error_payload(exc, operation=operation), pretty=pretty)
    raise typer.Exit(code=2)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _csv_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _csv_number(value: Any, *, integer: bool = False) -> int | float | None:
    if value in (None, ""):
        return None
    return int(value) if integer else float(value)


def _csv_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    return [item.strip() for item in str(value).split("|") if item.strip()]


def normalize_csv_comparable(row: dict[str, Any]) -> dict[str, Any]:
    """Expand the documented flat CSV transport into the nested price contract."""

    row = dict(row)
    if "price" in row:
        return row
    price_evidence = {
        "source_id": row.pop("price_source_id", None) or None,
        "source_url": row.pop("price_source_url", None) or None,
        "citation": row.pop("price_citation", None) or None,
        "evidence_type": row.pop("price_evidence_type", "UNSUPPORTED"),
        "grade": row.pop("price_evidence_grade", "UNSUPPORTED"),
        "synthetic": _csv_bool(row.pop("price_synthetic", False)),
        "notes": row.pop("price_evidence_notes", None) or None,
    }
    price = {
        "amount": _csv_number(row.pop("price_amount", None)),
        "currency": row.pop("price_currency", None),
        "basis": row.pop("price_basis", None),
        "period": row.pop("price_period", "ANNUAL"),
        "price_year": _csv_number(row.pop("price_year", None), integer=True),
        "units_per_year": _csv_number(row.pop("price_units_per_year", None)),
        "evidence": price_evidence,
    }
    normalized = {key: value for key, value in row.items() if value not in (None, "")}
    normalized["price"] = price
    if "access_restrictions" in normalized:
        normalized["access_restrictions"] = _csv_list(normalized["access_restrictions"])
    normalized.setdefault("evidence", {})
    return normalized


def _read_comparable_payload(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _read_json(path)
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [normalize_csv_comparable(dict(row)) for row in csv.DictReader(handle)]
    raise ValueError("Comparables must be a .csv or .json file")


def _validate_comparable_catalog(item_model: type[Any], set_model: type[Any], payload: Any) -> Any:
    """Validate a raw catalogue; indication-specific selection remains engine work."""

    if isinstance(payload, dict):
        for key in ("comparables", "drugs", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise TypeError("Comparable input must be a list or an object containing 'comparables'")
    items = [item_model.model_validate(item) for item in payload]
    return set_model.model_validate({"comparables": items})


def load_program(path: Path) -> Any:
    """Load and validate a program JSON file."""

    return validate_program_payload(_read_json(path))


def validate_program_payload(payload: Any) -> Any:
    """Validate an already-decoded program payload."""

    return _domain_api().ProgramInput.model_validate(payload)


def load_comparables(path: Path) -> Any:
    """Load and validate a comparable set from JSON or CSV."""

    return validate_comparables_payload(_read_comparable_payload(path))


def validate_comparables_payload(payload: Any) -> Any:
    """Validate already-decoded raw comparable records."""

    if isinstance(payload, dict):
        for key in ("comparables", "drugs", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, list):
        payload = [
            normalize_csv_comparable(item) if isinstance(item, dict) else item for item in payload
        ]
    api = _domain_api()
    return _validate_comparable_catalog(api.ComparableTherapy, api.ComparableSet, payload)


def run_analysis(
    program: Any,
    comparables: Any,
    *,
    simulations: int,
    seed: int,
) -> Any:
    """Run the public engine entry point with deterministic simulation controls."""

    engine = importlib.import_module("labrador_roi.engine")
    return engine.analyze_program(
        program,
        comparables,
        simulations=simulations,
        seed=seed,
    )


def _records(value: Any) -> list[dict[str, Any]]:
    data = _as_data(value)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("comparables", "drugs", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def comparable_summary(comparables: Any) -> dict[str, Any]:
    """Return a provenance-forward summary without inferring confidential net prices."""

    rows = _records(comparables)
    grouped_prices: dict[tuple[str, str], list[float]] = {}
    price_types: dict[str, int] = {}
    currencies: dict[str, int] = {}
    evidence: dict[str, int] = {}
    synthetic_count = 0
    for row in rows:
        price_record = row.get("price") if isinstance(row.get("price"), dict) else row
        evidence_record = (
            price_record.get("evidence") if isinstance(price_record.get("evidence"), dict) else {}
        )
        price = _number(
            _first(
                price_record,
                ("annual_price", "price", "observed_price", "public_price", "amount"),
            )
        )
        price_type = str(
            _first(price_record, ("price_type", "price_basis", "basis")) or "unspecified"
        )
        currency = str(_first(price_record, ("currency",)) or "unspecified")
        if price is not None:
            grouped_prices.setdefault((currency, price_type), []).append(price)
        grade = str(_first(evidence_record, ("evidence_grade", "grade")) or "unspecified")
        price_types[price_type] = price_types.get(price_type, 0) + 1
        currencies[currency] = currencies.get(currency, 0) + 1
        evidence[grade] = evidence.get(grade, 0) + 1
        marker = _first(
            evidence_record or row,
            ("synthetic", "is_synthetic", "source_type"),
        )
        if marker is True or str(marker).strip().lower() in {"true", "synthetic"}:
            synthetic_count += 1

    price_stats = [
        {
            "currency": currency,
            "price_basis": price_basis,
            "count": len(prices),
            "minimum": min(prices),
            "median": median(prices),
            "mean": mean(prices),
            "maximum": max(prices),
        }
        for (currency, price_basis), prices in sorted(grouped_prices.items())
    ]
    return {
        "status": "ok",
        "decision_grade": "NOT_DECISION_GRADE" if synthetic_count else "SOURCE_DEPENDENT",
        "comparable_count": len(rows),
        "synthetic_count": synthetic_count,
        "price_statistics_by_currency_and_basis": price_stats,
        "currencies": currencies,
        "price_types": price_types,
        "evidence_grades": evidence,
        "warning": (
            "Price statistics are separated by currency and price basis. Unadjusted public or "
            "synthetic observations do not establish an actual confidential manufacturer net "
            "price."
        ),
    }


def _portfolio_row(program: Any, result: Any, source_path: Path) -> dict[str, Any]:
    result_data = _as_data(result)
    summary = result_data["summary"]
    return {
        "program_id": summary["program_id"],
        "program_name": program.program_name,
        "source_file": source_path.name,
        "currency": program.currency,
        "valuation_year": program.valuation_year,
        "decision_grade": result_data["decision_grade"],
        "recommendation": result_data["recommendation"],
        "p10_rnpv": summary["p10_rnpv"],
        "p50_rnpv": summary["p50_rnpv"],
        "p90_rnpv": summary["p90_rnpv"],
        "probability_positive_rnpv": summary["probability_positive_rnpv"],
        "peak_cash_at_risk_p50": summary["peak_cash_at_risk_p50"],
        "effective_protected_years": summary["effective_protected_years"],
        "value_lost_per_launch_delay_year": summary["value_lost_per_launch_delay_year"],
        "input_digest": result_data["input_digest"],
        "run_id": result_data["run_id"],
        "warning_count": len(result_data.get("warnings", [])),
        "critical_evidence_gaps": sorted(
            key
            for key, supported in result_data.get("critical_evidence_status", {}).items()
            if not supported
        ),
    }


@app.command("validate")
def validate_command(
    program_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Program JSON file."),
    ],
    comparables_path: Annotated[
        Path | None,
        typer.Option(
            "--comparables",
            "-c",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional comparable CSV or JSON file.",
        ),
    ] = None,
    pretty: Annotated[
        bool, typer.Option("--pretty/--compact", help="Pretty-print JSON output.")
    ] = True,
) -> None:
    """Validate input files without running an analysis."""

    try:
        program = load_program(program_path)
        comparables = load_comparables(comparables_path) if comparables_path else None
        payload = {
            "status": "ok",
            "operation": "validate",
            "program": _as_data(program),
            "comparables": _as_data(comparables) if comparables is not None else None,
        }
        _emit(payload, pretty=pretty)
    except Exception as exc:
        _fail(exc, operation="validate", pretty=pretty)


@app.command("analyze")
def analyze_command(
    program_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Program JSON file."),
    ],
    comparables_path: Annotated[
        Path,
        typer.Option(
            "--comparables",
            "-c",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Comparable CSV or JSON file.",
        ),
    ],
    simulations: Annotated[
        int,
        typer.Option("--simulations", "-n", min=1, help="Monte Carlo draws."),
    ] = 1_000,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic random seed.")] = 42,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write result JSON to this path."),
    ] = None,
    pretty: Annotated[
        bool, typer.Option("--pretty/--compact", help="Pretty-print JSON output.")
    ] = True,
) -> None:
    """Validate inputs and run the complete program analysis."""

    try:
        program = load_program(program_path)
        comparables = load_comparables(comparables_path)
        result = run_analysis(
            program,
            comparables,
            simulations=simulations,
            seed=seed,
        )
        _emit(result, pretty=pretty, output=output)
    except Exception as exc:
        _fail(exc, operation="analyze", pretty=pretty)


@app.command("compare")
def compare_command(
    comparables_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Comparable CSV or JSON file.",
        ),
    ],
    pretty: Annotated[
        bool, typer.Option("--pretty/--compact", help="Pretty-print JSON output.")
    ] = True,
) -> None:
    """Validate and summarize comparable evidence without implying a net price."""

    try:
        comparables = load_comparables(comparables_path)
        _emit(comparable_summary(comparables), pretty=pretty)
    except Exception as exc:
        _fail(exc, operation="compare", pretty=pretty)


@app.command("portfolio")
def portfolio_command(
    program_paths: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Two or more program JSON files.",
        ),
    ],
    comparables_path: Annotated[
        Path,
        typer.Option(
            "--comparables",
            "-c",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Shared comparable CSV or JSON catalog.",
        ),
    ],
    simulations: Annotated[
        int,
        typer.Option("--simulations", "-n", min=1, help="Monte Carlo draws per program."),
    ] = 1_000,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Common random seed used for every program."),
    ] = 42,
    sort_by: Annotated[
        Literal[
            "p50_rnpv",
            "p90_rnpv",
            "probability_positive_rnpv",
            "peak_cash_at_risk_p50",
            "effective_protected_years",
        ],
        typer.Option("--sort-by", help="Transparent numeric ordering field."),
    ] = "p50_rnpv",
    ascending: Annotated[
        bool,
        typer.Option("--ascending/--descending", help="Sort direction."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write portfolio JSON here."),
    ] = None,
    pretty: Annotated[
        bool, typer.Option("--pretty/--compact", help="Pretty-print JSON output.")
    ] = True,
) -> None:
    """Analyze and rank two or more programs on standardized screening outputs."""

    try:
        if len(program_paths) < 2:
            raise ValueError("portfolio requires at least two program JSON paths")
        comparables = load_comparables(comparables_path)
        programs = [(path, load_program(path)) for path in program_paths]
        currencies = {program.currency for _, program in programs}
        valuation_years = {program.valuation_year for _, program in programs}
        if len(currencies) != 1:
            raise ValueError(
                "portfolio programs must share one currency; provide an explicit FX conversion "
                "outside LABrador before comparison"
            )
        if len(valuation_years) != 1:
            raise ValueError(
                "portfolio programs must share one valuation_year before numeric comparison"
            )
        rows: list[dict[str, Any]] = []
        for path, program in programs:
            result = run_analysis(
                program,
                comparables,
                simulations=simulations,
                seed=seed,
            )
            rows.append(_portfolio_row(program, result, path))
        rows.sort(key=lambda row: row[sort_by], reverse=not ascending)
        for rank, row in enumerate(rows, start=1):
            row["screening_rank"] = rank
        payload = {
            "status": "ok",
            "operation": "portfolio",
            "simulations_per_program": simulations,
            "seed": seed,
            "currency": next(iter(currencies)),
            "valuation_year": next(iter(valuation_years)),
            "sort": {"field": sort_by, "direction": "ascending" if ascending else "descending"},
            "program_count": len(rows),
            "rows": rows,
            "warning": (
                "Portfolio order is a transparent screening sort, not an investment ranking. "
                "NOT_DECISION_GRADE rows require evidence replacement and review."
            ),
        }
        _emit(payload, pretty=pretty, output=output)
    except Exception as exc:
        _fail(exc, operation="portfolio", pretty=pretty)


@app.command("example")
def example_command(
    kind: Annotated[
        Literal["manifest", "program", "comparables"],
        typer.Option("--kind", case_sensitive=False, help="Example payload to print."),
    ] = "manifest",
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            file_okay=False,
            help="Copy every demo fixture into a new or existing directory.",
        ),
    ] = None,
    pretty: Annotated[
        bool, typer.Option("--pretty/--compact", help="Pretty-print JSON output.")
    ] = True,
) -> None:
    """Print or copy the bundled, explicitly synthetic demo inputs."""

    try:
        paths = (
            DEMO_PROGRAM,
            DEMO_PROGRAM_B,
            DEMO_COMPARABLES_JSON,
            DEMO_COMPARABLES_CSV,
        )
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Bundled fixture(s) missing: {', '.join(missing)}")
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            copied = []
            for source in paths:
                target = output_dir / source.name
                shutil.copy2(source, target)
                copied.append(str(target.resolve()))
            _emit(
                {
                    "status": "ok",
                    "decision_grade": "NOT_DECISION_GRADE",
                    "synthetic": True,
                    "copied": copied,
                },
                pretty=pretty,
            )
            return
        if kind == "program":
            _emit(_read_json(DEMO_PROGRAM), pretty=pretty)
            return
        if kind == "comparables":
            _emit(_read_json(DEMO_COMPARABLES_JSON), pretty=pretty)
            return
        _emit(
            {
                "status": "ok",
                "decision_grade": "NOT_DECISION_GRADE",
                "synthetic": True,
                "warning": "All bundled demo values and comparables are synthetic.",
                "program": str(DEMO_PROGRAM.resolve()),
                "programs": [
                    str(DEMO_PROGRAM.resolve()),
                    str(DEMO_PROGRAM_B.resolve()),
                ],
                "comparables_json": str(DEMO_COMPARABLES_JSON.resolve()),
                "comparables_csv": str(DEMO_COMPARABLES_CSV.resolve()),
            },
            pretty=pretty,
        )
    except Exception as exc:
        _fail(exc, operation="example", pretty=pretty)


if __name__ == "__main__":
    app()
