"""CLI for local use and GitHub Actions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from .api import ENDPOINTS, GitHub, credential_map, normalize_repository
from .storage import repository_summary, save_json, update_index, utc_now


def repositories_from(raw, config_path):
    if raw and raw.strip():
        items = re.split(r"[\s,]+", raw.strip())
    else:
        try:
            document = json.loads(Path(config_path).read_text())
            items = document["repositories"]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("Set TARGET_REPOSITORIES or add repositories to config.json") from None
    if not isinstance(items, list) or not items:
        raise ValueError("Configure at least one repository using owner/repository")
    return list(dict.fromkeys(normalize_repository(item) for item in items))


def sync_repository(repository, output, tokens=None, api_factory=GitHub):
    api = api_factory(repository, tokens=tokens)
    root = Path(output) / repository
    started = utc_now()
    snapshot = Path("snapshots") / started[:10] / (started[11:26].replace(":", "") + "-" + uuid.uuid4().hex[:8])
    directory = root / snapshot
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1, "repository": repository, "started_at": started,
        "snapshot": str(snapshot), "status": "running", "traffic_timezone": "UTC",
        "methodology": [
            "Traffic snapshots cover overlapping rolling 14-day windows; do not add window totals.",
            "Daily index keeps the latest observation for each UTC date and metric.",
            "Missing dates/metrics are unknown, not zero. Current UTC day may be incomplete.",
            "Unique visitors/cloners cannot be added across dates or overlapping windows.",
            "Referrers and paths are top-10 windows, not a complete history.",
            "Paginated responses are stored as arrays of pages. Stars/forks list retained records.",
        ],
    }
    save_json(directory / "started.json", manifest, exclusive=True)
    records, saved = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(api.fetch, ENDPOINTS))
    for endpoint, (record, payload) in zip(ENDPOINTS, responses):
        record["observed_at"] = utc_now()
        if record["status"] == "saved":
            record["file"] = endpoint.name + ".json"
            record["sha256"] = save_json(directory / record["file"], payload, exclusive=True)
            saved[endpoint.name] = payload
        records[endpoint.name] = record
    manifest["endpoints"] = records
    for state, key in (("failed", "failed"), ("pending", "pending"), ("unavailable", "unavailable")):
        manifest[key] = [name for name, record in records.items() if record["status"] == state]
    warnings = []
    for metric in ("views", "clones"):
        days = saved.get(metric, {}).get(metric, [])
        if days:
            latest = datetime.fromisoformat(max(row["timestamp"] for row in days).replace("Z", "+00:00"))
            if latest.date() < (datetime.now(timezone.utc) - timedelta(days=2)).date():
                warnings.append(metric + ": data is over two UTC days behind")
    manifest["warnings"] = warnings
    manifest["completed_at"] = utc_now()
    manifest["status"] = ("partial" if manifest["failed"] or warnings else
                          "saved_with_gaps" if manifest["pending"] or manifest["unavailable"]
                          else "complete")
    save_json(directory / "manifest.json", manifest, exclusive=True)
    observations = {metric: saved[metric] for metric in ("views", "clones") if metric in saved}
    update_index(root, observations, manifest["completed_at"])
    summary = repository_summary(repository, manifest, saved)
    save_json(root / "latest.json", summary)
    if manifest["status"] == "complete":
        save_json(root / "latest-complete.json", {"snapshot": str(snapshot), "completed_at": manifest["completed_at"]})
    return summary


def write_report(results, output):
    lines = ["# GitHub Insights backup", "", "| Repository | Result | Stars | Forks |", "| --- | --- | ---: | ---: |"]
    for result in results:
        lines.append("| {repository} | {status} | {stars} | {forks} |".format(
            **{**result, "stars": result.get("stars") if result.get("stars") is not None else "—",
               "forks": result.get("forks") if result.get("forks") is not None else "—"}))
    for result in results:
        details = []
        for key in ("failed", "pending", "unavailable", "warnings"):
            if result.get(key):
                details.append(key + ": " + ", ".join(result[key]))
        if result.get("error"):
            details.append(result["error"])
        if details:
            lines.extend(["", "- **" + result["repository"] + "** — " + "; ".join(details)])
    lines.extend(["", "Traffic totals cover overlapping 14-day windows. Do not sum unique counts across dates.", ""])
    report = "\n".join(lines)
    Path(output).mkdir(parents=True, exist_ok=True)
    (Path(output) / "README.md").write_text(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Archive GitHub Insights for one or more authorized repositories.")
    parser.add_argument("--repositories", help="Comma/space-separated owner/repository names; overrides config")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="data")
    parser.add_argument("--check", action="store_true", help="Validate configuration without API calls or writes")
    arguments = parser.parse_args(argv)
    os.umask(0o077)
    try:
        repositories = repositories_from(arguments.repositories or os.environ.get("TARGET_REPOSITORIES"), arguments.config)
        tokens = credential_map()
        if not shutil.which("gh"):
            raise ValueError("Install GitHub CLI (gh) first: https://cli.github.com/")
        for repository in repositories:
            GitHub(repository, tokens=tokens)
    except ValueError as error:
        print("Configuration error: " + str(error), file=sys.stderr)
        return 2
    if arguments.check:
        print(json.dumps({"repositories": repositories, "output": arguments.output}))
        return 0
    results = []
    for repository in repositories:
        try:
            result = sync_repository(repository, arguments.output, tokens=tokens)
        except (OSError, ValueError):
            result = {"repository": repository, "status": "failed",
                      "error": "Could not write or read archive files; check output directory and existing JSON"}
        results.append(result)
        print(json.dumps(result), flush=True)
    write_report(results, arguments.output)
    return 1 if any(result["status"] in ("failed", "partial") for result in results) else 0
