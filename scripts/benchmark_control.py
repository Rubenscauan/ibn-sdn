"""Mede o validador em grafos sintéticos com decisões esperadas conhecidas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
from time import perf_counter_ns

from ibn_sdn.control import ControlIntent, NetworkState, SimulationController


def make_system(switches: int, rule_count: int, load: float) -> SimulationController:
    if switches < 2 or rule_count < 1 or not 0 <= load < 1:
        raise ValueError("Use >=2 switches, >=1 regra e carga em [0, 1).")
    hosts = {f"h{i}": f"10.0.0.{i + 1}" for i in range(4)}
    nodes = set(hosts) | {f"s{i}" for i in range(switches)} | {"isolated"}
    links = {tuple(sorted((f"s{i}", f"s{i + 1}"))): 100.0 for i in range(switches - 1)}
    for host, switch in (("h0", "s0"), ("h1", f"s{switches - 1}"), ("h2", "s0"), ("h3", "isolated")):
        links[tuple(sorted((host, switch)))] = 1000.0
    state = NetworkState(hosts, nodes, links)
    route = ("h0",) + tuple(f"s{i}" for i in range(switches)) + ("h1",)
    state.flows[("h0", "h1")] = (route, load * 100)
    rules = [{"id": "allow-flow", "operation": "ALLOW_FLOW", "effect": "allow"}]
    rules.extend({"id": f"other-{i}", "operation": "BLOCK_FLOW", "effect": "allow",
                  "source": "h0", "destination": "h1"} for i in range(rule_count - 1))
    return SimulationController(state, {"h0"}, rules)


def workload(load: float) -> list[tuple[ControlIntent, str]]:
    # Oráculo definido pela construção: caminho único de 100 Mbps e carga conhecida.
    return [
        (ControlIntent("ALLOW_FLOW", source="h2", destination="h1", bandwidth_mbps=10), "VALIDATED"),
        (ControlIntent("ALLOW_FLOW", source="h2", destination="h1", bandwidth_mbps=30),
         "VALIDATED" if 100 * (1 - load) >= 30 else "INSUFFICIENT_CAPACITY"),
        (ControlIntent("BLOCK_HOST", target="h0"), "HOST_PROTECTED"),
        (ControlIntent("BLOCK_HOST", target="h1"), "POLICY_DENIED"),
        (ControlIntent("ALLOW_FLOW", source="h2", destination="h3"), "NO_PATH"),
        (ControlIntent("BLOCK_HOST", target="missing"), "UNKNOWN_HOST"),
    ]


def measure(system: SimulationController, cases: list, count: int, seed: int) -> dict:
    requests = [cases[index % len(cases)] for index in range(count)]
    random.Random(seed).shuffle(requests)
    for intent, _ in requests[:min(20, count)]:
        system.submit(intent, dry_run=True)
    durations = []
    false_acceptances = false_rejections = correct_reasons = 0
    start_batch = perf_counter_ns()
    for intent, expected in requests:
        start = perf_counter_ns()
        decision = system.submit(intent, dry_run=True)
        durations.append((perf_counter_ns() - start) / 1e6)
        false_acceptances += decision.status == "APPROVED" and expected != "VALIDATED"
        false_rejections += decision.status != "APPROVED" and expected == "VALIDATED"
        correct_reasons += decision.code == expected
    seconds = (perf_counter_ns() - start_batch) / 1e9
    return {"requests": count, "false_acceptances": false_acceptances,
            "false_rejections": false_rejections, "correct_reason_rate": correct_reasons / count,
            "mean_ms": statistics.mean(durations), "median_ms": statistics.median(durations),
            "p95_ms": sorted(durations)[math.ceil(0.95 * count) - 1],
            "throughput_requests_per_second": count / seconds, "latencies_ms": durations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--switches", type=int, nargs="+", default=[8, 32, 128])
    parser.add_argument("--rules", type=int, nargs="+", default=[1, 50])
    parser.add_argument("--loads", type=float, nargs="+", default=[0.0, 0.8])
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--requests", type=int, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repetitions < 1 or args.requests < 6:
        parser.error("Use ao menos uma repetição e seis pedidos por repetição.")
    root = Path(__file__).resolve().parents[1]
    output = args.output or root / "results/control" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"python": platform.python_version(), "platform": platform.platform(),
                "seed": 42, "scope": "validator_only; synthetic chain; sequential dry-run",
                "switches": args.switches, "rules": args.rules, "loads": args.loads,
                "repetitions": args.repetitions, "requests_per_run": args.requests,
                "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in ("ibn_sdn/control.py", "scripts/benchmark_control.py")}}
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    with (output / "runs.jsonl").open("w", encoding="utf-8") as destination:
        for switches in args.switches:
            for rules in args.rules:
                for load in args.loads:
                    runs = []
                    for repetition in range(args.repetitions):
                        system = make_system(switches, rules, load)
                        result = {"switches": switches, "rules": rules, "load": load,
                                  "repetition": repetition, **measure(system, workload(load), args.requests, 42 + repetition)}
                        destination.write(json.dumps(result) + "\n")
                        runs.append(result)
                    print(json.dumps({"switches": switches, "rules": rules, "load": load,
                                      "mean_ms": round(statistics.mean(run["mean_ms"] for run in runs), 4),
                                      "false_acceptances": sum(run["false_acceptances"] for run in runs),
                                      "false_rejections": sum(run["false_rejections"] for run in runs)}))
    print(f"Medições e configuração: {output}")


if __name__ == "__main__":
    main()
