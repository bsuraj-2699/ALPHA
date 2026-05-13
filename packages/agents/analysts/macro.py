"""Macro analyst: rates, GDP, inflation, FX, sector rotation.

Owns the single rule category ``macro``. With one category the default
:meth:`aggregate` (mean over active categories) reduces to that category's
score, so no override is needed.
"""

from __future__ import annotations

from typing import ClassVar

from packages.agents.analysts._base import BaseAnalyst
from packages.shared.schemas import Pillar


class MacroAnalyst(BaseAnalyst):
    pillar: ClassVar[Pillar] = "macro"
    categories: ClassVar[tuple[str, ...]] = ("macro",)
