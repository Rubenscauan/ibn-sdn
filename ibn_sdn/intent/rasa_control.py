"""Adaptador restrito do resultado Rasa para as operações do demonstrador."""

from __future__ import annotations

import math
import re

from ibn_sdn.control import ControlIntent


def from_rasa_result(result: dict, *, minimum_confidence: float = 0.7) -> ControlIntent:
    """Rejeita baixa confiança, campos ausentes, repetidos ou fora do contrato."""
    intent = result.get("intent", {})
    operations = {"block_host": "BLOCK_HOST", "block_flow": "BLOCK_FLOW", "allow_flow": "ALLOW_FLOW"}
    confidence = intent.get("confidence", 0)
    if not isinstance(confidence, (float, int)) or not math.isfinite(confidence):
        raise ValueError("Confiança inválida na intenção.")
    if intent.get("name") not in operations or confidence < minimum_confidence:
        raise ValueError("Intenção desconhecida ou confiança insuficiente.")
    # Guarda conservadora do demonstrador: qualificadores fora do escopo
    # não devem virar um bloqueio global ou uma reserva com unidade errada.
    text = result.get("text", "").casefold()
    if re.search(r"\b(não|nao|not|except|exceto|porta|port|tcp|udp|gbps|kbps|latência|latency)\b", text):
        raise ValueError("Negação ou restrição fora do escopo operacional; esclareça o pedido.")
    values: dict[str, object] = {}
    for entity in result.get("entities", []):
        name = entity.get("entity")
        if name not in {"source", "destination", "target", "bandwidth_mbps"} or name in values:
            raise ValueError("Entidade não suportada ou repetida; esclareça o pedido.")
        confidence = entity.get("confidence_entity", 0)
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or confidence < minimum_confidence:
            raise ValueError("Confiança insuficiente na entidade extraída.")
        values[name] = entity.get("value")
    if "bandwidth_mbps" in values:
        values["bandwidth_mbps"] = float(str(values["bandwidth_mbps"]).replace(",", "."))
    return ControlIntent(operation=operations[intent["name"]], **values)


async def parse_with_rasa(model_path: str, text: str) -> ControlIntent:
    from rasa.core.agent import Agent

    agent = Agent.load(model_path)
    result = await agent.parse_message(text)
    return from_rasa_result(result)
