# Registro de transformacoes — versao inicial

| Campo FHIR | Transformacao planejada | Motivo | Validacao | Status |
| --- | --- | --- | --- | --- |
| `Patient.id` | Preservar como chave de integracao | Associar recursos ao paciente | Checar referencias e unicidade | Planejada |
| `Observation.code.coding` | Extrair sistema/codigo/descricao | Diferenciar conceitos clinicos | Conferir pares codigo-sistema | Planejada |
| `Observation.valueQuantity` | Extrair valor, unidade textual e codigo UCUM | Permitir comparacoes sem perder unidade | Testar consistencia por codigo e unidade | Planejada |
| `Observation.effectiveDateTime` | Converter para timestamp com timezone | Ordenar series temporais corretamente | Verificar parse e offsets | Planejada |
| `Encounter.subject.reference` | Resolver referencia com Patient | Integrar atendimento | Testar integridade referencial | Planejada |

**Regra geral:** jamais converter unidades ou inferir dados ausentes sem verificar a semantica do campo e registrar a decisao. Preservar os dados originais.
