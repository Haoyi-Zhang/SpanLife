"""Data-only topology table; do not publish disagreement as agreement."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from spanlife.topology_records import EXPECTED, TOPOLOGY_CASES, summarize_rows

GROUPS = (
    ('Valid split topology', ['split_link_valid', 'split_parent_valid']),
    ('Missing/wrong handoff', ['split_missing_relation', 'split_wrong_relation']),
    ('Boundary-order faults', ['split_submission_overlap', 'split_execution_early_end']),
    ('Missing segment', ['split_execution_missing', 'split_submission_missing']),
    ('Valid same-name concurrency', ['correlated_concurrent_valid']),
    ('Missing/swapped correlation', ['correlated_missing_attribute', 'correlated_swapped_attribute']),
    ('Duplicate correlation', ['correlated_duplicate_attribute']),
)


def topology_table(directory):
    directory = Path(directory)
    rows = json.loads((directory / 'trials.json').read_text())
    summary = json.loads((directory / 'summary.json').read_text())
    if not isinstance(rows, list) or not rows or not isinstance(summary, dict):
        raise ValueError('Missing topology trials or summary')
    identities = set()
    for row in rows:
        case, repeat = row['case'], row['repeat']
        if case not in EXPECTED or type(repeat) is not int or repeat < 0 or (case, repeat) in identities:
            raise ValueError('Invalid or duplicate topology trial identity')
        identities.add((case, repeat))
        expected_verdict, expected_codes = EXPECTED[case]
        if row['expected_verdict'] != expected_verdict or row['expected_codes'] != list(expected_codes):
            raise ValueError('Topology expectations differ from the declared contracts')
        for field in ('actual', 'direct', 'name'):
            if row[field] not in {'pass', 'fail', 'inconclusive'}:
                raise ValueError('Invalid topology verdict')
    if {case for case, _ in identities} != set(TOPOLOGY_CASES):
        raise ValueError('Incomplete topology case coverage')
    if type(summary.get('runner_failures')) is not int or summary['runner_failures'] != 0:
        raise ValueError('Cannot publish an incomplete topology campaign')
    computed = summarize_rows(rows, 0)
    if any(summary.get(key) != value for key, value in computed.items()):
        raise ValueError('Topology summary differs from trial rows')
    if computed['direct_disagreements']:
        raise ValueError('Cannot publish topology direct-check disagreement as agreement')
    lines = [r'\begin{tabular}{lccc}', r'\toprule',
             r'Contract family & SpanLife P/F/I & Direct & Name-only P/F/I\\', r'\midrule']
    for label, names in GROUPS:
        selected = [row for row in rows if row['case'] in names]
        counts = Counter(row['actual'] for row in selected)
        name_counts = Counter(row['name'] for row in selected)
        # The overall admission above and this selected comparison both derive
        # from actual trial outcomes, not a literal assertion in the template.
        if any(row['actual'] != row['direct'] for row in selected):
            raise ValueError(f'Direct-check disagreement: {label}')
        pfi = '/'.join(str(counts[verdict]) for verdict in ('pass', 'fail', 'inconclusive'))
        name_pfi = '/'.join(str(name_counts[verdict]) for verdict in ('pass', 'fail', 'inconclusive'))
        lines.append(f'{label} & {pfi} & agree & {name_pfi}\\\\')
    return '\n'.join([*lines, r'\bottomrule', r'\end{tabular}', ''])
