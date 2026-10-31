"""Interpreta com Rasa ou lê intenções de referência e executa a simulação."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path

from ibn_sdn.control import ControlIntent, SimulationController
from ibn_sdn.intent.rasa_control import parse_with_rasa


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--text", help="Ordem textual; exige Rasa no ambiente ativo.")
    inputs.add_argument("--commands", type=Path, help="JSON com uma lista de intenções estruturadas.")
    inputs.add_argument("--demo", action="store_true", help="Executa os cenários estruturados incluídos.")
    parser.add_argument("--rasa-model", default=str(ROOT / "models/rasa/control.tar.gz"))
    parser.add_argument("--topology", type=Path, default=ROOT / "knowledge/control_topology.yaml")
    parser.add_argument("--policies", type=Path, default=ROOT / "knowledge/control_policies.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Valida sem modificar o estado simulado.")
    args = parser.parse_args()
    controller = SimulationController.from_yaml(args.topology, args.policies)
    if args.text is not None:
        if not args.text.strip():
            parser.error("A ordem textual não pode ser vazia.")
        if not Path(args.rasa_model).is_file():
            parser.error("Modelo Rasa não encontrado. Treine-o conforme as instruções do README.")
        try:
            intents = [asyncio.run(parse_with_rasa(args.rasa_model, args.text))]
        except ModuleNotFoundError as error:
            if error.name != "rasa":
                raise
            parser.error("Rasa não está instalado neste ambiente. Use o Python de .venv-rasa.")
        except ValueError as error:
            print(json.dumps({"status": "REJECTED", "code": "INTERPRETATION_ERROR", "reason": str(error)}, ensure_ascii=False))
            return
    else:
        path = ROOT / "examples/control_commands.json" if args.demo else args.commands
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("O arquivo deve conter uma lista JSON de intenções.")
            intents = [ControlIntent(**record) for record in records]
        except (OSError, TypeError, ValueError) as error:
            parser.error(str(error))
    for intent in intents:
        decision = controller.submit(intent, dry_run=args.dry_run)
        print(json.dumps({"intent": asdict(intent), "decision": decision.to_dict()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
