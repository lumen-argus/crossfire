# Contributing

## Getting started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/crossfire.git
   cd crossfire
   ```
3. Set up the development environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   pre-commit install
   ```
4. Verify everything works:
   ```bash
   pytest
   ruff check crossfire/ tests/
   mypy crossfire/
   ```

## Development workflow

1. Create a branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Run the full check suite:
   ```bash
   pre-commit run --all-files
   pytest -v
   ```
5. Commit and open a Pull Request

## Code style

- Python 3.10+ with type annotations
- Formatted with `ruff` (line-length 100)
- Type checked with `mypy` (strict mode)
- Structured logging via `logging.getLogger("crossfire.<module>")`
- Fail-fast by default, lenient by opt-in (`--skip-invalid`)

## Tests

- Tests live in `tests/` and use pytest
- Test fixtures go in `tests/fixtures/`
- Run a single test file: `pytest tests/test_loader.py -v`
- Run a single test: `pytest tests/test_loader.py::TestLoadJson::test_load_array -v`

## Adding a format adapter

Crossfire uses a plugin system for format adapters. To add support for a new tool:

1. Create `crossfire/plugins/your_tool.py`
2. Implement the `RuleAdapter` protocol:
   ```python
   class YourToolAdapter:
       @property
       def name(self) -> str:
           return "your_tool"

       def can_load(self, path: str) -> bool:
           # Check extension + content sniffing (read max 2KB)
           ...

       def load(self, path: str) -> list[dict[str, object]]:
           # Return dicts with at least "name" and "pattern" keys
           ...
   ```
3. Register it in `crossfire/plugins/__init__.py` (`_register_builtin_adapters`)
4. Add a test fixture in `tests/fixtures/`
5. Add tests in `tests/test_plugins.py`

See `crossfire/plugins/gitleaks.py` for a reference implementation.

## Pull request guidelines

- Keep PRs focused on a single change
- Include tests for new functionality
- Update `CHANGELOG.md` for user-visible changes
- Ensure all checks pass (`pre-commit run --all-files`)
