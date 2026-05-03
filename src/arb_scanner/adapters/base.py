"""Adapter abstract base class."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from ..config import Settings
from ..models import Domain, NormalizedMarket

logger = logging.getLogger(__name__)


class Adapter(ABC):
    """One per venue. Returns a list of NormalizedMarket on each fetch."""

    id: str = ""
    domains: tuple[Domain, ...] = ()
    requires_auth: bool = False

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @abstractmethod
    async def fetch_markets(self) -> list[NormalizedMarket]:
        """Fetch and normalize markets from this venue."""

    def is_enabled(self) -> bool:
        """Whether this adapter has the credentials it needs and the user hasn't disabled it."""
        if self.settings.enabled_venues is not None and self.id not in self.settings.enabled_venues:
            return False
        return self.has_credentials()

    def has_credentials(self) -> bool:
        return True  # default: read-only public

    def domain_enabled(self) -> bool:
        target = self.settings.scanner_domain
        if target == "hybrid":
            return True
        return target in self.domains
