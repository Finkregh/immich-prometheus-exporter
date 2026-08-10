#!/usr/bin/env python3
"""Unit tests for Immich Prometheus Exporter

Tests the main functionality using mocked HTTP responses.
"""

import os

# Import the modules we want to test
import sys
from unittest import mock

import pytest
import requests
import responses
from typer.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import immich_prometheus_exporter.main as immich_prometheus_exporter

# Import the classes and app from the loaded module
ImmichAPI = immich_prometheus_exporter.ImmichAPI
PrometheusExporter = immich_prometheus_exporter.PrometheusExporter
ImmichCollector = immich_prometheus_exporter.ImmichCollector
app = immich_prometheus_exporter.app


# Shared fixture used by API, collector, and exporter tests for the /api/jobs
# endpoint. Covers three shapes:
#   * metadataExtraction: all six counts non-zero, active queue, not paused.
#   * smartSearch: paused queue with only failed>0, inactive.
#   * thumbnailGeneration: missing 'waiting' key to exercise the default-to-0 path.
MOCK_JOBS_RESPONSE = {
    "metadataExtraction": {
        "jobCounts": {
            "active": 2,
            "waiting": 5,
            "completed": 100,
            "failed": 1,
            "delayed": 3,
            "paused": 0,
        },
        "queueStatus": {"isActive": True, "isPaused": False},
    },
    "smartSearch": {
        "jobCounts": {
            "active": 0,
            "waiting": 0,
            "completed": 0,
            "failed": 7,
            "delayed": 0,
            "paused": 0,
        },
        "queueStatus": {"isActive": False, "isPaused": True},
    },
    "thumbnailGeneration": {
        "jobCounts": {
            "active": 1,
            # 'waiting' intentionally omitted to test default-to-0.
            "completed": 50,
            "failed": 0,
            "delayed": 0,
            "paused": 0,
        },
        "queueStatus": {"isActive": True, "isPaused": False},
    },
}


# Shared fixture used by server-statistics tests. Includes Alice (u1) with
# non-zero counts, Bob (u2) with all-zero counts, and no entry for Carol (u3)
# to exercise the "user in /admin/users but missing from usageByUser" path.
MOCK_SERVER_STATISTICS = {
    "photos": 12345,
    "videos": 678,
    "usage": 987_654_321,
    "usagePhotos": 800_000_000,
    "usageVideos": 187_654_321,
    "usageByUser": [
        {
            "userId": "u1",
            "userName": "Alice",
            "photos": 100,
            "videos": 5,
            "usage": 12_345_678,
            "usagePhotos": 12_000_000,
            "usageVideos": 345_678,
            "quotaSizeInBytes": 50_000_000_000,
        },
        {
            "userId": "u2",
            "userName": "Bob",
            "photos": 0,
            "videos": 0,
            "usage": 0,
            "usagePhotos": 0,
            "usageVideos": 0,
            "quotaSizeInBytes": 0,
        },
    ],
}


MOCK_MAINTENANCE_ACTIVE = {
    "active": True,
    "progress": 42,
    "action": "restore_database",
    "task": "restoring users table",
}


MOCK_MAINTENANCE_IDLE = {
    "active": False,
    "progress": 0,
    "action": "end",
    "task": "",
}


MOCK_PING_OK = {"res": "pong"}


# Extended admin/users fixture: Alice is an admin with an active status, Bob
# is a regular active user, Carol is being removed and has a non-null
# deletedAt.
MOCK_ADMIN_USERS_EXTENDED = [
    {
        "id": "u1",
        "name": "Alice",
        "email": "alice@example.com",
        "quotaSizeInBytes": 50_000_000_000,
        "quotaUsageInBytes": 12_345_678,
        "isAdmin": True,
        "status": "active",
        "deletedAt": None,
    },
    {
        "id": "u2",
        "name": "Bob",
        "email": "bob@example.com",
        "quotaSizeInBytes": None,
        "quotaUsageInBytes": None,
        "isAdmin": False,
        "status": "active",
        "deletedAt": None,
    },
    {
        "id": "u3",
        "name": "Carol",
        "email": "carol@example.com",
        "quotaSizeInBytes": None,
        "quotaUsageInBytes": None,
        "isAdmin": False,
        "status": "removing",
        "deletedAt": "2024-06-01T00:00:00.000Z",
    },
]


def _register_stub_immich_endpoints() -> None:
    """Register mock responses for endpoints the collector calls but the test
    does not care about (albums, libraries, storage, jobs, ping, maintenance).
    Uses zero-payload responses so a full ``collect()`` succeeds without
    surfacing errors from unrelated collectors.
    """
    responses.add(
        responses.GET,
        "http://localhost:2283/api/albums/statistics",
        json={"owned": 0, "shared": 0, "notShared": 0},
        status=200,
    )
    responses.add(
        responses.GET,
        "http://localhost:2283/api/libraries",
        json=[],
        status=200,
    )
    responses.add(
        responses.GET,
        "http://localhost:2283/api/server/storage",
        json={
            "diskSizeRaw": 0,
            "diskUseRaw": 0,
            "diskAvailableRaw": 0,
            "diskUsagePercentage": 0,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "http://localhost:2283/api/jobs",
        json={},
        status=200,
    )
    responses.add(
        responses.GET,
        "http://localhost:2283/api/server/ping",
        json=MOCK_PING_OK,
        status=200,
    )
    responses.add(
        responses.GET,
        "http://localhost:2283/api/admin/maintenance/status",
        json=MOCK_MAINTENANCE_IDLE,
        status=200,
    )


class TestImmichAPI:
    """Test the ImmichAPI class"""

    def setup_method(self) -> None:
        """Set up test fixtures"""
        self.api = ImmichAPI("http://localhost:2283", "test-api-key")

    @responses.activate
    def test_get_all_users(self) -> None:
        """Test getting all users"""
        mock_users = [
            {
                "id": "user1",
                "name": "John Doe",
                "email": "john@example.com",
                "quotaSizeInBytes": 1000000000,
                "quotaUsageInBytes": 500000000,
            },
            {
                "id": "user2",
                "name": "Jane Smith",
                "email": "jane@example.com",
                "quotaSizeInBytes": None,
                "quotaUsageInBytes": None,
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=mock_users,
            status=200,
        )

        users = self.api.get_all_users()
        assert len(users) == 2
        assert users[0]["name"] == "John Doe"
        assert users[1]["name"] == "Jane Smith"

    @responses.activate
    def test_get_album_statistics(self) -> None:
        """Test getting album statistics"""
        mock_stats = {
            "owned": 15,
            "shared": 5,
            "notShared": 10,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json=mock_stats,
            status=200,
        )

        stats = self.api.get_album_statistics()
        assert stats["owned"] == 15
        assert stats["shared"] == 5
        assert stats["notShared"] == 10

    @responses.activate
    def test_get_all_libraries(self) -> None:
        """Test getting all libraries"""
        mock_libraries = [
            {
                "id": "lib1",
                "name": "Photos Library",
                "ownerId": "user1",
            },
            {
                "id": "lib2",
                "name": "Videos Library",
                "ownerId": "user2",
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=mock_libraries,
            status=200,
        )

        libraries = self.api.get_all_libraries()
        assert len(libraries) == 2
        assert libraries[0]["name"] == "Photos Library"
        assert libraries[1]["name"] == "Videos Library"

    @responses.activate
    def test_get_library_statistics(self) -> None:
        """Test getting library statistics"""
        mock_stats = {
            "total": 5000,
            "photos": 4000,
            "videos": 1000,
            "usage": 50000000000,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries/lib1/statistics",
            json=mock_stats,
            status=200,
        )

        stats = self.api.get_library_statistics("lib1")
        assert stats["total"] == 5000
        assert stats["photos"] == 4000
        assert stats["videos"] == 1000
        assert stats["usage"] == 50000000000

    @responses.activate
    def test_get_storage(self) -> None:
        """Test getting storage information"""
        mock_storage = {
            "diskSizeRaw": 1000000000000,
            "diskUseRaw": 600000000000,
            "diskAvailableRaw": 400000000000,
            "diskUsagePercentage": 60.0,
            "diskSize": "1.0 TB",
            "diskUse": "600 GB",
            "diskAvailable": "400 GB",
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json=mock_storage,
            status=200,
        )

        storage = self.api.get_storage()
        assert storage["diskSizeRaw"] == 1000000000000
        assert storage["diskUseRaw"] == 600000000000
        assert storage["diskUsagePercentage"] == 60.0

    @responses.activate
    def test_api_error_handling(self) -> None:
        """Test API error handling"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json={"error": "Unauthorized"},
            status=401,
        )

        with pytest.raises(Exception):
            self.api.get_all_users()

    @responses.activate
    def test_invalid_json_response(self) -> None:
        """Test handling of invalid JSON responses"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            body="invalid json",
            status=200,
        )

        with pytest.raises(Exception):
            self.api.get_all_users()

    @responses.activate
    def test_non_list_response_for_users(self) -> None:
        """Test handling when users endpoint returns non-list"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json={"error": "Not a list"},
            status=200,
        )

        users = self.api.get_all_users()
        assert users == []

    @responses.activate
    def test_get_all_jobs_status(self) -> None:
        """Test getting all job queue status"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json=MOCK_JOBS_RESPONSE,
            status=200,
        )

        jobs = self.api.get_all_jobs_status()
        assert jobs == MOCK_JOBS_RESPONSE
        assert "metadataExtraction" in jobs
        assert "smartSearch" in jobs
        assert jobs["smartSearch"]["jobCounts"]["failed"] == 7
        assert jobs["smartSearch"]["queueStatus"]["isPaused"] is True

    @responses.activate
    def test_get_all_jobs_status_non_dict_response(self) -> None:
        """Test handling when jobs endpoint returns non-dict"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json=[],
            status=200,
        )

        jobs = self.api.get_all_jobs_status()
        assert jobs == {}

    @responses.activate
    def test_get_server_statistics(self) -> None:
        """Test getting instance-wide server statistics"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )

        stats = self.api.get_server_statistics()
        assert stats["photos"] == 12345
        assert stats["videos"] == 678
        assert isinstance(stats["usageByUser"], list)
        assert len(stats["usageByUser"]) == 2

    @responses.activate
    def test_get_server_statistics_non_dict_response(self) -> None:
        """Test handling when server statistics endpoint returns non-dict"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=[],
            status=200,
        )

        assert self.api.get_server_statistics() == {}

    @responses.activate
    def test_ping_ok(self) -> None:
        """Test the ping probe with a valid pong response"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json=MOCK_PING_OK,
            status=200,
        )

        assert self.api.ping() is True

    @responses.activate
    def test_ping_wrong_body(self) -> None:
        """Test the ping probe with a non-pong body returns False"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json={"res": "not-pong"},
            status=200,
        )

        assert self.api.ping() is False

    @responses.activate
    def test_ping_http_error(self) -> None:
        """Test the ping probe with an HTTP 500 returns False without raising"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json={"error": "boom"},
            status=500,
        )

        assert self.api.ping() is False

    @responses.activate
    def test_ping_network_error(self) -> None:
        """Test the ping probe with a network error returns False"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            body=requests.exceptions.ConnectionError("boom"),
        )

        assert self.api.ping() is False

    @responses.activate
    def test_get_maintenance_status(self) -> None:
        """Test getting maintenance status"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=MOCK_MAINTENANCE_ACTIVE,
            status=200,
        )

        status = self.api.get_maintenance_status()
        assert status["active"] is True
        assert status["progress"] == 42
        assert status["action"] == "restore_database"
        assert status["task"] == "restoring users table"

    @responses.activate
    def test_get_maintenance_status_non_dict_response(self) -> None:
        """Test handling when maintenance endpoint returns non-dict"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=[],
            status=200,
        )

        assert self.api.get_maintenance_status() == {}


class TestPrometheusExporter:
    """Test the PrometheusExporter class"""

    def setup_method(self) -> None:
        """Set up test fixtures"""
        self.api = ImmichAPI("http://localhost:2283", "test-api-key")
        self.exporter = PrometheusExporter(self.api)

    def test_add_metric_without_labels(self) -> None:
        """Test adding a metric without labels"""
        self.exporter._add_metric("test_metric", 42.0, help_text="Test metric")

        metrics = self.exporter.export_metrics()
        assert "# HELP test_metric Test metric" in metrics
        assert "# TYPE test_metric gauge" in metrics
        assert "test_metric 42.0" in metrics

    def test_add_metric_with_labels(self) -> None:
        """Test adding a metric with labels"""
        labels = {"user": "john", "type": "images"}
        self.exporter._add_metric(
            "test_metric",
            100.0,
            labels,
            "Test metric with labels",
        )

        metrics = self.exporter.export_metrics()
        assert "# HELP test_metric Test metric with labels" in metrics
        assert "# TYPE test_metric gauge" in metrics
        assert 'test_metric{user="john",type="images"} 100.0' in metrics

    @responses.activate
    def test_collect_user_metrics(self) -> None:
        """Test collecting user metrics

        Verifies the refactored user-metric flow: per-user counts come from
        /server/statistics.usageByUser, admin/status/deleted come from
        /admin/users, and no per-user /admin/users/{id}/statistics calls are
        made. Also guards the schema break (removed metrics, dropped
        user_email label).
        """
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=MOCK_ADMIN_USERS_EXTENDED,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )

        self.exporter.collect_user_metrics()
        metrics = self.exporter.export_metrics()

        # New metric names present.
        assert "immich_user_photos" in metrics
        assert "immich_user_videos" in metrics
        assert "immich_user_usage_bytes" in metrics
        assert "immich_user_usage_photos_bytes" in metrics
        assert "immich_user_usage_videos_bytes" in metrics
        assert "immich_user_quota_bytes" in metrics
        assert "immich_user_quota_usage_bytes" in metrics
        assert "immich_user_admin" in metrics
        assert "immich_user_status" in metrics
        assert "immich_user_deleted" in metrics

        # Legacy metric names must be gone.
        assert "immich_user_total_assets" not in metrics
        assert "immich_user_images_count" not in metrics
        assert "immich_user_videos_count" not in metrics

        # user_email label must be gone from every immich_user_* sample.
        for line in metrics.splitlines():
            if line.startswith("immich_user_"):
                assert "user_email=" not in line, line

        # Alice's values were sourced from /server/statistics.
        assert 'user_name="Alice"' in metrics
        assert 'immich_user_photos{user_id="u1",user_name="Alice"} 100' in metrics
        assert 'immich_user_admin{user_id="u1",user_name="Alice"} 1' in metrics
        # Carol is missing from usageByUser but still emits zero samples for
        # every per-user metric, and is flagged as deleted / removing.
        assert 'immich_user_photos{user_id="u3",user_name="Carol"} 0' in metrics
        assert 'immich_user_deleted{user_id="u3",user_name="Carol"} 1' in metrics
        assert (
            'immich_user_status{user_id="u3",user_name="Carol",status="removing"} 1'
            in metrics
        )

        # No requests should have been made to /admin/users/{id}/statistics.
        for call in responses.calls:
            assert "/admin/users/" not in call.request.url.split("/api")[-1] or (
                call.request.url.endswith("/api/admin/users")
            ), call.request.url

    @responses.activate
    def test_collect_album_metrics(self) -> None:
        """Test collecting album metrics"""
        mock_stats = {
            "owned": 15,
            "shared": 5,
            "notShared": 10,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json=mock_stats,
            status=200,
        )

        self.exporter.collect_album_metrics()
        metrics = self.exporter.export_metrics()

        assert "immich_albums_owned_total 15" in metrics
        assert "immich_albums_shared_total 5" in metrics
        assert "immich_albums_not_shared_total 10" in metrics

    @responses.activate
    def test_collect_library_metrics(self) -> None:
        """Test collecting library metrics"""
        # Mock libraries response
        mock_libraries = [
            {
                "id": "lib1",
                "name": "Photos Library",
                "ownerId": "user1",
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=mock_libraries,
            status=200,
        )

        # Mock library statistics response
        mock_stats = {
            "total": 5000,
            "photos": 4000,
            "videos": 1000,
            "usage": 50000000000,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries/lib1/statistics",
            json=mock_stats,
            status=200,
        )

        self.exporter.collect_library_metrics()
        metrics = self.exporter.export_metrics()

        assert "immich_library_total_assets" in metrics
        assert "immich_library_photos_count" in metrics
        assert "immich_library_videos_count" in metrics
        assert "immich_library_usage_bytes" in metrics
        assert 'library_name="Photos Library"' in metrics

    @responses.activate
    def test_collect_storage_metrics(self) -> None:
        """Test collecting storage metrics"""
        mock_storage = {
            "diskSizeRaw": 1000000000000,
            "diskUseRaw": 600000000000,
            "diskAvailableRaw": 400000000000,
            "diskUsagePercentage": 60.0,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json=mock_storage,
            status=200,
        )

        self.exporter.collect_storage_metrics()
        metrics = self.exporter.export_metrics()

        assert "immich_storage_disk_size_bytes 1000000000000" in metrics
        assert "immich_storage_disk_use_bytes 600000000000" in metrics
        assert "immich_storage_disk_available_bytes 400000000000" in metrics
        assert "immich_storage_disk_usage_percentage 60.0" in metrics

    @responses.activate
    def test_error_handling_in_collection(self):
        """Test error handling during metric collection"""
        # Mock a failing API call
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json={"error": "Server error"},
            status=500,
        )

        # Should not raise exception, but handle gracefully
        self.exporter.collect_user_metrics()
        # Metrics should be empty or contain only error-safe metrics
        metrics = self.exporter.export_metrics()
        # Should not contain user metrics due to error
        assert "immich_user_total_assets" not in metrics

    @responses.activate
    def test_collect_job_metrics(self):
        """Test collecting job metrics via legacy text exporter"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json=MOCK_JOBS_RESPONSE,
            status=200,
        )

        self.exporter.collect_job_metrics()
        output = self.exporter.export_metrics()

        # HELP and TYPE lines for each of the three metrics.
        assert "# HELP immich_job_queue_count " in output
        assert "# TYPE immich_job_queue_count gauge" in output
        assert "# HELP immich_job_queue_active " in output
        assert "# TYPE immich_job_queue_active gauge" in output
        assert "# HELP immich_job_queue_paused " in output
        assert "# TYPE immich_job_queue_paused gauge" in output

        # Exactly one HELP/TYPE pair per metric name (regression guard).
        for metric_name in (
            "immich_job_queue_count",
            "immich_job_queue_active",
            "immich_job_queue_paused",
        ):
            assert output.count(f"# HELP {metric_name} ") == 1
            assert output.count(f"# TYPE {metric_name} ") == 1

        # Concrete sample lines from the fixture.
        assert (
            'immich_job_queue_count{queue="metadataExtraction",state="failed"} 1'
            in output
        )
        assert 'immich_job_queue_count{queue="smartSearch",state="failed"} 7' in output
        assert (
            'immich_job_queue_count{queue="thumbnailGeneration",state="waiting"} 0'
            in output
        )
        assert 'immich_job_queue_active{queue="smartSearch"} 0' in output
        assert 'immich_job_queue_paused{queue="smartSearch"} 1' in output


class TestImmichCollector:
    """Test the ImmichCollector class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.api = ImmichAPI("http://localhost:2283", "test-api-key")
        self.collector = ImmichCollector(self.api)

    @responses.activate
    def test_collect_timestamp_metric(self):
        """Test that collector generates timestamp metric"""
        # Mock minimal API responses to avoid errors
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json={},
            status=200,
        )
        _register_stub_immich_endpoints()

        metrics = list(self.collector.collect())

        # Should have at least the timestamp metric
        assert len(metrics) > 0

        # First metric should be timestamp
        timestamp_metric = metrics[0]
        assert timestamp_metric.name == "immich_exporter_last_scrape_timestamp_ms"
        assert timestamp_metric.documentation == "Timestamp of last successful scrape"

        # immich_up must be second (right after timestamp) and always emit.
        assert metrics[1].name == "immich_up"

    @responses.activate
    def test_collect_user_metrics(self):
        """Test collecting user metrics via collector.

        Verifies the refactored user-metric flow: per-user counts come from
        /server/statistics.usageByUser, admin/status/deleted come from
        /admin/users, and no per-user /admin/users/{id}/statistics calls are
        made. Also guards the schema break.
        """
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=MOCK_ADMIN_USERS_EXTENDED,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )
        _register_stub_immich_endpoints()

        # Regression guard: no per-user /admin/users/{id}/statistics calls
        # must be made. The URL is not registered with `responses`, so any
        # actual call would raise ConnectionError; we additionally inspect
        # `responses.calls` to make the invariant explicit.
        metrics = list(self.collector.collect())
        assert not any(
            "/admin/users/" in call.request.url
            and call.request.url.endswith("/statistics")
            for call in responses.calls
        )

        # Extract families whose name starts with immich_user_.
        user_metrics = {m.name: m for m in metrics if m.name.startswith("immich_user_")}

        # New metric families present.
        for name in (
            "immich_user_photos",
            "immich_user_videos",
            "immich_user_usage_bytes",
            "immich_user_usage_photos_bytes",
            "immich_user_usage_videos_bytes",
            "immich_user_quota_bytes",
            "immich_user_quota_usage_bytes",
            "immich_user_admin",
            "immich_user_status",
            "immich_user_deleted",
        ):
            assert name in user_metrics, f"missing {name}"

        # Legacy metric families must be gone.
        assert "immich_user_total_assets" not in user_metrics
        assert "immich_user_images_count" not in user_metrics
        assert "immich_user_videos_count" not in user_metrics

        # No sample anywhere carries a user_email label.
        for family in user_metrics.values():
            for sample in family.samples:
                assert "user_email" not in sample.labels, sample

        def sample_value(family_name, **labels):
            for sample in user_metrics[family_name].samples:
                if all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
            return None

        # Alice: sourced from /server/statistics.
        assert sample_value("immich_user_photos", user_id="u1") == 100
        assert sample_value("immich_user_videos", user_id="u1") == 5
        assert sample_value("immich_user_admin", user_id="u1") == 1
        assert sample_value("immich_user_deleted", user_id="u1") == 0

        # Bob: present in both /admin/users and /server/statistics with zeros.
        assert sample_value("immich_user_photos", user_id="u2") == 0
        assert sample_value("immich_user_admin", user_id="u2") == 0

        # Carol: in /admin/users but absent from usageByUser -> zero samples,
        # non-null deletedAt and "removing" status.
        assert sample_value("immich_user_photos", user_id="u3") == 0
        assert sample_value("immich_user_deleted", user_id="u3") == 1
        assert sample_value("immich_user_status", user_id="u3", status="removing") == 1
        # And there is only one status sample for u3 (stateset shape).
        u3_status_samples = [
            s
            for s in user_metrics["immich_user_status"].samples
            if s.labels.get("user_id") == "u3"
        ]
        assert len(u3_status_samples) == 1

        # No sample line should have carried a user_email label. Same guard
        # via the label-set of every family.
        for family in user_metrics.values():
            for sample in family.samples:
                assert set(sample.labels).issubset({"user_id", "user_name", "status"})

    @responses.activate
    def test_collect_server_statistics_shared_with_user_metrics(self):
        """``/server/statistics`` must be fetched at most once per scrape."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=MOCK_ADMIN_USERS_EXTENDED,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )
        _register_stub_immich_endpoints()

        with mock.patch.object(
            ImmichAPI,
            "get_server_statistics",
            wraps=self.api.get_server_statistics,
        ) as mocked_get:
            list(self.collector.collect())
            assert mocked_get.call_count == 1

    @responses.activate
    def test_collect_up_metric_ok(self):
        """immich_up == 1 when /server/ping returns pong."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json={},
            status=200,
        )
        _register_stub_immich_endpoints()

        metrics = list(self.collector.collect())
        up = next(m for m in metrics if m.name == "immich_up")
        assert up.samples[0].value == 1

    @responses.activate
    def test_collect_up_metric_failure(self):
        """immich_up == 0 when /server/ping returns a 500."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"owned": 0, "shared": 0, "notShared": 0},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSizeRaw": 0,
                "diskUseRaw": 0,
                "diskAvailableRaw": 0,
                "diskUsagePercentage": 0,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json={"error": "boom"},
            status=500,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=MOCK_MAINTENANCE_IDLE,
            status=200,
        )

        metrics = list(self.collector.collect())
        up = next(m for m in metrics if m.name == "immich_up")
        assert up.samples[0].value == 0

    @responses.activate
    def test_collect_server_statistics(self):
        """Instance-wide server statistics gauges have the expected values."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )
        _register_stub_immich_endpoints()

        metrics = list(self.collector.collect())
        server_metrics = {
            m.name: m for m in metrics if m.name.startswith("immich_server_")
        }
        assert set(server_metrics) == {
            "immich_server_photos",
            "immich_server_videos",
            "immich_server_usage_bytes",
            "immich_server_usage_photos_bytes",
            "immich_server_usage_videos_bytes",
        }
        assert server_metrics["immich_server_photos"].samples[0].value == 12345
        assert server_metrics["immich_server_videos"].samples[0].value == 678
        assert (
            server_metrics["immich_server_usage_bytes"].samples[0].value == 987_654_321
        )
        assert (
            server_metrics["immich_server_usage_photos_bytes"].samples[0].value
            == 800_000_000
        )
        assert (
            server_metrics["immich_server_usage_videos_bytes"].samples[0].value
            == 187_654_321
        )

    @responses.activate
    def test_collect_maintenance_metrics_active(self):
        """immich_maintenance_* reflects an active maintenance payload."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"owned": 0, "shared": 0, "notShared": 0},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSizeRaw": 0,
                "diskUseRaw": 0,
                "diskAvailableRaw": 0,
                "diskUsagePercentage": 0,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json=MOCK_PING_OK,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=MOCK_MAINTENANCE_ACTIVE,
            status=200,
        )

        metrics = list(self.collector.collect())
        active = next(m for m in metrics if m.name == "immich_maintenance_active")
        progress = next(m for m in metrics if m.name == "immich_maintenance_progress")

        assert active.samples[0].labels == {
            "action": "restore_database",
            "task": "restoring users table",
        }
        assert active.samples[0].value == 1
        assert progress.samples[0].value == 42

    @responses.activate
    def test_collect_maintenance_metrics_idle(self):
        """immich_maintenance_* reports zeros when idle."""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json={},
            status=200,
        )
        _register_stub_immich_endpoints()

        metrics = list(self.collector.collect())
        active = next(m for m in metrics if m.name == "immich_maintenance_active")
        progress = next(m for m in metrics if m.name == "immich_maintenance_progress")

        assert active.samples[0].labels == {"action": "end", "task": ""}
        assert active.samples[0].value == 0
        assert progress.samples[0].value == 0

    @responses.activate
    def test_collect_error_handling(self):
        """Test collector error handling"""
        # Mock failing API calls
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json={"error": "Server error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"error": "Server error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json={"error": "Server error"},
            status=500,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={"error": "Server error"},
            status=500,
        )

        # Should not raise exception, but handle gracefully
        metrics = list(self.collector.collect())

        # Should still have timestamp metric even if others fail
        assert len(metrics) >= 1
        assert metrics[0].name == "immich_exporter_last_scrape_timestamp_ms"

    @responses.activate
    def test_collect_job_metrics(self):
        """Test collecting job metrics via collector"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json=MOCK_JOBS_RESPONSE,
            status=200,
        )

        metrics = list(self.collector._collect_job_metrics())

        # Expect exactly three GaugeMetricFamily instances.
        assert len(metrics) == 3
        metric_by_name = {m.name: m for m in metrics}
        assert set(metric_by_name.keys()) == {
            "immich_job_queue_count",
            "immich_job_queue_active",
            "immich_job_queue_paused",
        }

        count_metric = metric_by_name["immich_job_queue_count"]
        active_metric = metric_by_name["immich_job_queue_active"]
        paused_metric = metric_by_name["immich_job_queue_paused"]

        # 3 queues * 6 states = 18 samples for the count metric.
        assert len(count_metric.samples) == 3 * 6

        # Build a lookup keyed by (queue, state).
        count_samples = {
            (s.labels["queue"], s.labels["state"]): s.value
            for s in count_metric.samples
        }

        # Known-value assertions from the fixture.
        assert count_samples[("metadataExtraction", "active")] == 2
        assert count_samples[("metadataExtraction", "waiting")] == 5
        assert count_samples[("metadataExtraction", "completed")] == 100
        assert count_samples[("metadataExtraction", "failed")] == 1
        assert count_samples[("metadataExtraction", "delayed")] == 3
        assert count_samples[("metadataExtraction", "paused")] == 0

        assert count_samples[("smartSearch", "failed")] == 7
        assert count_samples[("smartSearch", "active")] == 0

        # Missing 'waiting' key must yield a 0 sample, not absence.
        assert ("thumbnailGeneration", "waiting") in count_samples
        assert count_samples[("thumbnailGeneration", "waiting")] == 0

        # isActive / isPaused as 0/1 gauges.
        active_samples = {s.labels["queue"]: s.value for s in active_metric.samples}
        paused_samples = {s.labels["queue"]: s.value for s in paused_metric.samples}

        assert active_samples["metadataExtraction"] == 1
        assert paused_samples["metadataExtraction"] == 0
        assert active_samples["smartSearch"] == 0
        assert paused_samples["smartSearch"] == 1
        assert active_samples["thumbnailGeneration"] == 1
        assert paused_samples["thumbnailGeneration"] == 0

    @responses.activate
    def test_collect_job_metrics_error_handling(self):
        """Test that job collection errors don't break other collectors"""
        # Jobs endpoint fails.
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json={"error": "Server error"},
            status=500,
        )

        # Other collectors must still work: mock them with minimal payloads.
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"owned": 0, "shared": 0, "notShared": 0},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSizeRaw": 0,
                "diskUseRaw": 0,
                "diskAvailableRaw": 0,
                "diskUsagePercentage": 0,
            },
            status=200,
        )

        # _collect_job_metrics itself must not raise.
        job_metrics = list(self.collector._collect_job_metrics())
        # On failure the family generator returns before yielding anything.
        assert job_metrics == []

        # A full collect() run must still produce the timestamp metric and not
        # surface the failure as an exception.
        metrics = list(self.collector.collect())
        assert len(metrics) >= 1
        assert metrics[0].name == "immich_exporter_last_scrape_timestamp_ms"
        # No job metric families should be present in the aggregated output.
        job_metric_names = [
            m.name for m in metrics if m.name.startswith("immich_job_queue_")
        ]
        assert job_metric_names == []


class TestCLICommands:
    """Test the CLI commands"""

    def setup_method(self):
        """Set up test fixtures"""
        self.runner = CliRunner()

    def test_help_command(self):
        """Test the help command"""
        result = self.runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Immich Prometheus Exporter" in result.stdout
        assert "export" in result.stdout
        assert "test-connection" in result.stdout

    def test_export_help(self):
        """Test export command help"""
        result = self.runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "Export Immich metrics" in result.stdout
        assert "--url" in result.stdout
        assert "--api-key" in result.stdout
        assert "--output" in result.stdout
        assert "--interval" in result.stdout

    def test_test_connection_help(self):
        """Test test-connection command help"""
        result = self.runner.invoke(app, ["test-connection", "--help"])
        assert result.exit_code == 0
        assert "Test connection" in result.stdout
        assert "--url" in result.stdout
        assert "--api-key" in result.stdout

    def test_export_missing_required_args(self):
        """Test export command with missing required arguments"""
        result = self.runner.invoke(app, ["export"])
        assert result.exit_code != 0
        # Check both stdout and stderr for the error message
        output = result.stdout + result.stderr
        assert "Missing option" in output or "required" in output.lower()

    def test_test_connection_missing_required_args(self):
        """Test test-connection command with missing required arguments"""
        result = self.runner.invoke(app, ["test-connection"])
        assert result.exit_code != 0
        # Check both stdout and stderr for the error message
        output = result.stdout + result.stderr
        assert "Missing option" in output or "required" in output.lower()

    @responses.activate
    def test_successful_export(self):
        """Test successful export command"""
        # Mock all required API endpoints
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"owned": 0, "shared": 0, "notShared": 0},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=[],
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSizeRaw": 0,
                "diskUseRaw": 0,
                "diskAvailableRaw": 0,
                "diskUsagePercentage": 0,
            },
            status=200,
        )

        result = self.runner.invoke(
            app,
            [
                "export",
                "--url",
                "http://localhost:2283",
                "--api-key",
                "test-key",
            ],
        )

        assert result.exit_code == 0
        assert "immich_exporter_last_scrape_timestamp_ms" in result.stdout

    @responses.activate
    def test_successful_test_connection(self):
        """Test successful test-connection command"""
        # Mock storage endpoint for basic connectivity test
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSize": "1.0 TB",
                "diskUsagePercentage": 60.0,
            },
            status=200,
        )

        # Mock users endpoint for admin access test
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=[{"id": "user1", "name": "Test User"}],
            status=200,
        )

        # Mocks for the diagnostic checks the command now performs.
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json=MOCK_PING_OK,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=MOCK_MAINTENANCE_ACTIVE,
            status=200,
        )

        result = self.runner.invoke(
            app,
            [
                "test-connection",
                "--url",
                "http://localhost:2283",
                "--api-key",
                "test-key",
            ],
        )

        assert result.exit_code == 0
        assert "Connection successful" in result.stdout
        assert "Admin access confirmed" in result.stdout
        assert "Server statistics reachable" in result.stdout
        assert "Immich reachable (ping=pong)" in result.stdout
        assert "Maintenance status reachable" in result.stdout

    @responses.activate
    def test_failed_test_connection(self):
        """Test failed test-connection command"""
        # Mock a failing API call
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={"error": "Unauthorized"},
            status=401,
        )

        result = self.runner.invoke(
            app,
            [
                "test-connection",
                "--url",
                "http://localhost:2283",
                "--api-key",
                "invalid-key",
            ],
        )

        assert result.exit_code == 1
        # Check both stdout and stderr for the error message
        output = result.stdout + result.stderr
        assert "Connection failed" in output or "error" in output.lower()


class TestIntegration:
    """Integration tests"""

    @responses.activate
    def test_full_export_workflow(self):
        """Test the complete export workflow with realistic data"""
        # Mock all API endpoints with realistic data
        mock_users = MOCK_ADMIN_USERS_EXTENDED

        mock_album_stats = {
            "owned": 15,
            "shared": 5,
            "notShared": 10,
        }

        mock_libraries = [
            {
                "id": "lib1",
                "name": "Photos Library",
                "ownerId": "u1",
            },
        ]

        mock_library_stats = {
            "total": 5000,
            "photos": 4000,
            "videos": 1000,
            "usage": 50000000000,
        }

        mock_storage = {
            "diskSizeRaw": 1000000000000,
            "diskUseRaw": 600000000000,
            "diskAvailableRaw": 400000000000,
            "diskUsagePercentage": 60.0,
        }

        # Add all mock responses
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=mock_users,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/statistics",
            json=MOCK_SERVER_STATISTICS,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json=mock_album_stats,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=mock_libraries,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries/lib1/statistics",
            json=mock_library_stats,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json=mock_storage,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/jobs",
            json={},
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/ping",
            json=MOCK_PING_OK,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/maintenance/status",
            json=MOCK_MAINTENANCE_ACTIVE,
            status=200,
        )

        # Create API and exporter
        api = ImmichAPI("http://localhost:2283", "test-api-key")
        exporter = PrometheusExporter(api)

        # Collect all metrics
        exporter.collect_all_metrics()
        metrics = exporter.export_metrics()

        # Verify all expected metrics are present
        expected_metrics = [
            "immich_user_photos",
            "immich_user_videos",
            "immich_user_usage_bytes",
            "immich_user_quota_bytes",
            "immich_user_quota_usage_bytes",
            "immich_user_admin",
            "immich_user_status",
            "immich_user_deleted",
            "immich_albums_owned_total",
            "immich_albums_shared_total",
            "immich_albums_not_shared_total",
            "immich_library_total_assets",
            "immich_library_photos_count",
            "immich_library_videos_count",
            "immich_library_usage_bytes",
            "immich_storage_disk_size_bytes",
            "immich_storage_disk_use_bytes",
            "immich_storage_disk_available_bytes",
            "immich_storage_disk_usage_percentage",
            "immich_server_photos",
            "immich_server_videos",
            "immich_server_usage_bytes",
            "immich_up",
            "immich_maintenance_active",
            "immich_maintenance_progress",
        ]

        for metric in expected_metrics:
            assert metric in metrics, f"Missing metric: {metric}"

        # Legacy metric names must be gone.
        assert "immich_user_total_assets" not in metrics
        assert "immich_user_images_count" not in metrics
        assert "immich_user_videos_count" not in metrics

        # Verify specific values
        assert "immich_user_photos{" in metrics
        assert "immich_albums_owned_total 15" in metrics
        assert "immich_library_total_assets{" in metrics
        assert "5000" in metrics  # library total assets
        assert "immich_storage_disk_size_bytes 1000000000000" in metrics
        assert "immich_up 1" in metrics
        assert "immich_server_photos 12345" in metrics


if __name__ == "__main__":
    pytest.main([__file__])
