# Installation

## Requirements

- Python 3.10 or higher
- No heavy dependencies

## Install from source

```bash
git clone https://github.com/lumen-argus/crossfire.git
cd crossfire
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Optional: Rich tables

For enhanced terminal table output:

```bash
pip install crossfire[rich]
```

## Verify installation

```bash
crossfire --version
```
