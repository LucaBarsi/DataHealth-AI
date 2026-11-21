# Escopo do DataHealth AI

## Problema de negocio
Os dados clinicos e operacionais estao distribuidos entre sistemas heterogeneos. A fragmentacao dificulta localizar informacoes relevantes e aumenta o tempo de consulta.

## Objetivo do MVP
Desenvolver um assistente de consulta aos registros de pacientes **sinteticos**, utilizando recuperacao de textos (RAG) e consultas estruturadas SQL, com fontes verificaveis e limites de acesso.

## Resultado da fase 1
Auditar os tipos de recursos FHIR, seus metadados, codigos, unidades e completude antes de modelar o banco de dados.

## Decisoes
- Fonte: dados sinteticos Synthea em FHIR R4.
- Na etapa local inicial, Python padrao para auditoria; em seguida SQLite ou PostgreSQL para consultas.
- Futuramente: embeddings, ChromaDB, Qwen 3.5 4B via Ollama, Streamlit.
- Em extensao: Kafka, Spark e camadas Bronze/Silver/Gold.
- Nao fazer diagnosticos, preditores clinicos ou alertas assistenciais autonomos.

## Metricas de avaliacao futuras
- Acerto de recuperacao de documentos e registros.
- Fidelidade factual das respostas aos registros citados.
- Tempo de resposta mediano e p95.
- Exito de consultas autorizadas e bloqueio de consultas proibidas.
- Integridade e rastreabilidade dos dados transformados.
