"""Rebuild deterministic tables and self-contained figures from an audited seal."""
from collections import Counter, defaultdict
from pathlib import Path
import csv
import html
import io
import json
from rcwg_full.evidence import canonical, digest, read, sha, write, exclusive_directory
from rcwg_full.campaign.sealing import authorized_package, relative_file
from .metrics import normalize, summarize, template_means, frontier,common_reference_domain,pair_e2
from .statistics import paired_inference, holm, hypothesis_registry


def _csv(rows):
    columns = sorted({k for row in rows for k in row})
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, columns, lineterminator='\n'); writer.writeheader()
    for row in rows:
        writer.writerow({k: canonical(v).decode() if isinstance(v, (dict, list)) else v for k, v in row.items()})
    return stream.getvalue().encode('utf-8')


def _bar_chart(rows):
    width, height = 900, 90 + 38 * len(rows)
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="#fff"/>',
                '<text x="24" y="28" font-family="sans-serif" font-size="18">Success@Budget · fixed-denominator identification bounds</text>']
    for index, row in enumerate(rows):
        y = 65 + index * 38
        lower, upper = row['identification_lower'], row['identification_upper']
        label = html.escape(f"{row['generator']} / {row['protocol']}")
        elements.extend([f'<text x="24" y="{y + 16}" font-family="sans-serif" font-size="13">{label}</text>',
                         f'<rect x="180" y="{y}" width="{600 * upper:.3f}" height="22" fill="#cbd5e1"/>',
                         f'<rect x="180" y="{y}" width="{600 * lower:.3f}" height="22" fill="#2563eb"/>',
                         f'<text x="795" y="{y + 16}" font-family="sans-serif" font-size="12">{lower:.3f}–{upper:.3f}</text>'])
    return ('\n'.join(elements) + '\n</svg>').encode('utf-8')


def rebuild(sealed_manifest, output):
    manifest, release = authorized_package(sealed_manifest)
    root = Path(sealed_manifest).parent
    def load(name, default=None):
        if name not in manifest['files']:
            if default is not None: return default
            raise ValueError('SEALED_INPUT_MISSING:' + name)
        return json.loads(read(relative_file(root, name)))
    expected, observations = load('expected.json'), load('observations.json')
    references = load('references.json', {})
    normalized = normalize(expected, observations, references, mode=manifest['mode'])
    reference_domain=common_reference_domain(expected,references,mode=manifest['mode'])
    e2_expected=[s for s in expected if s.get('experiment_id')=='E2']
    e2_observed=[s for s in observations if s.get('experiment_id')=='E2']
    e2=normalize(e2_expected,e2_observed,references,mode=manifest['mode'],ledger_role='DIAGNOSTIC')
    paired=[]
    if e2['rows']:
        # Restrict to the preregistered diagnostic identities before pairing.
        e2_keys={(r['task_id'],r['generator'],r['protocol'],r['trial_label'],r['execution_repeat']) for r in e2['rows']}
        adaptive=[r for r in normalized['rows'] if (r['task_id'],r['generator'],r['protocol'],r['trial_label'],r['execution_repeat']) in e2_keys]
        paired=pair_e2(adaptive,e2['rows'])
    groups = defaultdict(list)
    for row in normalized['rows']:
        groups[(row['generator'], row['protocol'], row.get('arm'))].append(row)
    if not groups:
        raise ValueError('NO_PRIMARY_EXECUTION_SLOTS')
    summaries, efficient, coverage = [], [], []
    for (generator, protocol, arm), rows in sorted(groups.items(), key=lambda item: str(item[0])):
        families = sorted({r['family'] for r in rows})
        if manifest['mode'] == 'FORMAL' and families != [f'F{i}' for i in range(1, 7)]:
            raise ValueError('FORMAL_FAMILY_COVERAGE')
        identity = {'generator': generator, 'protocol': protocol, 'arm': arm}
        summaries.append({**identity, **summarize(rows, families=families, evidence_integrity=normalized['evidence_integrity'])})
        for epsilon in [0.1, 0.2, 0.5]:
            selected = [{**r, 'efficient': False if r['success'] is False else r['rho'] <= 1 + epsilon if r['rho'] is not None else None}
                        for r in rows if r['task_id'] in reference_domain]
            if selected and {r['family'] for r in selected} == set(families):
                estimate = summarize(selected, 'efficient', families=families, evidence_integrity=normalized['evidence_integrity'])
            else:
                estimate = {'point': None, 'reason': 'REFERENCE_COVERAGE_INCOMPLETE', 'denominator': len(selected)}
            efficient.append({**identity, 'epsilon': epsilon, 'primary_denominator': len(rows), 'common_reference_domain_hash':digest(sorted(reference_domain)),**estimate})
        for family in families:
            family_rows = [r for r in rows if r['family'] == family]
            coverage.append({**identity, 'family': family, 'expected': len(family_rows),
                             'observed': sum(r['selected_attempt'] is not None for r in family_rows),
                             'reference_covered': sum(r['reference_covered'] for r in family_rows),
                             'frozen_common_reference_slots':sum(r['task_id'] in reference_domain for r in family_rows),
                             'timing_valid': sum(r.get('completed_time_ns') is not None for r in family_rows)})
    hypotheses = hypothesis_registry(); infer = []
    for definition in hypotheses['tests']:
        key = definition['generator']; metric = 'success' if definition['metric'] == 'SuccessBudget' else 'efficient'
        record = {**definition, 'status': 'NOT_ESTIMABLE', 'reason': 'PAIRED_OBSERVATIONS_OR_REFERENCE_MISSING'}
        if definition['contrast'] != 'Adaptive-Frozen':
            left, right = groups.get((key, 'P1', None)), groups.get((key, 'P0', None))
            if metric=='efficient':
                left=[r for r in (left or []) if r['task_id'] in reference_domain]
                right=[r for r in (right or []) if r['task_id'] in reference_domain]
            if left and right and not any(r[metric] is None for r in left + right):
                # All lower-level units must be paired before any template mean.
                pairing = lambda rows: {(r['task_id'], r['trial_label'], r['execution_repeat']) for r in rows}
                if pairing(left) != pairing(right): raise ValueError('PRIMARY_PAIRING_MISMATCH')
                families = sorted({r['family'] for r in left})
                record.update(status='ESTIMATED', reason=None,
                              **paired_inference(template_means(left, metric, 0), template_means(right, metric, 0), families=families))
        else:
            selected=[(a,b) for a,b in paired if a['generator']==key]
            if selected and e2['evidence_integrity']=='PASS' and not any(r['success'] is None for pair in selected for r in pair):
                left=[a for a,b in selected];right=[b for a,b in selected]
                families=sorted({r['family'] for r in left})
                record.update(status='ESTIMATED',reason=None,protocol_pooling='equal protocol weight within identical lower-level units',
                    **paired_inference(template_means(left,'success',0),template_means(right,'success',0),families=families))
        infer.append(record)
    # The family remains all 18 preregistered hypotheses. A missing test is never
    # dropped to shrink multiplicity; p=1 is only an internal conservative bound.
    adjusted = holm({r['id']: r.get('p_two_sided', 1.0) for r in infer})
    for record in infer:
        record['p_holm'] = adjusted[record['id']] if record['status'] == 'ESTIMATED' else None
    statuses = [dict(status=k, count=v) for k, v in sorted(Counter(r['observed_status'] for r in normalized['rows']).items())]
    strata = []
    for stratum in ['standard', 'compositional']:
        for condition in ['C0', 'C1', 'C2', 'C3']:
            subset = [r for r in normalized['rows'] if r.get('stratum') == stratum and r['condition'] == condition]
            strata.append({'stratum': stratum, 'condition': condition, 'denominator': len(subset),
                           'unknown': sum(r['success'] is None for r in subset)})
    diagnostics = [r for r in observations if r.get('experiment_id') in {'E2','E3','E4','E5','E7','E8'}]
    selected_by_attempt={r['selected_attempt']:r for r in normalized['rows'] if r['selected_attempt']}
    resources = [{**r,**selected_by_attempt[r['attempt_id']]} for r in observations if r['attempt_id'] in selected_by_attempt]
    resource_frontier = frontier(resources, ['exec_elapsed_ns', 'worker_memory_peak_bytes'])
    tables = {'task_resource_coverage': coverage, 'success_budget': summaries, 'efficient_success': efficient,
              'failure_unknown_not_run': statuses, 'reference_coverage': coverage,
              'resource_vectors': resources, 'resource_frontier': resource_frontier,
              'frozen_adaptive': [{'task_id':a['task_id'],'generator':a['generator'],'protocol':a['protocol'],
                'trial_label':a['trial_label'],'execution_repeat':a['execution_repeat'],'adaptive_success':a['success'],
                'frozen_success':b['success'],'difference':int(a['success'])-int(b['success']) if a['success'] is not None and b['success'] is not None else None,
                'frozen_plan_hash':b.get('plan_hash'),'c0_source_plan_hash':b.get('c0_source_plan_hash')} for a,b in paired],
              'artifact_lifetime': load('artifact_lifetimes.json', []),
              'information_fidelity': load('information_fidelity.json', []),
              'diagnostics': diagnostics, 'generalization': strata,
              'external_coverage': [r for r in diagnostics if r.get('experiment_id') == 'E8'],
              'hypotheses': infer}
    out = exclusive_directory(output); outputs = {}
    metadata = {'manifest_hash': manifest['manifest_hash'], 'mode': manifest['mode'],
                'scope': 'SEALED_PRIMARY_LOGICAL_EXECUTION_SLOTS', 'unit': 'proportion_or_declared_metric_unit',
                'filter': 'role=PRIMARY; confirmation excluded; at most one reconciled facility retry',
                'denominator': len(normalized['rows']), 'measurement_status': 'PRESERVED_FROM_INPUT_NOT_INFERRED',
                'formal_ready': False}
    for name, rows in tables.items():
        outputs[name + '.json'] = write(out / (name + '.json'), {'metadata': {**metadata, 'table_rows': len(rows)}, 'rows': rows})
        outputs[name + '.csv'] = write(out / (name + '.csv'), _csv(rows))
    outputs['success.svg'] = write(out / 'success.svg', _bar_chart(summaries))
    sections = ''.join(f'<section><h2>{html.escape(name.replace("_", " "))}</h2><p>{len(rows)} rows</p><a href="{name}.csv">CSV</a> · <a href="{name}.json">JSON and scope</a></section>' for name, rows in tables.items())
    page = ('<!doctype html><meta charset="utf-8"><title>RCWG offline analysis</title>'
            '<style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:0 20px;color:#172554}section{padding:12px 0;border-top:1px solid #cbd5e1}img{max-width:100%}</style>'
            f'<h1>RCWG offline analysis</h1><p>Mode: {html.escape(manifest["mode"])} · Formal gate: BLOCKED_NOT_FROZEN</p>'
            '<p>Gray intervals show unresolved outcomes at a fixed denominator. They are not confidence intervals.</p>'
            '<img src="success.svg" alt="Success identification bounds">' + sections)
    outputs['report.html'] = write(out / 'report.html', page.encode('utf-8'))
    code = {p.name: sha(read(p)) for p in sorted(Path(__file__).parent.glob('*.py'))}
    result = {'schema_version': 'FULL001_ANALYSIS_1', 'sealed_manifest_hash': manifest['manifest_hash'],
              'audit_release_hash': digest(release), 'inputs': manifest['files'], 'outputs': outputs,
              'statistics_code': code, 'bootstrap_seed': 170029, 'sign_seed': 290017,
              'renderer': 'FULL001_SVG_1', 'numerical_tables_hash': digest(tables),
              'evidence_integrity': normalized['evidence_integrity'], 'formal_ready': False}
    write(out / 'analysis-manifest.json', result)
    return result
