# DataHealth AI — Technical Documentation

**Data that connects. Insights you can trace.**

This directory organizes the technical documentation for the **local, synthetic-data DataHealth AI research prototype**. It is a **navigation index**; historical phase README files were moved into `development_history/` during Phase 22, with relative Markdown links updated.

> **Synthetic data only.** This project is not intended for clinical decisions or use with real patient information. Structural quality checks and valid source identifiers do not establish clinical correctness.

For an overview, setup instructions, screenshots, implemented features, and current limitations, start with the [main project README](../README.md).

## Architecture and project scope

| Document | Focus |
|---|---|
| [Architecture overview](architecture_overview.mmd) | Source Mermaid system diagram |
| [Project scope](project_scope.md) | Prototype boundaries and objectives |
| [Hybrid assistant architecture](hybrid_assistant_architecture.md) | Clinical AI and retrieval integration |
| [Visual identity](visual_identity.md) | Design conventions |

## Data engineering and quality

| Document | Focus |
|---|---|
| [FHIR mapping notes](fhir_mapping_notes.md) | FHIR-derived field mappings |
| [Silver Layer rules](silver_layer_rules.md) | Normalization and structural quality treatment |
| [Gold Layer design](gold_layer_design.md) | Relational analytics schema |
| [Data quality plan](data_quality_plan.md) | Planned quality checks |
| [Data quality findings](data_quality_findings.md) | Observed quality findings |
| [Transformation log](transformation_log.md) | Transformation notes |
| [Patient name mapping](patient_name_mapping.md) | Synthetic patient display names and mapping |

## Clinical AI, retrieval, and evaluation

| Document | Focus |
|---|---|
| [RAG architecture](rag_architecture.md) | Document retrieval design |
| [Phase 5 LLM integration](phase5_llm_integration.md) | Earlier LLM integration work |
| [Phase 14 Cloud Demo suggestions](phase14_cloud_qwen_suggestions.md) | Suggested-question flow |
| [Phase 17 semantic RAG](phase17_semantic_rag.md) | Semantic retrieval experiments |
| [Phase 17.1 retrieval benchmark](phase17_1_retrieval_benchmark.md) | Retrieval benchmark notes |
| [Phase 17.2 hybrid retrieval](phase17_2_hybrid_retrieval.md) | Hybrid retrieval evaluation |
| [Phase 17.3 RRF weight analysis](phase17_3_rrf_weight_analysis.md) | Retrieval fusion analysis |
| [LLM evaluation methodology](llm_evaluation_methodology.md) | Evaluation methods and scope |
| [Citation reliability policy](reliability_citation_policy.md) | Source-marker and citation safeguards |
| [Evidence scope consistency](evidence_scope_consistency.md) | Evidence and patient-scope checks |
| [Cloud LLM evaluation security](cloud_llm_evaluation_security.md) | Cloud Demo evaluation and security notes |
| [Cloud Qwen diagnostics](cloud_qwen_diagnostics.md) | Model-inference diagnostics |

## Interfaces, analytics, and forecasting

| Document | Focus |
|---|---|
| [Streamlit interface](streamlit_interface.md) | UI implementation notes |
| [Analytics Dashboard](analytics_dashboard.md) | Structured analytics interface |
| [Contextual charts](contextual_charts.md) | Evidence-linked measurement displays |
| [Phase 18 workload forecasting](phase18_workload_forecasting.md) | Exploratory operational forecasting |
| [Power BI dashboard guide](power_bi_dashboard_guide.md) | Downstream export/reporting guidance |

## Deployment, publication, and safety

| Document | Focus |
|---|---|
| [Deployment readiness](deployment_readiness.md) | Local-to-hosted deployment boundaries |
| [Cloud deployment plan](cloud_deployment_plan.md) | Proposed cloud architecture, not an implemented deployment |
| [Publication checklist](publication_checklist.md) | Release safety and publishing preparation |

## Development history — phase READMEs

Phase-specific historical reports are stored in `docs/development_history/` as the project's technical development record. Their relative Markdown links were updated and checked during Phase 22.

| Phase / topic | Document |
|---|---|
| Phase 6 | [README_PHASE6.md](development_history/README_PHASE6.md) |
| Phase 7 | [README_PHASE7.md](development_history/README_PHASE7.md) |
| Phase 8 / 8.1 | [Phase 8](development_history/README_PHASE8.md) · [Phase 8.1](development_history/README_PHASE8_1.md) |
| Phase 9 | [README_PHASE9.md](development_history/README_PHASE9.md) |
| Phase 10 | [README_PHASE10.md](development_history/README_PHASE10.md) |
| Phase 11 | [README_PHASE11.md](development_history/README_PHASE11.md) |
| Phase 12 | [README_PHASE12.md](development_history/README_PHASE12.md) |
| Phase 13 | [README_PHASE13.md](development_history/README_PHASE13.md) |
| Phase 14 | [README_PHASE14.md](development_history/README_PHASE14.md) |
| Phase 15 | [README_PHASE15.md](development_history/README_PHASE15.md) |
| Phase 16 / 16.1 | [Phase 16](development_history/README_PHASE16.md) · [Phase 16.1](development_history/README_PHASE16_1.md) |
| Phase 17 | [README_PHASE17.md](development_history/README_PHASE17.md) |
| Phase 17.1 / 17.2 / 17.3 | [17.1](development_history/README_PHASE17_1.md) · [17.2](development_history/README_PHASE17_2.md) · [17.3](development_history/README_PHASE17_3.md) |
| Phase 18 / 18.1 | [Phase 18](development_history/README_PHASE18.md) · [Phase 18.1](development_history/README_PHASE18_1.md) |
| Phase 19 | [Spark ETL](development_history/README_PHASE19_SPARK.md) |
| Phase 20 | [Local integration audit](development_history/README_PHASE20_LOCAL_INTEGRATION.md) |
| Phase 21 | [Contextual charts validation](development_history/PHASE21_CONTEXTUAL_CHARTS_VALIDATION.md) |
| Power BI | [README_POWER_BI.md](development_history/README_POWER_BI.md) |

## Environment and dependency manifests

- [Windows application requirements](../requirements.txt)
- [Ubuntu/WSL Spark requirements](../requirements-spark.txt)
- Historical `requirements_phase*.txt` files remain at repository root.

**Phase 22 release note:** The migration moved 23 historical Markdown documents and updated 33 local Markdown links; the post-migration link check reported no missing local targets. This does not validate screenshots, external URLs, technical accuracy, or full clean-machine reproducibility. The source release was committed and pushed to the private GitHub `main` branch. See the [Phase 22 final validation report](../PHASE22_FINAL_VALIDATION.md).
