"""Test statistics collection after a statement was first parsed without it."""
import importlib.util
from pathlib import Path
import sys
import types

folder=Path(__file__).resolve().parent
sys.argv=['capture.py','--dbms','oracle','--schema','non-indexed',
          '--out',str(folder/'oracle-cache-probe')]
spec=importlib.util.spec_from_file_location('b8',folder/'capture.py')
b8=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b8)
b8.connection.ensure_connection()
b8.install_trace()

def sql(connection,params):
    with connection.cursor() as c:
        c.execute('SELECT /* B8-cache-probe-20260919 */ COUNT(*) AS n FROM part WHERE p_partkey=%s',[1])
        return [dict(zip([x[0] for x in c.description],row)) for row in c.fetchall()]

module=types.SimpleNamespace(run_query_sql=sql)
results={}
try:
    with b8.connection.cursor() as c:c.execute('ALTER SESSION SET statistics_level=TYPICAL')
    b8.execute_function(module,'sql',{},'warmup')
    for label in ['cached-after-warmup','cache-disabled','new-session']:
        if label=='cache-disabled':b8.connection.connection.stmtcachesize=0
        if label=='new-session':
            b8.connection.close()
            b8.connection.ensure_connection()
            b8.connection.connection.stmtcachesize=0
        try:
            result=b8.capture_oracle(module,'sql',{},label)
            results[label]={'passed':True,'operators':result['actual_plan_operators']}
        except Exception as error:
            results[label]={'passed':False,'error':str(error)}
        print(label,results[label],flush=True)
    b8.write('comparison.json',results)
finally:
    b8.connection.close()
