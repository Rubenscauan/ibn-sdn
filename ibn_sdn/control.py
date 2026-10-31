"""Validação de intenções e execução em um estado de rede simulado em memória."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import math
from pathlib import Path

import yaml


OPERATIONS = {"BLOCK_HOST", "BLOCK_FLOW", "ALLOW_FLOW"}


@dataclass(frozen=True)
class ControlIntent:
    operation: str
    source: str | None = None
    destination: str | None = None
    target: str | None = None
    bandwidth_mbps: float = 0

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise ValueError("Operação não suportada.")
        for value in (self.source, self.destination, self.target):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Identificadores de hosts devem ser textos não vazios.")
        if isinstance(self.bandwidth_mbps, bool) or not isinstance(self.bandwidth_mbps, (int, float)):
            raise ValueError("A banda deve ser numérica, em Mbps.")
        if not math.isfinite(self.bandwidth_mbps) or self.bandwidth_mbps < 0:
            raise ValueError("A banda deve ser finita e não negativa.")
        if self.operation == "BLOCK_HOST":
            if not self.target or self.source or self.destination:
                raise ValueError("BLOCK_HOST exige somente target.")
        elif not self.source or not self.destination or self.target:
            raise ValueError("Operações de fluxo exigem source e destination.")
        if self.operation != "ALLOW_FLOW" and self.bandwidth_mbps:
            raise ValueError("Somente ALLOW_FLOW aceita requisito de banda.")


@dataclass(frozen=True)
class ControlDecision:
    status: str
    code: str
    reason: str
    path: tuple[str, ...] = ()
    policy_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class NetworkState:
    hosts: dict[str, str]
    nodes: set[str]
    links: dict[tuple[str, str], float]
    blocked_hosts: set[str] = field(default_factory=set)
    blocked_flows: set[tuple[str, str]] = field(default_factory=set)
    flows: dict[tuple[str, str], tuple[tuple[str, ...], float]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "NetworkState":
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        hosts = document["hosts"]
        nodes = set(document["switches"]) | set(hosts)
        if not hosts or len(nodes) != len(document["switches"]) + len(hosts):
            raise ValueError("Defina hosts e switches com identificadores distintos.")
        if len(set(hosts.values())) != len(hosts):
            raise ValueError("Os IPs dos hosts devem ser únicos.")
        links: dict[tuple[str, str], float] = {}
        for link in document["links"]:
            left, right = link["source"], link["target"]
            capacity = link["capacity_mbps"]
            key = tuple(sorted((left, right)))
            if left not in nodes or right not in nodes or left == right or key in links:
                raise ValueError("Enlace inválido ou duplicado.")
            if isinstance(capacity, bool) or not isinstance(capacity, (int, float)):
                raise ValueError("Capacidade deve ser numérica.")
            if not math.isfinite(capacity) or capacity <= 0:
                raise ValueError("Capacidade deve ser positiva e finita.")
            links[key] = float(capacity)
        return cls(hosts=dict(hosts), nodes=nodes, links=links)

    def resolve(self, identifier: str) -> str | None:
        for host, ip in self.hosts.items():
            if identifier.casefold() == host.casefold() or identifier == ip:
                return host
        return None

    def path(self, source: str, destination: str, bandwidth: float | None,
             replacing: tuple[str, str]) -> tuple[str, ...]:
        capacities = dict(self.links)
        if bandwidth is not None:
            for key, (route, reserved) in self.flows.items():
                if key != replacing:
                    for left, right in zip(route, route[1:]):
                        capacities[tuple(sorted((left, right)))] -= reserved
        adjacency: dict[str, list[str]] = {node: [] for node in self.nodes}
        for (left, right), available in sorted(capacities.items()):
            if bandwidth is None or available + 1e-9 >= bandwidth:
                adjacency[left].append(right)
                adjacency[right].append(left)
        queue = deque([(source, (source,))])
        visited = {source}
        while queue:
            node, route = queue.popleft()
            if node == destination:
                return route
            for neighbor in adjacency[node]:
                if neighbor in visited or neighbor in self.blocked_hosts:
                    continue
                # Hosts não encaminham tráfego de outros hosts.
                if neighbor in self.hosts and neighbor != destination:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, route + (neighbor,)))
        return ()


class SimulationController:
    """Decide e aplica atomicamente no modelo local, sem conexão com SDN."""

    def __init__(self, state: NetworkState, protected_hosts: set[str], rules: list[dict]):
        self.state = state
        self.protected_hosts = protected_hosts
        self.rules = rules
        if not protected_hosts <= state.hosts.keys():
            raise ValueError("Política de proteção referencia host inexistente.")
        ids: set[str] = set()
        for rule in rules:
            if not {"id", "operation", "effect"} <= rule.keys():
                raise ValueError("Regra exige id, operation e effect.")
            if rule["id"] in ids or rule["operation"] not in OPERATIONS | {"*"}:
                raise ValueError("ID duplicado ou operação de política inválida.")
            ids.add(rule["id"])
            if rule["effect"] not in {"allow", "deny"}:
                raise ValueError("Efeito deve ser allow ou deny.")
            if set(rule) - {"id", "operation", "effect", "source", "destination", "target"}:
                raise ValueError("Campo de política não suportado.")
            for field_name in ("source", "destination", "target"):
                if rule.get(field_name, "*") not in state.hosts.keys() | {"*"}:
                    raise ValueError("Regra referencia host inexistente.")

    @classmethod
    def from_yaml(cls, topology: Path, policies: Path) -> "SimulationController":
        document = yaml.safe_load(policies.read_text(encoding="utf-8"))
        return cls(NetworkState.from_yaml(topology), set(document.get("protected_hosts", [])),
                   document.get("rules", []))

    def _decide(self, intent: ControlIntent) -> tuple[ControlDecision, ControlIntent]:
        identifiers = {name: getattr(intent, name) for name in ("source", "destination", "target")}
        resolved: dict[str, str | None] = {}
        for name, identifier in identifiers.items():
            resolved[name] = self.state.resolve(identifier) if identifier else None
            if identifier and resolved[name] is None:
                return ControlDecision("REJECTED", "UNKNOWN_HOST", f"Host desconhecido: {identifier}"), intent
        normalized = ControlIntent(intent.operation, **resolved, bandwidth_mbps=intent.bandwidth_mbps)
        affected = {host for host in resolved.values() if host}
        if intent.operation.startswith("BLOCK") and affected & self.protected_hosts:
            return ControlDecision("REJECTED", "HOST_PROTECTED", "A operação afeta um host protegido."), normalized
        matching = [rule for rule in self.rules if
                    rule["operation"] in {"*", intent.operation} and all(
                        rule.get(name, "*") == "*" or rule[name] == resolved[name]
                        for name in identifiers)]
        policy_ids = tuple(rule["id"] for rule in matching)
        if not matching or any(rule["effect"] == "deny" for rule in matching):
            return ControlDecision("REJECTED", "POLICY_DENIED",
                                   "Política proíbe a operação ou não há permissão explícita.",
                                   policy_ids=policy_ids), normalized
        route: tuple[str, ...] = ()
        if intent.operation == "ALLOW_FLOW":
            source, destination = normalized.source, normalized.destination
            assert source and destination
            if source == destination:
                return ControlDecision("REJECTED", "INVALID_ENDPOINTS", "Origem e destino devem ser diferentes."), normalized
            if affected & self.state.blocked_hosts or (source, destination) in self.state.blocked_flows:
                return ControlDecision("REJECTED", "EXISTING_BLOCK", "Existe bloqueio ativo para o pedido."), normalized
            if not self.state.path(source, destination, None, (source, destination)):
                return ControlDecision("REJECTED", "NO_PATH", "Não existe caminho entre os hosts."), normalized
            route = self.state.path(source, destination, intent.bandwidth_mbps, (source, destination))
            if not route:
                return ControlDecision("REJECTED", "INSUFFICIENT_CAPACITY", "Nenhum caminho tem a banda disponível solicitada."), normalized
        return ControlDecision("APPROVED", "VALIDATED", "Intenção autorizada e viável no modelo.", route, policy_ids), normalized

    def submit(self, intent: ControlIntent, *, dry_run: bool = False) -> ControlDecision:
        decision, intent = self._decide(intent)
        if decision.status != "APPROVED" or dry_run:
            return decision
        if intent.operation == "BLOCK_HOST":
            assert intent.target
            self.state.blocked_hosts.add(intent.target)
            self.state.flows = {key: value for key, value in self.state.flows.items() if intent.target not in key}
        else:
            assert intent.source and intent.destination
            key = (intent.source, intent.destination)
            if intent.operation == "BLOCK_FLOW":
                self.state.blocked_flows.add(key)
                self.state.flows.pop(key, None)
            else:
                self.state.flows[key] = (decision.path, intent.bandwidth_mbps)
        return ControlDecision("SIMULATED", "APPLIED_TO_SIMULATION",
                               "Alteração aplicada somente ao estado simulado em memória.",
                               decision.path, decision.policy_ids)
