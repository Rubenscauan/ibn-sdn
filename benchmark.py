"""ContextBench-IBN: benchmark independente do experimento do artigo.

Execute ``python benchmark.py --help`` na raiz do projeto.
Todas as consultas usam dry_run: nenhuma medição aplica bloqueios ou reservas.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from html import escape
import importlib.util
import importlib.metadata
from itertools import product
import json
import logging
import math
from pathlib import Path
import platform
import random
import statistics
import sys
from time import perf_counter

from yaml import YAMLError

from ibn_sdn.control import ControlDecision, ControlIntent, NetworkState, SimulationController
from ibn_sdn.intent.rasa_control import from_rasa_result


ROOT = Path(__file__).resolve().parent
CASE_IDS = ('viable', 'capacity', 'protected', 'denied', 'disconnected', 'unknown')
CODES = ('VALIDATED', 'UNKNOWN_HOST', 'HOST_PROTECTED', 'POLICY_DENIED',
         'INVALID_ENDPOINTS', 'EXISTING_BLOCK', 'NO_PATH', 'INSUFFICIENT_CAPACITY',
         'INTERPRETATION_ERROR')
SYNTHETIC_DEFAULTS = dict(switches=[8, 32, 128], rules=[1, 50], loads=[0., .8],
                          capacity=100., access_capacity=1000., bandwidths=[10., 30.],
                          cases=list(CASE_IDS))


@dataclass(frozen=True)
class Case:
    id: str
    text: str | None = None
    intent: ControlIntent | None = None
    expected_code: str | None = None
    expected_intent: ControlIntent | None = None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--text', action='append', help='Frase para Rasa; pode repetir esta opção.')
    inputs.add_argument('--phrases', type=Path, help='Lista JSON de frases e referências opcionais.')
    inputs.add_argument('--intents', type=Path, help='Lista JSON de intenções estruturadas para um cenário YAML.')
    inputs.add_argument('--scenarios', type=Path, help='Lista JSON de cenários estruturados para comparar.')
    parser.add_argument('--expected-code', choices=CODES, help='Referência para uma única --text.')
    parser.add_argument('--rasa-model', type=Path, default=ROOT / 'models/rasa/control.tar.gz')
    parser.add_argument('--topology', type=Path, help='Topologia YAML para --intents ou modo textual.')
    parser.add_argument('--policies', type=Path, help='Políticas YAML para --intents ou modo textual.')
    parser.add_argument('--switches', type=int, nargs='+', help='Switches na cadeia sintética.')
    parser.add_argument('--rules', type=int, nargs='+', help='Quantidade de políticas sintéticas.')
    parser.add_argument('--loads', type=float, nargs='+', help='Fração ocupada, de 0 a menos de 1.')
    parser.add_argument('--capacity', type=float, help='Mbps entre switches sintéticos.')
    parser.add_argument('--access-capacity', type=float, help='Mbps nos acessos sintéticos.')
    parser.add_argument('--bandwidths', type=float, nargs=2, metavar=('B1', 'B2'),
                        help='Mbps dos casos viable e capacity; referências recalculadas por construção.')
    parser.add_argument('--cases', nargs='+', choices=CASE_IDS, help='Casos sintéticos selecionados.')
    parser.add_argument('--requests', type=int, default=120, help='Consultas medidas por repetição.')
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=20, help='Consultas não medidas antes de cada repetição.')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path, help='Pasta nova; uma pasta existente nunca é sobrescrita.')
    args = parser.parse_args(argv)
    if args.scenarios and (args.topology or args.policies):
        parser.error('Com --scenarios, defina topology e policies em cada cenário do JSON.')
    if (args.topology or args.policies) and not (args.intents or args.text or args.phrases):
        parser.error('Use --intents, --text ou --phrases com --topology ou --policies.')
    if args.intents or args.scenarios or args.text or args.phrases:
        for name in SYNTHETIC_DEFAULTS:
            if getattr(args, name) is not None:
                parser.error(f"--{name.replace('_', '-')} só se aplica ao cenário sintético.")
    for name, default in SYNTHETIC_DEFAULTS.items():
        if getattr(args, name) is None:
            setattr(args, name, default.copy() if isinstance(default, list) else default)
    args.topology = args.topology or ROOT / 'knowledge/control_topology.yaml'
    args.policies = args.policies or ROOT / 'knowledge/control_policies.yaml'
    if args.requests < 1 or args.repetitions < 1 or args.warmup < 0:
        parser.error('Use requests e repetitions positivos e warmup não negativo.')
    if any(n < 2 for n in args.switches) or any(n < 1 for n in args.rules):
        parser.error('Use ao menos dois switches e uma política.')
    if any(not math.isfinite(n) or not 0 <= n < 1 for n in args.loads):
        parser.error('Cada ocupação deve ser finita e estar em [0, 1).')
    if any(not math.isfinite(n) or n <= 0 for n in (args.capacity, args.access_capacity)):
        parser.error('As capacidades devem ser positivas e finitas.')
    if any(not math.isfinite(n) or n < 0 for n in args.bandwidths):
        parser.error('As bandas solicitadas devem ser finitas e não negativas.')
    if args.text and any(not text.strip() for text in args.text):
        parser.error('As frases não podem ser vazias.')
    if args.expected_code and (not args.text or len(args.text) != 1):
        parser.error('--expected-code exige exatamente uma --text; use --phrases para várias referências.')
    for name in ('switches', 'rules', 'loads', 'cases'):
        if len(getattr(args, name)) != len(set(getattr(args, name))):
            parser.error(f'Não repita valores em --{name}.')
    return args


def synthetic_scenario(args, switches, rule_count, load):
    hosts = {f'h{i}': f'10.0.0.{i+1}' for i in range(4)}
    nodes = set(hosts) | {f's{i}' for i in range(switches)} | {'isolated'}
    links = {tuple(sorted((f's{i}', f's{i+1}'))): args.capacity for i in range(switches - 1)}
    for host, switch in (('h0', 's0'), ('h1', f's{switches-1}'), ('h2', 's0'), ('h3', 'isolated')):
        links[tuple(sorted((host, switch)))] = args.access_capacity
    state = NetworkState(hosts, nodes, links)
    route = ('h0',) + tuple(f's{i}' for i in range(switches)) + ('h1',)
    reservation = args.capacity * load
    if reservation > args.access_capacity:
        raise ValueError('A reserva inicial excede a capacidade de acesso; aumente --access-capacity.')
    state.flows[('h0', 'h1')] = (route, reservation)
    rules = [{'id': 'allow-flow', 'operation': 'ALLOW_FLOW', 'effect': 'allow'}]
    rules += [{'id': f'other-{i}', 'operation': 'BLOCK_FLOW', 'effect': 'allow',
               'source': 'h0', 'destination': 'h1'} for i in range(rule_count - 1)]
    system = SimulationController(state, {'h0'}, rules)
    # Oráculo independente da busca: todos os caminhos viáveis são conhecidos.
    # h2 tem acesso livre; h1 compartilha seu acesso com a reserva h0 -> h1.
    available = min(args.capacity - reservation, args.access_capacity - reservation)
    cases = []
    for name, bandwidth in zip(CASE_IDS[:2], args.bandwidths):
        intent = ControlIntent('ALLOW_FLOW', source='h2', destination='h1', bandwidth_mbps=bandwidth)
        cases.append(Case(name, intent=intent, expected_code=(
            'VALIDATED' if available + 1e-9 >= bandwidth else 'INSUFFICIENT_CAPACITY')))
    cases += [
        Case('protected', intent=ControlIntent('BLOCK_HOST', target='h0'), expected_code='HOST_PROTECTED'),
        Case('denied', intent=ControlIntent('BLOCK_HOST', target='h1'), expected_code='POLICY_DENIED'),
        Case('disconnected', intent=ControlIntent('ALLOW_FLOW', source='h2', destination='h3'), expected_code='NO_PATH'),
        Case('unknown', intent=ControlIntent('BLOCK_HOST', target='missing'), expected_code='UNKNOWN_HOST'),
    ]
    return system, [case for case in cases if case.id in args.cases]


def read_record_list(path):
    records = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(records, list) or not records:
        raise ValueError(f'{path} deve conter uma lista JSON não vazia.')
    return records


def named_records(records, fields, label):
    ids = set()
    for record in records:
        if not isinstance(record, dict) or record.keys() - fields - {'id'}:
            raise ValueError(f'{label} aceita os campos id, {", ".join(sorted(fields))}.')
        name = record.get('id')
        if not isinstance(name, str) or not name.strip() or name in ids:
            raise ValueError(f'{label} exige um id não vazio e único: {name!r}.')
        ids.add(name)
        yield name, record


def load_phrases(args):
    if args.text:
        records = [dict(id=f'text-{i+1}', text=text, expected_code=args.expected_code)
                   for i, text in enumerate(args.text)]
    else:
        records = read_record_list(args.phrases)
    cases = []
    for name, record in named_records(records, {'text', 'expected_code', 'expected_intent'}, 'Frase'):
        text = record.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'Frase vazia ou inválida: {name}.')
        code = record.get('expected_code')
        if code is not None and code not in CODES:
            raise ValueError(f'Código de referência inválido: {name}.')
        expected = record.get('expected_intent')
        if expected is not None:
            if not isinstance(expected, dict):
                raise ValueError(f'expected_intent deve ser um objeto: {name}.')
            expected = ControlIntent(**expected)
        cases.append(Case(name, text=text, expected_code=code, expected_intent=expected))
    return cases


def load_intents(path):
    cases = []
    for name, record in named_records(read_record_list(path), {'intent', 'expected_code'}, 'Pedido'):
        code = record.get('expected_code')
        if code is not None and code not in CODES[:-1]:
            raise ValueError(f'Código de referência estruturado inválido: {name}.')
        try:
            intent = ControlIntent(**record['intent'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f'Intenção inválida no pedido {name}: {error}') from error
        cases.append(Case(name, intent=intent, expected_code=code))
    return cases


def apply_reservations(state, reservations):
    if not isinstance(reservations, list):
        raise ValueError('reservations deve ser uma lista de rotas e bandas iniciais.')
    available = state.links.copy()
    for reservation in reservations:
        if not isinstance(reservation, dict) or reservation.keys() != {'path', 'bandwidth_mbps'}:
            raise ValueError('Cada reserva exige path e bandwidth_mbps.')
        route, bandwidth = reservation['path'], reservation['bandwidth_mbps']
        if (not isinstance(route, list) or len(route) < 2
                or not all(isinstance(node, str) and node in state.nodes for node in route)
                or len(set(route)) != len(route) or route[0] not in state.hosts
                or route[-1] not in state.hosts or any(node in state.hosts for node in route[1:-1])):
            raise ValueError(f'Rota de reserva inválida: {route!r}. Use dois hosts e switches intermediários.')
        if (isinstance(bandwidth, bool) or not isinstance(bandwidth, (int, float))
                or not math.isfinite(bandwidth) or bandwidth <= 0):
            raise ValueError('A banda reservada deve ser positiva e finita.')
        key = (route[0], route[-1])
        if key in state.flows:
            raise ValueError(f'Reserva duplicada: {key[0]} para {key[1]}.')
        for left, right in zip(route, route[1:]):
            link = tuple(sorted((left, right)))
            if link not in available or available[link] + 1e-9 < bandwidth:
                raise ValueError(f'Reserva usa enlace inexistente ou sem capacidade: {left} / {right}.')
            available[link] -= bandwidth
        state.flows[key] = (tuple(route), bandwidth)


def load_scenarios(manifest):
    sources = [manifest]
    configurations = []
    fields = {'topology', 'policies', 'intents'}
    for name, record in named_records(read_record_list(manifest), fields | {'reservations'}, 'Cenário'):
        try:
            topology, policies, intents = [
                manifest.resolve().parent / record[field] for field in ('topology', 'policies', 'intents')
            ]
            system = SimulationController.from_yaml(topology, policies)
            apply_reservations(system.state, record.get('reservations', []))
            cases = load_intents(intents)
        except (OSError, KeyError, TypeError, ValueError, YAMLError) as error:
            raise ValueError(f'Cenário {name}: {error}') from error
        configurations.append((name, system, cases))
        sources.extend([topology, policies, intents])
    return configurations, sources


def load_model(path):
    if not path.is_file():
        raise ValueError(f'Modelo não encontrado: {path}. Use um modelo já treinado em --rasa-model.')
    try:
        from rasa.core.agent import Agent
        from rasa.utils.log_utils import configure_structlog
    except ImportError as error:
        raise ValueError('Rasa indisponível. Execute com o Python de .venv-rasa e instale requirements-rasa.txt.') from error
    # Logs de cada inferência alterariam o custo medido e poluiriam a saída.
    logging.getLogger('rasa').setLevel(logging.WARNING)
    configure_structlog(logging.WARNING)
    return Agent.load(str(path))


def canonical(intent, system):
    result = asdict(intent)
    for key in ('source', 'destination', 'target'):
        if result[key]:
            result[key] = system.state.resolve(result[key]) or result[key].casefold()
    return result


async def collect(system, cases, args, configuration, agent=None):
    samples, runs = [], []
    for repetition in range(args.repetitions):
        seed = args.seed + repetition
        order = [cases[i % len(cases)] for i in range(args.requests)]
        random.Random(seed).shuffle(order)
        warmup = [cases[i % len(cases)] for i in range(args.warmup)]
        random.Random(seed).shuffle(warmup)
        measured = []
        batch_start = None
        for index, case in enumerate(warmup + order):
            if index == len(warmup):
                batch_start = perf_counter()
            intent, raw, error = case.intent, None, None
            interpretation_ms = validation_ms = None
            start = perf_counter()
            if agent is not None:
                raw = await agent.parse_message(case.text)
                try:
                    intent = from_rasa_result(raw)
                except ValueError as exc:
                    error = str(exc)
                interpretation_ms = (perf_counter() - start) * 1000
            if error is None:
                validation_start = perf_counter()
                decision = system.submit(intent, dry_run=True)
                validation_ms = (perf_counter() - validation_start) * 1000
            else:
                decision = ControlDecision('REJECTED', 'INTERPRETATION_ERROR', error)
            total_ms = (perf_counter() - start) * 1000
            if index >= len(warmup):
                measured.append((case, intent, raw, decision, interpretation_ms, validation_ms, total_ms))
        elapsed = perf_counter() - batch_start
        # A comparação com referências e a escrita ficam fora da janela medida.
        for index, (case, intent, raw, decision, interpretation_ms, validation_ms, total_ms) in enumerate(measured):
            samples.append(dict(configuration=configuration, repetition=repetition, seed=seed, index=index,
                                case_id=case.id, text=case.text,
                                intent=asdict(intent) if intent else None,
                                rasa_intent=raw.get('intent') if raw else None,
                                status=decision.status, code=decision.code, reason=decision.reason,
                                path=list(decision.path), expected_code=case.expected_code,
                                expected_intent=asdict(case.expected_intent) if case.expected_intent else None,
                                decision_match=decision.code == case.expected_code if case.expected_code else None,
                                intent_match=(canonical(intent, system) == canonical(case.expected_intent, system)
                                              if intent and case.expected_intent else
                                              False if case.expected_intent else None),
                                interpretation_ms=interpretation_ms, validation_ms=validation_ms, total_ms=total_ms))
        runs.append(dict(configuration=configuration, repetition=repetition, seed=seed,
                         requests=len(measured), warmup=args.warmup, elapsed_seconds=elapsed,
                         throughput_requests_per_second=len(measured) / elapsed,
                         mean_ms=statistics.mean(item[-1] for item in measured)))
    return samples, runs


def summarize(samples, batches):
    times = sorted(s['total_ms'] for s in samples)
    labelled = [s for s in samples if s['expected_code'] is not None]
    interpreted = [s['intent_match'] for s in samples if s['intent_match'] is not None]
    means = [r['mean_ms'] for r in batches]
    result = dict(requests=len(samples), mean_ms=statistics.mean(times), median_ms=statistics.median(times),
                  p95_ms=times[math.ceil(.95 * len(times)) - 1],
                  variance_ms2=statistics.variance(times) if len(times) > 1 else 0.,
                  stddev_repetition_mean_ms=(statistics.stdev(means) if len(means) > 1 else 0. if means else None),
                  throughput_requests_per_second=(len(samples) / sum(r['elapsed_seconds'] for r in batches)
                                                  if batches else None),
                  decision_references=len(labelled), intent_references=len(interpreted),
                  decision_match_rate=statistics.mean(s['decision_match'] for s in labelled) if labelled else None,
                  intent_match_rate=statistics.mean(interpreted) if interpreted else None,
                  false_acceptances=sum(s['status'] == 'APPROVED' and s['expected_code'] != 'VALIDATED'
                                        for s in labelled) if labelled else None,
                  false_rejections=sum(s['status'] != 'APPROVED' and s['expected_code'] == 'VALIDATED'
                                       for s in labelled) if labelled else None,
                  interpretation_errors=sum(s['code'] == 'INTERPRETATION_ERROR' for s in samples))
    for stage in ('interpretation', 'validation'):
        values = [s[f'{stage}_ms'] for s in samples if s[f'{stage}_ms'] is not None]
        result[f'{stage}_requests'] = len(values)
        result[f'{stage}_mean_ms'] = statistics.mean(values) if values else None
    return result


def write_csv(path, records):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def make_charts(output, summaries, samples):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    labels = [r['configuration'] for r in summaries]
    colors = ['#176b87', '#b45309']
    for name, field, ylabel in (
        ('latency', 'mean_ms', 'Latência total média (ms)'),
        ('throughput', 'throughput_requests_per_second', 'Consultas por segundo'),
    ):
        fig, ax = plt.subplots(figsize=(max(8, len(labels) * .75), 5))
        ax.bar(labels, [r[field] for r in summaries], color=colors[0],
               yerr=[r['stddev_repetition_mean_ms'] for r in summaries] if name == 'latency' else None,
               capsize=4)
        ax.set(ylabel=ylabel, title=f'ContextBench-IBN: {ylabel.lower()}')
        ax.tick_params(axis='x', labelrotation=40)
        if name == 'latency':
            fig.text(.02, .01, 'Barras: desvio padrão entre as médias das repetições; não são intervalos de confiança.', fontsize=8)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        fig.tight_layout(rect=(0, .04, 1, 1))
        fig.savefig(output / f'{name}.png', dpi=150)
        plt.close(fig)
    counts = Counter(s['code'] for s in samples)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(list(counts), list(counts.values()), color=colors[1])
    ax.set(xlabel='Consultas medidas', title='Decisões observadas (a contagem não indica acerto)')
    fig.tight_layout()
    fig.savefig(output / 'decisions.png', dpi=150)
    plt.close(fig)
    if any(s['interpretation_ms'] is not None for s in samples):
        fig, ax = plt.subplots(figsize=(8, 5))
        row = summaries[0]
        values = [row['interpretation_mean_ms'], row['validation_mean_ms']]
        ax.bar(['Interpretação + adaptação', 'Validação'], [v or 0 for v in values], color=colors[:2])
        ax.set(ylabel='Tempo médio (ms)', title='Tempo de cada etapa nas consultas em que foi executada')
        for i, value in enumerate(values):
            ax.text(i, value or 0, 'não executada' if value is None else f'{value:.4f} ms', ha='center', va='bottom')
        fig.tight_layout()
        fig.savefig(output / 'stages.png', dpi=150)
        plt.close(fig)


def html_table(rows, columns):
    header = ''.join(f'<th scope="col">{escape(label)}</th>' for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key)
            value = 'sem referência' if value is None else f'{value:.6g}' if isinstance(value, float) else str(value)
            cells.append(f'<td>{escape(value)}</td>')
        body.append('<tr>' + ''.join(cells) + '</tr>')
    return f'<div class="table"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def write_reports(output, samples, runs, metadata):
    groups = defaultdict(list)
    case_groups = defaultdict(list)
    for sample in samples:
        groups[sample['configuration']].append(sample)
        case_groups[(sample['configuration'], sample['case_id'])].append(sample)
    summaries = [dict(configuration=name, **summarize(group, [r for r in runs if r['configuration'] == name]))
                 for name, group in groups.items()]
    by_case = [dict(configuration=name, case_id=case, **summarize(group, []))
               for (name, case), group in case_groups.items()]
    write_csv(output / 'summary.csv', summaries)
    write_csv(output / 'cases.csv', by_case)
    write_csv(output / 'runs.csv', runs)
    with (output / 'samples.jsonl').open('w', encoding='utf-8') as stream:
        for sample in samples:
            stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + '\n')
    (output / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    make_charts(output, summaries, samples)
    architecture = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 150" role="img">
    <title>Arquitetura do ContextBench-IBN</title>
    <defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#176b87"/></marker></defs>
    <g fill="#eef5f8" stroke="#176b87" stroke-width="2">
    <rect x="5" y="25" width="180" height="85" rx="8"/><rect x="205" y="25" width="180" height="85" rx="8"/>
    <rect x="405" y="25" width="180" height="85" rx="8"/><rect x="605" y="25" width="180" height="85" rx="8"/><rect x="805" y="25" width="190" height="85" rx="8"/>
    <path d="M185,67 H202 M385,67 H402 M585,67 H602 M785,67 H802" marker-end="url(#arrow)"/></g>
    <g text-anchor="middle" font-family="sans-serif" font-size="16" fill="#173344">
    <text x="95" y="59">Cenários e carga</text><text x="95" y="84">Referências prévias</text>
    <text x="295" y="59">Rasa/DIET</text><text x="295" y="84">Somente nas frases</text>
    <text x="495" y="59">Validador Python</text><text x="495" y="84">Topologia + políticas</text>
    <text x="695" y="59">Medições repetidas</text><text x="695" y="84">Acertos e tempos</text>
    <text x="900" y="59">CSV, JSON e HTML</text><text x="900" y="84">Gráficos automáticos</text></g>
    <text x="500" y="140" text-anchor="middle" font-family="sans-serif" font-size="14">Pedidos estruturados seguem diretamente para o validador; todas as consultas preservam o estado.</text></svg>'''
    (output / 'architecture.svg').write_text(architecture, encoding='utf-8')
    performance = html_table(summaries, [('configuration', 'Configuração'), ('requests', 'Consultas'),
        ('mean_ms', 'Média (ms)'), ('median_ms', 'Mediana (ms)'), ('p95_ms', 'P95 (ms)'),
        ('stddev_repetition_mean_ms', 'DP das médias (ms)'), ('throughput_requests_per_second', 'Consultas/s')])
    accuracy = html_table(summaries, [('configuration', 'Configuração'), ('decision_references', 'Referências de decisão'),
        ('decision_match_rate', 'Acerto do código (0–1)'), ('false_acceptances', 'Aceitações indevidas'),
        ('false_rejections', 'Rejeições indevidas'), ('intent_references', 'Referências de interpretação'),
        ('intent_match_rate', 'Acerto da intenção completa (0–1)'), ('interpretation_errors', 'Erros de interpretação')])
    examples = []
    for group in case_groups.values():
        sample = group[0]
        examples.append(dict(configuration=sample['configuration'], case_id=sample['case_id'],
            input=sample['text'] or json.dumps(sample['intent'], ensure_ascii=False),
            predicted=json.dumps(sample['intent'], ensure_ascii=False), code=sample['code'],
            expected_code=sample['expected_code'], reason=sample['reason']))
    example_table = html_table(examples, [('configuration', 'Configuração'), ('case_id', 'Caso'),
        ('input', 'Entrada'), ('predicted', 'Intenção interpretada / fornecida'), ('code', 'Código observado'),
        ('expected_code', 'Código esperado'), ('reason', 'Motivo observado')])
    stage_chart = '<img src="stages.png" alt="Tempos médios de interpretação e validação">' if metadata['mode'] == 'text' else ''
    initialization = (f"Inicialização do Rasa: {metadata['rasa_initialization_ms']:.3f} ms (fora da inferência)."
                      if metadata['mode'] == 'text' else 'O modo estruturado utiliza diretamente o validador.')
    limits = ''.join(f'<li>{escape(item)}</li>' for item in metadata['limitations'])
    html = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>ContextBench-IBN</title>
    <style>body{{font:16px/1.5 system-ui,sans-serif;color:#183343;max-width:1250px;margin:auto;padding:24px}}
    h1,h2{{line-height:1.2}}h2{{margin-top:32px}}.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}
    th,td{{border:1px solid #cad7dd;padding:9px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#eef5f8}}
    img{{display:block;max-width:100%;height:auto;margin:20px auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef5f8;padding:16px}}
    a{{color:#125d83}}.note{{border-left:4px solid #176b87;padding:12px;background:#eef5f8}}</style></head><body>
    <h1>ContextBench-IBN</h1><p>Benchmark exploratório de intenções de rede. Modo: <strong>{escape(metadata['mode'])}</strong>.</p>
    <p>{len(samples)} consultas medidas, além do aquecimento. {initialization}</p>
    <p class="note">As taxas de acerto usam somente casos com referências informadas. Uma decisão permitida não é, por si só, um acerto.
    No modo textual, o código avalia o fluxo completo, e a intenção completa é comparada separadamente quando há anotação.</p>
    <h2>Arquitetura</h2><img src="architecture.svg" alt="Carga, interpretação opcional, validação, medições e resultados">
    <h2>Desempenho</h2>{performance}<p>DP: desvio padrão amostral entre as médias das repetições. P95: percentil por posto mais próximo sobre os tempos individuais.
    A vazão usa o tempo dos lotes e inclui o laço de coleta; não é calculada como o inverso da latência média.</p>
    <img src="latency.png" alt="Latência média por configuração, com desvio padrão entre repetições">
    <img src="throughput.png" alt="Vazão por configuração">{stage_chart}
    <h2>Acerto e decisões</h2>{accuracy}<img src="decisions.png" alt="Contagem de códigos de decisão">
    <h2>Exemplos observados</h2><p>Primeira observação de cada caso em cada configuração. Todas as consultas estão no arquivo de dados brutos.</p>{example_table}
    <h2>Limites de interpretação</h2><ul>{limits}</ul>
    <h2>Arquivos e reprodução</h2><p><a href="summary.csv">Resumo CSV</a> · <a href="cases.csv">Casos CSV</a> ·
    <a href="runs.csv">Repetições CSV</a> · <a href="samples.jsonl">Dados brutos</a> · <a href="metadata.json">Metadados</a></p>
    <pre>{escape(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre></body></html>'''
    (output / 'report.html').write_text(html, encoding='utf-8')
    return summaries


async def run_benchmark(args):
    if importlib.util.find_spec('matplotlib') is None:
        raise ValueError('Instale as dependências: python -m pip install -r requirements-benchmark.txt')
    text_mode = bool(args.text or args.phrases)
    output = args.output or ROOT / 'results/benchmark' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if output.exists():
        raise ValueError(f'A pasta já existe: {output}. Escolha uma pasta nova com --output.')
    samples, runs, configurations = [], [], []
    sources = [ROOT / 'benchmark.py', ROOT / 'ibn_sdn/control.py', ROOT / 'ibn_sdn/intent/rasa_control.py']
    initialization_ms = 0.
    agent = None
    if text_mode:
        cases = load_phrases(args)
        system = SimulationController.from_yaml(args.topology, args.policies)
        sources += [args.topology, args.policies, args.rasa_model]
        if args.phrases:
            sources.append(args.phrases)
        start = perf_counter()
        agent = load_model(args.rasa_model)
        initialization_ms = (perf_counter() - start) * 1000
        configurations = [('text', system, cases)]
    elif args.scenarios:
        configurations, scenario_sources = load_scenarios(args.scenarios)
        sources.extend(scenario_sources)
        random.Random(args.seed).shuffle(configurations)
    elif args.intents:
        system = SimulationController.from_yaml(args.topology, args.policies)
        configurations = [('custom', system, load_intents(args.intents))]
        sources.extend([args.topology, args.policies, args.intents])
    else:
        factors = list(product(args.switches, args.rules, args.loads))
        random.Random(args.seed).shuffle(factors)
        for switches, rules, load in factors:
            system, cases = synthetic_scenario(args, switches, rules, load)
            configurations.append((f's{switches}-p{rules}-o{load!r}', system, cases))
    if args.requests < max(len(cases) for _, _, cases in configurations):
        raise ValueError('--requests deve ser ao menos a quantidade de casos selecionados, para cobrir todos.')
    custom_context = bool(args.scenarios or args.intents)
    context_type = 'yaml' if text_mode or custom_context else 'synthetic'
    context_note = (
        'Topologia e políticas vieram dos arquivos informados; o estado inicial é fixo por configuração.'
        if context_type == 'yaml' else
        'O cenário sintético usa uma cadeia, quatro hosts e um switch isolado; políticas adicionais não correspondem aos fluxos de teste.'
    )
    metadata = dict(name='ContextBench-IBN', mode='text' if text_mode else 'structured',
        context_type=context_type,
        started_at_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
        python_executable=sys.executable, platform=platform.platform(), processor=platform.processor(),
        parameters={key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        rasa_initialization_ms=initialization_ms,
        library_versions={name: importlib.metadata.version(name) for name in ('PyYAML', 'matplotlib')},
        source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in dict.fromkeys(source.resolve() for source in sources)},
        configuration_order=[name for name, _, _ in configurations],
        workload={name: [dict(id=c.id, text=c.text, intent=asdict(c.intent) if c.intent else None,
                              expected_code=c.expected_code,
                              expected_intent=asdict(c.expected_intent) if c.expected_intent else None)
                         for c in cases] for name, _, cases in configurations},
        limitations=[
            'Consultas locais sequenciais sem alteração do estado, controlador SDN ou tráfego de pacotes.',
            'Volume, aquecimento e repetições são configuráveis; seus valores não são uma justificativa estatística.',
            'A latência exclui inicialização, montagem dos cenários, comparação com referências e escrita dos resultados.',
            'A vazão inclui o laço de coleta e o armazenamento temporário das observações na memória.',
            'O tempo total mistura casos de aprovação e diferentes rejeições. Consulte cases.csv para separar os casos.',
            context_note,
            'As configurações são embaralhadas uma vez; cada configuração executa todas as repetições em sequência.',
            'No modo textual, referências são fornecidas pelo usuário; os exemplos incluídos são demonstrações, sem comprovar generalização.',
            'Interpretação inclui a adaptação da saída Rasa. A média de validação considera apenas consultas que chegaram ao validador.',
            'Amostras de uma mesma repetição não são repetições independentes; nenhuma barra representa intervalo de confiança.',
        ])
    for name, system, cases in configurations:
        print(f'Medindo {name}: {args.repetitions} repetições x {args.requests} consultas.', flush=True)
        measured, batches = await collect(system, cases, args, name, agent)
        samples.extend(measured)
        runs.extend(batches)
    output.mkdir(parents=True, exist_ok=False)
    summaries = write_reports(output, samples, runs, metadata)
    print('Configuração | consultas | média (ms) | p95 (ms) | consultas/s | acerto do código')
    for row in summaries:
        accuracy = 'sem referência' if row['decision_match_rate'] is None else f"{row['decision_match_rate']:.1%}"
        print(f"{row['configuration']} | {row['requests']} | {row['mean_ms']:.4f} | {row['p95_ms']:.4f} | "
              f"{row['throughput_requests_per_second']:.1f} | {accuracy}")
    if text_mode:
        for case in configurations[0][2]:
            sample = next(s for s in samples if s['case_id'] == case.id)
            print(json.dumps({key: sample[key] for key in ('text', 'intent', 'code', 'reason', 'expected_code')}, ensure_ascii=False))
    print(f'Relatório: {(output / "report.html").resolve()}')
    return output


def main():
    args = parse_args()
    try:
        asyncio.run(run_benchmark(args))
    except (OSError, ValueError, TypeError, KeyError, YAMLError) as error:
        raise SystemExit(f'Erro no benchmark: {error}') from None


if __name__ == '__main__':
    main()
