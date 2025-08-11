"""Immich Prometheus Exporter

A Python package that exports Immich statistics as Prometheus metrics.
"""

__version__ = "1.0.0"
__author__ = "Immich Prometheus Exporter Contributors"
__email__ = ""
__description__ = "A Python script that exports Immich statistics as Prometheus metrics"

from .main import app

__all__ = ["app"]
