# Contributing

Python 3.9+ and GitHub CLI are the only runtime requirements. The test suite uses Python's standard library, synthetic data, and mocked API responses:

```bash
python3 -m unittest discover -s tests -v
```

Please preserve these guarantees:

- Never commit real tokens or private Insights data to the public project.
- Every source API call is read-only. The workflow may only write to its private archive.
- Never add overlapping traffic windows or daily unique values into an alleged deduplicated total.
- Failed/missing responses must not become zero counts.
- Preserve partial successes, immutable snapshots, and complete pagination.
- Cover changes to collection, error handling, and date merging with meaningful tests.

Open an issue or pull request with the problem, expected behavior, and test results. Share synthetic or sanitized examples. Do not include personal access tokens, private metrics, or credential-helper output.
