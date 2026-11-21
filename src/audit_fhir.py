"""Fase 1 do DataHealth AI: auditoria exploratoria de dados HL7 FHIR R4.

Sem dependencias externas. Aceita um arquivo ZIP oficial Synthea ou uma pasta
contendo bundles JSON. Gera inventario e relatorio de qualidade.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Iterable, Iterator, Tuple
from zipfile import ZipFile, BadZipFile


def iter_documents(source: Path) -> Iterator[Tuple[str, dict]]:
    if source.is_file() and source.suffix.lower() == '.zip':
        with ZipFile(source) as zf:
            for filename in sorted(zf.namelist()):
                if not filename.lower().endswith('.json') or filename.endswith('/'):
                    continue
                with zf.open(filename) as stream:
                    try:
                        document = json.load(io.TextIOWrapper(stream, encoding='utf-8'))
                    except (json.JSONDecodeError, UnicodeError) as exc:
                        raise ValueError(f'JSON invalido em {filename}: {exc}') from exc
                yield filename, document
    elif source.is_dir():
        for item in sorted(source.rglob('*.json')):
            try:
                with item.open(encoding='utf-8') as stream:
                    yield str(item.relative_to(source)), json.load(stream)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ValueError(f'JSON invalido em {item}: {exc}') from exc
    elif source.is_file() and source.suffix.lower() == '.json':
        with source.open(encoding='utf-8') as stream:
            yield source.name, json.load(stream)
    else:
        raise ValueError('Informe ZIP, arquivo .json ou diretorio de JSONs FHIR.')


def resources_from_document(document: dict) -> Iterable[dict]:
    if document.get('resourceType') == 'Bundle':
        for entry in document.get('entry', []):
            resource = entry.get('resource')
            if isinstance(resource, dict) and resource.get('resourceType'):
                yield resource
    elif document.get('resourceType'):
        yield document


def primary_code(resource: dict) -> tuple[str, str, str]:
    value = resource.get('code', {})
    if not isinstance(value, dict):
        return '', '', ''
    for coding in value.get('coding', []):
        if isinstance(coding, dict) and coding.get('code'):
            return str(coding.get('system', '')), str(coding['code']), str(coding.get('display') or value.get('text') or '')
    return '', '', str(value.get('text', ''))


def observation_value_kind(record: dict) -> str:
    for key in ('valueQuantity','valueCodeableConcept','valueString','valueBoolean','valueInteger','valueDateTime','valuePeriod','valueRange','valueRatio','valueSampledData','component'):
        if key in record:
            return key
    return 'ausente'


def run_audit(input_path: Path, output_path: Path) -> dict:
    output_path.mkdir(parents=True, exist_ok=True)
    totals = Counter()
    observed_fields = defaultdict(Counter)
    observation_codes = Counter()
    observation_meta = {}
    patient_ids = set()
    observations_missing = Counter()
    examples = []
    documents = 0
    patient_document_count = 0
    resource_ids_by_type = defaultdict(set)
    repeated_resource_ids = Counter()
    for filename, document in iter_documents(input_path):
        documents += 1
        if not isinstance(document, dict):
            continue
        resources = list(resources_from_document(document))
        if any(r.get('resourceType') == 'Patient' for r in resources):
            patient_document_count += 1
        for r in resources:
            kind = r.get('resourceType', 'Unknown')
            totals[kind] += 1
            observed_fields[kind].update(r.keys())
            rid = str(r.get('id', ''))
            if rid:
                if rid in resource_ids_by_type[kind]:
                    repeated_resource_ids[kind] += 1
                resource_ids_by_type[kind].add(rid)
            if kind == 'Patient':
                patient_ids.add(rid)
            if kind == 'Observation':
                system, code, label = primary_code(r)
                category = ', '.join(
                    c.get('coding', [{}])[0].get('code', '')
                    for c in r.get('category', []) if c.get('coding')
                )
                quantity = r.get('valueQuantity', {})
                unit = quantity.get('unit', '') if isinstance(quantity, dict) else ''
                unit_code = quantity.get('code', '') if isinstance(quantity, dict) else ''
                key = (system, code, label, category, unit, unit_code, observation_value_kind(r))
                observation_codes[key] += 1
                if not r.get('subject', {}).get('reference'):
                    observations_missing['sem_subject'] += 1
                if not (r.get('effectiveDateTime') or r.get('effectivePeriod') or r.get('issued')):
                    observations_missing['sem_data_medicao'] += 1
                if observation_value_kind(r) == 'ausente':
                    observations_missing['sem_valor_observacao'] += 1
                if len(examples) < 20:
                    examples.append({
                        'id': rid,
                        'subject_reference': r.get('subject', {}).get('reference', ''),
                        'date': r.get('effectiveDateTime') or r.get('issued') or '',
                        'code': code,
                        'description': label,
                        'value': quantity.get('value', '') if isinstance(quantity, dict) else '',
                        'unit': unit,
                        'source_file': filename,
                    })
    if documents == 0:
        raise ValueError('Nenhum arquivo JSON encontrado. Confira caminho e conteudo do ZIP.')
    resource_count = sum(totals.values())
    overview = {
        'source': str(input_path),
        'processed_at_utc': datetime.now(timezone.utc).isoformat(),
        'json_documents': documents,
        'documents_with_patient': patient_document_count,
        'unique_patients': len(patient_ids),
        'total_resources': resource_count,
        'resource_types': dict(sorted(totals.items())),
        'observation_data_quality': dict(observations_missing),
        'duplicate_ids_within_resource_type': dict(repeated_resource_ids),
    }
    (output_path / 'summary.json').write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output_path / 'resource_types.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['resource_type', 'count'])
        writer.writerows(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))
    with (output_path / 'field_inventory.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['resource_type', 'field', 'records_with_field', 'total_records', 'coverage_percent'])
        for kind in sorted(observed_fields):
            for field, n in sorted(observed_fields[kind].items()):
                writer.writerow([kind, field, n, totals[kind], round(n * 100 / totals[kind], 1)])
    with (output_path / 'observation_codes.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['coding_system', 'code', 'description', 'category', 'unit_label', 'unit_code', 'value_type', 'count'])
        for key, n in sorted(observation_codes.items(), key=lambda kv: (-kv[1], kv[0])):
            writer.writerow([*key, n])
    with (output_path / 'observation_examples.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        fields = ['id','subject_reference','date','code','description','value','unit','source_file']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(examples)
    observations = totals['Observation']
    lines = [
        '# Relatorio exploratorio inicial — DataHealth AI',
        '',
        f'- Documentos JSON processados: **{documents}**',
        f'- Arquivos com recurso Patient: **{patient_document_count}**',
        f'- Pacientes unicos identificados por ID: **{len(patient_ids)}**',
        f'- Recursos FHIR identificados: **{resource_count}**',
        f'- Observations: **{observations}**',
        '',
        '## Qualidade preliminar de Observation',
        '',
        f'- Sem referencia ao paciente: **{observations_missing["sem_subject"]}**',
        f'- Sem horario da medicao ou emissao: **{observations_missing["sem_data_medicao"]}**',
        f'- Sem campo de valor nem componentes: **{observations_missing["sem_valor_observacao"]}**',
        '',
        '## Limites desta auditoria',
        '',
        '- Inventario estrutural, ainda nao valida a conformidade integral com HL7 FHIR.',
        '- IDs duplicados devem ser investigados: podem representar repeticao de exportacao.',
        '- Codigos, unidades e metadados nao foram convertidos automaticamente.',
        '- Dados simulados nao devem sustentar conclusoes clinicas.',
        '',
        '## Proximos passos',
        '',
        '1. Examinar `field_inventory.csv` e `observation_codes.csv`.',
        '2. Definir mapeamentos por codigo e unidade, com validacao.',
        '3. Criar tabelas Patient, Encounter, Observation, Condition e MedicationRequest.',
        '4. Construir consultas estruturadas por paciente e testes de qualidade.',
    ]
    (output_path / 'eda_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return overview


def main() -> None:
    parser = argparse.ArgumentParser(description='Auditoria inicial dos recursos FHIR do Synthea')
    parser.add_argument('--input', required=True, type=Path, help='ZIP Synthea, arquivo JSON ou pasta de JSONs')
    parser.add_argument('--output', default=Path('reports'), type=Path)
    args = parser.parse_args()
    overview = run_audit(args.input, args.output)
    print(f"Concluido: {overview['total_resources']} recursos, {overview['unique_patients']} pacientes")
    print(f"Relatorios em: {args.output.resolve()}")


if __name__ == '__main__':
    main()
