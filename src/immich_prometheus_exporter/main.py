#!/usr/bin/env python3
"""Immich Prometheus Exporter

This script exports Immich statistics as Prometheus metrics.
It collects data about users, libraries, albums, and storage usage.
"""

import json
import logging
import sys
import time
from typing import Any

import requests
import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    help="Immich Prometheus Exporter - Export Immich statistics as Prometheus metrics",
)

# Global logger - will be configured in setup_logging()
log = logging.getLogger(__name__)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    use_stderr: bool = True,
) -> None:
    """Setup logging configuration.
    
    :param level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    :type level: str
    :param log_file: Optional log file path
    :type log_file: str | None
    :param use_stderr: Whether to log to stderr (default) or stdout
    :type use_stderr: bool
    """
    # Clear any existing handlers
    for handler in log.handlers[:]:
        log.removeHandler(handler)
    
    # Set logging level
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    log.setLevel(numeric_level)
    
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    else:
        # Add console handler
        console = Console(stderr=use_stderr)
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(console_handler)

class ImmichAPI:
    """Client for interacting with Immich API"""

    def __init__(self, base_url: str, api_key: str) -> None:
        """Initialize the Immich API client.

        :param base_url: The base URL of the Immich server.
        :type base_url: str
        :param api_key: The API key for authentication.
        :type api_key: str
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make HTTP request to Immich API.

        :param endpoint: The API endpoint to request.
        :type endpoint: str
        :param method: The HTTP method to use (GET, POST, etc.).
        :type method: str
        :param data: Optional data to send with the request.
        :type data: dict | None
        :return: The JSON response from the API.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        :raises requests.exceptions.HTTPError: If the HTTP request fails.
        :raises requests.exceptions.RequestException: If there's a network error.
        :raises json.JSONDecodeError: If the response is not valid JSON.
        """
        url = f"{self.base_url}/api/{endpoint.lstrip('/')}"
        
        # Debug logging for API requests
        log.debug(f"Making {method} request to: {url}")
        if data:
            log.debug(f"Request data: {data}")

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=30,
            )
            response.raise_for_status()
            log.debug(f"Request successful: {response.status_code}")
            return response.json()
        except requests.exceptions.HTTPError as e:
            log.error(f"HTTP Error {response.status_code}: {e} for {url}")
            typer.echo(f"HTTP Error {response.status_code}: {e} for {url}", err=True)
            raise
        except requests.exceptions.RequestException as e:
            log.error(f"Request Error: {e} for {url}")
            typer.echo(f"Request Error: {e} for {url}", err=True)
            raise
        except json.JSONDecodeError as e:
            log.error(f"JSON decode error: {e}")
            typer.echo(f"JSON decode error: {e}", err=True)
            raise

    def get_all_users(self) -> list[dict[str, Any]]:
        """Get all users using admin endpoint.

        :return: List of user dictionaries or empty list if request fails.
        :rtype: list[dict[str, Any]]
        """
        result = self._make_request("/admin/users")
        return result if isinstance(result, list) else []

    def get_user_statistics(self, user_id: str) -> dict[str, Any]:
        """Get statistics for a specific user.

        :param user_id: The unique identifier of the user.
        :type user_id: str
        :return: Dictionary containing user statistics or empty dict if request fails.
        :rtype: dict[str, Any]
        """
        result = self._make_request(f"/admin/users/{user_id}/statistics")
        return result if isinstance(result, dict) else {}

    def get_album_statistics(self) -> dict[str, Any]:
        """Get album statistics.

        :return: Dictionary containing album statistics or empty dict if request fails.
        :rtype: dict[str, Any]
        """
        result = self._make_request("/albums/statistics")
        return result if isinstance(result, dict) else {}

    def get_all_libraries(self) -> list[dict[str, Any]]:
        """Get all libraries.

        :return: List of library dictionaries or empty list if request fails.
        :rtype: list[dict[str, Any]]
        """
        result = self._make_request("/libraries")
        return result if isinstance(result, list) else []

    def get_library_statistics(self, library_id: str) -> dict[str, Any]:
        """Get statistics for a specific library.

        :param library_id: The unique identifier of the library.
        :type library_id: str
        :return: Dictionary containing library statistics or empty dict if request fails.
        :rtype: dict[str, Any]
        """
        result = self._make_request(f"/libraries/{library_id}/statistics")
        return result if isinstance(result, dict) else {}

    def get_storage(self) -> dict[str, Any]:
        """Get storage information.

        :return: Dictionary containing storage information or empty dict if request fails.
        :rtype: dict[str, Any]
        """
        result = self._make_request("/server/storage")
        return result if isinstance(result, dict) else {}


class PrometheusExporter:
    """Prometheus metrics exporter for Immich"""

    def __init__(self, api: ImmichAPI) -> None:
        """Initialize the Prometheus exporter.

        :param api: The Immich API client instance.
        :type api: ImmichAPI
        """
        self.api: ImmichAPI = api
        self.metrics: list[str] = []

    def _add_metric(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        help_text: str = "",
    ) -> None:
        """Add a metric to the collection.

        :param name: The metric name.
        :type name: str
        :param value: The metric value.
        :type value: float
        :param labels: Optional labels for the metric.
        :type labels: dict[str, str] | None
        :param help_text: Optional help text for the metric.
        :type help_text: str
        """
        if help_text:
            self.metrics.append(f"# HELP {name} {help_text}")
            self.metrics.append(f"# TYPE {name} gauge")

        label_str = ""
        if labels:
            label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
            label_str = "{" + ",".join(label_pairs) + "}"

        self.metrics.append(f"{name}{label_str} {value}")

    def collect_user_metrics(self) -> None:
        """Collect metrics for all users.

        Retrieves user statistics from Immich API and adds them as Prometheus metrics.
        Includes total assets, images, videos, and quota information if available.
        """
        try:
            users = self.api.get_all_users()
            log.info(f"Found {len(users)} users")

            for user in users:
                user_id = user["id"]
                user_name = user["name"]
                user_email = user["email"]
                
                log.debug(f"Processing user: {user_name} ({user_email})")

                try:
                    stats = self.api.get_user_statistics(user_id)

                    labels = {
                        "user_id": user_id,
                        "user_name": user_name,
                        "user_email": user_email,
                    }

                    # Total assets
                    self._add_metric(
                        "immich_user_total_assets",
                        stats.get("total", 0),
                        labels,
                        "Total number of assets for user",
                    )

                    # Images
                    self._add_metric(
                        "immich_user_images_count",
                        stats.get("images", 0),
                        labels,
                        "Number of images for user",
                    )

                    # Videos
                    self._add_metric(
                        "immich_user_videos_count",
                        stats.get("videos", 0),
                        labels,
                        "Number of videos for user",
                    )

                    # User quota and usage (if available)
                    if (
                        "quotaSizeInBytes" in user
                        and user["quotaSizeInBytes"] is not None
                    ):
                        self._add_metric(
                            "immich_user_quota_bytes",
                            user["quotaSizeInBytes"],
                            labels,
                            "User quota in bytes",
                        )

                    if (
                        "quotaUsageInBytes" in user
                        and user["quotaUsageInBytes"] is not None
                    ):
                        self._add_metric(
                            "immich_user_quota_usage_bytes",
                            user["quotaUsageInBytes"],
                            labels,
                            "User quota usage in bytes",
                        )
                    
                    log.debug(f"Successfully collected metrics for user: {user_name}")

                except Exception as e:
                    log.error(f"Error getting statistics for user {user_name}: {e}")
                    continue

        except Exception as e:
            log.error(f"Error collecting user metrics: {e}")

    def collect_album_metrics(self) -> None:
        """Collect album statistics.

        Retrieves album statistics from Immich API and adds them as Prometheus metrics.
        Includes owned, shared, and not shared album counts.
        """
        try:
            album_stats: dict[str, Any] = self.api.get_album_statistics()
            log.debug(f"Album statistics: {album_stats}")

            self._add_metric(
                "immich_albums_owned_total",
                album_stats.get("owned", 0),
                help_text="Total number of albums owned by users",
            )

            self._add_metric(
                "immich_albums_shared_total",
                album_stats.get("shared", 0),
                help_text="Total number of shared albums",
            )

            self._add_metric(
                "immich_albums_not_shared_total",
                album_stats.get("notShared", 0),
                help_text="Total number of albums not shared",
            )
            
            log.info("Successfully collected album metrics")

        except Exception as e:
            log.error(f"Error collecting album metrics: {e}")

    def collect_library_metrics(self) -> None:
        """Collect metrics for all libraries.

        Retrieves library statistics from Immich API and adds them as Prometheus metrics.
        Includes total assets, photos, videos, and usage information for each library.
        """
        try:
            libraries = self.api.get_all_libraries()
            log.info(f"Found {len(libraries)} libraries")

            for library in libraries:
                library_id = library["id"]
                library_name = library["name"]
                owner_id = library["ownerId"]
                
                log.debug(f"Processing library: {library_name} (ID: {library_id})")

                try:
                    stats = self.api.get_library_statistics(library_id)

                    labels = {
                        "library_id": library_id,
                        "library_name": library_name,
                        "owner_id": owner_id,
                    }

                    # Total assets in library
                    self._add_metric(
                        "immich_library_total_assets",
                        stats.get("total", 0),
                        labels,
                        "Total number of assets in library",
                    )

                    # Photos in library
                    self._add_metric(
                        "immich_library_photos_count",
                        stats.get("photos", 0),
                        labels,
                        "Number of photos in library",
                    )

                    # Videos in library
                    self._add_metric(
                        "immich_library_videos_count",
                        stats.get("videos", 0),
                        labels,
                        "Number of videos in library",
                    )

                    # Library usage in bytes
                    self._add_metric(
                        "immich_library_usage_bytes",
                        stats.get("usage", 0),
                        labels,
                        "Library usage in bytes",
                    )
                    
                    log.debug(f"Successfully collected metrics for library: {library_name}")

                except Exception as e:
                    log.error(f"Error getting statistics for library {library_name}: {e}")
                    continue

        except Exception as e:
            log.error(f"Error collecting library metrics: {e}")

    def collect_storage_metrics(self) -> None:
        """Collect storage metrics.

        Retrieves storage information from Immich API and adds them as Prometheus metrics.
        Includes disk size, usage, available space, and usage percentage.
        """
        try:
            storage = self.api.get_storage()
            log.debug(f"Storage information: {storage}")

            self._add_metric(
                "immich_storage_disk_size_bytes",
                storage.get("diskSizeRaw", 0),
                help_text="Total disk size in bytes",
            )

            self._add_metric(
                "immich_storage_disk_use_bytes",
                storage.get("diskUseRaw", 0),
                help_text="Used disk space in bytes",
            )

            self._add_metric(
                "immich_storage_disk_available_bytes",
                storage.get("diskAvailableRaw", 0),
                help_text="Available disk space in bytes",
            )

            self._add_metric(
                "immich_storage_disk_usage_percentage",
                storage.get("diskUsagePercentage", 0),
                help_text="Disk usage percentage",
            )
            
            log.info("Successfully collected storage metrics")

        except Exception as e:
            log.error(f"Error collecting storage metrics: {e}")

    def collect_all_metrics(self) -> None:
        """Collect all metrics.

        Orchestrates the collection of all metric types: user, album, library, and storage metrics.
        """
        log.info("Collecting user metrics...")
        self.collect_user_metrics()

        log.info("Collecting album metrics...")
        self.collect_album_metrics()

        log.info("Collecting library metrics...")
        self.collect_library_metrics()

        log.info("Collecting storage metrics...")
        self.collect_storage_metrics()
        
        log.info("Metrics collection completed")

    def export_metrics(self) -> str:
        """Export metrics in Prometheus format.

        :return: String containing all metrics in Prometheus format.
        :rtype: str
        """
        return "\n".join(self.metrics)


@app.command()
def export(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="Immich server URL (e.g., http://localhost:2283)",
    ),
    api_key: str = typer.Option(..., "--api-key", "-k", help="Immich API key"),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file (default: stdout)",
    ),
    interval: int | None = typer.Option(
        None,
        "--interval",
        "-i",
        help="Continuous export interval in seconds",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    ),
    log_file: str | None = typer.Option(
        None,
        "--log-file",
        help="Log file path (default: stderr)",
    ),
    log_to_stdout: bool = typer.Option(
        False,
        "--log-to-stdout",
        help="Log to stdout instead of stderr (requires --output to be set)",
    ),
):
    """Export Immich metrics in Prometheus format.

    :param url: The Immich server URL.
    :type url: str
    :param api_key: The Immich API key for authentication.
    :type api_key: str
    :param output: Optional output file path. If not provided, outputs to stdout.
    :type output: str | None
    :param interval: Optional interval in seconds for continuous export.
    :type interval: int | None
    :param log_level: Logging level.
    :type log_level: str
    :param log_file: Optional log file path.
    :type log_file: str | None
    :param log_to_stdout: Whether to log to stdout instead of stderr.
    :type log_to_stdout: bool
    :raises typer.Exit: If required parameters are missing or export fails.
    """
    # Validate inputs
    if not url:
        typer.echo("Error: URL is required", err=True)
        raise typer.Exit(1)

    if not api_key:
        typer.echo("Error: API key is required", err=True)
        raise typer.Exit(1)

    # Validate logging configuration
    if log_to_stdout and not output:
        typer.echo(
            "Error: --log-to-stdout requires --output to be set to avoid mixing "
            "prometheus metrics with logging output on stdout",
            err=True,
        )
        raise typer.Exit(1)

    # Setup logging
    use_stderr = not log_to_stdout
    setup_logging(level=log_level, log_file=log_file, use_stderr=use_stderr)
    
    log.info("Starting Immich Prometheus Exporter")
    log.info(f"Immich server URL: {url}")
    log.info(f"Log level: {log_level}")
    if log_file:
        log.info(f"Logging to file: {log_file}")
    elif log_to_stdout:
        log.info("Logging to stdout")
    else:
        log.info("Logging to stderr")

    # Initialize API client and exporter
    api = ImmichAPI(url, api_key)
    exporter = PrometheusExporter(api)

    def export_once():
        """Perform a single export operation.

        :return: True if export was successful, False otherwise.
        :rtype: bool
        """
        try:
            log.debug("Starting metrics export")
            
            # Clear previous metrics
            exporter.metrics = []

            # Add timestamp
            timestamp = int(time.time() * 1000)
            exporter._add_metric(
                "immich_exporter_last_scrape_timestamp_ms",
                timestamp,
                help_text="Timestamp of last successful scrape",
            )

            # Collect all metrics
            exporter.collect_all_metrics()

            # Export metrics
            metrics_output = exporter.export_metrics()
            log.debug(f"Generated {len(exporter.metrics)} metric lines")

            if output:
                with open(output, "w") as f:
                    f.write(metrics_output)
                log.info(f"Metrics exported to {output}")
            else:
                print(metrics_output)
                log.debug("Metrics written to stdout")

            log.info("Export completed successfully")
            return True

        except Exception as e:
            log.error(f"Error during export: {e}")
            return False

    if interval:
        log.info(f"Starting continuous export every {interval} seconds...")
        log.info("Press Ctrl+C to stop")

        try:
            while True:
                success = export_once()
                if not success:
                    log.error("Export failed, retrying in next interval...")

                log.debug(f"Sleeping for {interval} seconds...")
                time.sleep(interval)

        except KeyboardInterrupt:
            log.info("Export stopped by user")
            raise typer.Exit(0)
    else:
        success = export_once()
        if not success:
            raise typer.Exit(1)


@app.command()
def test_connection(
    url: str = typer.Option(..., "--url", "-u", help="Immich server URL"),
    api_key: str = typer.Option(..., "--api-key", "-k", help="Immich API key"),
):
    """Test connection to Immich server.

    Verifies that the provided URL and API key can successfully connect to the Immich server
    and that the API key has admin privileges required for metrics collection.

    :param url: The Immich server URL.
    :type url: str
    :param api_key: The Immich API key for authentication.
    :type api_key: str
    :raises typer.Exit: If connection fails or API key lacks required permissions.
    """
    try:
        api = ImmichAPI(url, api_key)

        # Test basic connectivity by getting storage info
        storage = api.get_storage()
        typer.echo("✅ Connection successful!")
        typer.echo(f"Server disk size: {storage.get('diskSize', 'Unknown')}")
        typer.echo(f"Server disk usage: {storage.get('diskUsagePercentage', 0):.1f}%")

        # Test admin access by getting users
        users = api.get_all_users()
        typer.echo(f"✅ Admin access confirmed! Found {len(users)} users")

    except Exception as e:
        typer.echo(f"❌ Connection failed: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
