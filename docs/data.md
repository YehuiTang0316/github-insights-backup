# Archive format

```text
data/
  README.md                         Latest run summary for configured repositories
  owner/repository/
    latest.json                     Latest attempt, including any partial failures
    latest-complete.json             Pointer to the latest fully complete snapshot, if one exists
    traffic-daily.json               Latest observed values indexed by UTC date
    traffic-daily.csv                The same daily index for analysis
    snapshots/YYYY-MM-DD/run-id/
      started.json                  Metadata written before requests begin
      manifest.json                 Per-endpoint status, timestamps, and SHA-256 checksums
      repository.json
      views.json
      clones.json
      referrers.json
      paths.json
      stargazers.json
      forks.json
      contributors.json
      commit_activity.json
      code_frequency.json
      participation.json
      punch_card.json
      releases.json
      community_profile.json
      languages.json
```

All dates are UTC. Snapshot directories are immutable and unique, including manual reruns on the same day. A cancelled run may contain `started.json` without a final manifest; do not treat it as complete.

## Responses and status

Non-paginated JSON files contain the parsed API response body, including `null` for HTTP 204. Paginated files (`stargazers`, `forks`, `releases`) contain **an array of pages**, each page being an array of records. Flatten one level before analysis. This preserves page boundaries and prevents silent truncation after the first 100 records.

Each saved endpoint has a filename and SHA-256 checksum in `manifest.json`. Failed, pending, and unavailable endpoints have no data file; details are recorded in the manifest.

- `saved`: response parsed and written.
- `pending`: GitHub statistics still return HTTP 202 after retries.
- `unavailable`: GitHub code-frequency statistics reject a repository with 10,000 or more commits (HTTP 422), or the community profile is not available (HTTP 404; forks are excluded by GitHub).
- `failed`: authentication, permission, transport, invalid response, or other API failure.

`saved_with_gaps` means supported data was saved but at least one optional endpoint is pending or unavailable. It is not a claim that every Insights statistic was backed up. Such a run is nonfatal and listed explicitly in the Actions summary. Other failures or stale traffic make the run `partial` and return a nonzero exit code. Exit code 2 indicates a configuration error.

## Daily traffic

The daily index updates each date and metric independently, using the latest successful observation. Repeated pulls never increment a stored daily total. A later revision may legitimately reduce a count.

Missing metric cells are blank in CSV and absent in JSON. We do not invent zeroes for gaps. Unobserved dates are omitted. Data from the current UTC day may not be final; subsequent runs update it while it remains in the rolling window.

To report a period's **views or clones**, sum its daily count rows once and disclose gaps. Do not sum 14-day window totals. For a **unique** audience, use only an aggregate GitHub actually supplies for the matching window: summing daily uniques or adjacent windows does not deduplicate repeat users.

Traffic is a rolling 14-day API, with UTC daily boundaries. Exact historical recovery is possible only for dates captured previously. Referrers/popular pages cover top-10 rolling lists. Clones can include repeat or automated use. Star/Fork lists reflect current retained records and are not a complete audit log of removals.

## Retention and growth

Nothing is pruned automatically. Long-running archives, especially large stargazer lists, can grow substantially. Use a dedicated private repository and monitor storage. This tool does not currently provide archival migration or retention automation.

Source requests are read-only. Credentials are supplied through environment variables or GitHub CLI's credential store; authorization headers, tokens, and raw credential-helper error output are not saved. Archive write access comes from the private repository's own workflow token.
