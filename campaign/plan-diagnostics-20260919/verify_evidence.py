"""Independently verify complete outputs and the retained plan records."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
cases = ['commercial-q17-django','commercial-q18-django','oracle-q17-django','oracle-q20-django']
expected_counts = {'region':5,'nation':25,'supplier':10000,'customer':150000,
                   'part':200000,'partsupp':800000,'orders':1500000,'lineitem':6001215}
ns = {'p':'http://schemas.microsoft.com/sqlserver/2004/07/showplan'}
expected_sources = json.loads((root.parent/'paper-source-hashes.json').read_text())
expected_parameters = {
    17:{'brand':'Brand#23','container':'MED BOX'},
    18:{'quantity':300},
    # params_of() expands Q20's documented 12-month qualification window.
    20:{'color':'forest','date':{'type':'date','value':'1994-01-01'},
        'nation':'CANADA','date_end':{'type':'date','value':'1995-01-01'}},
}

def read(path):
    return json.loads(path.read_text())

def value(v):
    if isinstance(v,dict) and 'type' in v and 'value' in v:
        if v['type'] in ['Decimal','float']:
            return Decimal(v['value'])
        if v['type']=='datetime':
            assert v['value'].endswith(' 00:00:00')
            return v['value'][:10]
        if v['type']=='date':
            return v['value']
        raise AssertionError(f'Unsupported result type {v["type"]}')
    return v

def rows(record):
    return [{k.lower():value(v) for k,v in r.items()} for r in record['rows']]

report = {}
for name in cases:
    folder = root/name
    if not (folder/'completion.json').exists():
        report[name] = {'complete':False,'reason':'completion record missing'}
        continue
    completion = read(folder/'completion.json')
    inventory = read(folder/'inventory.json')
    case = read(folder/'case.json')
    records = {stage+'-'+path:read(folder/(stage+'-'+path+'.json'))
               for stage in ['warmup','capture'] for path in ['sql','orm']}
    reference = rows(records['warmup-sql'])
    checks = {
        'source_hashes_match':not inventory['source_mismatches'] and inventory['source_hashes']==expected_sources,
        'collector_version_retained':hashlib.sha256((root.parent/'collector-versions'/(inventory['capture_sha256']+'.py')).read_bytes()).hexdigest()==inventory['capture_sha256'],
        'sf1_counts':inventory['row_counts']==expected_counts,
        'host_checks':inventory['host_verification']['returncode']==0 and read(folder/'host-after.json')['returncode']==0,
        'client_affinity':inventory['client_cpus']==[2,3],
        'index_check':read(folder/'index-verification.json')['returncode']==0,
        'qualification_input':case['param_set_id']==f'q{case["query"]:02d}s0',
        'qualification_values':case['parameters']==expected_parameters[case['query']],
        'historical_rows_linked':len(case['historical_rows'])>0 and all(r['scale_factor']=='1' and r['param_set_id']==case['param_set_id'] for r in case['historical_rows']),
        'exact_named_ordered_results':all(rows(r)==reference for r in records.values()),
        'nonempty_results':len(reference)>0,
        'completed_flags':all(completion[k] for k in ['plans_captured','warmup_exact_agreement','capture_exact_agreement','host_pass']),
    }
    for path in ['sql','orm']:
        warm, capture = records['warmup-'+path],records['capture-'+path]
        checks[path+'_driver_sql_bindings_preserved'] = warm['driver_statements']==capture['driver_statements']
        if name.startswith('commercial'):
            plans = list(folder.glob(f'capture-{path}-plan-*.sqlplan'))
            counters = [c for p in plans for c in ET.parse(p).findall('.//p:RunTimeCountersPerThread',ns)]
            checks[path+'_runtime_counters_present'] = len(counters)>0
        else:
            plan = read(folder/f'capture-{path}-plan.json')
            checks[path+'_plan_sql_matches_execution'] = plan['sql'].strip()==capture['driver_statements'][0]['sql'].strip()
            checks[path+'_runtime_counters_present'] = any(op['last_starts'] for op in plan['operators'])
            checks[path+'_text_plan_contains_statistics'] = 'A-Rows' in (folder/f'capture-{path}-plan.txt').read_text()
    if (folder/'warmup-provenance.json').exists():
        provenance=read(folder/'warmup-provenance.json')
        prior=root/Path(provenance['reused_from']).name
        checks['reused_warmup_inventory_verified']=hashlib.sha256((prior/'inventory.json').read_bytes()).hexdigest()==provenance['prior_inventory_sha256']
        checks['reused_warmup_files_unchanged']=all((prior/f'warmup-{p}.json').read_bytes()==(folder/f'warmup-{p}.json').read_bytes() for p in ['sql','orm'])
    report[name] = {'complete':all(checks.values()),'rows':len(reference),'checks':checks}
output = root/'independent-verification.json'
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if not all(r['complete'] for r in report.values()):
    raise SystemExit(1)
