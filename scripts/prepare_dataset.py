"""Converte o dataset Rasa NLU original em CSV para o classificador scikit-learn."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "raw" / "nlu.md"
OUTPUT = ROOT / "data" / "processed" / "training_intents.csv"
HEADER = re.compile(r"^##\s+intent:(?P<intent>[^\s]+)\s*$")
ANNOTATION = re.compile(r"\[(?P<value>[^\]]+)\]\([^\)]+\)")


def parse_rasa_markdown(content: str) -> list[dict[str, str]]:
    """Extrai textos e intent labels do formato Markdown usado pelo Rasa 2.x."""
    current_intent: str | None = None
    rows: list[dict[str, str]] = []

    for raw_line in content.splitlines():
        if match := HEADER.match(raw_line):
            current_intent = match.group("intent")
            continue
        if current_intent and raw_line.startswith("- "):
            text = ANNOTATION.sub(r"\g<value>", raw_line[2:]).strip()
            if text:
                rows.append({"text": text, "intent": current_intent})
    return rows


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Dataset de origem não encontrado: {SOURCE}")
    rows = parse_rasa_markdown(SOURCE.read_text(encoding="utf-8"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["text", "intent"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Geradas {len(rows)} amostras em {OUTPUT}")


if __name__ == "__main__":
    main()
