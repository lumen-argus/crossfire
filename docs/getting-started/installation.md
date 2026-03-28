# Installation

## Requirements

- Python 3.11 or higher
- No heavy dependencies

## Install from PyPI

```bash
pip install crossfire-rules
```

## Optional: RE2 regex acceleration

For **10-100x faster regex matching** on large rule sets, install with RE2 support:

=== "macOS"

    ```bash
    brew install re2
    pip install crossfire-rules[re2]
    ```

=== "Ubuntu / Debian"

    ```bash
    sudo apt-get install -y libre2-dev
    pip install crossfire-rules[re2]
    ```

=== "Fedora / RHEL"

    ```bash
    sudo dnf install -y re2-devel
    pip install crossfire-rules[re2]
    ```

RE2 is entirely optional — Crossfire works fine without it using Python's stdlib `re` module.

**How it works:** RE2 uses a Thompson NFA engine instead of backtracking, which is dramatically faster for most patterns. Crossfire tries RE2 first for each pattern, and automatically falls back to stdlib `re` for patterns that use PCRE-only features (backreferences, lookahead, lookbehind). No configuration needed.

**When it helps most:** Large rule sets (100+ rules) with high sample counts. The regex matching step in the evaluator is the bottleneck, and RE2 accelerates it directly.

## Optional: Rich tables

For enhanced terminal table output:

```bash
pip install crossfire-rules[rich]
```

## Install from source

```bash
git clone https://github.com/lumen-argus/crossfire.git
cd crossfire
pip install -e .
```

For development (includes test and lint tools):

```bash
pip install -e ".[dev]"
```

## Verify installation

```bash
crossfire --version
```
