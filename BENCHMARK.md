# ContextBench-IBN

Aplicação de benchmark para medir decisões e tempos de processamento de intenções
de rede. O ponto de entrada é **`benchmark.py`**, na raiz do repositório.
Ele é independente de `scripts/benchmark_control.py`, que permanece como estava
para o experimento do artigo. As saídas novas ficam em `results/benchmark/`.

## Instalação

Execute os comandos na raiz do repositório. Para consultas estruturadas, use
Python 3.10 ou superior:

```powershell
python -m venv .venv-benchmark
.\.venv-benchmark\Scripts\python.exe -m pip install -r requirements-benchmark.txt
.\.venv-benchmark\Scripts\python.exe benchmark.py --help
```

O modo textual usa o ambiente Python 3.10 com Rasa descrito no README do projeto.
Acrescente nele as dependências dos gráficos:

```powershell
uv pip install --python .venv-rasa\Scripts\python.exe -r requirements-benchmark.txt
$env:RASA_TELEMETRY_ENABLED = "false"
```

É necessário ter o modelo `models/rasa/control.tar.gz`, ou informar outro modelo
compatível com `--rasa-model`. O benchmark carrega o modelo uma vez por execução,
registra o custo de inicialização separadamente e não faz treinamento.

## Demonstração em Docker

A imagem inclui Python e as bibliotecas do benchmark estruturado. É
necessário ter Docker com contêineres Linux e o comando `docker compose`.
Prepare a imagem uma vez, com internet, na raiz do projeto:

```powershell
docker build -t contextbench-ibn:demo .
```

Com a imagem pronta, o roteiro de apresentação roda sem rede. O Compose
usa a imagem local e monta as pastas de entradas para que você possa editar
os JSON e YAML entre execuções.

```powershell
$saida = "results/benchmark/demo-docker-$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
docker compose run --rm benchmark --scenarios examples/benchmark_scenarios.json --requests 12 --repetitions 2 --warmup 3 --output $saida
if ($LASTEXITCODE -eq 0) { Invoke-Item (Join-Path $saida 'report.html') }
```

No HTML, a seção **Exemplos observados** mostra o caso `fluxo-30-mbps`.
Ele retorna `VALIDATED` em `sem-reserva` e `INSUFFICIENT_CAPACITY` em
`reserva-de-40-mbps`. É possível usar outros parâmetros estruturados no
mesmo comando. Essa imagem atende ao modo estruturado. Use a instalação
com Rasa descrita acima para os exemplos com frases.

Para levar a imagem a outro computador compatível que já tenha Docker,
exporte-a com `docker image save -o contextbench-ibn-demo.tar contextbench-ibn:demo`.
No outro computador, copie a imagem e a pasta do projeto e importe com
`docker image load -i contextbench-ibn-demo.tar`. A importação usa o arquivo
local e dispensa a compilação da imagem no dia da apresentação.

## Operação: cenário sintético

```powershell
.\.venv-benchmark\Scripts\python.exe benchmark.py --switches 8 32 128 --rules 1 50 --loads 0 0.8 --requests 1200 --repetitions 10 --warmup 100 --seed 42
```

Esse exemplo cruza 12 configurações. Em cada uma, executa 10 repetições de 1.200
consultas, precedidas por 100 consultas de aquecimento em cada repetição. Esses
valores são exemplos de uso, sem justificar a precisão estatística da coleta.

O grafo sintético contém uma cadeia, quatro hosts e mais um switch isolado.
`--switches` conta somente os switches da cadeia. Uma reserva entre `h0` e `h1`
estabelece a ocupação inicial. Apenas uma política permite fluxos; as políticas
adicionais são regras para bloqueio direcional que não correspondem aos pedidos
de fluxo da carga. Portanto, esse fator mede a inspeção dessa lista específica,
sem representar todas as combinações de permissões e proibições.

| Caso | Pedido | Referência |
|---|---|---|
| `viable` | Fluxo h2 → h1 com a primeira banda de `--bandwidths` | Caminho admite a banda ou não, conforme as capacidades configuradas. |
| `capacity` | Mesmo par, com a segunda banda | Mesma verificação independente por construção. |
| `protected` | Bloquear h0 | `HOST_PROTECTED`. |
| `denied` | Bloquear h1 | `POLICY_DENIED`. |
| `disconnected` | Fluxo h2 → h3 | `NO_PATH`. |
| `unknown` | Bloquear host inexistente | `UNKNOWN_HOST`. |

Os dois primeiros nomes identificam casos; alterar as bandas pode mudar suas
decisões esperadas. O oráculo utiliza o único caminho e as reservas conhecidas,
sem consultar a resposta do validador para definir o esperado.

Para selecionar outra composição de carga:

```powershell
.\.venv-benchmark\Scripts\python.exe benchmark.py --switches 8 --rules 10 --loads 0.5 --capacity 200 --access-capacity 1000 --bandwidths 20 150 --cases viable capacity denied --requests 300 --repetitions 5 --warmup 30
```

Os casos selecionados têm quantidades iguais, ou diferença de uma consulta
quando o total não é divisível pela quantidade de casos. É preciso ter ao menos
uma consulta por caso. A ordem dos pedidos é embaralhada pela semente mais o
índice da repetição. As configurações também são embaralhadas, uma vez, pela
semente inicial. Não há geração de frases nesse modo.

## Operação: topologia, políticas e pedidos próprios

Passe uma carga estruturada com `--intents`. O arquivo é uma lista JSON.
Cada item tem um `id` único, uma `intent` e, opcionalmente,
`expected_code` para calcular o acerto.

```powershell
.\.venv-benchmark\Scripts\python.exe benchmark.py --intents examples/benchmark_intents.json --topology knowledge/control_topology.yaml --policies knowledge/control_policies.yaml --requests 12 --repetitions 2 --warmup 3
```

Use os YAML do exemplo como ponto de partida para definir seus hosts,
switches, enlaces, capacidades e regras. Se omitir `--topology` ou
`--policies`, o benchmark usa o respectivo YAML padrão.

| Operação | Campos de `intent` |
|---|---|
| `BLOCK_HOST` | `operation` e `target`. |
| `BLOCK_FLOW` | `operation`, `source` e `destination`. O par é direcional. |
| `ALLOW_FLOW` | `operation`, `source`, `destination` e `bandwidth_mbps` opcional. |

Cada entrada da lista recebe uma parte da carga por repetição, com diferença
de no máximo uma consulta entre entradas. Use IDs diferentes para pedidos
distintos. Para comparar o acerto, defina `expected_code` antes da coleta.
Sem esse campo, a decisão e a latência continuam disponíveis nas saídas.

### Comparar cenários no mesmo relatório

```powershell
.\.venv-benchmark\Scripts\python.exe benchmark.py --scenarios examples/benchmark_scenarios.json --requests 12 --repetitions 2 --warmup 3
```

Cada cenário da lista informa `id`, `topology`, `policies` e `intents`.
Os caminhos relativos partem da pasta do próprio JSON. Reuse o mesmo
arquivo quando quiser mantê-lo fixo. Para variar só as políticas, por exemplo,
use a mesma topologia e a mesma carga em dois cenários, com YAML de políticas
diferentes. Se os códigos esperados mudarem e você quiser medir o acerto,
use arquivos de intenções com referências próprias para cada cenário.

O campo opcional `reservations` aceita uma lista de reservas iniciais, cada
uma com `path` (hosts nas extremidades, switches intermediários) e
`bandwidth_mbps` positiva. O carregamento verifica se a rota existe e se
as reservas cabem na capacidade compartilhada dos enlaces. As reservas são
parte do estado inicial da simulação. As consultas preservam esse estado.

O exemplo mantém os três arquivos de entrada fixos e compara o mesmo
enlace de 50 Mbps sem reserva e com uma reserva de 40 Mbps. O pedido de
30 Mbps deve ser aprovado no primeiro cenário e rejeitado por falta de
banda no segundo. Esse caso está sem `expected_code` no JSON compartilhado,
então o HTML mostra os códigos observados e a taxa considera só os dois
bloqueios anotados. Os resultados e gráficos identificam cada cenário pelo
`id`, e os metadados registram os hashes da lista e dos arquivos carregados.

## Operação: uma frase

```powershell
.\.venv-rasa\Scripts\python.exe benchmark.py --text "bloqueie o host A" --expected-code HOST_PROTECTED --requests 20 --repetitions 3 --warmup 5
```

O terminal e o relatório mostram a intenção extraída e o motivo da decisão.
A referência `HOST_PROTECTED` corresponde aos arquivos padrão, que protegem
`hosta`. Sem `--expected-code`, a decisão e os tempos são apresentados, mas não
há pontuação de acerto. Permitir ou rejeitar um pedido não prova que a decisão
esteja certa sem uma referência independente.

Pode-se repetir `--text` para várias frases sem referências. Para anotar várias
frases, utilize `--phrases`. `--expected-code` aceita somente uma frase avulsa.

## Operação: conjunto de frases

```powershell
.\.venv-rasa\Scripts\python.exe benchmark.py --phrases examples/benchmark_phrases.json --requests 60 --repetitions 3 --warmup 12
```

O arquivo JSON contém objetos com `id` único e `text`. As referências são
opcionais e devem ser definidas antes da coleta:

```json
[
  {
    "id": "protected-host",
    "text": "bloqueie o host A",
    "expected_intent": {"operation": "BLOCK_HOST", "target": "hosta"},
    "expected_code": "HOST_PROTECTED"
  }
]
```

`expected_intent` verifica a operação e todos os parâmetros. Nomes e endereços
IP que identificam o mesmo host são normalizados antes dessa comparação.
`expected_code` verifica o resultado do fluxo completo. Uma intenção interpretada
errada pode, por coincidência, produzir o mesmo código esperado: por isso as
duas taxas são apresentadas separadamente.

Essas frases usam `--topology knowledge/control_topology.yaml` e
`--policies knowledge/control_policies.yaml`, com caminhos alternativos opcionais.
Os parâmetros do gerador sintético (`--switches`, `--rules`, `--loads`,
capacidades, bandas e `--cases`) se aplicam somente às execuções sem
`--text`, `--phrases`, `--intents` ou `--scenarios`.

Os exemplos incluídos são operacionais e alguns coincidem com frases de treino.
Servem para demonstrar a integração, sem comprovar generalização do Rasa/DIET.
Um erro do adaptador produz `INTERPRETATION_ERROR` e não chama o validador.

## Saídas automáticas

O programa cria uma pasta com identificador UTC. Para escolher outra, use
`--output results/benchmark/minha-coleta`. A pasta escolhida deve ser nova;
resultados existentes não são sobrescritos.

| Arquivo | Conteúdo |
|---|---|
| `report.html` | Relatório local com tabelas, exemplos, gráficos, arquitetura e limites. |
| `summary.csv` | Estatísticas consolidadas por configuração. |
| `cases.csv` | Estatísticas e acertos separados por caso; não calcula vazão por caso. |
| `runs.csv` | Sementes, tempos dos lotes e médias de cada repetição. |
| `samples.jsonl` | Tempos individuais, pedido, decisão, referências e comparações. |
| `metadata.json` | Parâmetros, ordem, carga, ambiente, inicialização e hashes dos fontes e entradas. |
| `latency.png` | Média do tempo total e desvio padrão das médias das repetições. |
| `throughput.png` | Vazão dos lotes por configuração. |
| `decisions.png` | Quantidades dos códigos observados, sem confundir frequência com acerto. |
| `stages.png` | Somente no modo textual: médias das etapas nas consultas em que ocorreram. |
| `architecture.svg` | Imagem da arquitetura para relatório e slides. |

Abra `report.html` no navegador. Para compartilhar o relatório, preserve os
arquivos da mesma pasta: o HTML utiliza imagens e dados locais. Ele não depende
de um servidor, JavaScript ou serviços externos.

## Métricas e arquitetura do código

`parse_args` valida os parâmetros. `synthetic_scenario` constrói o grafo, as
políticas e as referências. `load_intents` lê a carga estruturada personalizada,
`load_scenarios` prepara os cenários comparados e `load_phrases` lê a carga textual. `collect` executa
aquecimentos e consultas, sempre com `dry_run=True`. `summarize` calcula as
estatísticas, e `write_reports` produz os arquivos e chama `make_charts`.

As consultas preservam o estado: bloquear um host ou aprovar uma banda não
afeta os pedidos seguintes. Construção, leitura de arquivos, avaliação das
referências e geração dos relatórios ficam fora das janelas de medição.

- **Latência total:** duração de uma consulta; no modo textual inclui Rasa,
  adaptação e, quando aplicável, validação.
- **Interpretação:** Rasa e adaptação para `ControlIntent`.
- **Validação:** tempo de `submit(dry_run=True)`. Não é medido quando a
  interpretação impede que o pedido chegue ao validador.
- **P95:** posto `ceil(0,95 × N)` nos tempos ordenados; não é a média dos P95.
- **Variância:** variância amostral dos tempos individuais, em ms².
- **Desvio entre repetições:** desvio padrão amostral das médias dos lotes;
  com uma única repetição, a barra de dispersão é zero por convenção.
- **Vazão:** total de consultas dividido pelo tempo total dos lotes. Inclui o
  laço de coleta e o registro temporário em memória, sem escrita em disco.
- **Acerto do código:** proporção de códigos iguais às referências disponíveis.
  No modo textual mede o fluxo completo, incluindo erros de interpretação.
- **Aceitações/rejeições indevidas:** compara aprovação com a referência;
  `VALIDATED` representa aprovação e os outros códigos representam rejeição.
- **Acerto da intenção completa:** proporção de operações e parâmetros que
  coincidem com `expected_intent`, somente quando essa anotação existe.

Os campos sem referência ficam vazios no CSV e aparecem como “sem referência”
no relatório. Os denominadores estão nas colunas `decision_references` e
`intent_references`. As taxas variam de 0 a 1 nos arquivos de resultados.

As amostras repetidas não são frases diferentes nem repetições independentes.
O benchmark não oferece intervalos de confiança, garantias de rede ou avaliação
de instalação de regras. Feche cargas concorrentes durante medições, registre
as condições do computador e use o piloto para definir o volume da coleta.

## Verificação

```powershell
python -m pip install -r requirements-dev.txt -r requirements-benchmark.txt
python -m pytest tests/test_benchmark.py -q
```

Os testes cobrem o oráculo, preservação do estado, estatísticas com números
conhecidos, frases sem referência, erros de interpretação, distinção entre
acerto da intenção e da decisão, parâmetros inválidos e geração dos arquivos.
Os testes automatizados usam um interpretador controlado; uma execução com o
modelo Rasa salvo verifica a integração real separadamente.
