#!/usr/bin/env python3
"""Unit tests for Immich Prometheus Exporter

Tests the main functionality using mocked HTTP responses.
"""

import os

# Import the modules we want to test
import sys

import pytest
import responses
from typer.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import immich_prometheus_exporter.main as immich_prometheus_exporter

# Import the classes and app from the loaded module
ImmichAPI = immich_prometheus_exporter.ImmichAPI
PrometheusExporter = immich_prometheus_exporter.PrometheusExporter
ImmichCollector = immich_prometheus_exporter.ImmichCollector
app = immich_prometheus_exporter.app


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
    def test_get_user_statistics(self) -> None:
        """Test getting user statistics"""
        mock_stats = {
            "total": 1250,
            "images": 1000,
            "videos": 250,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users/user1/statistics",
            json=mock_stats,
            status=200,
        )

        stats = self.api.get_user_statistics("user1")
        assert stats["total"] == 1250
        assert stats["images"] == 1000
        assert stats["videos"] == 250

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
    def test_non_dict_response_for_stats(self) -> None:
        """Test handling when stats endpoint returns non-dict"""
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users/user1/statistics",
            json=["not", "a", "dict"],
            status=200,
        )

        stats = self.api.get_user_statistics("user1")
        assert stats == {}


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
        """Test collecting user metrics"""
        # Mock users response
        mock_users = [
            {
                "id": "user1",
                "name": "John Doe",
                "email": "john@example.com",
                "quotaSizeInBytes": 1000000000,
                "quotaUsageInBytes": 500000000,
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=mock_users,
            status=200,
        )

        # Mock user statistics response
        mock_stats = {
            "total": 1250,
            "images": 1000,
            "videos": 250,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users/user1/statistics",
            json=mock_stats,
            status=200,
        )

        self.exporter.collect_user_metrics()
        metrics = self.exporter.export_metrics()

        assert "immich_user_total_assets" in metrics
        assert "immich_user_images_count" in metrics
        assert "immich_user_videos_count" in metrics
        assert "immich_user_quota_bytes" in metrics
        assert "immich_user_quota_usage_bytes" in metrics
        assert 'user_name="John Doe"' in metrics
        assert 'user_email="john@example.com"' in metrics

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

        metrics = list(self.collector.collect())

        # Should have at least the timestamp metric
        assert len(metrics) > 0

        # First metric should be timestamp
        timestamp_metric = metrics[0]
        assert timestamp_metric.name == "immich_exporter_last_scrape_timestamp_ms"
        assert timestamp_metric.documentation == "Timestamp of last successful scrape"

    @responses.activate
    def test_collect_user_metrics(self):
        """Test collecting user metrics via collector"""
        # Mock users response
        mock_users = [
            {
                "id": "user1",
                "name": "John Doe",
                "email": "john@example.com",
                "quotaSizeInBytes": 1000000000,
                "quotaUsageInBytes": 500000000,
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=mock_users,
            status=200,
        )

        # Mock user statistics response
        mock_stats = {
            "total": 1250,
            "images": 1000,
            "videos": 250,
        }

        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users/user1/statistics",
            json=mock_stats,
            status=200,
        )

        # Mock other endpoints to avoid errors
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

        metrics = list(self.collector.collect())

        # Find user metrics
        user_metrics = [m for m in metrics if m.name.startswith("immich_user_")]
        assert (
            len(user_metrics) >= 3
        )  # At least total_assets, images_count, videos_count

        # Check specific metrics exist
        metric_names = [m.name for m in user_metrics]
        assert "immich_user_total_assets" in metric_names
        assert "immich_user_images_count" in metric_names
        assert "immich_user_videos_count" in metric_names

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
        mock_users = [
            {
                "id": "user1",
                "name": "John Doe",
                "email": "john@example.com",
                "quotaSizeInBytes": 1000000000,
                "quotaUsageInBytes": 500000000,
            },
        ]

        mock_user_stats = {
            "total": 1250,
            "images": 1000,
            "videos": 250,
        }

        mock_album_stats = {
            "owned": 15,
            "shared": 5,
            "notShared": 10,
        }

        mock_libraries = [
            {
                "id": "lib1",
                "name": "Photos Library",
                "ownerId": "user1",
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
            "http://localhost:2283/api/admin/users/user1/statistics",
            json=mock_user_stats,
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

        # Create API and exporter
        api = ImmichAPI("http://localhost:2283", "test-api-key")
        exporter = PrometheusExporter(api)

        # Collect all metrics
        exporter.collect_all_metrics()
        metrics = exporter.export_metrics()

        # Verify all expected metrics are present
        expected_metrics = [
            "immich_user_total_assets",
            "immich_user_images_count",
            "immich_user_videos_count",
            "immich_user_quota_bytes",
            "immich_user_quota_usage_bytes",
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
        ]

        for metric in expected_metrics:
            assert metric in metrics, f"Missing metric: {metric}"

        # Verify specific values
        assert "immich_user_total_assets{" in metrics
        assert "1250" in metrics  # user total assets
        assert "immich_albums_owned_total 15" in metrics
        assert "immich_library_total_assets{" in metrics
        assert "5000" in metrics  # library total assets
        assert "immich_storage_disk_size_bytes 1000000000000" in metrics


if __name__ == "__main__":
    pytest.main([__file__])
