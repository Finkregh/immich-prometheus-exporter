#!/usr/bin/env python3
"""Unit tests for duplicate HELP/TYPE issue in Immich Prometheus Exporter

Tests that HELP and TYPE lines are only emitted once per metric, even when
there are multiple users/libraries/etc.
"""

import os
import sys

import pytest
import responses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import immich_prometheus_exporter.main as immich_prometheus_exporter

# Import the classes from the loaded module
ImmichAPI = immich_prometheus_exporter.ImmichAPI
PrometheusExporter = immich_prometheus_exporter.PrometheusExporter
ImmichCollector = immich_prometheus_exporter.ImmichCollector


class TestDuplicateHelpType:
    """Test that HELP and TYPE lines are not duplicated"""

    def setup_method(self) -> None:
        """Set up test fixtures"""
        self.api = ImmichAPI("http://localhost:2283", "test-api-key")
        self.exporter = PrometheusExporter(self.api)

    @responses.activate
    def test_no_duplicate_help_type_with_multiple_users(self) -> None:
        """Test that HELP and TYPE are only emitted once per metric with multiple users"""
        # Mock multiple users
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
                "quotaSizeInBytes": 2000000000,
                "quotaUsageInBytes": 1000000000,
            },
            {
                "id": "user3",
                "name": "Bob Wilson",
                "email": "bob@example.com",
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

        # Mock user statistics for each user
        for i, user in enumerate(mock_users, 1):
            mock_stats = {
                "total": 1000 * i,
                "images": 800 * i,
                "videos": 200 * i,
            }
            responses.add(
                responses.GET,
                f"http://localhost:2283/api/admin/users/{user['id']}/statistics",
                json=mock_stats,
                status=200,
            )

        # Collect user metrics
        self.exporter.collect_user_metrics()
        metrics_output = self.exporter.export_metrics()
        
        # Split into lines for analysis
        lines = metrics_output.split('\n')
        
        # Count HELP and TYPE occurrences for each metric
        help_counts = {}
        type_counts = {}
        
        for line in lines:
            if line.startswith('# HELP '):
                metric_name = line.split()[2]  # Extract metric name
                help_counts[metric_name] = help_counts.get(metric_name, 0) + 1
            elif line.startswith('# TYPE '):
                metric_name = line.split()[2]  # Extract metric name
                type_counts[metric_name] = type_counts.get(metric_name, 0) + 1
        
        # Verify each metric has exactly one HELP and one TYPE line
        expected_metrics = [
            'immich_user_total_assets',
            'immich_user_images_count', 
            'immich_user_videos_count',
            'immich_user_quota_bytes',
            'immich_user_quota_usage_bytes'
        ]
        
        for metric in expected_metrics:
            if metric in help_counts:
                assert help_counts[metric] == 1, f"Metric {metric} has {help_counts[metric]} HELP lines, expected 1"
            if metric in type_counts:
                assert type_counts[metric] == 1, f"Metric {metric} has {type_counts[metric]} TYPE lines, expected 1"

        # Also verify we have the expected number of data lines (one per user per metric)
        # Count actual metric data lines (not HELP/TYPE)
        data_lines = [line for line in lines if line and not line.startswith('#')]
        
        # We should have data lines for each user for each metric they have data for
        # user1 and user2 have quota data, user3 doesn't
        expected_data_lines = (
            3 * 3 +  # 3 users * 3 basic metrics (total_assets, images_count, videos_count)
            2 * 2    # 2 users * 2 quota metrics (quota_bytes, quota_usage_bytes)
        )
        
        assert len(data_lines) == expected_data_lines, f"Expected {expected_data_lines} data lines, got {len(data_lines)}"

    @responses.activate
    def test_no_duplicate_help_type_with_multiple_libraries(self) -> None:
        """Test that HELP and TYPE are only emitted once per metric with multiple libraries"""
        # Mock multiple libraries
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
            {
                "id": "lib3",
                "name": "Archive Library", 
                "ownerId": "user1",
            },
        ]

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=mock_libraries,
            status=200,
        )

        # Mock library statistics for each library
        for i, library in enumerate(mock_libraries, 1):
            mock_stats = {
                "total": 2000 * i,
                "photos": 1500 * i,
                "videos": 500 * i,
                "usage": 50000000000 * i,
            }
            responses.add(
                responses.GET,
                f"http://localhost:2283/api/libraries/{library['id']}/statistics",
                json=mock_stats,
                status=200,
            )

        # Collect library metrics
        self.exporter.collect_library_metrics()
        metrics_output = self.exporter.export_metrics()
        
        # Split into lines for analysis
        lines = metrics_output.split('\n')
        
        # Count HELP and TYPE occurrences for each metric
        help_counts = {}
        type_counts = {}
        
        for line in lines:
            if line.startswith('# HELP '):
                metric_name = line.split()[2]  # Extract metric name
                help_counts[metric_name] = help_counts.get(metric_name, 0) + 1
            elif line.startswith('# TYPE '):
                metric_name = line.split()[2]  # Extract metric name
                type_counts[metric_name] = type_counts.get(metric_name, 0) + 1
        
        # Verify each metric has exactly one HELP and one TYPE line
        expected_metrics = [
            'immich_library_total_assets',
            'immich_library_photos_count',
            'immich_library_videos_count', 
            'immich_library_usage_bytes'
        ]
        
        for metric in expected_metrics:
            if metric in help_counts:
                assert help_counts[metric] == 1, f"Metric {metric} has {help_counts[metric]} HELP lines, expected 1"
            if metric in type_counts:
                assert type_counts[metric] == 1, f"Metric {metric} has {type_counts[metric]} TYPE lines, expected 1"

        # Verify we have the expected number of data lines (one per library per metric)
        data_lines = [line for line in lines if line and not line.startswith('#')]
        expected_data_lines = 3 * 4  # 3 libraries * 4 metrics each
        
        assert len(data_lines) == expected_data_lines, f"Expected {expected_data_lines} data lines, got {len(data_lines)}"

    @responses.activate
    def test_full_export_no_duplicate_help_type(self) -> None:
        """Test full export workflow doesn't produce duplicate HELP/TYPE lines"""
        # Mock all API endpoints with multiple entities
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
                "quotaSizeInBytes": 2000000000,
                "quotaUsageInBytes": 1000000000,
            },
        ]

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

        # Add all mock responses
        responses.add(
            responses.GET,
            "http://localhost:2283/api/admin/users",
            json=mock_users,
            status=200,
        )
        
        for i, user in enumerate(mock_users, 1):
            responses.add(
                responses.GET,
                f"http://localhost:2283/api/admin/users/{user['id']}/statistics",
                json={"total": 1000 * i, "images": 800 * i, "videos": 200 * i},
                status=200,
            )

        responses.add(
            responses.GET,
            "http://localhost:2283/api/albums/statistics",
            json={"owned": 15, "shared": 5, "notShared": 10},
            status=200,
        )

        responses.add(
            responses.GET,
            "http://localhost:2283/api/libraries",
            json=mock_libraries,
            status=200,
        )
        
        for i, library in enumerate(mock_libraries, 1):
            responses.add(
                responses.GET,
                f"http://localhost:2283/api/libraries/{library['id']}/statistics",
                json={"total": 2000 * i, "photos": 1500 * i, "videos": 500 * i, "usage": 50000000000 * i},
                status=200,
            )

        responses.add(
            responses.GET,
            "http://localhost:2283/api/server/storage",
            json={
                "diskSizeRaw": 1000000000000,
                "diskUseRaw": 600000000000,
                "diskAvailableRaw": 400000000000,
                "diskUsagePercentage": 60.0,
            },
            status=200,
        )

        # Collect all metrics
        self.exporter.collect_all_metrics()
        metrics_output = self.exporter.export_metrics()
        
        # Split into lines for analysis
        lines = metrics_output.split('\n')
        
        # Count HELP and TYPE occurrences for each metric
        help_counts = {}
        type_counts = {}
        
        for line in lines:
            if line.startswith('# HELP '):
                metric_name = line.split()[2]  # Extract metric name
                help_counts[metric_name] = help_counts.get(metric_name, 0) + 1
            elif line.startswith('# TYPE '):
                metric_name = line.split()[2]  # Extract metric name
                type_counts[metric_name] = type_counts.get(metric_name, 0) + 1
        
        # Verify NO metric has more than one HELP or TYPE line
        for metric_name, count in help_counts.items():
            assert count == 1, f"Metric {metric_name} has {count} HELP lines, expected 1"
            
        for metric_name, count in type_counts.items():
            assert count == 1, f"Metric {metric_name} has {count} TYPE lines, expected 1"

        # Print debug info for manual inspection
        print(f"\nTotal lines: {len(lines)}")
        print(f"HELP lines: {sum(help_counts.values())}")
        print(f"TYPE lines: {sum(type_counts.values())}")
        print(f"Unique metrics with HELP: {len(help_counts)}")
        print(f"Unique metrics with TYPE: {len(type_counts)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
