"""Immutable snapshots and a daily index; overlapping windows never get summed."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def save_json(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if exclusive:
        with path.open("xb") as output:
            output.write(raw)
    else:
        temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
        temporary.write_bytes(raw)
        temporary.replace(path)
    return hashlib.sha256(raw).hexdigest()


def merge_traffic(existing, observations, observed_at):
    """Keep the latest observation for each UTC date and metric independently."""
    merged = {day: dict(values) for day, values in existing.items()}
    for metric, payload in observations.items():
        for value in payload[metric]:
            day = value["timestamp"][:10]
            target = merged.setdefault(day, {})
            if observed_at >= target.get(metric + "_observed_at", ""):
                target[metric] = value["count"]
                target[metric + "_uniques"] = value["uniques"]
                target[metric + "_observed_at"] = observed_at
    return dict(sorted(merged.items()))


def update_index(repository_root, observations, observed_at):
    path = repository_root / "traffic-daily.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    merged = merge_traffic(existing, observations, observed_at)
    save_json(path, merged)
    fields = ["date_utc", "views", "views_uniques", "clones", "clones_uniques",
              "views_observed_at", "clones_observed_at"]
    csv_path = repository_root / "traffic-daily.csv"
    temporary = csv_path.with_name("." + csv_path.name + "." + uuid.uuid4().hex)
    with temporary.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for day, values in merged.items():
            writer.writerow({"date_utc": day, **values})
    temporary.replace(csv_path)


def repository_summary(repository, manifest, saved):
    metadata = saved.get("repository", {})
    result = {
        "repository": repository,
        "observed_at": manifest["completed_at"],
        "status": manifest["status"],
        "snapshot": manifest["snapshot"],
        "stars": metadata.get("stargazers_count"),
        "forks": metadata.get("forks_count"),
        "traffic_window": {},
        "failed": manifest["failed"],
        "pending": manifest["pending"],
        "unavailable": manifest["unavailable"],
        "warnings": manifest["warnings"],
    }
    for metric in ("views", "clones"):
        data = saved.get(metric)
        if data is not None:
            days = [row["timestamp"][:10] for row in data[metric]]
            result["traffic_window"][metric] = {
                "count": data["count"], "uniques": data["uniques"],
                "first_reported_day_utc": min(days) if days else None,
                "last_reported_day_utc": max(days) if days else None,
            }
    return result
