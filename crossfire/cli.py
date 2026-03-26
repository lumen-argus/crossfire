"""Command-line interface for Crossfire."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

import crossfire
from crossfire.errors import CrossfireError, LoadError, ValidationError
from crossfire.logging import setup_logging


# Exit codes
EXIT_OK = 0
EXIT_DUPLICATES = 1
EXIT_INPUT_ERROR = 2
EXIT_RUNTIME_ERROR = 3


@click.group()
@click.version_option(version=crossfire.__version__, prog_name="crossfire")
@click.option("--log-level", default="warning", type=click.Choice(
    ["debug", "info", "warning", "error"], case_sensitive=False),
    help="Logging verbosity.")
@click.option("--log-file", default=None, type=click.Path(), help="Write logs to file.")
@click.option("--log-format", default="text", type=click.Choice(["text", "json"]),
    help="Log format.")
@click.pass_context
def main(ctx: click.Context, log_level: str, log_file: Optional[str], log_format: str) -> None:
    """Crossfire — Regex rule overlap analyzer."""
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    ctx.obj["log_file"] = log_file
    ctx.obj["log_format"] = log_format
    setup_logging(level=log_level, log_file=log_file, log_format=log_format)


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--threshold", default=0.8, type=float, help="Overlap threshold (0.0-1.0).")
@click.option("--samples", default=50, type=int, help="Corpus strings per rule.")
@click.option("--negative-samples", default=10, type=int, help="Negative samples per rule.")
@click.option("--format", "fmt", default="table", type=click.Choice(
    ["json", "table", "csv", "summary"]), help="Output format.")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--workers", default=0, type=int, help="Parallel workers (0=auto).")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@click.option("--fail-on-duplicate", is_flag=True, help="Exit code 1 if duplicates found.")
@click.option("--partition-by", default=None, type=str,
    help="Partition rules by field (e.g., 'detector').")
def scan(
    files: tuple[str, ...],
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: Optional[str],
    workers: int,
    seed: Optional[int],
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: Optional[str],
) -> None:
    """Find overlapping rules within one or more files.

    Loads rules, generates synthetic test strings, cross-evaluates all rules
    against all strings, and reports duplicates, subsets, and overlaps.
    """
    _run_analysis(
        list(files), threshold=threshold, samples=samples,
        negative_samples=negative_samples, fmt=fmt, output=output,
        workers=workers, seed=seed, skip_invalid=skip_invalid,
        fail_on_duplicate=fail_on_duplicate, partition_by=partition_by,
    )


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--threshold", default=0.8, type=float, help="Overlap threshold (0.0-1.0).")
@click.option("--samples", default=50, type=int, help="Corpus strings per rule.")
@click.option("--negative-samples", default=10, type=int, help="Negative samples per rule.")
@click.option("--format", "fmt", default="table", type=click.Choice(
    ["json", "table", "csv", "summary"]), help="Output format.")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--workers", default=0, type=int, help="Parallel workers (0=auto).")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@click.option("--fail-on-duplicate", is_flag=True, help="Exit code 1 if duplicates found.")
@click.option("--partition-by", default=None, type=str,
    help="Partition rules by field (e.g., 'detector').")
@click.option("--priority", default=None, type=str,
    help="Priority mapping (e.g., 'curated.json=100,community.json=80').")
def compare(
    files: tuple[str, ...],
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: Optional[str],
    workers: int,
    seed: Optional[int],
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: Optional[str],
    priority: Optional[str],
) -> None:
    """Compare two or more rule files for cross-file overlap.

    Loads rules from multiple files, generates synthetic test strings,
    cross-evaluates, and reports which rules overlap between files.
    """
    priorities = _parse_priorities(priority) if priority else None

    _run_analysis(
        list(files), threshold=threshold, samples=samples,
        negative_samples=negative_samples, fmt=fmt, output=output,
        workers=workers, seed=seed, skip_invalid=skip_invalid,
        fail_on_duplicate=fail_on_duplicate, partition_by=partition_by,
        priorities=priorities,
    )


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
def validate(files: tuple[str, ...], skip_invalid: bool) -> None:
    """Validate regex patterns in rule files.

    Checks that all rules have valid names, non-empty patterns, and
    compilable regexes. Fails on first error unless --skip-invalid is set.
    """
    from crossfire.loader import load_rules

    total = 0
    for file_path in files:
        try:
            rules = load_rules(file_path, skip_invalid=skip_invalid)
            total += len(rules)
            click.echo(f"OK: {file_path} — {len(rules)} valid rules")
        except (ValidationError, LoadError) as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(EXIT_INPUT_ERROR)

    click.echo(f"\nAll {total} rules valid across {len(files)} file(s).")


@main.command("generate-corpus")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--output", "-o", required=True, type=click.Path(), help="Output corpus file.")
@click.option("--samples", default=50, type=int, help="Corpus strings per rule.")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
def generate_corpus(
    files: tuple[str, ...],
    output: str,
    samples: int,
    seed: Optional[int],
    skip_invalid: bool,
) -> None:
    """Generate corpus strings from rules (for debugging or external use)."""
    import json
    from crossfire.generator import CorpusGenerator
    from crossfire.loader import load_multiple

    try:
        rules = load_multiple(list(files), skip_invalid=skip_invalid)
    except (ValidationError, LoadError) as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)

    generator = CorpusGenerator(samples_per_rule=samples, seed=seed)

    try:
        corpus = generator.generate(rules, skip_invalid=skip_invalid)
    except CrossfireError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_RUNTIME_ERROR)

    entries = [
        {"text": e.text, "source_rule": e.source_rule, "is_negative": e.is_negative}
        for e in corpus
    ]

    with open(output, "w") as f:
        json.dump(entries, f, indent=2)

    click.echo(f"Generated {len(entries)} corpus entries → {output}")


def _run_analysis(
    files: list[str],
    *,
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: Optional[str],
    workers: int,
    seed: Optional[int],
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: Optional[str],
    priorities: Optional[dict[str, int]] = None,
) -> None:
    """Shared analysis runner for scan and compare commands."""
    from crossfire.analyzer import analyze
    from crossfire.reporter import render

    try:
        report = analyze(
            files,
            threshold=threshold,
            samples_per_rule=samples,
            negative_samples=negative_samples,
            seed=seed,
            workers=workers,
            partition_by=partition_by,
            skip_invalid=skip_invalid,
            priorities=priorities,
        )
    except (ValidationError, LoadError) as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)
    except CrossfireError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_RUNTIME_ERROR)

    if output:
        with open(output, "w") as f:
            render(report, fmt, f)
        click.echo(f"Report written to {output}")
    else:
        render(report, fmt, sys.stdout)

    if fail_on_duplicate and report.duplicates:
        sys.exit(EXIT_DUPLICATES)


def _parse_priorities(priority_str: str) -> dict[str, int]:
    """Parse priority string like 'curated.json=100,community.json=80'."""
    result: dict[str, int] = {}
    for part in priority_str.split(","):
        part = part.strip()
        if "=" not in part:
            raise click.BadParameter(f"Invalid priority format: '{part}' (expected 'file=N')")
        name, value = part.rsplit("=", 1)
        try:
            result[name.strip()] = int(value.strip())
        except ValueError:
            raise click.BadParameter(f"Invalid priority value: '{value}' (expected integer)")
    return result
