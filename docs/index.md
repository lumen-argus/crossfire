# Crossfire

**Find duplicate and overlapping regex rules before they create duplicate alerts.**

If you maintain detection rules for secret scanning, DLP, SAST, YARA, or IDS — you probably have rules that fire on the same input. Crossfire finds them.

```
$ crossfire scan my_rules.json

========================================================================
  Crossfire Analysis Report
  Rules: 142 from 1 file(s) | Corpus: 4,260 strings | Time: 3.2s
========================================================================

  Duplicates (3 pairs)
  Rule A                    Rule B                     Jaccard Recommendation
  aws_key_v1                aws_key_v2                   1.00      Keep A
  slack_hook                slack_webhook_url            0.94      Keep A
  npm_token                 npm_auth_token               1.00      Keep A

  Subsets (5 pairs)
  Subset Rule               Superset Rule               A->B %
  stripe_sk_live            generic_secret                 98%
  github_pat_v2             github_token                  100%

  Quality Insights
  Broad patterns (2):
    generic_secret           overlaps with 15 rules
    email                    overlaps with 27 rules

  Summary: Drop 7 rules, review 3, 2 broad patterns
```

## The Problem

Detection rule sets grow over time. Different team members add rules independently. You merge rules from upstream projects. Eventually:

- Multiple rules match the same secret (duplicate findings)
- Broad rules like `generic_secret` silently cover what specific rules already catch
- Nobody knows which rules to remove without breaking coverage

**No existing tool solves this.** Regex equivalence is undecidable for real-world patterns (anchors, lookahead, backreferences). YARA dedup tools only find exact matches. Secret scanners handle duplicates at the output level — too late.

## How It Works

Crossfire uses a **corpus-based approach**: generate synthetic strings from each rule's regex, test every rule against every string, and measure overlap empirically.

```
Load rules -> Validate regexes -> Generate test strings -> Cross-evaluate -> Classify -> Report
```

This handles any regex feature Python supports — anchors, lookahead, backreferences, Unicode. No structural analysis limitations.

## Performance

Tested on 1,722 real detection rules (54 community + 1,668 commercial):

| Step | Time |
|------|------|
| Load + validate | <1s |
| Generate corpus (30 samples/rule) | ~26s |
| Cross-evaluate (72M regex matches) | ~3s |
| Classify + quality assessment | <1s |
| **Total** | **~30s** |

Results: 22 duplicates, 249 subsets, 82 overlaps, 18 clusters, 31 broad patterns, 240 fully redundant rules.
