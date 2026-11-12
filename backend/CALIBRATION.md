# Scoring Calibration Methodology

## What the fixtures are

`backend/tests/fixtures/pr_eval_cases.py` contains 12 hand-built PR evidence
profiles representing the archetypes a recruiter actually sees:

- small critical bug fixes (race condition, SQL injection)
- large routine refactors
- concurrency fixes
- security fixes
- performance improvements
- API changes
- documentation-only and test-only changes
- merged, closed-unmerged, reverted, and own-repo PRs
- heavy vs minimal maintainer review

Each fixture encodes the *evidence* the pipeline would collect — file category
counts, test add/modify/remove status, CI outcome, review counts, eligibility —
not invented quality judgments.

## What we assert

`test_calibration.py` checks **ordering invariants**, not exact scores:

- docs-only and trivial PRs never outscore substantive engineering work
- technical substance is independent of acceptance (an unmerged substantial PR
  outranks a merged typo fix on substance while losing on acceptance)
- own-repo PRs earn zero collaboration credit but keep technical merit
- missing evidence lowers confidence rather than fabricating conclusions
- reverted PRs lose acceptance credit, not substance credit

## Honest limitations

- The dimension weights (0.22/0.13/0.12/0.13/0.15/0.15/0.10) are **engineering
  judgement, not validated psychometrics**. They were chosen so the invariants
  above hold; they have not been fit against recruiter-labelled outcomes.
- Fixtures are synthetic. Real PR evidence is messier: patches truncate, CI is
  absent on many repos, review bots inflate reviewer counts, and fork networks
  blur ownership.
- `code_quality` and `problem_significance` are deterministic *proxies*
  (patch coverage, scope discipline, linked issues, labels, LLM complexity
  grade). They cannot see actual readability or production impact — the LLM
  layer interprets but never overrides these facts.
- A proper next step is a labelled set of ~100 real PRs scored blind by
  engineers, used to fit weights via rank correlation (e.g., Kendall's tau)
  rather than hand-tuned constants.
