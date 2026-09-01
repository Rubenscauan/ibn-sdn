# Dados

`raw/nlu.md` é o dataset sintético original **NLU Dataset for IBNs**, de Saha, Haab e Podleski, obtido do repositório `barun-saha/IBNs`.

O arquivo `processed/training_intents.csv` é derivado dele pelo comando abaixo. Ele não deve ser editado manualmente.

```powershell
python scripts/prepare_dataset.py
```

O script remove a marcação de entidades do formato Rasa NLU e produz as colunas `text` e `intent` para o classificador TF-IDF + SVM.
