# Generic CI Integration

Crossfire can be added to any CI pipeline.

## Installation

```bash
pip install crossfire-rules
```

## Usage

```bash
crossfire compare rules/*.json --fail-on-duplicate --format summary
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean — no issues found |
| `1` | Duplicates found (with `--fail-on-duplicate`) |
| `2` | Input error (invalid file, bad regex) |
| `3` | Runtime error |

## Examples

### GitLab CI

```yaml
rule-check:
  image: python:3.12
  script:
    - pip install crossfire-rules
    - crossfire compare rules/*.json --fail-on-duplicate --format summary
```

### Jenkins

```groovy
stage('Rule Overlap Check') {
    sh '''
        pip install crossfire-rules
        crossfire compare rules/*.json --fail-on-duplicate --format summary
    '''
}
```

### CircleCI

```yaml
jobs:
  rule-check:
    docker:
      - image: cimg/python:3.12
    steps:
      - checkout
      - run:
          name: Check rule overlaps
          command: |
            pip install crossfire-rules
            crossfire compare rules/*.json --fail-on-duplicate --format summary
```
