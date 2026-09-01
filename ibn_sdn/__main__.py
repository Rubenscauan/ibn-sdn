"""Interface de linha de comando do pipeline inicial."""

from __future__ import annotations

import argparse

from .intent.parser import parse_intent


def main() -> None:
    parser = argparse.ArgumentParser(description="Converte texto em uma intenção de rede.")
    parser.add_argument("sentence", help="Instrução de rede em linguagem natural.")
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Treina novamente o modelo a partir do dataset processado.",
    )
    args = parser.parse_args()
    print(parse_intent(args.sentence, retrain=args.retrain).to_json())


if __name__ == "__main__":
    main()
