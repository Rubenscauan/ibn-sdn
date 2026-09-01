from pathlib import Path

from ibn_sdn.intent.parser import IntentParser


def test_parse_intent_builds_network_intent() -> None:
    parser = IntentParser().train(Path("data/processed/training_intents.csv"))
    intent = parser.parse("block host1 from accessing host2")

    assert intent.to_dict() == {
        "action": "BLOCK_ACCESS",
        "source": "host1",
        "destination": "host2",
    }


def test_parse_intent_handles_between_phrase() -> None:
    parser = IntentParser().train(Path("data/processed/training_intents.csv"))
    intent = parser.parse("block traffic between host1 and host2")

    assert intent.action == "BLOCK_ACCESS"
    assert intent.source == "host1"
    assert intent.destination == "host2"


def test_parse_intent_returns_unknown_for_unrelated_sentence() -> None:
    parser = IntentParser().train(Path("data/processed/training_intents.csv"))

    intent = parser.parse("what is the weather forecast for tomorrow?")

    assert intent.to_dict() == {"action": "UNKNOWN"}
