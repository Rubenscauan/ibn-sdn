# IBN-SDN

Protótipo para **validação contextual de intenções de rede** e avaliação de
desempenho. O fluxo é:

**Rasa/DIET → intenção estruturada → validação de políticas e topologia → decisão → simulação**

O sistema verifica se uma ordem pode ser aplicada de acordo com hosts
protegidos, permissões, conectividade e capacidade disponível. A execução altera
somente um estado de rede em memória. Não há integração com controlador SDN nesta versão.

## Estrutura

- `ibn_sdn/control.py`: contrato das intenções, topologia, políticas e simulação.
- `ibn_sdn/intent/rasa_control.py`: adaptação da saída Rasa para o contrato.
- `ibn_sdn/cli.py`: interface de linha de comando.
- `knowledge/control_topology.yaml`: hosts, switches e enlaces do laboratório.
- `knowledge/control_policies.yaml`: proteção de hosts e permissões.
- `rasa/`: configuração DIET e exemplos operacionais anotados.
- `examples/control_commands.json`: sequência de pedidos para demonstração.
- `scripts/benchmark_control.py`: experimento de desempenho do validador.
- `tests/`: testes funcionais, do adaptador, da carga e da interface.
- `results/control/`: medições piloto e metadados de reprodução.
- `artigo/`: fontes LaTeX, referências e estilos SBC.

## Instalação básica

Python 3.10 ou superior. A simulação e o benchmark precisam apenas de PyYAML.
Os testes são instalados com `requirements-dev.txt`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Os comandos abaixo são executados na raiz do repositório.

## Demonstração com intenções estruturadas

```powershell
.\.venv\Scripts\python.exe -m ibn_sdn --demo
```

A sequência demonstra rejeição de bloqueio de host protegido, reserva de banda,
rejeição por capacidade insuficiente, falta de caminho e bloqueio permitido.

Operações disponíveis:

| Operação | Campos | Efeito |
|---|---|---|
| `BLOCK_HOST` | `target` | Bloqueia o host nos dois sentidos |
| `BLOCK_FLOW` | `source`, `destination` | Bloqueia somente o fluxo direcional |
| `ALLOW_FLOW` | `source`, `destination`, `bandwidth_mbps` opcional | Cria ou atualiza um fluxo |

Exemplo de arquivo JSON para `--commands`:

```json
[
  {"operation": "BLOCK_HOST", "target": "hosta"},
  {"operation": "ALLOW_FLOW", "source": "hosta", "destination": "hostb", "bandwidth_mbps": 30}
]
```

```powershell
.\.venv\Scripts\python.exe -m ibn_sdn --commands examples/control_commands.json
.\.venv\Scripts\python.exe -m ibn_sdn --demo --dry-run
```

Sem `--dry-run`, os pedidos da mesma execução compartilham reservas e bloqueios.
Cada invocação começa com estado novo. Com `--dry-run`, o sistema apenas valida,
sem consumir capacidade nem aplicar bloqueios.

As decisões são `REJECTED`, `APPROVED` (consulta sem execução) ou `SIMULATED`
(alteração aplicada ao modelo). O campo `code` identifica o motivo:
`HOST_PROTECTED`, `POLICY_DENIED`, `UNKNOWN_HOST`, `NO_PATH`,
`INSUFFICIENT_CAPACITY` ou `EXISTING_BLOCK`.

Proibições prevalecem sobre permissões; ausência de permissão implica rejeição.
Uma rejeição preserva o estado anterior. Os enlaces são bidirecionais, com
capacidade compartilhada entre os sentidos. Os hosts não encaminham tráfego
de outros hosts. Omitir banda significa não reservar capacidade para o fluxo.

## Interpretação textual com Rasa/DIET

Rasa 3.6.21 exige Python 3.10 neste projeto. Use um ambiente separado. Com
[uv](https://docs.astral.sh/uv/) instalado:

```powershell
uv python install 3.10
uv venv .venv-rasa --python 3.10
uv pip install --python .venv-rasa\Scripts\python.exe -r requirements-rasa.txt
$env:RASA_TELEMETRY_ENABLED = "false"
.\.venv-rasa\Scripts\python.exe -m rasa train nlu --config rasa/control_config.yml --nlu rasa/control_nlu.yml --out models/rasa --fixed-model-name control
.\.venv-rasa\Scripts\python.exe -m ibn_sdn --text "bloqueie o host A"
```

O treino salva `models/rasa/control.tar.gz`; interpretar uma frase carrega esse
arquivo e não retreina. O exemplo rejeita a ordem porque `hosta` está protegido.

Os exemplos PT/EN de `rasa/control_nlu.yml` foram escritos para a demonstração
operacional. Não são o corpus IBNs nem um teste independente de generalização.
A configuração NLU é adaptada do [pipeline publicado por Saha et al.](https://github.com/barun-saha/IBNs/blob/main/config.yml);
não constitui reprodução de sua versão Rasa ou de seu experimento.

O limiar de confiança de 0,7 é provisório. O adaptador rejeita campos ausentes,
entidades repetidas e alguns qualificadores não suportados, como porta e
negação. Essa guarda não garante compreensão de toda frase. O conjunto pequeno
de treino serve para integração, sem demonstrar segurança ou qualidade em produção.

O atalho anterior `python -m scripts.run_control` continua disponível com as
mesmas opções da interface principal.

## Testes e desempenho

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.benchmark_control
```

O experimento varia o tamanho da cadeia de switches (8, 32 e 128, além de um
switch isolado), a quantidade de políticas (1 e 50) e a ocupação prévia dos
enlaces (0% e 80%). Cada uma das 12 configurações utiliza cinco repetições de
120 consultas balanceadas, após aquecimento.

Registra latência média, mediana, p95, vazão em pedidos por segundo, aceitações
e rejeições indevidas e correção dos motivos. Cada execução cria uma pasta
nova em `results/control/`, com tempos individuais, parâmetros, sementes,
ambiente e hashes do código. Consulte `python -m scripts.benchmark_control --help`
para ajustar os fatores.

As medições isolam o validador, com intenções estruturadas e estado fixo por
repetição. Construção da topologia, Rasa, escrita em disco e instalação de regras
não integram esse tempo. Os resultados atuais são pilotos sobre uma topologia
sintética simples; não comprovam desempenho em SDN real. Não execute treinamento
ou outras cargas pesadas durante uma coleta confirmatória.

## Arquivos locais e publicação

Ambientes virtuais, modelos treinados, dados externos, caches, arquivos
`.env` e saídas de compilação LaTeX são ignorados pelo Git. Os fontes do
artigo e as medições piloto são preservados. O código dos experimentos antigos
de classificação e de IaC foi retirado do projeto; o escopo atual é o fluxo
Rasa/DIET, validação contextual, simulação e avaliação de desempenho.
