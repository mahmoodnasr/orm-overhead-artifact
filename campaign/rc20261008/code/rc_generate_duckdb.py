import duckdb, sys, time
out, sf = sys.argv[1], float(sys.argv[2])
t=time.time(); con=duckdb.connect(out); con.execute("INSTALL tpch; LOAD tpch;"); con.execute(f"CALL dbgen(sf={sf:g})")
print(out, con.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0], round(time.time()-t,1), duckdb.__version__)
print(con.execute("SELECT extension_name, extension_version FROM duckdb_extensions() WHERE extension_name='tpch'").fetchall())
