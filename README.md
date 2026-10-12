# GitHub Insights Backup

**Keep your repository's history beyond GitHub's 14-day traffic window.**

An open-source GitHub template that backs up Insights to **your own private repository** every day. Add repository names and a read-only token. GitHub Actions handles collection, snapshots, and synchronization—no server or database to maintain.

[Create your private archive](https://github.com/new?template_name=github-insights-backup&template_owner=YehuiTang0316) · [中文指南](docs/README.zh-CN.md) · [Data format](docs/data.md)

## What you get

- Multiple repositories in one archive, including repositories from different organizations.
- Daily views and clones, unique visitors and cloners, top referrers and popular pages.
- Star timestamps, fork records, repository metadata, releases, languages, and available contribution statistics.
- Immutable raw JSON snapshots, SHA-256 checksums, and a daily CSV that deduplicates overlapping windows.
- Daily cloud runs and a **Run workflow** button for manual synchronization.
- No central service: code is public; your tokens and archived data stay in your private copy.

Traffic is available only for repositories you are authorized to administer/read traffic for. This tool does not expose private Insights for arbitrary public repositories. [GitHub documents the permission requirements here](https://docs.github.com/en/rest/metrics/traffic).

## Set up in GitHub

### 1. Create a private copy

Select **Use this template → Create a new repository**, then choose **Private**. Do not fork the public repository: create a new private repository from the template instead.

The public template contains no real metrics. The backup workflow refuses to save data in a public repository.

### 2. Add your repositories

In your copy, open **Settings → Secrets and variables → Actions → Variables**, and create:

| Variable | Example |
| --- | --- |
| `TARGET_REPOSITORIES` | `your-org/project-a, your-username/project-b` |

Alternatively, edit `config.json`:

```json
{
  "repositories": ["your-org/project-a", "your-org/project-b"]
}
```

Manual input takes priority over the variable; the variable takes priority over `config.json`.

### 3. Add authentication

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new?name=GitHub+Insights+Backup&description=Read+Insights+for+my+selected+repositories&administration=read&contents=read&metadata=read&expires_in=90). Select the **owner of the repositories being tracked** and only those repositories. Grant:

| Repository permission | Access | Purpose |
| --- | --- | --- |
| Administration | Read-only | Views, clones, referrers, and popular pages |
| Contents | Read-only | Releases and supported repository data, including private projects |
| Metadata | Read-only | Repository metadata, stars, forks, and statistics; automatically included |

Your account must already have the necessary access to those repositories. An organization may require approval. Token permissions do not grant your account access it does not have.

In the **private archive**, open **Settings → Secrets and variables → Actions → Secrets**, and add the token as **`INSIGHTS_TOKEN`**. Never put it in a variable, config file, issue, or commit.

The archive's built-in `GITHUB_TOKEN` writes snapshots to the archive. Your Insights token only reads the source repositories. A regular workflow token cannot read another repository's private Traffic data.

**Multiple owners:** a fine-grained token belongs to one resource owner. For several owners, use the **`INSIGHTS_TOKENS_JSON` secret**, containing a JSON object mapping owners to their tokens:

```json
{
  "your-org": "TOKEN_FOR_YOUR_ORG",
  "another-org": "TOKEN_FOR_ANOTHER_ORG",
  "your-username/specific-repo": "TOKEN_FOR_THIS_REPOSITORY"
}
```

Exact repository matches take priority over owner matches, then `INSIGHTS_TOKEN`. These are examples, not real credentials. Set an expiration appropriate to your policy and rotate tokens before they expire.

### 4. Run once

Open **Actions → Back up Insights → Run workflow**. Enable Actions if GitHub asks. Leave the optional repository input blank to use your saved configuration.

After a successful run, open `data/README.md` for the latest status and `data/<owner>/<repo>/traffic-daily.csv` for daily traffic. Inspect the run summary for endpoints still being computed by GitHub.

The default schedule is **daily at 01:00 UTC / 09:00 Asia/Shanghai**. Change the cron expression in `.github/workflows/backup.yml` to choose another time. Scheduled runs use the default branch and may be delayed by GitHub; this is not a precise-time scheduler. [Schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Run locally

Requires **Python 3.9+** and [GitHub CLI](https://cli.github.com/) with `gh api --slurp` support. The GitHub-hosted workflow installs Python and uses its preinstalled CLI.

```bash
git clone https://github.com/YehuiTang0316/github-insights-backup.git
cd github-insights-backup
gh auth login
python3 -m insights_backup --repositories your-org/your-repo
```

No Python dependencies or installation step are required. Local runs use your existing `gh` login, or `INSIGHTS_TOKEN` / `INSIGHTS_TOKENS_JSON` from your environment. Credentials are never written into the archive.

```bash
# Validate configuration without API calls or writes.
python3 -m insights_backup --repositories your-org/your-repo --check

# Select another output directory.
python3 -m insights_backup --repositories your-org/your-repo --output /path/to/private-backups

# Run the test suite without network access or credentials.
python3 -m unittest discover -s tests -v
```

`data/` is ignored locally to prevent accidental publication. Only the private backup workflow deliberately adds it to Git. Avoid running multiple local processes against the same output directory.

## What the numbers mean

GitHub Traffic exposes a rolling 14-day window. Daily snapshots preserve future observations; they cannot recover older data that GitHub no longer exposes.

- **Views and clones:** daily rows are updated by UTC date, never added across overlapping snapshots. Current-day counts may be incomplete.
- **Unique visitors and cloners:** retain daily values and GitHub's window aggregates. You cannot sum these into a deduplicated lifetime unique count.
- **Missing data:** missing days or endpoints remain unknown, not zero.
- **Referrers and pages:** GitHub returns top-10 lists, not every source or page.
- **Stars and forks:** retained records and snapshot counts; removed stars/forks before collection cannot be reconstructed.
- **Commit statistics:** GitHub can return HTTP 202 while computing them. The run preserves all other data, records the pending endpoint, and tries again on the next run. Some large-repository statistics are unavailable.

See [the complete archive format and limitations](docs/data.md).

## Troubleshooting

| Result | What to check |
| --- | --- |
| Public archive rejected | Create a private repository using the template. |
| Configuration error | Set `TARGET_REPOSITORIES` or fill `config.json`; add an Insights secret. |
| HTTP 401 | Token expiration, revocation, or a malformed secret. |
| HTTP 403 | Source access, Administration read permission, organization approval/policy, or API rate limits. |
| HTTP 404 | Repository spelling, private-repository access, or token repository selection. |
| `pending` statistics | GitHub is computing the report; check a later run. No zero is substituted. |
| Git push fails | Archive policies may block the Actions bot. Use a dedicated archive with suitable write policy. |
| No scheduled run | Check Actions is enabled, the workflow is on the default branch, and your GitHub Actions quota. |

Successful responses are committed even if another endpoint fails. Authentication/API failures and stale traffic produce a failing job, visible in Actions. GitHub sends notifications according to your account settings. Hosted Actions usage and private repository storage are subject to your GitHub plan.

If committing or pushing snapshots fails, the workflow attempts to upload a private recovery artifact, retained for 14 days. Download it from the failed run before it expires.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports should include a sanitized manifest and workflow status—not tokens or private metrics. This is an independent project, not an official GitHub product.

## License

MIT. See [LICENSE](LICENSE).
