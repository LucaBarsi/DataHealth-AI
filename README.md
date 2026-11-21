# DataHealth AI — Fase 1: exploracao e auditoria de dados FHIR

Projeto educativo de engenharia de dados e LLM na saude, utilizando **somente pacientes sinteticos**.

## 1. Testar o projeto imediatamente

Precisa apenas do Python 3.10+ (sem dependencias externas).

No Windows PowerShell, dentro da pasta do projeto:

```powershell
python -m src.audit_fhir --input data/demo --output reports/demo
python -m unittest discover -s tests -v
```

Os relatorios aparecerao em `reports/demo/`.

## 2. Baixar os dados oficiais

Fonte: https://synthetichealth.github.io/downloads.html

Na secao **Latest Version of Synthea**, baixar **100 Sample Synthetic Patient Records, FHIR R4**.

Salvar o ZIP em `data/raw/synthea_sample_data_fhir_latest.zip` (sem extrair).

## 3. Auditar os dados oficiais

```powershell
python -m src.audit_fhir --input data/raw/synthea_sample_data_fhir_latest.zip --output reports/synthea
```

O script identifica recursos e gera:

- `summary.json` — contagens e indicadores iniciais;
- `resource_types.csv` — distribuicao dos tipos FHIR;
- `field_inventory.csv` — cobertura dos campos (metadados de estrutura);
- `observation_codes.csv` — sistemas de codificacao, codigos, unidades, tipos e frequencias;
- `observation_examples.csv` — pequenas amostras de observacoes **sinteticas**;
- `eda_report.md` — interpretacao preliminar e proximos passos.

O script NAO modifica nem transforma a base original.

## 4. O que nos enviar para a proxima etapa

Compartilhe o `summary.json`, `field_inventory.csv`, `observation_codes.csv` e `eda_report.md` gerados, ou envie o ZIP oficial se preferir.

## 5. Arquitetura prevista

FHIR sintetico -> integracao -> dados estruturados + documentos -> SQL + RAG -> Qwen 3.5 4B (Ollama) -> app Streamlit.

Kafka, Spark e nuvem entram em fases posteriores para demonstrar arquitetura escalavel, depois do MVP funcional.

## Restricoes

- Nao usar dados reais de pacientes neste ambiente de aprendizado.
- Nao enviar `.env`, senhas ou chaves de API.
- Os dados Synthea sao ficticios; resultados nao comprovam acuracia clinica.
- Consultas com LLM exigirao verificacao de fontes, controle de acesso e tratamento de erros.

## Credito

Synthea (MITRE): https://github.com/synthetichealth/synthea
