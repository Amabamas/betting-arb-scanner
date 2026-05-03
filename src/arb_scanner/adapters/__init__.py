"""Adapter registry."""

from __future__ import annotations

from .azuro import AzuroAdapter
from .base import Adapter
from .cloudbet import CloudbetAdapter
from .drift import DriftBetAdapter
from .kalshi import KalshiAdapter
from .limitless import LimitlessAdapter
from .monaco import MonacoAdapter
from .overtime import OvertimeAdapter
from .polkamarkets import PolkamarketsAdapter
from .polymarket import PolymarketAdapter
from .ps3838 import PS3838Adapter
from .sxbet import SxBetAdapter
from .zeitgeist import ZeitgeistAdapter

ALL_ADAPTERS: list[type[Adapter]] = [
    PolymarketAdapter,
    KalshiAdapter,
    LimitlessAdapter,
    DriftBetAdapter,
    SxBetAdapter,
    AzuroAdapter,
    CloudbetAdapter,
    PS3838Adapter,
    OvertimeAdapter,
    ZeitgeistAdapter,
    PolkamarketsAdapter,
    MonacoAdapter,
]

__all__ = ["ALL_ADAPTERS", "Adapter"]
