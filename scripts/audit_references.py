#!/usr/bin/env python3
"""Offline bibliography/citation/provenance audit for the submitted manuscript."""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent

ENTRY = re.compile(r"^@([A-Za-z]+)\{([^,]+),(.*?)(?=^@[A-Za-z]+\{|\Z)", re.M | re.S)
FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*\{(.*?)\}\s*,?\s*$", re.M | re.S)

def parse_bib(text: str) -> dict[str, dict]:
    out = {}
    for typ, key, body in ENTRY.findall(text):
        key = key.strip()
        assert key not in out, f"duplicate BibTeX key: {key}"
        fields = {name.lower(): re.sub(r"\s+", " ", value.strip()) for name, value in FIELD.findall(body)}
        out[key] = {"type": typ.lower(), "fields": fields,
                    "record_sha256": hashlib.sha256((f"@{typ}{{{key},{body}").encode()).hexdigest()}
    return out

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, default=ROOT/'results/reference-audit-summary.json')
    args = ap.parse_args()
    bib_path = PROJECT/'paper/references.bib'
    tex_path = PROJECT/'paper/main.tex'
    audit_path = ROOT/'provenance/reference-audit.json'
    bib_text = bib_path.read_text(); tex = tex_path.read_text(); audit = json.loads(audit_path.read_text())
    entries = parse_bib(bib_text)
    citations = []
    for match in re.finditer(r"\\cite\{([^}]+)\}", tex):
        citations.extend(k.strip() for k in match.group(1).split(',') if k.strip())
    cite_set = set(citations); bib_set = set(entries)
    assert cite_set == bib_set, {"missing": sorted(cite_set-bib_set), "uncited": sorted(bib_set-cite_set)}
    records = audit['records']; audit_map = {r['bib_key']: r for r in records}
    assert len(audit_map) == len(records) == audit['reference_count'] == len(entries)
    assert set(audit_map) == bib_set
    assert len(entries) >= 60

    identifiers = []
    category_counts = Counter()
    for key, entry in entries.items():
        f = entry['fields']
        assert {'author','title','year'} <= set(f), (key, f.keys())
        assert re.fullmatch(r"(?:19|20)\d{2}", f['year']), (key, f['year'])
        record = audit_map[key]
        category_counts[record['category']] += 1
        verified_on = record.get('verified_on','')
        assert re.fullmatch(r'20\d{2}-\d{2}-\d{2}', verified_on), (key, verified_on)
        assert verified_on <= audit.get('verified_through', audit['verified_on']), (key, verified_on)
        assert record.get('source_url','').startswith('https://')
        assert record.get('checked_fields')
        ident = record.get('identifier','').strip()
        assert ident, key
        identifiers.append((key, ident.casefold()))
        if record['category'] == 'peer-reviewed-research':
            assert ident.startswith('doi:') or any(x in record['source_url'] for x in ('usenix.org','research.google')), (key, ident)
        if record['category'] == 'research-preprint':
            joined = ' '.join(f.values()).lower()
            assert 'arxiv' in joined and ('arxiv:' in ident.lower()), (key, ident)
        if record['category'] in ('primary-source','official-documentation'):
            assert any(host in record['source_url'] for host in (
                'github.com','pypi.org','python.org','docs.python.org','opentelemetry.io','w3.org',
                'anyio.readthedocs.io','starlette.io','fastapi.tiangolo.com','tracetest.io','kubeshop.github.io','openai.com')) or key in {'tracetest','tracetestconfig'}, (key, record['source_url'])
    doi_values = [ident for _, ident in identifiers if ident.startswith('doi:')]
    dup_doi = [ident for ident,c in Counter(doi_values).items() if c>1]
    assert not dup_doi, dup_doi
    title_norm = [re.sub(r'[^a-z0-9]+','',e['fields']['title'].lower()) for e in entries.values()]
    duplicate_titles = [t for t,c in Counter(title_norm).items() if c>1]
    # The affected/fixed source and native-test pairs deliberately share titles; record those exact exceptions.
    allowed = {
        re.sub(r'[^a-z0-9]+','',entries['asyncioaffected']['fields']['title'].lower()),
        re.sub(r'[^a-z0-9]+','',entries['nativetestsold']['fields']['title'].lower()),
    }
    assert set(duplicate_titles) <= allowed, duplicate_titles

    report = {
        'schema': 1,
        'status': 'pass',
        'verified_through': audit.get('verified_through', audit['verified_on']),
        'bibliography_entries': len(entries),
        'citation_occurrences': len(citations),
        'all_entries_cited': True,
        'all_citations_resolved': True,
        'category_counts': dict(sorted(category_counts.items())),
        'peer_reviewed_with_doi_or_official_venue': category_counts['peer-reviewed-research'],
        'preprints_explicitly_labelled': category_counts['research-preprint'],
        'bib_sha256': hashlib.sha256(bib_path.read_bytes()).hexdigest(),
        'audit_sha256': hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        'entry_record_hashes': {k: entries[k]['record_sha256'] for k in sorted(entries)},
        'limitations': audit['limitations'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='entry_record_hashes'},indent=2,sort_keys=True))

if __name__ == '__main__': main()
