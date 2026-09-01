from ibn_sdn.nlp.classifier import TfidfSvmIntentClassifier


def test_tfidf_svm_classifies_block_access() -> None:
    classifier = TfidfSvmIntentClassifier().fit(
        ["block access", "deny traffic", "allow access", "permit traffic"],
        ["BLOCK_ACCESS", "BLOCK_ACCESS", "ALLOW_ACCESS", "ALLOW_ACCESS"],
    )

    assert classifier.predict("block traffic") == "BLOCK_ACCESS"


def test_tfidf_svm_returns_vocabulary_coverage() -> None:
    classifier = TfidfSvmIntentClassifier().fit(
        ["block access", "deny traffic", "allow access", "permit traffic"],
        ["BLOCK_ACCESS", "BLOCK_ACCESS", "ALLOW_ACCESS", "ALLOW_ACCESS"],
    )

    label, confidence = classifier.predict_with_confidence("block traffic")

    assert label == "BLOCK_ACCESS"
    assert 0 <= confidence <= 1


def test_tfidf_svm_can_be_saved_and_loaded(tmp_path) -> None:
    classifier = TfidfSvmIntentClassifier().fit(
        ["block access", "deny traffic", "allow access", "permit traffic"],
        ["BLOCK_ACCESS", "BLOCK_ACCESS", "ALLOW_ACCESS", "ALLOW_ACCESS"],
    )
    model_path = tmp_path / "intent_classifier.joblib"

    classifier.save(model_path)
    restored = TfidfSvmIntentClassifier.load(model_path)

    assert restored.predict("block access") == "BLOCK_ACCESS"
