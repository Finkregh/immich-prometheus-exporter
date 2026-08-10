#!/usr/bin/env python3
"""Immich Prometheus Exporter

This script exports Immich statistics as Prometheus metrics.
It collects data about users, libraries, albums, and storage usage.
"""

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import requests
import typer
from prometheus_client import REGISTRY, Info, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    help="Immich Prometheus Exporter - Export Immich statistics as Prometheus metrics",
    context_settings={"auto_envvar_prefix": "IMMICHEXPORTER"},
)

# Global logger - will be configured in setup_logging()
log = logging.getLogger(__name__)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    *,
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
        datefmt="%Y-%m-%d %H:%M:%S",
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
            show_path=False,
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(console_handler)


class ImmichAPI:
    """Client for interacting with Immich API."""

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

    def get_all_jobs_status(self) -> dict[str, Any]:
        """Get status of all Immich job queues.

        Calls ``GET /api/jobs`` (operationId ``getAllJobsStatus`` on v1.137.3,
        renamed to ``getQueuesLegacy`` on v3.1.0 with identical response shape).

        :return: Mapping of queue name to job status dict, or empty dict if the
            request fails or the response is not a dict.
        :rtype: dict[str, Any]
        """
        result = self._make_request("/jobs")
        return result if isinstance(result, dict) else {}

    def get_server_statistics(self) -> dict[str, Any]:
        """Get instance-wide server statistics.

        Calls ``GET /api/server/statistics`` (operationId
        ``getServerStatistics``). Response is ``ServerStatsResponseDto`` with
        top-level ``photos``, ``videos``, ``usage``, ``usagePhotos``,
        ``usageVideos``, and a per-user ``usageByUser`` array.

        :return: Dictionary containing server statistics or empty dict if the
            request fails or the response is not a dict.
        :rtype: dict[str, Any]
        """
        result = self._make_request("/server/statistics")
        return result if isinstance(result, dict) else {}

    def ping(self) -> bool:
        """Probe ``GET /api/server/ping`` and return reachability as a bool.

        This is the only API method that swallows exceptions: it is a health
        probe and callers rely on the returned bool to drive the ``immich_up``
        gauge without a surrounding try/except at every call site.

        :return: ``True`` iff the response is a dict and ``dict.get("res")``
            equals ``"pong"``, else ``False``.
        :rtype: bool
        """
        try:
            result = self._make_request("/server/ping")
        except Exception:
            return False
        return isinstance(result, dict) and result.get("res") == "pong"

    def get_maintenance_status(self) -> dict[str, Any]:
        """Get Immich maintenance status.

        Calls ``GET /api/admin/maintenance/status`` (operationId
        ``getMaintenanceStatus``). Response is ``MaintenanceStatusResponseDto``
        with ``active``, ``progress``, ``action``, and ``task`` fields.

        :return: Dictionary containing maintenance status or empty dict if the
            request fails or the response is not a dict.
        :rtype: dict[str, Any]
        """
        result = self._make_request("/admin/maintenance/status")
        return result if isinstance(result, dict) else {}


class ImmichCollector(Collector):
    """Custom Prometheus collector for Immich metrics"""

    def __init__(self, api: ImmichAPI) -> None:
        """Initialize the Immich collector.

        :param api: The Immich API client instance.
        :type api: ImmichAPI
        """
        self.api = api
        # Per-scrape memo cache for /server/statistics so that user metrics
        # and instance-wide server statistics can share a single fetch. Reset
        # at the top of every collect() call.
        self._server_stats_cache: dict[str, Any] | None = None

    def _get_server_stats_this_scrape(self) -> dict[str, Any]:
        """Return the /server/statistics payload, fetching at most once per scrape.

        :return: The cached ``ServerStatsResponseDto`` dict for the current
            scrape, or ``{}`` if the fetch failed.
        :rtype: dict[str, Any]
        """
        if self._server_stats_cache is None:
            self._server_stats_cache = self.api.get_server_statistics()
        return self._server_stats_cache

    def collect(self) -> Iterator[GaugeMetricFamily | CounterMetricFamily]:
        """Collect metrics from Immich API and yield metric families.

        :return: Iterator of metric families.
        :rtype: Iterator[GaugeMetricFamily | CounterMetricFamily]
        """
        # Reset per-scrape memoisation of /server/statistics.
        self._server_stats_cache = None

        # Yield timestamp metric
        timestamp = int(time.time() * 1000)
        timestamp_metric = GaugeMetricFamily(
            "immich_exporter_last_scrape_timestamp_ms",
            "Timestamp of last successful scrape",
        )
        timestamp_metric.add_metric([], timestamp)
        yield timestamp_metric

        # Health probe first, so alerting always sees an up sample even if
        # every other collector explodes.
        yield from self._collect_up_metric()

        # Collect user metrics
        yield from self._collect_user_metrics()

        # Collect album metrics
        yield from self._collect_album_metrics()

        # Collect library metrics
        yield from self._collect_library_metrics()

        # Collect storage metrics
        yield from self._collect_storage_metrics()

        # Collect instance-wide server statistics
        yield from self._collect_server_statistics()

        # Collect maintenance status
        yield from self._collect_maintenance_metrics()

        # Collect job metrics
        yield from self._collect_job_metrics()

    def _collect_user_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect metrics for all users.

        Per-user asset counts and usage bytes are sourced from a single
        ``/server/statistics`` call (via the per-scrape memo cache). Admin
        flag, status, deletion state, and quota fields come from the already
        fetched ``/admin/users`` response.

        :return: Iterator of user metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            users = self.api.get_all_users()
            log.info(f"Found {len(users)} users")

            server_stats = self._get_server_stats_this_scrape()
            usage_by_user_list = server_stats.get("usageByUser") or []
            usage_by_user = {
                entry.get("userId"): entry
                for entry in usage_by_user_list
                if isinstance(entry, dict) and entry.get("userId")
            }

            user_labels = ["user_id", "user_name"]

            photos_metric = GaugeMetricFamily(
                "immich_user_photos",
                "Number of photo assets owned by user",
                labels=user_labels,
            )
            videos_metric = GaugeMetricFamily(
                "immich_user_videos",
                "Number of video assets owned by user",
                labels=user_labels,
            )
            usage_metric = GaugeMetricFamily(
                "immich_user_usage_bytes",
                "Total storage used by user, in bytes",
                labels=user_labels,
            )
            usage_photos_metric = GaugeMetricFamily(
                "immich_user_usage_photos_bytes",
                "Storage used by user's photo assets, in bytes",
                labels=user_labels,
            )
            usage_videos_metric = GaugeMetricFamily(
                "immich_user_usage_videos_bytes",
                "Storage used by user's video assets, in bytes",
                labels=user_labels,
            )
            quota_metric = GaugeMetricFamily(
                "immich_user_quota_bytes",
                "User quota in bytes",
                labels=user_labels,
            )
            quota_usage_metric = GaugeMetricFamily(
                "immich_user_quota_usage_bytes",
                "User quota usage in bytes",
                labels=user_labels,
            )
            admin_metric = GaugeMetricFamily(
                "immich_user_admin",
                "1 if the user has admin privileges, else 0",
                labels=user_labels,
            )
            status_metric = GaugeMetricFamily(
                "immich_user_status",
                "User account status (stateset: emitted once per user with "
                "the current status as a label)",
                labels=[*user_labels, "status"],
            )
            deleted_metric = GaugeMetricFamily(
                "immich_user_deleted",
                "1 if the user has a non-null deletedAt timestamp, else 0",
                labels=user_labels,
            )

            for user in users:
                user_id = user.get("id", "")
                user_name = user.get("name", "")

                log.debug(f"Processing user: {user_name}")

                usage_entry = usage_by_user.get(user_id, {}) or {}
                labels = [user_id, user_name]

                photos_metric.add_metric(labels, usage_entry.get("photos", 0) or 0)
                videos_metric.add_metric(labels, usage_entry.get("videos", 0) or 0)
                usage_metric.add_metric(labels, usage_entry.get("usage", 0) or 0)
                usage_photos_metric.add_metric(
                    labels,
                    usage_entry.get("usagePhotos", 0) or 0,
                )
                usage_videos_metric.add_metric(
                    labels,
                    usage_entry.get("usageVideos", 0) or 0,
                )

                # Quota fields come from /admin/users (authoritative and
                # present even for users with no usageByUser row yet).
                quota_size = user.get("quotaSizeInBytes")
                if quota_size is not None:
                    quota_metric.add_metric(labels, quota_size)

                quota_usage = user.get("quotaUsageInBytes")
                if quota_usage is not None:
                    quota_usage_metric.add_metric(labels, quota_usage)

                admin_metric.add_metric(
                    labels,
                    1 if user.get("isAdmin") else 0,
                )

                status_value = str(user.get("status") or "").lower()
                status_metric.add_metric([*labels, status_value], 1)

                deleted_metric.add_metric(
                    labels,
                    1 if user.get("deletedAt") else 0,
                )

            # Yield in alphabetical order for readability.
            yield admin_metric
            yield deleted_metric
            yield photos_metric
            yield quota_metric
            yield quota_usage_metric
            yield status_metric
            yield usage_metric
            yield usage_photos_metric
            yield usage_videos_metric
            yield videos_metric

        except Exception as e:
            log.error(f"Error collecting user metrics: {e}")

    def _collect_album_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect album statistics.

        :return: Iterator of album metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            album_stats = self.api.get_album_statistics()
            log.debug(f"Album statistics: {album_stats}")

            owned_metric = GaugeMetricFamily(
                "immich_albums_owned_total",
                "Total number of albums owned by users",
            )
            owned_metric.add_metric([], album_stats.get("owned", 0))
            yield owned_metric

            shared_metric = GaugeMetricFamily(
                "immich_albums_shared_total",
                "Total number of shared albums",
            )
            shared_metric.add_metric([], album_stats.get("shared", 0))
            yield shared_metric

            not_shared_metric = GaugeMetricFamily(
                "immich_albums_not_shared_total",
                "Total number of albums not shared",
            )
            not_shared_metric.add_metric([], album_stats.get("notShared", 0))
            yield not_shared_metric

            log.info("Successfully collected album metrics")

        except Exception as e:
            log.error(f"Error collecting album metrics: {e}")

    def _collect_library_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect metrics for all libraries.

        :return: Iterator of library metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            libraries = self.api.get_all_libraries()
            log.info(f"Found {len(libraries)} libraries")

            # Create metric families
            total_assets_metric = GaugeMetricFamily(
                "immich_library_total_assets",
                "Total number of assets in library",
                labels=["library_id", "library_name", "owner_id"],
            )
            photos_metric = GaugeMetricFamily(
                "immich_library_photos_count",
                "Number of photos in library",
                labels=["library_id", "library_name", "owner_id"],
            )
            videos_metric = GaugeMetricFamily(
                "immich_library_videos_count",
                "Number of videos in library",
                labels=["library_id", "library_name", "owner_id"],
            )
            usage_metric = GaugeMetricFamily(
                "immich_library_usage_bytes",
                "Library usage in bytes",
                labels=["library_id", "library_name", "owner_id"],
            )

            for library in libraries:
                library_id = library["id"]
                library_name = library["name"]
                owner_id = library["ownerId"]

                log.debug(f"Processing library: {library_name} (ID: {library_id})")

                try:
                    stats = self.api.get_library_statistics(library_id)
                    labels = [library_id, library_name, owner_id]

                    # Add metrics for this library
                    total_assets_metric.add_metric(labels, stats.get("total", 0))
                    photos_metric.add_metric(labels, stats.get("photos", 0))
                    videos_metric.add_metric(labels, stats.get("videos", 0))
                    usage_metric.add_metric(labels, stats.get("usage", 0))

                    log.debug(
                        f"Successfully collected metrics for library: {library_name}",
                    )

                except Exception as e:
                    log.error(
                        f"Error getting statistics for library {library_name}: {e}",
                    )
                    continue

            # Yield all library metrics
            yield total_assets_metric
            yield photos_metric
            yield videos_metric
            yield usage_metric

        except Exception as e:
            log.error(f"Error collecting library metrics: {e}")

    def _collect_storage_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect storage metrics.

        :return: Iterator of storage metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            storage = self.api.get_storage()
            log.debug(f"Storage information: {storage}")

            disk_size_metric = GaugeMetricFamily(
                "immich_storage_disk_size_bytes",
                "Total disk size in bytes",
            )
            disk_size_metric.add_metric([], storage.get("diskSizeRaw", 0))
            yield disk_size_metric

            disk_use_metric = GaugeMetricFamily(
                "immich_storage_disk_use_bytes",
                "Used disk space in bytes",
            )
            disk_use_metric.add_metric([], storage.get("diskUseRaw", 0))
            yield disk_use_metric

            disk_available_metric = GaugeMetricFamily(
                "immich_storage_disk_available_bytes",
                "Available disk space in bytes",
            )
            disk_available_metric.add_metric([], storage.get("diskAvailableRaw", 0))
            yield disk_available_metric

            disk_usage_percentage_metric = GaugeMetricFamily(
                "immich_storage_disk_usage_percentage",
                "Disk usage percentage",
            )
            disk_usage_percentage_metric.add_metric(
                [],
                storage.get("diskUsagePercentage", 0),
            )
            yield disk_usage_percentage_metric

            log.info("Successfully collected storage metrics")

        except Exception as e:
            log.error(f"Error collecting storage metrics: {e}")

    def _collect_up_metric(self) -> Iterator[GaugeMetricFamily]:
        """Emit the ``immich_up`` health gauge.

        Never raises: ``self.api.ping()`` already returns a bool. The gauge is
        emitted on every scrape, including when other collectors fail.

        :return: Iterator yielding the single ``immich_up`` metric family.
        :rtype: Iterator[GaugeMetricFamily]
        """
        up_metric = GaugeMetricFamily(
            "immich_up",
            "1 if the Immich API responded to /server/ping successfully, 0 otherwise",
        )
        up_metric.add_metric([], 1 if self.api.ping() else 0)
        yield up_metric

    def _collect_server_statistics(self) -> Iterator[GaugeMetricFamily]:
        """Collect instance-wide server statistics from ``/server/statistics``.

        Only emits the top-level totals; per-user rows are handled by
        ``_collect_user_metrics`` from the same memoised fetch.

        :return: Iterator of server statistics metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            stats = self._get_server_stats_this_scrape()

            photos_metric = GaugeMetricFamily(
                "immich_server_photos",
                "Total number of photo assets across the Immich instance",
            )
            photos_metric.add_metric([], stats.get("photos", 0) or 0)
            yield photos_metric

            videos_metric = GaugeMetricFamily(
                "immich_server_videos",
                "Total number of video assets across the Immich instance",
            )
            videos_metric.add_metric([], stats.get("videos", 0) or 0)
            yield videos_metric

            usage_metric = GaugeMetricFamily(
                "immich_server_usage_bytes",
                "Total storage used by assets across the Immich instance, in bytes",
            )
            usage_metric.add_metric([], stats.get("usage", 0) or 0)
            yield usage_metric

            usage_photos_metric = GaugeMetricFamily(
                "immich_server_usage_photos_bytes",
                "Total storage used by photo assets, in bytes",
            )
            usage_photos_metric.add_metric([], stats.get("usagePhotos", 0) or 0)
            yield usage_photos_metric

            usage_videos_metric = GaugeMetricFamily(
                "immich_server_usage_videos_bytes",
                "Total storage used by video assets, in bytes",
            )
            usage_videos_metric.add_metric([], stats.get("usageVideos", 0) or 0)
            yield usage_videos_metric

            log.info("Successfully collected server statistics")

        except Exception as e:
            log.error(f"Error collecting server statistics: {e}")

    def _collect_maintenance_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect Immich maintenance status metrics.

        Emits two gauges labelled with (``action``, ``task``): an active flag
        and a 0-100 progress value.

        :return: Iterator of maintenance metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        try:
            status = self.api.get_maintenance_status()

            action = str(status.get("action") or "")
            task = str(status.get("task") or "")
            active_value = 1 if status.get("active") else 0
            progress_value = status.get("progress", 0) or 0

            active_metric = GaugeMetricFamily(
                "immich_maintenance_active",
                "1 if an Immich maintenance action is currently in progress, else 0",
                labels=["action", "task"],
            )
            active_metric.add_metric([action, task], active_value)
            yield active_metric

            progress_metric = GaugeMetricFamily(
                "immich_maintenance_progress",
                "Progress of the current Immich maintenance action, 0\u2013100",
                labels=["action", "task"],
            )
            progress_metric.add_metric([action, task], progress_value)
            yield progress_metric

            log.info("Successfully collected maintenance metrics")

        except Exception as e:
            log.error(f"Error collecting maintenance metrics: {e}")

    def _collect_job_metrics(self) -> Iterator[GaugeMetricFamily]:
        """Collect metrics for all Immich job queues.

        Emits three gauges:

        * ``immich_job_queue_count`` with labels ``queue`` and ``state``
          (state ∈ active, waiting, completed, failed, delayed, paused).
        * ``immich_job_queue_active`` with label ``queue`` (1 if the queue
          is active, else 0).
        * ``immich_job_queue_paused`` with label ``queue`` (1 if the queue
          is paused, else 0).

        :return: Iterator of job metric families.
        :rtype: Iterator[GaugeMetricFamily]
        """
        # Fixed state set: missing states default to 0 for a stable series set,
        # and any new states Immich adds later are ignored (predictable cardinality).
        job_states = (
            "active",
            "waiting",
            "completed",
            "failed",
            "delayed",
            "paused",
        )

        try:
            jobs = self.api.get_all_jobs_status()
            log.debug(f"Found {len(jobs)} job queues")

            count_metric = GaugeMetricFamily(
                "immich_job_queue_count",
                "Number of jobs in an Immich queue by state "
                "(active, waiting, completed, failed, delayed, paused)",
                labels=["queue", "state"],
            )
            active_metric = GaugeMetricFamily(
                "immich_job_queue_active",
                "Whether the Immich queue is currently active (1) or not (0), "
                "from queueStatus.isActive",
                labels=["queue"],
            )
            paused_metric = GaugeMetricFamily(
                "immich_job_queue_paused",
                "Whether the Immich queue is currently paused (1) or not (0), "
                "from queueStatus.isPaused",
                labels=["queue"],
            )

            for queue_name, status in jobs.items():
                # Defensive guards against unexpected payload shapes.
                if not isinstance(queue_name, str) or not queue_name:
                    continue
                if not isinstance(status, dict):
                    continue

                job_counts = status.get("jobCounts", {}) or {}
                for state in job_states:
                    count_metric.add_metric(
                        [queue_name, state],
                        job_counts.get(state, 0),
                    )

                queue_status = status.get("queueStatus", {}) or {}
                active_metric.add_metric(
                    [queue_name],
                    1 if queue_status.get("isActive") else 0,
                )
                paused_metric.add_metric(
                    [queue_name],
                    1 if queue_status.get("isPaused") else 0,
                )

            yield count_metric
            yield active_metric
            yield paused_metric

            log.info("Successfully collected job metrics")

        except Exception as e:
            log.error(f"Error collecting job metrics: {e}")


class PrometheusExporter:
    """Prometheus metrics exporter for Immich (legacy format for export command)"""

    def __init__(self, api: ImmichAPI) -> None:
        """Initialize the Prometheus exporter.

        :param api: The Immich API client instance.
        :type api: ImmichAPI
        """
        self.api: ImmichAPI = api
        self.metrics: list[str] = []
        self._help_type_added: set[str] = set()
        # Per-scrape memo cache for /server/statistics, shared by
        # collect_user_metrics and collect_server_statistics.
        self._server_stats_cache: dict[str, Any] | None = None

    def _get_server_stats_this_scrape(self) -> dict[str, Any]:
        """Return the /server/statistics payload, fetching at most once per scrape.

        :return: The cached ``ServerStatsResponseDto`` dict for the current
            scrape, or ``{}`` if the fetch failed.
        :rtype: dict[str, Any]
        """
        if self._server_stats_cache is None:
            self._server_stats_cache = self.api.get_server_statistics()
        return self._server_stats_cache

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
        # Only add HELP and TYPE lines once per metric name
        if help_text and name not in self._help_type_added:
            self.metrics.append(f"# HELP {name} {help_text}")
            self.metrics.append(f"# TYPE {name} gauge")
            self._help_type_added.add(name)

        label_str = ""
        if labels:
            label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
            label_str = "{" + ",".join(label_pairs) + "}"

        self.metrics.append(f"{name}{label_str} {value}")

    def collect_user_metrics(self) -> None:
        """Collect metrics for all users.

        Per-user asset counts and usage bytes come from a single
        ``/server/statistics`` call (via the per-scrape memo cache). Admin flag,
        status, deletion state, and quota fields come from the already
        fetched ``/admin/users`` response.
        """
        try:
            users = self.api.get_all_users()
            log.info(f"Found {len(users)} users")

            server_stats = self._get_server_stats_this_scrape()
            usage_by_user_list = server_stats.get("usageByUser") or []
            usage_by_user = {
                entry.get("userId"): entry
                for entry in usage_by_user_list
                if isinstance(entry, dict) and entry.get("userId")
            }

            for user in users:
                user_id = user.get("id", "")
                user_name = user.get("name", "")

                log.debug(f"Processing user: {user_name}")

                labels = {
                    "user_id": user_id,
                    "user_name": user_name,
                }
                usage_entry = usage_by_user.get(user_id, {}) or {}

                self._add_metric(
                    "immich_user_photos",
                    usage_entry.get("photos", 0) or 0,
                    labels,
                    "Number of photo assets owned by user",
                )
                self._add_metric(
                    "immich_user_videos",
                    usage_entry.get("videos", 0) or 0,
                    labels,
                    "Number of video assets owned by user",
                )
                self._add_metric(
                    "immich_user_usage_bytes",
                    usage_entry.get("usage", 0) or 0,
                    labels,
                    "Total storage used by user, in bytes",
                )
                self._add_metric(
                    "immich_user_usage_photos_bytes",
                    usage_entry.get("usagePhotos", 0) or 0,
                    labels,
                    "Storage used by user's photo assets, in bytes",
                )
                self._add_metric(
                    "immich_user_usage_videos_bytes",
                    usage_entry.get("usageVideos", 0) or 0,
                    labels,
                    "Storage used by user's video assets, in bytes",
                )

                quota_size = user.get("quotaSizeInBytes")
                if quota_size is not None:
                    self._add_metric(
                        "immich_user_quota_bytes",
                        quota_size,
                        labels,
                        "User quota in bytes",
                    )

                quota_usage = user.get("quotaUsageInBytes")
                if quota_usage is not None:
                    self._add_metric(
                        "immich_user_quota_usage_bytes",
                        quota_usage,
                        labels,
                        "User quota usage in bytes",
                    )

                self._add_metric(
                    "immich_user_admin",
                    1 if user.get("isAdmin") else 0,
                    labels,
                    "1 if the user has admin privileges, else 0",
                )

                status_value = str(user.get("status") or "").lower()
                self._add_metric(
                    "immich_user_status",
                    1,
                    {**labels, "status": status_value},
                    "User account status (stateset: emitted once per user "
                    "with the current status as a label)",
                )

                self._add_metric(
                    "immich_user_deleted",
                    1 if user.get("deletedAt") else 0,
                    labels,
                    "1 if the user has a non-null deletedAt timestamp, else 0",
                )

                log.debug(f"Successfully collected metrics for user: {user_name}")

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

                    log.debug(
                        f"Successfully collected metrics for library: {library_name}",
                    )

                except Exception as e:
                    log.error(
                        f"Error getting statistics for library {library_name}: {e}",
                    )
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

    def collect_job_metrics(self) -> None:
        """Collect metrics for all Immich job queues.

        Retrieves job queue status from the Immich API and adds one gauge per
        (queue, state) pair for ``immich_job_queue_count``, plus per-queue
        gauges for ``immich_job_queue_active`` and ``immich_job_queue_paused``.
        """
        job_states = (
            "active",
            "waiting",
            "completed",
            "failed",
            "delayed",
            "paused",
        )

        try:
            jobs = self.api.get_all_jobs_status()
            log.debug(f"Found {len(jobs)} job queues")

            for queue_name, status in jobs.items():
                if not isinstance(queue_name, str) or not queue_name:
                    continue
                if not isinstance(status, dict):
                    continue

                job_counts = status.get("jobCounts", {}) or {}
                for state in job_states:
                    self._add_metric(
                        "immich_job_queue_count",
                        job_counts.get(state, 0),
                        {"queue": queue_name, "state": state},
                        "Number of jobs in an Immich queue by state "
                        "(active, waiting, completed, failed, delayed, paused)",
                    )

                queue_status = status.get("queueStatus", {}) or {}
                self._add_metric(
                    "immich_job_queue_active",
                    1 if queue_status.get("isActive") else 0,
                    {"queue": queue_name},
                    "Whether the Immich queue is currently active (1) or not (0), "
                    "from queueStatus.isActive",
                )
                self._add_metric(
                    "immich_job_queue_paused",
                    1 if queue_status.get("isPaused") else 0,
                    {"queue": queue_name},
                    "Whether the Immich queue is currently paused (1) or not (0), "
                    "from queueStatus.isPaused",
                )

            log.info("Successfully collected job metrics")

        except Exception as e:
            log.error(f"Error collecting job metrics: {e}")

    def collect_up_metric(self) -> None:
        """Emit the ``immich_up`` health gauge.

        Never raises: ``self.api.ping()`` already returns a bool.
        """
        self._add_metric(
            "immich_up",
            1 if self.api.ping() else 0,
            help_text=(
                "1 if the Immich API responded to /server/ping successfully, "
                "0 otherwise"
            ),
        )

    def collect_server_statistics(self) -> None:
        """Collect instance-wide server statistics from ``/server/statistics``.

        Only emits the top-level totals; per-user rows are handled by
        ``collect_user_metrics`` from the same memoised fetch.
        """
        try:
            stats = self._get_server_stats_this_scrape()

            self._add_metric(
                "immich_server_photos",
                stats.get("photos", 0) or 0,
                help_text="Total number of photo assets across the Immich instance",
            )
            self._add_metric(
                "immich_server_videos",
                stats.get("videos", 0) or 0,
                help_text="Total number of video assets across the Immich instance",
            )
            self._add_metric(
                "immich_server_usage_bytes",
                stats.get("usage", 0) or 0,
                help_text=(
                    "Total storage used by assets across the Immich instance, in bytes"
                ),
            )
            self._add_metric(
                "immich_server_usage_photos_bytes",
                stats.get("usagePhotos", 0) or 0,
                help_text="Total storage used by photo assets, in bytes",
            )
            self._add_metric(
                "immich_server_usage_videos_bytes",
                stats.get("usageVideos", 0) or 0,
                help_text="Total storage used by video assets, in bytes",
            )

            log.info("Successfully collected server statistics")

        except Exception as e:
            log.error(f"Error collecting server statistics: {e}")

    def collect_maintenance_metrics(self) -> None:
        """Collect Immich maintenance status metrics."""
        try:
            status = self.api.get_maintenance_status()

            action = str(status.get("action") or "")
            task = str(status.get("task") or "")
            labels = {"action": action, "task": task}

            self._add_metric(
                "immich_maintenance_active",
                1 if status.get("active") else 0,
                labels,
                "1 if an Immich maintenance action is currently in progress, else 0",
            )
            self._add_metric(
                "immich_maintenance_progress",
                status.get("progress", 0) or 0,
                labels,
                "Progress of the current Immich maintenance action, 0\u2013100",
            )

            log.info("Successfully collected maintenance metrics")

        except Exception as e:
            log.error(f"Error collecting maintenance metrics: {e}")

    def collect_all_metrics(self) -> None:
        """Collect all metrics.

        Orchestrates the collection of all metric types. Order matches
        ``ImmichCollector.collect``: health probe first, then per-entity
        families, then instance-wide server stats, maintenance, and jobs.
        """
        log.info("Collecting health metric...")
        self.collect_up_metric()

        log.info("Collecting user metrics...")
        self.collect_user_metrics()

        log.info("Collecting album metrics...")
        self.collect_album_metrics()

        log.info("Collecting library metrics...")
        self.collect_library_metrics()

        log.info("Collecting storage metrics...")
        self.collect_storage_metrics()

        log.info("Collecting server statistics...")
        self.collect_server_statistics()

        log.info("Collecting maintenance metrics...")
        self.collect_maintenance_metrics()

        log.info("Collecting job metrics...")
        self.collect_job_metrics()

        log.info("Metrics collection completed")

    def clear_metrics(self) -> None:
        """Clear all metrics and reset state.

        This should be called before collecting new metrics to ensure
        HELP and TYPE lines are properly managed.
        """
        self.metrics = []
        self._help_type_added = set()
        self._server_stats_cache = None

    def export_metrics(self) -> str:
        """Export metrics in Prometheus format.

        :return: String containing all metrics in Prometheus format.
        :rtype: str
        """
        return "\n".join(self.metrics) + "\n"


@app.command()
def serve(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="Immich server URL (e.g., http://localhost:2283)",
    ),
    api_key: str = typer.Option(..., "--api-key", "-k", help="Immich API key"),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to serve metrics on",
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
) -> None:
    """Start HTTP server to serve Immich metrics in Prometheus format.

    :param url: The Immich server URL.
    :type url: str
    :param api_key: The Immich API key for authentication.
    :type api_key: str
    :param port: The port to serve metrics on.
    :type port: int
    :param log_level: Logging level.
    :type log_level: str
    :param log_file: Optional log file path.
    :type log_file: str | None
    :raises typer.Exit: If required parameters are missing or server fails to start.
    """
    # Validate inputs
    if not url:
        typer.echo("Error: URL is required", err=True)
        raise typer.Exit(1)

    if not api_key:
        typer.echo("Error: API key is required", err=True)
        raise typer.Exit(1)

    # Setup logging
    setup_logging(level=log_level, log_file=log_file, use_stderr=True)

    log.info("Starting Immich Prometheus Exporter HTTP Server")
    log.info(f"Immich server URL: {url}")
    log.info(f"Serving metrics on port: {port}")
    log.info(f"Log level: {log_level}")
    if log_file:
        log.info(f"Logging to file: {log_file}")
    else:
        log.info("Logging to stderr")

    try:
        # Initialize API client and collector
        api = ImmichAPI(url, api_key)
        collector = ImmichCollector(api)

        # Register collector
        REGISTRY.register(collector)
        log.info("Registered Immich collector")

        # Add exporter info
        info = Info("immich_exporter", "Immich Prometheus Exporter")
        info.info({"version": "1.0.0", "immich_url": url})

        # Start HTTP server
        start_http_server(port)
        log.info(f"HTTP server started on port {port}")
        log.info(f"Metrics available at http://localhost:{port}/metrics")
        log.info("Press Ctrl+C to stop")

        # Keep the server running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Server stopped by user")

    except Exception as e:
        log.error(f"Error starting server: {e}")
        raise typer.Exit(1)


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
) -> None:
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

    def export_once() -> bool:
        """Perform a single export operation.

        :return: True if export was successful, False otherwise.
        :rtype: bool
        """
        try:
            log.debug("Starting metrics export")

            # Clear previous metrics and reset state
            exporter.clear_metrics()

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
) -> None:
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

        # Test jobs endpoint reachability (admin-only)
        try:
            jobs = api.get_all_jobs_status()
            typer.echo(f"✅ Jobs endpoint reachable ({len(jobs)} queues)")
        except Exception as e:
            typer.echo(f"⚠️  Jobs endpoint check failed: {e}", err=True)

        # Test server statistics endpoint reachability (admin-only)
        try:
            server_stats = api.get_server_statistics()
            typer.echo(
                "✅ Server statistics reachable "
                f"(photos={server_stats.get('photos', 0)}, "
                f"videos={server_stats.get('videos', 0)}, "
                f"users={len(server_stats.get('usageByUser') or [])})",
            )
        except Exception as e:
            typer.echo(f"⚠️  Server statistics check failed: {e}", err=True)

        # Test /server/ping reachability (does not require auth).
        try:
            if api.ping():
                typer.echo("✅ Immich reachable (ping=pong)")
            else:
                typer.echo("⚠️  Ping check failed", err=True)
        except Exception as e:
            typer.echo(f"⚠️  Ping check failed: {e}", err=True)

        # Test maintenance status reachability.
        try:
            maint = api.get_maintenance_status()
            typer.echo(
                "✅ Maintenance status reachable "
                f"(active={maint.get('active')}, "
                f"progress={maint.get('progress')})",
            )
        except Exception as e:
            typer.echo(f"⚠️  Maintenance status check failed: {e}", err=True)

    except Exception as e:
        typer.echo(f"❌ Connection failed: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
