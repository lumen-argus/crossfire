# Contributing to Crossfire

Thank you for your interest in contributing to Crossfire. This document explains how to get involved.

## Getting Started

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
   ```
4. Verify everything works:
   ```bash
   pytest
   ruff check crossfire/ tests/
   ```

## Development Workflow

1. Create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes
3. Add tests for new functionality
4. Run the test suite:
   ```bash
   pytest -v
   ```
5. Run the linter:
   ```bash
   ruff check crossfire/ tests/
   ```
6. Commit with a descriptive message
7. Push to your fork and open a Pull Request

## Code Style

- Python 3.10+ with type annotations
- Formatted with `ruff` (configuration in `pyproject.toml`)
- Structured logging via `logging.getLogger("crossfire.<module>")`
- Fail-fast by default, lenient by opt-in (`--skip-invalid`)

## Tests

- Tests live in `tests/` and use pytest
- Test fixtures go in `tests/fixtures/`
- Aim for test coverage on all new code paths
- Run a single test file: `pytest tests/test_loader.py -v`
- Run a single test: `pytest tests/test_loader.py::TestLoadJson::test_load_array -v`

## Adding a Format Adapter

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

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include the crossfire version (`crossfire --version`)
- For bugs, include the command you ran, the input file format, and the error output
- For rule format support requests, include a sample rule file

## Pull Request Guidelines

- Keep PRs focused on a single change
- Include tests for new functionality
- Update `CHANGELOG.md` for user-visible changes
- Ensure all tests pass and linter is clean
- Write a clear PR description explaining what and why

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
