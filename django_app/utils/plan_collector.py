"""
Query execution plan collector for mechanistic analysis.
Collects and parses query plans from all database systems.
"""

from django.db import connections
import json
import logging

logger = logging.getLogger(__name__)


class QueryPlanCollector:
    """Collect query execution plans from all databases for analysis."""

    def __init__(self):
        self.plans = {}

    def collect_plan(self, sql, database="default"):
        """
        Collect query execution plan for given SQL.

        Args:
            sql: SQL query string
            database: Database alias

        Returns:
            Dictionary containing plan data
        """
        conn = connections[database]

        try:
            if conn.vendor == "postgresql":
                return self.collect_plan_postgresql(sql, database)
            elif conn.vendor == "mysql":
                return self.collect_plan_mysql(sql, database)
            elif conn.vendor == "oracle":
                return self.collect_plan_oracle(sql, database)
            elif conn.vendor == "microsoft":
                return self.collect_plan_sqlserver(sql, database)
            else:
                logger.error(f"Unsupported database vendor: {conn.vendor}")
                return {"error": f"Unsupported vendor: {conn.vendor}"}
        except Exception as e:
            logger.error(f"Error collecting plan from {database}: {e}")
            return {"error": str(e)}

    def collect_plan_postgresql(self, sql, database="default"):
        """Collect PostgreSQL execution plan using EXPLAIN ANALYZE."""
        with connections[database].cursor() as cursor:
            explain_sql = f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"
            cursor.execute(explain_sql)
            result = cursor.fetchone()[0]

            # Parse JSON result
            plan_data = json.loads(result) if isinstance(result, str) else result

            return {
                "database": database,
                "vendor": "postgresql",
                "plan": plan_data,
                "raw_plan": json.dumps(plan_data, indent=2),
            }

    def collect_plan_mysql(self, sql, database="default"):
        """Collect MySQL execution plan using EXPLAIN ANALYZE FORMAT=JSON."""
        with connections[database].cursor() as cursor:
            # MySQL 8.0+ supports EXPLAIN ANALYZE
            explain_sql = f"EXPLAIN ANALYZE FORMAT=JSON {sql}"
            cursor.execute(explain_sql)
            result = cursor.fetchone()[0]

            # Parse JSON result
            plan_data = json.loads(result) if isinstance(result, str) else result

            return {
                "database": database,
                "vendor": "mysql",
                "plan": plan_data,
                "raw_plan": json.dumps(plan_data, indent=2),
            }

    def collect_plan_oracle(self, sql, database="default"):
        """Collect Oracle execution plan using DBMS_XPLAN."""
        with connections[database].cursor() as cursor:
            # First, execute the query with plan collection
            cursor.execute("ALTER SESSION SET STATISTICS_LEVEL = ALL")

            # Execute query
            cursor.execute(sql)
            _ = cursor.fetchall()  # Fetch results

            # Get SQL_ID
            cursor.execute(
                "SELECT prev_sql_id FROM v$session WHERE sid = SYS_CONTEXT('USERENV', 'SID')"
            )
            sql_id = cursor.fetchone()[0]

            # Get execution plan
            cursor.execute(
                f"SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR('{sql_id}', NULL, 'ALLSTATS LAST'))"
            )
            plan_lines = cursor.fetchall()

            plan_text = "\n".join([line[0] for line in plan_lines])

            return {
                "database": database,
                "vendor": "oracle",
                "sql_id": sql_id,
                "plan": plan_text,
                "raw_plan": plan_text,
            }

    def collect_plan_sqlserver(self, sql, database="default"):
        """Collect SQL Server execution plan using SET STATISTICS XML ON."""
        with connections[database].cursor() as cursor:
            # Enable XML plan output
            cursor.execute("SET STATISTICS XML ON")

            # Execute query
            cursor.execute(sql)
            results = cursor.fetchall()

            # Get plan (next result set contains the XML plan)
            cursor.nextset()
            plan_xml = None
            if cursor.description:
                plan_row = cursor.fetchone()
                if plan_row:
                    plan_xml = plan_row[0]

            # Disable XML output
            cursor.execute("SET STATISTICS XML OFF")

            return {
                "database": database,
                "vendor": "sqlserver",
                "plan": plan_xml,
                "raw_plan": plan_xml,
            }

    def parse_plan_metrics(self, plan_data):
        """
        Extract key metrics from execution plan.

        Metrics include:
        - Estimated vs actual rows (for q-error calculation)
        - Join algorithms used
        - Index usage
        - Cost estimates
        """
        vendor = plan_data.get("vendor")

        if vendor == "postgresql":
            return self._parse_postgresql_metrics(plan_data["plan"])
        elif vendor == "mysql":
            return self._parse_mysql_metrics(plan_data["plan"])
        elif vendor == "oracle":
            return self._parse_oracle_metrics(plan_data["plan"])
        elif vendor == "sqlserver":
            return self._parse_sqlserver_metrics(plan_data["plan"])

        return {}

    def calculate_q_error(self, estimated_rows: float, actual_rows: float) -> float:
        """
        Calculate q-error: max(estimated/actual, actual/estimated)

        Q-error measures the quality of cardinality estimation.
        A q-error of 1.0 means perfect estimation.
        Higher values indicate worse estimation.

        Args:
            estimated_rows: Estimated number of rows from query plan
            actual_rows: Actual number of rows returned

        Returns:
            Q-error value (>= 1.0)
        """
        if estimated_rows is None or actual_rows is None:
            return None

        if estimated_rows <= 0 or actual_rows <= 0:
            return None

        # Q-error = max(estimated/actual, actual/estimated)
        ratio1 = estimated_rows / actual_rows if actual_rows > 0 else float("inf")
        ratio2 = actual_rows / estimated_rows if estimated_rows > 0 else float("inf")

        q_error = max(ratio1, ratio2)
        return q_error

    def _parse_postgresql_metrics(self, plan):
        """Parse PostgreSQL plan metrics."""
        metrics = {
            "total_cost": None,
            "actual_time": None,
            "rows_estimated": None,
            "rows_actual": None,
            "join_types": [],
            "index_scans": [],
            "q_error": None,
        }

        def extract_from_node(node):
            if isinstance(node, dict):
                # PostgreSQL JSON plan structure
                if "Total Cost" in node:
                    metrics["total_cost"] = node["Total Cost"]
                elif "total_cost" in node:
                    metrics["total_cost"] = node["total_cost"]

                if "Actual Total Time" in node:
                    metrics["actual_time"] = node["Actual Total Time"]
                elif "actual_total_time" in node:
                    metrics["actual_time"] = node["actual_total_time"]

                if "Plan Rows" in node:
                    metrics["rows_estimated"] = node["Plan Rows"]
                elif "plan_rows" in node:
                    metrics["rows_estimated"] = node["plan_rows"]

                if "Actual Rows" in node:
                    metrics["rows_actual"] = node["Actual Rows"]
                elif "actual_rows" in node:
                    metrics["rows_actual"] = node["actual_rows"]

                if "Node Type" in node and "Join" in str(node["Node Type"]):
                    metrics["join_types"].append(node["Node Type"])
                elif "node_type" in node and "Join" in str(node["node_type"]):
                    metrics["join_types"].append(node["node_type"])

                if "Node Type" in node and "Index Scan" in str(node["Node Type"]):
                    metrics["index_scans"].append(node.get("Index Name", "unknown"))
                elif "node_type" in node and "Index Scan" in str(node["node_type"]):
                    metrics["index_scans"].append(node.get("index_name", "unknown"))

                # Recurse into plans
                if "Plans" in node:
                    for subplan in node["Plans"]:
                        extract_from_node(subplan)
                elif "plans" in node:
                    for subplan in node["plans"]:
                        extract_from_node(subplan)

        # Handle PostgreSQL JSON plan format
        if isinstance(plan, list) and len(plan) > 0:
            root_plan = plan[0]
            if isinstance(root_plan, dict):
                if "Plan" in root_plan:
                    extract_from_node(root_plan["Plan"])
                else:
                    extract_from_node(root_plan)

        # Calculate q-error if we have both estimated and actual rows
        if metrics["rows_estimated"] is not None and metrics["rows_actual"] is not None:
            metrics["q_error"] = self.calculate_q_error(
                metrics["rows_estimated"], metrics["rows_actual"]
            )

        return metrics

    def _parse_mysql_metrics(self, plan):
        """Parse MySQL plan metrics."""
        # MySQL EXPLAIN ANALYZE FORMAT=JSON structure
        return {"vendor": "mysql", "plan": "parsed"}

    def _parse_oracle_metrics(self, plan):
        """Parse Oracle plan metrics."""
        # Parse Oracle text plan
        return {"vendor": "oracle", "plan": "parsed"}

    def _parse_sqlserver_metrics(self, plan):
        """Parse SQL Server XML plan metrics."""
        # Parse SQL Server XML plan
        return {"vendor": "sqlserver", "plan": "parsed"}

    def save_plan(self, query_name, plan_data, output_dir="results/plans"):
        """Save plan data to file."""
        import os
        import datetime

        database = plan_data.get("database", "unknown")
        os.makedirs(f"{output_dir}/{database}", exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/{database}/{query_name}_{timestamp}.json"

        with open(filename, "w") as f:
            json.dump(plan_data, f, indent=2, default=str)

        logger.info(f"Saved plan to {filename}")
        return filename
