from scripts.prepare_dataset import parse_rasa_markdown


def test_converts_rasa_annotations_to_plain_text() -> None:
    rows = parse_rasa_markdown(
        "## intent:apply_filter\n- [block](action:DENY) [host1](source) from [host2](target)\n"
    )

    assert rows == [{"text": "block host1 from host2", "intent": "apply_filter"}]
