from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WebexApiClient:
    base_url: str
    token: str

