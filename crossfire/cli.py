"""Command-line interface for Crossfire."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click

import crossfire
from crossfire.corpus import DiffReport, EvaluationReport
from crossfire.errors import CrossfireError, LoadError, ValidationError
from crossfire.logging import setup_logging

F = TypeVar("F", bound=Callable[..., Any])

# Exit codes
EXIT_OK = 0
EXIT_DUPLICATES = 1
EXIT_INPUT_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def _logging_options(f: F) -> F:
    """Shared logging options for all commands."""
    f = click.option(
        "--log-format", default="text", type=click.Choice(["text", "json"]), help="Log format."
    )(f)
    f = click.option("--log-file", default=None, type=click.Path(), help="Write logs to file.")(f)
    f = click.option(
        "--log-level",
        default="warning",
        type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
        help="Logging verbosity.",
    )(f)
    return f


def _init_logging(log_level: str, log_file: str | None, log_format: str) -> None:
    """Initialize logging from command options."""
    setup_logging(level=log_level, log_file=log_file, log_format=log_format)


@click.group()
@click.version_option(version=crossfire.__version__, prog_name="crossfire")
@_logging_options
def main(log_level: str, log_file: str | None, log_format: str) -> None:
    """Crossfire — Regex rule overlap analyzer."""
    _init_logging(log_level, log_file, log_format)


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--threshold", default=0.8, type=float, help="Overlap threshold (0.0-1.0).")
@click.option("--samples", default=50, type=int, help="Corpus strings per rule.")
@click.option("--negative-samples", default=10, type=int, help="Negative samples per rule.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["json", "table", "csv", "summary"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--workers", default=0, type=int, help="Parallel workers (0=auto).")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@click.option("--fail-on-duplicate", is_flag=True, help="Exit code 1 if duplicates found.")
@click.option(
    "--partition-by", default=None, type=str, help="Partition rules by field (e.g., 'detector')."
)
@_logging_options
def scan(
    files: tuple[str, ...],
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: str | None,
    workers: int,
    seed: int | None,
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: str | None,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Find overlapping rules within one or more files.

    Loads rules, generates synthetic test strings, cross-evaluates all rules
    against all strings, and reports duplicates, subsets, and overlaps.
    """
    _init_logging(log_level, log_file, log_format)
    _run_analysis(
        list(files),
        threshold=threshold,
        samples=samples,
        negative_samples=negative_samples,
        fmt=fmt,
        output=output,
        workers=workers,
        seed=seed,
        skip_invalid=skip_invalid,
        fail_on_duplicate=fail_on_duplicate,
        partition_by=partition_by,
    )


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--threshold", default=0.8, type=float, help="Overlap threshold (0.0-1.0).")
@click.option("--samples", default=50, type=int, help="Corpus strings per rule.")
@click.option("--negative-samples", default=10, type=int, help="Negative samples per rule.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["json", "table", "csv", "summary"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--workers", default=0, type=int, help="Parallel workers (0=auto).")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@click.option("--fail-on-duplicate", is_flag=True, help="Exit code 1 if duplicates found.")
@click.option(
    "--partition-by", default=None, type=str, help="Partition rules by field (e.g., 'detector')."
)
@click.option(
    "--priority",
    default=None,
    type=str,
    help="Priority mapping (e.g., 'curated.json=100,community.json=80').",
)
@_logging_options
def compare(
    files: tuple[str, ...],
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: str | None,
    workers: int,
    seed: int | None,
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: str | None,
    priority: str | None,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Compare two or more rule files for cross-file overlap.

    Loads rules from multiple files, generates synthetic test strings,
    cross-evaluates, and reports which rules overlap between files.
    """
    _init_logging(log_level, log_file, log_format)
    priorities = _parse_priorities(priority) if priority else None

    _run_analysis(
        list(files),
        threshold=threshold,
        samples=samples,
        negative_samples=negative_samples,
        fmt=fmt,
        output=output,
        workers=workers,
        seed=seed,
        skip_invalid=skip_invalid,
        fail_on_duplicate=fail_on_duplicate,
        partition_by=partition_by,
        priorities=priorities,
    )


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@_logging_options
def validate(
    files: tuple[str, ...],
    skip_invalid: bool,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Validate regex patterns in rule files.

    Checks that all rules have valid names, non-empty patterns, and
    compilable regexes. Fails on first error unless --skip-invalid is set.
    """
    _init_logging(log_level, log_file, log_format)
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
@_logging_options
def generate_corpus(
    files: tuple[str, ...],
    output: str,
    samples: int,
    seed: int | None,
    skip_invalid: bool,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Generate corpus strings from rules (for debugging or external use)."""
    _init_logging(log_level, log_file, log_format)
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
        {"text": e.text, "source_rule": e.source_rule, "is_negative": e.is_negative} for e in corpus
    ]

    with open(output, "w") as f:
        json.dump(entries, f, indent=2)

    click.echo(f"Generated {len(entries)} corpus entries → {output}")


@main.command("evaluate")
@click.argument("rules_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--corpus",
    required=True,
    type=click.Path(exists=True),
    help="JSONL corpus file to test rules against.",
)
@click.option("--corpus-field", default="text", help="Field name for text content in JSONL.")
@click.option("--label-field", default="label", help="Field name for ground-truth labels.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["json", "table", "summary"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@click.option("--redact-samples", is_flag=True, help="Don't include matched text in debug logs.")
@_logging_options
def evaluate_cmd(
    rules_files: tuple[str, ...],
    corpus: str,
    corpus_field: str,
    label_field: str,
    fmt: str,
    output: str | None,
    skip_invalid: bool,
    redact_samples: bool,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Evaluate rules against a real-world corpus.

    Tests which rules fire on real data. If the corpus has labels,
    computes precision, recall, and F1 per rule.
    """
    _init_logging(log_level, log_file, log_format)
    from crossfire.corpus import evaluate_corpus, load_corpus_jsonl

    rules = _load_rules_or_exit(rules_files, skip_invalid)

    try:
        entries = load_corpus_jsonl(
            corpus,
            text_field=corpus_field,
            label_field=label_field,
        )
    except LoadError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)

    report = evaluate_corpus(rules, entries, redact_samples=redact_samples)
    _render_evaluation(report, fmt, output)


@main.command("evaluate-git")
@click.argument("rules_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--repo", required=True, type=click.Path(exists=True), help="Path to git repository.")
@click.option("--max-commits", default=500, type=int, help="Maximum commits to scan.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["json", "table", "summary"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@_logging_options
def evaluate_git_cmd(
    rules_files: tuple[str, ...],
    repo: str,
    max_commits: int,
    fmt: str,
    output: str | None,
    skip_invalid: bool,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Evaluate rules against git repository history.

    Extracts added/modified lines from recent commits and tests
    which rules match.
    """
    _init_logging(log_level, log_file, log_format)
    from crossfire.corpus import evaluate_corpus, load_corpus_git

    rules = _load_rules_or_exit(rules_files, skip_invalid)

    try:
        entries = load_corpus_git(repo, max_commits=max_commits)
    except (LoadError, CrossfireError) as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)

    report = evaluate_corpus(rules, entries)
    _render_evaluation(report, fmt, output)


@main.command("diff")
@click.argument("rules_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--corpus-a", required=True, type=click.Path(exists=True), help="First JSONL corpus file."
)
@click.option(
    "--corpus-b", required=True, type=click.Path(exists=True), help="Second JSONL corpus file."
)
@click.option("--corpus-field", default="text", help="Field name for text content.")
@click.option(
    "--format", "fmt", default="table", type=click.Choice(["json", "table"]), help="Output format."
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--skip-invalid", is_flag=True, help="Skip invalid rules instead of failing.")
@_logging_options
def diff_cmd(
    rules_files: tuple[str, ...],
    corpus_a: str,
    corpus_b: str,
    corpus_field: str,
    fmt: str,
    output: str | None,
    skip_invalid: bool,
    log_level: str,
    log_file: str | None,
    log_format: str,
) -> None:
    """Compare rule behavior across two corpora (coverage drift).

    For each rule, computes match rate in each corpus and flags rules
    with >5% divergence.
    """
    _init_logging(log_level, log_file, log_format)
    import json

    from crossfire.corpus import diff_corpora, load_corpus_jsonl

    rules = _load_rules_or_exit(rules_files, skip_invalid)

    try:
        entries_a = load_corpus_jsonl(corpus_a, text_field=corpus_field)
        entries_b = load_corpus_jsonl(corpus_b, text_field=corpus_field)
    except LoadError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)

    result = diff_corpora(
        rules,
        entries_a,
        entries_b,
        name_a=Path(corpus_a).stem,
        name_b=Path(corpus_b).stem,
    )

    if fmt == "json":
        from dataclasses import asdict

        content = json.dumps(asdict(result), indent=2, default=str)
        if output:
            Path(output).write_text(content)
            click.echo(f"Report written to {output}")
        else:
            click.echo(content)
    else:
        _render_diff_table(result, output)


def _load_rules_or_exit(
    rules_files: tuple[str, ...] | list[str],
    skip_invalid: bool,
) -> list[Any]:
    """Load rules from files, exiting on error."""
    from crossfire.loader import load_multiple

    try:
        return load_multiple(list(rules_files), skip_invalid=skip_invalid)
    except (ValidationError, LoadError) as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_INPUT_ERROR)


def _render_evaluation(report: EvaluationReport, fmt: str, output: str | None) -> None:
    """Render evaluation report."""
    import json

    if fmt == "json":
        data = _evaluation_to_dict(report)
        content = json.dumps(data, indent=2, default=str)
        if output:
            Path(output).write_text(content)
            click.echo(f"Report written to {output}")
        else:
            click.echo(content)
    elif fmt == "summary":
        s = report.summary
        click.echo(
            f"Evaluated {report.total_entries} entries against {report.rules_evaluated} rules. "
            f"{s['rules_firing']} rules fired, {s['co_firing_pairs']} co-firing pairs."
        )
        if report.labeled_entries:
            click.echo(
                f"Labeled: avg precision={s['avg_precision']:.2f}, "
                f"avg recall={s['avg_recall']:.2f}."
            )
    else:
        # Table format
        click.echo(f"\n{'=' * 72}")
        click.echo("  Crossfire Evaluation Report")
        click.echo(
            f"  Entries: {report.total_entries} "
            f"({report.labeled_entries} labeled) | "
            f"Rules: {report.rules_evaluated} | "
            f"Time: {report.duration_s}s"
        )
        click.echo(f"{'=' * 72}\n")

        # Rules that fired
        firing = sorted(
            [m for m in report.rule_metrics if m.matched_count > 0],
            key=lambda m: m.matched_count,
            reverse=True,
        )
        if firing:
            click.echo(f"  Rules that fired ({len(firing)}):")
            click.echo(f"  {'-' * 55}")
            if report.labeled_entries:
                click.echo(f"  {'Rule':<30} {'Matches':>8} {'Prec':>6} {'Recall':>6} {'F1':>6}")
                click.echo(f"  {'-' * 55}")
                for m in firing[:30]:
                    click.echo(
                        f"  {m.name:<30} {m.matched_count:>8} "
                        f"{m.precision:>5.2f} {m.recall:>6.2f} {m.f1:>5.2f}"
                    )
            else:
                click.echo(f"  {'Rule':<40} {'Matches':>8}")
                click.echo(f"  {'-' * 55}")
                for m in firing[:30]:
                    click.echo(f"  {m.name:<40} {m.matched_count:>8}")
            if len(firing) > 30:
                click.echo(f"  ... and {len(firing) - 30} more")
            click.echo()

        # Top co-firing pairs
        if report.co_firing:
            click.echo(f"  Top co-firing pairs ({len(report.co_firing)}):")
            click.echo(f"  {'-' * 55}")
            click.echo(f"  {'Rule A':<25} {'Rule B':<25} {'Count':>5}")
            click.echo(f"  {'-' * 55}")
            for a, b, count in report.co_firing[:15]:
                click.echo(f"  {a:<25} {b:<25} {count:>5}")
            click.echo()

        if output:
            import json

            data = _evaluation_to_dict(report)
            Path(output).write_text(json.dumps(data, indent=2, default=str))
            click.echo(f"  Full report written to {output}")


def _evaluation_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """Convert evaluation report to a JSON-serializable dict."""
    from dataclasses import asdict

    return {
        "total_entries": report.total_entries,
        "labeled_entries": report.labeled_entries,
        "rules_evaluated": report.rules_evaluated,
        "rule_metrics": [asdict(m) for m in report.rule_metrics if m.matched_count > 0],
        "co_firing": [{"rule_a": a, "rule_b": b, "count": c} for a, b, c in report.co_firing],
        "summary": report.summary,
    }


def _render_diff_table(report: DiffReport, output: str | None) -> None:
    """Render differential analysis as a table."""

    click.echo(f"\n{'=' * 72}")
    click.echo("  Crossfire Differential Analysis")
    click.echo(
        f"  {report.name_a}: {report.entries_a} entries | "
        f"{report.name_b}: {report.entries_b} entries"
    )
    click.echo(f"{'=' * 72}\n")

    significant = [r for r in report.results if r.significant]
    if significant:
        click.echo(f"  Rules with significant drift ({len(significant)}):")
        click.echo(f"  {'-' * 65}")
        click.echo(
            f"  {'Rule':<30} {report.name_a + ' %':>10} {report.name_b + ' %':>10} {'Drift':>8}"
        )
        click.echo(f"  {'-' * 65}")
        for r in significant[:30]:
            click.echo(
                f"  {r.rule:<30} "
                f"{r.rate_a * 100:>9.1f}% "
                f"{r.rate_b * 100:>9.1f}% "
                f"{r.drift * 100:>7.1f}%"
            )
        click.echo()
    else:
        click.echo("  No significant drift detected.\n")

    if output:
        import json
        from dataclasses import asdict

        Path(output).write_text(json.dumps(asdict(report), indent=2, default=str))
        click.echo(f"  Full report written to {output}")


def _run_analysis(
    files: list[str],
    *,
    threshold: float,
    samples: int,
    negative_samples: int,
    fmt: str,
    output: str | None,
    workers: int,
    seed: int | None,
    skip_invalid: bool,
    fail_on_duplicate: bool,
    partition_by: str | None,
    priorities: dict[str, int] | None = None,
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
        except ValueError as err:
            raise click.BadParameter(
                f"Invalid priority value: '{value}' (expected integer)"
            ) from err
    return result
