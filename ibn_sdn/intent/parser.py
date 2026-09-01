"""Composição da classificação e extração em uma intenção estruturada."""

from __future__ import annotations

from pathlib import Path

from ibn_sdn.intent.models import NetworkIntent
from ibn_sdn.nlp.classifier import TfidfSvmIntentClassifier
from ibn_sdn.nlp.entity_extractor import EntityExtractor


class IntentParser:
    """Ponto de entrada para os Milestones 1 e 2; não executa mudanças de rede."""

    UNKNOWN_VOCABULARY_COVERAGE_THRESHOLD = 0.40

    def __init__(
        self,
        classifier: TfidfSvmIntentClassifier | None = None,
        extractor: EntityExtractor | None = None,
    ) -> None:
        self.classifier = classifier or TfidfSvmIntentClassifier()
        self.extractor = extractor or EntityExtractor()

    def train(self, dataset_path: Path) -> "IntentParser":
        self.classifier.fit_from_csv(dataset_path)
        return self

    def parse(self, text: str) -> NetworkIntent:
        if not text or not text.strip():
            raise ValueError("A instrução não pode estar vazia.")
        entities = self.extractor.extract(text)
        intent_class, vocabulary_coverage = self.classifier.predict_with_confidence(text)
        if vocabulary_coverage < self.UNKNOWN_VOCABULARY_COVERAGE_THRESHOLD:
            return NetworkIntent(action="UNKNOWN")
        return NetworkIntent(action=_to_network_action(intent_class, text), **entities)


def _default_dataset_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "processed" / "training_intents.csv"


def _default_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / "intent_classifier.joblib"


def _to_network_action(intent_class: str, text: str) -> str:
    """Normaliza a classe do dataset para a ação estável do contrato interno."""
    normalized = text.lower()
    if intent_class == "apply_filter":
        if any(term in normalized for term in ("block", "deny", "drop", "close", "not be able")):
            return "BLOCK_ACCESS"
        return "ALLOW_ACCESS"
    return intent_class.upper().replace("+", "_AND_")


def parse_intent(text: str, *, retrain: bool = False) -> NetworkIntent:
    """Interpreta uma frase com o modelo salvo; treina somente na primeira execução."""
    model_path = _default_model_path()
    if retrain or not model_path.exists():
        classifier = TfidfSvmIntentClassifier().fit_from_csv(_default_dataset_path())
        classifier.save(model_path)
    else:
        classifier = TfidfSvmIntentClassifier.load(model_path)
    return IntentParser(classifier=classifier).parse(text)
