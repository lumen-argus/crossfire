# CLAUDE.md

## Project Overview

Crossfire is a standalone, open-source regex rule overlap analyzer. It detects duplicate, subset, and overlapping rules in DLP, secret scanning, SAST, YARA, and IDS toolsets using corpus-based analysis.

## Build & Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest

# Run single test
pytest tests/test_loader.py -v

# Lint
ruff check crossfire/ tests/

# Type check
mypy crossfire/
```

## Architecture

Pipeline: Load → Validate (fail-fast) → Generate corpus → Cross-evaluate → Classify → Report

- `models.py` — Rule, CorpusEntry, OverlapResult, AnalysisReport dataclasses
- `loader.py` — Format-agnostic rule loading (JSON/YAML/CSV/TOML) with fail-fast validation
- `generator.py` — Corpus generation via rstr + fallback, per-rule timeout, negative samples
- `evaluator.py` — Parallel cross-rule regex evaluation, NxN match matrix
- `classifier.py` — Relationship classification (duplicate/subset/superset/overlap/disjoint), clustering
- `reporter.py` — Output rendering (JSON/table/CSV/summary)
- `analyzer.py` — Orchestrator coordinating the full pipeline
- `cli.py` — Click CLI with scan, compare, validate, generate-corpus commands
- `errors.py` — CrossfireError, ValidationError, LoadError, GenerationError
- `logging.py` — Structured logging (text + JSON formats)

## Key Design Decisions

- **Fail-fast by default**: Invalid regex, empty pattern, duplicate names → immediate failure. `--skip-invalid` for lenient mode.
- **Corpus-based, not structural**: Generates strings from regexes and tests empirically. Handles any Python `re` feature (anchors, lookahead, backrefs).
- **Three commands**: `validate` (syntax check), `scan` (internal overlap), `compare` (cross-file overlap).
- **rstr** for string generation (BSD license), not exrex (AGPL).
- **ProcessPoolExecutor** for parallel evaluation — regexes re-compiled in workers since Pattern objects aren't serializable.

## CLI Commands

```bash
crossfire validate rules.json                    # Quick syntax check
crossfire scan rules.json --format table         # Find internal duplicates
crossfire compare a.json b.json --format json    # Cross-file overlap
crossfire generate-corpus rules.json -o out.json # Export corpus for debugging
```

## Dependencies

Runtime: `rstr>=3.2`, `click>=8.0`, `pyyaml>=6.0`
Optional: `rich>=13.0` (terminal tables)
Dev: `pytest`, `pytest-cov`, `ruff`, `mypy`
