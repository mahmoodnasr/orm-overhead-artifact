"""Extract inspectable operator summaries without interpreting causation."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
ns = {'p':'http://schemas.microsoft.com/sqlserver/2004/07/showplan'}
summaries = {}
for path in sorted(root.rglob('*.sqlplan')):
    tree = ET.parse(path)
    statements = []
    for statement in tree.findall('.//p:StmtSimple', ns):
        result = {'statement':statement.attrib,'operators':[]}
        queryplan = statement.find('p:QueryPlan', ns)
        if queryplan is None:
            continue
        result['query_plan'] = queryplan.attrib
        result['query_time'] = [x.attrib for x in queryplan.findall('p:QueryTimeStats',ns)]
        result['memory_grant'] = [x.attrib for x in queryplan.findall('p:MemoryGrantInfo',ns)]
        result['waits'] = [x.attrib for x in queryplan.findall('p:WaitStats/p:Wait',ns)]
        result['warnings'] = [ET.tostring(x,encoding='unicode') for x in queryplan.findall('.//p:Warnings',ns)]
        result['parameters'] = [x.attrib for x in queryplan.findall('.//p:ParameterList/p:ColumnReference',ns)]
        for op in queryplan.findall('.//p:RelOp',ns):
            record = dict(op.attrib)
            record['runtime'] = [x.attrib for x in op.findall('p:RunTimeInformation/p:RunTimeCountersPerThread',ns)]
            record['objects'] = []
            for physical in op:
                record['objects'] += [x.attrib for x in physical.findall('p:Object',ns)]
            record['predicates'] = [x.attrib.get('ScalarString') for child in op for x in child.findall('p:Predicate/p:ScalarOperator',ns)]
            result['operators'].append(record)
        statements.append(result)
    summaries[str(path.relative_to(root))] = statements
for path in sorted(root.rglob('*-plan.json')):
    summaries[str(path.relative_to(root))] = json.loads(path.read_text())
(root/'operator-summaries.json').write_text(json.dumps(summaries,indent=2)+'\n')
for name, data in summaries.items():
    print(name)
    if isinstance(data,list):
        for stmt in data:
            print('  query_time',stmt['query_time'],'operators',len(stmt['operators']))
            for op in stmt['operators']:
                executions = sum(float(r.get('ActualExecutions',0)) for r in op['runtime'])
                reads = sum(float(r.get('ActualLogicalReads',0)) for r in op['runtime'])
                rows = sum(float(r.get('ActualRows',0)) for r in op['runtime'])
                print(' ',op['NodeId'],op['PhysicalOp'],'est',op.get('EstimateRows'),'actual',rows,'exec',executions,'reads',reads,op['objects'])
    else:
        for op in data['operators']:
            print(' ',op['id'],op['operation'],op['options'],op['object_name'],'starts',op['last_starts'],'rows',op['last_output_rows'],'reads',op['last_cr_buffer_gets'])
