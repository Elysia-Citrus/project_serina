from __future__ import annotations

from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request
import json


@dataclass(frozen=True)
class MemOSHealth:
    ok: bool
    payload: dict[str, object]


class MyNeuroMemOSClient:
    """Tiny optional adapter point for the future MemOS bridge."""

    def __init__(self, *, base_url: str, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def healthcheck(self) -> MemOSHealth:
        request = urllib_request.Request(url=self.base_url + "/health", method="GET")
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_s) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.URLError:
            return MemOSHealth(ok=False, payload={})
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {"raw": raw_body}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        return MemOSHealth(ok=True, payload=payload)
