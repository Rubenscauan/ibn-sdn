from copy import deepcopy
from pathlib import Path

import pytest

from ibn_sdn.control import ControlIntent, NetworkState, SimulationController
from ibn_sdn.intent.rasa_control import from_rasa_result


def controller():
    return SimulationController.from_yaml(Path("knowledge/control_topology.yaml"),
                                         Path("knowledge/control_policies.yaml"))


def test_protected_host_cannot_be_blocked_by_name_or_ip():
    system = controller()
    before = deepcopy(system.state)
    for identifier in ("host A".replace(" ", ""), "10.0.0.1"):
        result = system.submit(ControlIntent("BLOCK_HOST", target=identifier))
        assert result.code == "HOST_PROTECTED"
    assert system.state == before


def test_block_changes_simulation_and_prevents_later_flow():
    system = controller()
    assert system.submit(ControlIntent("BLOCK_HOST", target="hostb")).status == "SIMULATED"
    assert system.state.blocked_hosts == {"hostb"}
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hostb", destination="hostc")).code == "EXISTING_BLOCK"


def test_capacity_is_shared_and_failed_update_preserves_previous_reservation():
    system = controller()
    first = ControlIntent("ALLOW_FLOW", source="hosta", destination="hostb", bandwidth_mbps=30)
    assert system.submit(first).status == "SIMULATED"
    before = deepcopy(system.state)
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hosta", destination="hostc", bandwidth_mbps=30)).code == "INSUFFICIENT_CAPACITY"
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hosta", destination="hostb", bandwidth_mbps=70)).code == "INSUFFICIENT_CAPACITY"
    assert system.state == before
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hosta", destination="hostb", bandwidth_mbps=40)).status == "SIMULATED"


def test_alternative_path_is_used_when_shortest_is_full():
    system = controller()
    system.state.nodes.add("s4")
    system.state.links.update({("s1", "s4"): 100, ("s2", "s4"): 100})
    result = system.submit(ControlIntent("ALLOW_FLOW", source="hosta", destination="hostb", bandwidth_mbps=80))
    assert result.status == "SIMULATED"
    assert "s4" in result.path


def test_unknown_disconnected_and_dry_run():
    system = controller()
    assert system.submit(ControlIntent("BLOCK_HOST", target="missing")).code == "UNKNOWN_HOST"
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hostb", destination="hostd")).code == "NO_PATH"
    before = deepcopy(system.state)
    assert system.submit(ControlIntent("BLOCK_HOST", target="hostb"), dry_run=True).status == "APPROVED"
    assert system.state == before


def test_deny_overrides_allow_and_no_rule_denies():
    system = controller()
    request = ControlIntent("ALLOW_FLOW", source="hostb", destination="hostc")
    system.rules.append({"id": "explicit-deny", "operation": "ALLOW_FLOW", "effect": "deny"})
    for rules in (system.rules, list(reversed(system.rules)), []):
        configured = SimulationController(system.state, set(), rules)
        assert configured.submit(request).code == "POLICY_DENIED"


def test_blocking_flow_releases_bandwidth_but_does_not_block_reverse_direction():
    system = controller()
    system.submit(ControlIntent("ALLOW_FLOW", source="hostb", destination="hostc", bandwidth_mbps=20))
    assert system.submit(ControlIntent("BLOCK_FLOW", source="hostb", destination="hostc")).status == "SIMULATED"
    assert not system.state.flows
    assert system.submit(ControlIntent("ALLOW_FLOW", source="hostc", destination="hostb")).status == "SIMULATED"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_bandwidth_is_rejected(value):
    with pytest.raises(ValueError):
        ControlIntent("ALLOW_FLOW", source="hostb", destination="hostc", bandwidth_mbps=value)


def test_rasa_adapter_rejects_ambiguous_or_incomplete_prediction():
    result = {"intent": {"name": "block_host", "confidence": 0.99},
              "entities": [{"entity": "target", "value": "hosta", "confidence_entity": 0.99}]}
    assert from_rasa_result(result) == ControlIntent("BLOCK_HOST", target="hosta")
    result["entities"] *= 2
    with pytest.raises(ValueError, match="repetida"):
        from_rasa_result(result)
    result["entities"] = []
    with pytest.raises(ValueError):
        from_rasa_result(result)


def test_rasa_adapter_does_not_silently_expand_port_block_to_entire_host():
    result = {"text": "bloqueie o hosta na porta 80",
              "intent": {"name": "block_host", "confidence": 0.99},
              "entities": [{"entity": "target", "value": "hosta", "confidence_entity": 0.99}]}
    with pytest.raises(ValueError, match="fora do escopo"):
        from_rasa_result(result)


def test_performance_workload_matches_constructed_reference():
    from scripts.benchmark_control import make_system, workload

    for load in (0, 0.8):
        system = make_system(8, 50, load)
        for intent, expected in workload(load):
            assert system.submit(intent, dry_run=True).code == expected
