# IBN-SDN

Protótipo inicial de *Intent-Based Networking* que converte instruções de rede em linguagem natural em uma intenção estruturada. Nesta etapa, o projeto implementa apenas:

- **Milestone 1:** classificação de intenção com TF-IDF + SVM;
- **Milestone 2:** extração de entidades e criação de `NetworkIntent`.

Os módulos de base de conhecimento, políticas e SDN ficam deliberadamente fora desta primeira entrega.

## Requisitos

- Python 3.10 ou superior

```powershell
python -m pip install -r requirements.txt
```

## Uso

```powershell
python -m ibn_sdn "block host1 from accessing host2"
```

Saída esperada:

```json
{
  "action": "BLOCK_ACCESS",
  "source": "host1",
  "destination": "host2"
}
```

Na primeira execução, o classificador é treinado e salvo em `models/intent_classifier.joblib`. As próximas execuções apenas carregam esse arquivo. Depois de alterar o dataset, atualize o modelo explicitamente:

```powershell
python -m ibn_sdn --retrain "block host1 from accessing host2"
```

O modelo é treinado localmente a partir de `data/processed/training_intents.csv`, derivado do [NLU Dataset for IBNs](https://github.com/barun-saha/IBNs). Para recriar o CSV a partir da fonte original, execute `python scripts/prepare_dataset.py`. Para experimentar outro classificador ou dataset, mantenha as colunas `text` e `intent` e injete outro classificador compatível em `IntentParser`.

Se menos de 40% dos termos (palavras e pares de palavras) de uma frase aparecem no vocabulário aprendido, o pipeline retorna `{"action": "UNKNOWN"}` e não tenta interpretar entidades. Essa é uma proteção inicial contra mensagens fora de domínio; o limiar deverá ser calibrado com um conjunto de validação quando os experimentos forem adicionados.

## Testes

```powershell
python -m pytest
```
