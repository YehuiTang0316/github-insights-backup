import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from insights_backup.api import ENDPOINTS, Endpoint, GitHub, credential_map, normalize_repository
from insights_backup.cli import repositories_from, sync_repository
from insights_backup.storage import merge_traffic, utc_now


def traffic(metric, day="2026-01-01", count=10, uniques=3):
    return {"count": count, "uniques": uniques,
            metric: [{"timestamp": day + "T00:00:00Z", "count": count, "uniques": uniques}]}


class ConfigurationTests(unittest.TestCase):
    def test_invalid_repository_cannot_become_a_path_or_query(self):
        for name in ("../repo", "owner/..", "owner/repo/x", "owner/repo?x=1", "https://github.com/a/b", "a/b\nc/d"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                normalize_repository(name)

    def test_names_are_normalized_and_deduplicated(self):
        self.assertEqual(repositories_from("Owner/Repo, owner/repo\nother/one", "unused"),
                         ["owner/repo", "other/one"])

    def test_empty_config_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"repositories": []}')
            with self.assertRaises(ValueError):
                repositories_from("", config)

    def test_bad_token_json_does_not_echo_secret(self):
        with self.assertRaises(ValueError) as error:
            credential_map({"INSIGHTS_TOKENS_JSON": "secret-value"})
        self.assertNotIn("secret-value", str(error.exception))

    def test_repository_token_overrides_owner_and_default(self):
        with patch.dict(os.environ, {"INSIGHTS_TOKEN": "default"}, clear=True):
            client = GitHub("owner/repo", tokens={"owner": "owner-value", "owner/repo": "repo-value"})
            self.assertEqual(client.environment["GH_TOKEN"], "repo-value")

    def test_actions_cannot_fall_back_to_its_own_github_token(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "workflow-token"}, clear=True):
            with self.assertRaises(ValueError):
                GitHub("owner/repo", tokens={})


class DailyIndexTests(unittest.TestCase):
    def test_overlapping_windows_update_instead_of_add(self):
        first = merge_traffic({}, {"clones": traffic("clones", count=10)}, "2026-01-02T00:00:00Z")
        second = merge_traffic(first, {"clones": traffic("clones", count=12)}, "2026-01-03T00:00:00Z")
        self.assertEqual(second["2026-01-01"]["clones"], 12)
        self.assertEqual(second["2026-01-01"]["clones_uniques"], 3)

    def test_newest_revision_can_reduce_a_count(self):
        first = merge_traffic({}, {"views": traffic("views", count=10)}, "2026-01-02T00:00:00Z")
        revised = merge_traffic(first, {"views": traffic("views", count=8)}, "2026-01-03T00:00:00Z")
        self.assertEqual(revised["2026-01-01"]["views"], 8)

    def test_old_observation_does_not_replace_newer_data(self):
        first = merge_traffic({}, {"views": traffic("views", count=10)}, "2026-01-03T00:00:00Z")
        second = merge_traffic(first, {"views": traffic("views", count=12)}, "2026-01-02T00:00:00Z")
        self.assertEqual(second, first)

    def test_missing_days_and_metrics_are_not_zero_filled(self):
        first = merge_traffic({}, {"clones": traffic("clones")}, "2026-01-02T00:00:00Z")
        second = merge_traffic(first, {"views": traffic("views", day="2026-01-03")}, "2026-01-04T00:00:00Z")
        self.assertNotIn("2026-01-02", second)
        self.assertNotIn("views", second["2026-01-01"])
        self.assertNotIn("clones", second["2026-01-03"])
        self.assertNotIn("total_uniques", second)


class APITests(unittest.TestCase):
    def client(self, replies):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            return replies.pop(0)
        client = GitHub("owner/repo", tokens={"owner": "example-secret"}, runner=runner, sleep=lambda _: None)
        return client, calls

    def response(self, code, body, returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, "HTTP/2.0 %s Status\n\n%s" % (code, json.dumps(body)), stderr)

    def test_pending_statistics_do_not_masquerade_as_empty_data(self):
        client, calls = self.client([self.response(202, {}) for _ in range(3)])
        record, data = client.fetch(Endpoint("code_frequency", "/stats/code_frequency", statistics=True))
        self.assertEqual(record["status"], "pending")
        self.assertIsNone(data)
        self.assertEqual(len(calls), 3)

    def test_recovered_request_drops_old_error(self):
        client, _ = self.client([self.response(202, {}), self.response(200, [])])
        record, data = client.fetch(Endpoint("contributors", "/stats/contributors", statistics=True))
        self.assertEqual(record["status"], "saved")
        self.assertNotIn("error", record)
        self.assertEqual(data, [])

    def test_unsupported_community_profile_is_an_explicit_gap(self):
        client, _ = self.client([self.response(404, {}, 1, "HTTP 404")])
        record, data = client.fetch(Endpoint("community_profile", "/community/profile"))
        self.assertEqual(record["status"], "unavailable")
        self.assertIsNone(data)

    def test_403_is_failure_without_retry_or_secret_in_error(self):
        client, calls = self.client([self.response(403, {}, 1, "HTTP 403 example-secret")])
        record, _ = client.fetch(Endpoint("clones", "/traffic/clones"))
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("example-secret", json.dumps(record))
        self.assertEqual(len(calls), 1)

    def test_pagination_preserves_every_page(self):
        reply = subprocess.CompletedProcess([], 0, '[[{"id":1}],[{"id":2}]]', "")
        client, calls = self.client([reply])
        record, data = client.fetch(Endpoint("forks", "/forks", paginated=True))
        self.assertEqual(record["items"], 2)
        self.assertEqual(data[1][0]["id"], 2)
        self.assertIn("--paginate", calls[0])

    def test_non_paginated_shape_is_rejected(self):
        replies = [subprocess.CompletedProcess([], 0, '[{"id":1}]', "") for _ in range(3)]
        client, _ = self.client(replies)
        record, _ = client.fetch(Endpoint("forks", "/forks", paginated=True))
        self.assertEqual(record["status"], "failed")

    def test_invalid_traffic_payload_is_not_saved(self):
        for data in ({}, {"count": 2, "uniques": 1, "clones": [{"timestamp": "bad", "count": 2, "uniques": 1}]}):
            client, _ = self.client([self.response(200, data) for _ in range(3)])
            record, _ = client.fetch(Endpoint("clones", "/traffic/clones"))
            self.assertEqual(record["status"], "failed")


class ArchiveTests(unittest.TestCase):
    def test_partial_backup_preserves_success_and_missing_is_not_zero(self):
        class FakeAPI:
            def __init__(self, *args, **kwargs):
                pass
            def fetch(self, endpoint):
                if endpoint.name == "clones":
                    return {"status": "failed", "http_status": 403}, None
                if endpoint.name == "repository":
                    return {"status": "saved"}, {"full_name": "owner/repo", "stargazers_count": 2, "forks_count": 1}
                if endpoint.name == "views":
                    return {"status": "saved"}, traffic("views", day=utc_now()[:10])
                return {"status": "saved"}, []
        with tempfile.TemporaryDirectory() as directory:
            first = sync_repository("owner/repo", directory, tokens={}, api_factory=FakeAPI)
            root = Path(directory) / "owner/repo"
            snapshot = root / first["snapshot"]
            original_manifest = (snapshot / "manifest.json").read_bytes()
            self.assertEqual(first["status"], "partial")
            self.assertNotIn("clones", first["traffic_window"])
            self.assertFalse((snapshot / "clones.json").exists())
            self.assertFalse((root / "latest-complete.json").exists())
            index = json.loads((root / "traffic-daily.json").read_text())
            self.assertNotIn("clones", next(iter(index.values())))
            second = sync_repository("owner/repo", directory, tokens={}, api_factory=FakeAPI)
            self.assertNotEqual(first["snapshot"], second["snapshot"])
            self.assertEqual((snapshot / "manifest.json").read_bytes(), original_manifest)
            manifest = json.loads(original_manifest)
            for record in manifest["endpoints"].values():
                if record["status"] == "saved":
                    self.assertEqual(hashlib.sha256((snapshot / record["file"]).read_bytes()).hexdigest(), record["sha256"])


if __name__ == "__main__":
    unittest.main()
