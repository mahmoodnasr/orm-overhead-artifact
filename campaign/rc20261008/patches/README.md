# Proposed source corrections (campaign rc20261008)

Drafted from the static code study before any runtime evidence. They are
applied to the campaign branch `revision-campaign-20261008` only after the
transaction pilot records the asymmetry they correct, with old and new file
hashes recorded in `applied.json`. Historical measurements were taken with the
uncorrected code and are not altered.

| Patch | Defect | Evidence required before applying |
|---|---|---|
| C1-djsql-payment-hdata | Django SQL Payment writes a different `history.h_data` than the other three paths | pilot block where the Django pair's committed differences disagree only in `h_data` |
| C2-sasql-orderstatus-orderlines | SQLAlchemy SQL Order-Status never reads ORDER_LINE | pilot `tables_touched` for sqlalchemy/sql T3 lacking `order_line` while sqlalchemy/orm has it |
