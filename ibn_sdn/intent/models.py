"""Contrato entre a camada de NLP e as futuras camadas determinísticas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True, slots=True)
class NetworkIntent:
    """Uma intenção de rede interpretada, ainda sem autorização ou execução."""

    action: str
    source: str | None = None
    destination: str | None = None
    protocol: str | None = None
    bandwidth: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        """Retorna somente os campos definidos, em formato adequado para integração."""
        return {key: value for key, value in asdict(self).items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
