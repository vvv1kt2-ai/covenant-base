import sys; sys.stdout.reconfigure(encoding='utf-8')
import json
with open('results.json', encoding='utf-8') as f:
    data = json.load(f)
for r in data:
    errors = r.get('parse_errors', [])
    covs = r.get('total_covenants', 0)
    if errors or (covs == 0 and not r.get('needs_program_check')):
        pass
    if errors:
        isin = r['isin']
        issuer = r.get('issuer', '')[:35]
        url = r.get('decision_url', '')[:80]
        print(f'{isin} | {issuer:35s} | cov={covs} | errors={errors}')
        print(f'  url={url}')