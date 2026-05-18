"""
Structured JSON logger — mirrors Google Cloud Logging format.
In production: replace with google.cloud.logging client.
"""
import json
import logging
import sys
from datetime import datetime


class StructuredLogger:
    """
    Emits JSON logs compatible with Cloud Logging ingestion.
    GCP swap: google.cloud.logging.Client().setup_logging()
    """
    def __init__(self, component: str):
        self.component = component
        self._logger = logging.getLogger(component)
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.DEBUG)

    def _emit(self, severity: str, event: str, **kwargs):
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity": severity,
            "component": self.component,
            "event": event,
            **kwargs
        }
        self._logger.info(json.dumps(payload))

    def info(self, event: str, **kwargs): self._emit("INFO", event, **kwargs)
    def error(self, event: str, **kwargs): self._emit("ERROR", event, **kwargs)
    def warning(self, event: str, **kwargs): self._emit("WARNING", event, **kwargs)
    def debug(self, event: str, **kwargs): self._emit("DEBUG", event, **kwargs)
