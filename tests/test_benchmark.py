import asyncio
import csv
import json
from copy import deepcopy

import pytest

import benchmark


def test_synthetic_oracle_and_measurement_preserve_state():
    args = benchmark.parse_args([
        '--switches', '8', '--rules', '50', '--loads', '0.8',
        '--requests', '12', '--repetitions', '2', '--warmup', '3',
    ])
    system, cases = benchmark.synthetic_scenario(args, 8, 50, .8)
    assert [case.expected_code for case in cases] == [
        'VALIDATED', 'INSUFFICIENT_CAPACITY', 'HOST_PROTECTED',
        'POLICY_DENIED', 'NO_PATH', 'UNKNOWN_HOST',
    ]
    before = deepcopy(system.state)
    samples, runs = asyncio.run(benchmark.collect(system, cases, args, 'test'))
    assert len(samples) == 24 and len(runs) == 2
    assert all(s['decision_match'] for s in samples)
    assert system.state == before
    assert {s['case_id'] for s in samples} == {case.id for case in cases}


def test_statistics_use_references_and_batch_elapsed_time():
    samples = [dict(total_ms=t, interpretation_ms=None, validation_ms=t,
                    decision_match=match, intent_match=None,
                    expected_code=expected, code=code, status=status)
               for t, match, expected, code, status in [
                   (1, True, 'VALIDATED', 'VALIDATED', 'APPROVED'),
                   (2, False, 'POLICY_DENIED', 'VALIDATED', 'APPROVED'),
                   (3, None, None, 'NO_PATH', 'REJECTED'),
                   (4, False, 'VALIDATED', 'NO_PATH', 'REJECTED'),
               ]]
    batches = [dict(requests=2, elapsed_seconds=1, mean_ms=1.5),
               dict(requests=2, elapsed_seconds=3, mean_ms=3.5)]
    result = benchmark.summarize(samples, batches)
    assert result['mean_ms'] == 2.5
    assert result['median_ms'] == 2.5
    assert result['p95_ms'] == 4
    assert result['variance_ms2'] == pytest.approx(5 / 3)
    assert result['throughput_requests_per_second'] == 1
    assert result['decision_references'] == 3
    assert result['decision_match_rate'] == pytest.approx(1 / 3)
    assert result['false_acceptances'] == result['false_rejections'] == 1
    assert result['intent_match_rate'] is None


def test_custom_access_capacity_changes_constructed_reference():
    args = benchmark.parse_args(['--capacity', '100', '--access-capacity', '50',
                                 '--bandwidths', '20', '40', '--cases', 'viable', 'capacity'])
    system, cases = benchmark.synthetic_scenario(args, 8, 1, .2)
    # A reserva é de 20 Mbps: sobram 80 na cadeia, mas somente 30 no acesso a h1.
    assert [c.expected_code for c in cases] == ['VALIDATED', 'INSUFFICIENT_CAPACITY']
    assert [system.submit(c.intent, dry_run=True).code for c in cases] == [
        'VALIDATED', 'INSUFFICIENT_CAPACITY']


class FakeAgent:
    def __init__(self):
        self.calls = 0

    async def parse_message(self, text):
        self.calls += 1
        if text == 'fora do escopo':
            return {'text': text, 'intent': {'name': 'out_of_scope', 'confidence': .99}}
        # Rejeitar o bloqueio também de hosta não prova que a frase foi entendida.
        return {'text': text, 'intent': {'name': 'block_host', 'confidence': .99},
                'entities': [{'entity': 'target', 'value': 'hosta', 'confidence_entity': .99}]}


def test_text_tracks_interpretation_errors_and_wrong_intents_separately(tmp_path):
    phrases = tmp_path / 'phrases.json'
    phrases.write_text(json.dumps([
        {'id': 'wrong-target', 'text': 'bloqueie hostb', 'expected_code': 'VALIDATED',
         'expected_intent': {'operation': 'BLOCK_HOST', 'target': 'hostb'}},
        {'id': 'unknown', 'text': 'fora do escopo', 'expected_code': 'INTERPRETATION_ERROR'},
        {'id': 'same-code', 'text': 'bloqueie o fluxo de hosta para hostb',
         'expected_code': 'HOST_PROTECTED',
         'expected_intent': {'operation': 'BLOCK_FLOW', 'source': 'hosta', 'destination': 'hostb'}},
    ]), encoding='utf-8')
    args = benchmark.parse_args(['--phrases', str(phrases), '--requests', '3',
                                 '--repetitions', '2', '--warmup', '1'])
    cases = benchmark.load_phrases(args)
    system = benchmark.SimulationController.from_yaml(args.topology, args.policies)
    agent = FakeAgent()
    samples, runs = asyncio.run(benchmark.collect(system, cases, args, 'text', agent))
    assert agent.calls == 8  # Seis medições e dois aquecimentos.
    wrong = [s for s in samples if s['case_id'] == 'wrong-target']
    assert all(s['intent_match'] is False and s['decision_match'] is False for s in wrong)
    rejected = [s for s in samples if s['case_id'] == 'unknown']
    assert all(s['validation_ms'] is None and s['decision_match'] for s in rejected)
    same_code = [s for s in samples if s['case_id'] == 'same-code']
    assert all(s['decision_match'] is True and s['intent_match'] is False for s in same_code)
    assert benchmark.summarize(samples, runs)['interpretation_errors'] == 2
    assert not system.state.blocked_hosts


def test_unlabelled_text_does_not_claim_accuracy():
    args = benchmark.parse_args(['--text', 'bloqueie hosta', '--requests', '1',
                                 '--repetitions', '1', '--warmup', '0'])
    system = benchmark.SimulationController.from_yaml(args.topology, args.policies)
    samples, runs = asyncio.run(benchmark.collect(
        system, benchmark.load_phrases(args), args, 'text', FakeAgent()))
    result = benchmark.summarize(samples, runs)
    assert result['decision_match_rate'] is None
    assert result['false_acceptances'] is None
    assert result['false_rejections'] is None


def test_cli_generates_reports_and_escapes_text_without_loading_rasa(tmp_path, monkeypatch):
    text = '<script>alert(1)</script>'
    output = tmp_path / 'results'
    args = benchmark.parse_args(['--text', text, '--requests', '2', '--repetitions', '1',
                                 '--warmup', '0', '--output', str(output)])
    loads = []

    def fake_load(path):
        loads.append(path)
        return FakeAgent()

    monkeypatch.setattr(benchmark, 'load_model', fake_load)
    asyncio.run(benchmark.run_benchmark(args))
    assert len(loads) == 1
    assert all((output / name).is_file() for name in [
        'metadata.json', 'samples.jsonl', 'summary.csv', 'cases.csv', 'runs.csv',
        'report.html', 'architecture.svg', 'latency.png', 'throughput.png',
        'decisions.png', 'stages.png',
    ])
    report = (output / 'report.html').read_text(encoding='utf-8')
    assert text not in report and '&lt;script&gt;' in report
    with (output / 'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['requests'] == '2'
    assert row['decision_match_rate'] == ''
    assert row['false_acceptances'] == ''


def test_close_occupancies_remain_separate_in_reports(tmp_path):
    output = tmp_path / 'close-loads'
    args = benchmark.parse_args(['--switches', '2', '--rules', '1', '--loads',
        '0.8000001', '0.8000002', '--requests', '6', '--warmup', '0',
        '--repetitions', '1', '--output', str(output)])
    asyncio.run(benchmark.run_benchmark(args))
    with (output / 'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert {r['configuration'] for r in rows} == {'s2-p1-o0.8000001', 's2-p1-o0.8000002'}
    assert all(r['requests'] == '6' for r in rows)


def test_custom_scenarios_use_supplied_graph_workload_and_reservations(tmp_path):
    topology = tmp_path / 'topology.yaml'
    topology.write_text(
        'hosts: {client: 10.0.0.1, server: 10.0.0.2, backup: 10.0.0.3}\n'
        'switches: [edge, core]\n'
        'links:\n'
        '  - {source: client, target: edge, capacity_mbps: 100}\n'
        '  - {source: server, target: core, capacity_mbps: 100}\n'
        '  - {source: backup, target: core, capacity_mbps: 100}\n'
        '  - {source: edge, target: core, capacity_mbps: 50}\n',
        encoding='utf-8',
    )
    policies = tmp_path / 'policies.yaml'
    policies.write_text(
        'rules:\n  - {id: allow, operation: ALLOW_FLOW, effect: allow}\n',
        encoding='utf-8',
    )
    intents = tmp_path / 'intents.json'
    intents.write_text(json.dumps([{
        'id': 'new-flow',
        'intent': {'operation': 'ALLOW_FLOW', 'source': 'client',
                   'destination': 'server', 'bandwidth_mbps': 30},
    }]), encoding='utf-8')
    manifest = tmp_path / 'scenarios.json'
    files = dict(topology=topology.name, policies=policies.name, intents=intents.name)
    manifest.write_text(json.dumps([
        dict(id='free', **files),
        dict(id='busy', **files, reservations=[
            {'path': ['backup', 'core', 'edge', 'client'], 'bandwidth_mbps': 40},
        ]),
    ]), encoding='utf-8')
    output = tmp_path / 'output'
    args = benchmark.parse_args(['--scenarios', str(manifest), '--requests', '2',
                                 '--repetitions', '2', '--warmup', '1', '--output', str(output)])
    asyncio.run(benchmark.run_benchmark(args))
    samples = [json.loads(row) for row in (output / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(samples) == 8
    assert {(s['configuration'], s['case_id'], s['code']) for s in samples} == {
        ('free', 'new-flow', 'VALIDATED'),
        ('busy', 'new-flow', 'INSUFFICIENT_CAPACITY'),
    }
    assert all(s['decision_match'] is None for s in samples)
    metadata = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
    assert metadata['context_type'] == 'yaml'
    assert all(str(path.resolve()) in metadata['source_sha256']
               for path in (manifest, topology, policies, intents))


@pytest.mark.parametrize('options', [
    ['--loads', 'nan'], ['--capacity', '0'], ['--warmup', '-1'],
    ['--repetitions', '0'], ['--requests', '0'], ['--bandwidths', '-1', '30'],
    ['--text', ''], ['--expected-code', 'VALIDATED'],
    ['--text', 'a', '--text', 'b', '--expected-code', 'VALIDATED'],
    ['--topology', 'topology.yaml'],
    ['--intents', 'intents.json', '--loads', '0.8'],
    ['--scenarios', 'scenarios.json', '--policies', 'policies.yaml'],
])
def test_invalid_parameters_fail_before_measurement(options):
    with pytest.raises(SystemExit):
        benchmark.parse_args(options)
