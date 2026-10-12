"""Read-only GitHub API access via gh; credentials never enter archive files."""

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Endpoint:
    name: str
    path: str
    paginated: bool = False
    statistics: bool = False


ENDPOINTS = (
    Endpoint("repository", ""),
    Endpoint("views", "/traffic/views?per=day"),
    Endpoint("clones", "/traffic/clones?per=day"),
    Endpoint("referrers", "/traffic/popular/referrers"),
    Endpoint("paths", "/traffic/popular/paths"),
    Endpoint("stargazers", "/stargazers?per_page=100", True),
    Endpoint("forks", "/forks?per_page=100&sort=oldest", True),
    Endpoint("contributors", "/stats/contributors", statistics=True),
    Endpoint("commit_activity", "/stats/commit_activity", statistics=True),
    Endpoint("code_frequency", "/stats/code_frequency", statistics=True),
    Endpoint("participation", "/stats/participation", statistics=True),
    Endpoint("punch_card", "/stats/punch_card", statistics=True),
    Endpoint("releases", "/releases?per_page=100", True),
    Endpoint("community_profile", "/community/profile"),
    Endpoint("languages", "/languages"),
)


def normalize_repository(value):
    if not isinstance(value, str):
        raise ValueError("Each repository must be an owner/repository string")
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+", value):
        raise ValueError("Use owner/repository, without a URL, query string, or path")
    if value.split("/")[1] in (".", ".."):
        raise ValueError("Invalid repository name")
    return value.lower()


def credential_map(environ=None):
    environ = os.environ if environ is None else environ
    try:
        values = json.loads(environ.get("INSIGHTS_TOKENS_JSON") or "{}")
    except ValueError:
        raise ValueError("INSIGHTS_TOKENS_JSON must be a JSON object") from None
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v.strip()
        for k, v in values.items()
    ):
        raise ValueError("INSIGHTS_TOKENS_JSON must map owners or repositories to tokens")
    return {k.lower(): v.strip() for k, v in values.items()}


class GitHub:
    def __init__(self, repository, tokens=None, runner=subprocess.run, sleep=time.sleep):
        self.repository = normalize_repository(repository)
        tokens = credential_map() if tokens is None else tokens
        self.environment = dict(os.environ)
        token = (tokens.get(self.repository) or tokens.get(self.repository.split("/")[0])
                 or os.environ.get("INSIGHTS_TOKEN"))
        if token:
            self.environment["GH_TOKEN"] = token
        elif os.environ.get("GITHUB_ACTIONS") == "true":
            raise ValueError("Configure INSIGHTS_TOKEN or INSIGHTS_TOKENS_JSON in Actions secrets")
        self.runner = runner
        self.sleep = sleep

    def fetch(self, endpoint):
        path = "repos/" + self.repository + endpoint.path
        accept = ("application/vnd.github.star+json" if endpoint.name == "stargazers"
                  else "application/vnd.github+json")
        command = ["gh", "api", "--hostname", "github.com", "--method", "GET",
                   "-H", "Accept: " + accept]
        command += ["--paginate", "--slurp"] if endpoint.paginated else ["--include"]
        command.append(path)
        record = {"endpoint": "https://api.github.com/" + path,
                  "format": "array_of_pages" if endpoint.paginated else "response_body"}
        data = None
        for attempt in range(1, 4):
            code: Optional[int] = None
            record["attempts"] = attempt
            try:
                response = self.runner(command, capture_output=True, text=True,
                                       timeout=120, env=self.environment)
                raw = response.stdout.replace("\r\n", "\n")
                if endpoint.paginated:
                    code = 200 if response.returncode == 0 else None
                    body = raw
                else:
                    headers, separator, body = raw.partition("\n\n")
                    match = re.match(r"HTTP/\S+\s+(\d+)", headers)
                    code = int(match.group(1)) if match else None
                    if not separator:
                        body = raw
                if response.returncode != 0:
                    # Do not log raw stderr: a credential helper may print secrets.
                    match = re.search(r"HTTP (\d{3})", response.stderr)
                    code = code or (int(match.group(1)) if match else None)
                    raise RuntimeError("GitHub request failed" + (" (HTTP %s)" % code if code else ""))
                if code == 202:
                    raise RuntimeError("GitHub is generating statistics (HTTP 202)")
                if code not in (200, 204):
                    raise RuntimeError("Unexpected HTTP status: %s" % code)
                data = json.loads(body) if body.strip() else None
                self.validate(endpoint, data)
                record.update(status="saved", http_status=code)
                record.pop("error", None)
                if endpoint.paginated:
                    record["items"] = sum(len(page) for page in data)
                return record, data
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                record["http_status"] = code
                record["error"] = (str(error) if isinstance(error, RuntimeError)
                                   else "Invalid response, missing gh, or request timed out")
                if code in (401, 403, 404, 422) or attempt == 3:
                    break
                self.sleep(3 if attempt == 1 else 10)
        if endpoint.statistics and code == 202:
            record["status"] = "pending"
        elif endpoint.name == "code_frequency" and code == 422:
            record["status"] = "unavailable"
            record["error"] = "GitHub does not provide code frequency for repositories with 10,000+ commits"
        elif endpoint.name == "community_profile" and code == 404:
            record["status"] = "unavailable"
            record["error"] = "Community profile unavailable; GitHub excludes forks and may limit this endpoint"
        else:
            record["status"] = "failed"
        return record, None

    @staticmethod
    def validate(endpoint, data):
        if endpoint.paginated:
            if not isinstance(data, list) or not all(isinstance(page, list) for page in data):
                raise ValueError("Incomplete pagination")
        if endpoint.name == "repository":
            if not isinstance(data, dict) or "full_name" not in data:
                raise ValueError("Invalid repository response")
        if endpoint.name in ("views", "clones"):
            metric = endpoint.name
            if not isinstance(data, dict) or not isinstance(data.get(metric), list):
                raise ValueError("Invalid traffic response")
            for key in ("count", "uniques"):
                if type(data.get(key)) is not int or data[key] < 0:
                    raise ValueError("Invalid traffic count")
            for row in data[metric]:
                if (not isinstance(row, dict)
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00Z", str(row.get("timestamp")))
                    or any(type(row.get(k)) is not int or row[k] < 0 for k in ("count", "uniques"))):
                    raise ValueError("Invalid daily traffic row")
