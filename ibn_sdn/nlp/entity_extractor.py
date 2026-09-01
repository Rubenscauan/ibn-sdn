"""Extração simples e determinística de entidades para o MVP."""

from __future__ import annotations

import re


def _entity(name: str) -> str:
    return rf"(?P<{name}>[A-Za-z][A-Za-z0-9_-]*|(?:\d{{1,3}}\.){{3}}\d{{1,3}})"


class EntityExtractor:
    """Extrai origem e destino de padrões de acesso comuns em inglês."""

    _PATTERNS = (
        re.compile(
            rf"\b{_entity('source')}\s+(?:from\s+)?(?:accessing|to\s+access|reach(?:ing)?|communicat(?:e|ing)\s+with)\s+{_entity('destination')}\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\bbetween\s+{_entity('source')}\s+and\s+{_entity('destination')}\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\bfrom\s+{_entity('source')}\s+to\s+{_entity('destination')}\b",
            re.IGNORECASE,
        ),
    )

    def extract(self, text: str) -> dict[str, str | None]:
        for pattern in self._PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "source": match.group("source").lower(),
                    "destination": match.group("destination").lower(),
                }
        return {"source": None, "destination": None}
