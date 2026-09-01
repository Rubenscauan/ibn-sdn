from ibn_sdn.nlp.entity_extractor import EntityExtractor


def test_extracts_hosts_from_access_pattern() -> None:
    assert EntityExtractor().extract("block host1 from accessing host2") == {
        "source": "host1",
        "destination": "host2",
    }


def test_extracts_ip_addresses() -> None:
    assert EntityExtractor().extract("block 10.0.0.1 from accessing 10.0.0.2") == {
        "source": "10.0.0.1",
        "destination": "10.0.0.2",
    }
