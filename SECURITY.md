# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in Crossfire, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email the maintainers directly or use GitHub's private vulnerability reporting feature.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### What to expect

- Acknowledgment within 48 hours
- Assessment and timeline within 1 week
- Fix released as soon as practical

## Scope

Crossfire processes regex patterns and test strings locally. It does not:
- Make network requests (except git clone for `evaluate-git`)
- Execute rule patterns as code
- Store or transmit user data

Security concerns most likely involve:
- ReDoS (catastrophic backtracking) from malicious regex patterns — mitigated by per-rule generation timeouts
- Memory exhaustion from very large rule sets or corpus files
- Path traversal in file loading
