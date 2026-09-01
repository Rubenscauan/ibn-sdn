"""Classificação de intenção com TF-IDF e SVM linear."""

from __future__ import annotations

import csv
from pathlib import Path

from joblib import dump, load
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC


class TfidfSvmIntentClassifier:
    """Classificador treinável que isola a escolha do algoritmo do restante do pipeline."""

    def __init__(self) -> None:
        self._pipeline = Pipeline(
            [
                ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)),
                ("classifier", LinearSVC()),
            ]
        )
        self._is_trained = False

    def fit(self, texts: list[str], labels: list[str]) -> "TfidfSvmIntentClassifier":
        if len(texts) != len(labels) or not texts:
            raise ValueError("texts e labels devem ter o mesmo tamanho e conter exemplos.")
        self._pipeline.fit(texts, labels)
        self._is_trained = True
        return self

    def fit_from_csv(self, dataset_path: Path) -> "TfidfSvmIntentClassifier":
        with dataset_path.open(encoding="utf-8", newline="") as dataset:
            rows = list(csv.DictReader(dataset))
        if not rows or not {"text", "intent"}.issubset(rows[0]):
            raise ValueError("O dataset deve conter as colunas 'text' e 'intent'.")
        return self.fit([row["text"] for row in rows], [row["intent"] for row in rows])

    def predict(self, text: str) -> str:
        return self.predict_with_confidence(text)[0]

    def predict_with_confidence(self, text: str) -> tuple[str, float]:
        """Retorna a classe prevista e a cobertura do vocabulário aprendido."""
        if not self._is_trained:
            raise RuntimeError("O classificador precisa ser treinado antes da predição.")
        vectorizer = self._pipeline.named_steps["tfidf"]
        terms = vectorizer.build_analyzer()(text)
        known_terms = sum(term in vectorizer.vocabulary_ for term in terms)
        coverage = known_terms / len(terms) if terms else 0.0
        return str(self._pipeline.predict([text])[0]), coverage

    def save(self, model_path: Path) -> None:
        """Persiste o pipeline treinado para uso em execuções futuras."""
        if not self._is_trained:
            raise RuntimeError("Não é possível salvar um classificador sem treinamento.")
        model_path.parent.mkdir(parents=True, exist_ok=True)
        dump(self._pipeline, model_path)

    @classmethod
    def load(cls, model_path: Path) -> "TfidfSvmIntentClassifier":
        """Restaura um pipeline previamente treinado."""
        if not model_path.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {model_path}")
        instance = cls()
        instance._pipeline = load(model_path)
        instance._is_trained = True
        return instance
