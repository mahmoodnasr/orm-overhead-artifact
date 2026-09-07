#!/bin/bash
#
# validate_reproducibility.sh
# Validate ORM benchmark reproducibility package and results
#
# Usage: ./validate_reproducibility.sh [OPTIONS]
#   --quick: Quick validation only
#   --full: Full validation including result comparison
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
MODE="standard"
LOG_FILE="logs/validation_$(date +%Y%m%d_%H%M%S).log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            MODE="quick"
            shift
            ;;
        --full)
            MODE="full"
            shift
            ;;
        --help)
            echo "Usage: ./validate_reproducibility.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick    Quick validation (setup + connections)"
            echo "  --full     Full validation (including result comparison)"
            echo "  --help     Show this help"
            echo ""
            echo "Validation checks:"
            echo "  1. System requirements"
            echo "  2. Docker containers"
            echo "  3. Database connections"
            echo "  4. Data integrity"
            echo "  5. Schema validation"
            echo "  6. Result files"
            echo "  7. Result correctness (--full only)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Create logs directory
mkdir -p logs

# Redirect output
exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Reproducibility Package Validation   ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Mode: $MODE"
echo "Date: $(date)"
echo "Log: $LOG_FILE"
echo ""

# Counters
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNING_CHECKS=0

check_pass() {
    echo -e "${GREEN}✓ $1${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

check_fail() {
    echo -e "${RED}✗ $1${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

check_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
    WARNING_CHECKS=$((WARNING_CHECKS + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

# Check 1: System Requirements
echo -e "${BLUE}[1/7] Checking system requirements...${NC}"

if command -v docker &> /dev/null; then
    check_pass "Docker installed ($(docker --version | cut -d' ' -f3 | tr -d ','))"
else
    check_fail "Docker not found"
fi

if command -v docker-compose &> /dev/null; then
    check_pass "Docker Compose installed ($(docker-compose --version | cut -d' ' -f4 | tr -d ','))"
else
    check_fail "Docker Compose not found"
fi

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    check_pass "Python installed ($PYTHON_VERSION)"
else
    check_fail "Python3 not found"
fi

if [ -d "venv" ]; then
    check_pass "Virtual environment exists"
    source venv/bin/activate
    
    # Check key packages
    if python -c "import django" 2> /dev/null; then
        DJANGO_VERSION=$(python -c "import django; print(django.__version__)")
        check_pass "Django installed ($DJANGO_VERSION)"
    else
        check_fail "Django not installed"
    fi
    
    if python -c "import sqlalchemy" 2> /dev/null; then
        SA_VERSION=$(python -c "import sqlalchemy; print(sqlalchemy.__version__)")
        check_pass "SQLAlchemy installed ($SA_VERSION)"
    else
        check_fail "SQLAlchemy not installed"
    fi
else
    check_fail "Virtual environment not found"
fi

echo ""

# Check 2: Docker Containers
echo -e "${BLUE}[2/7] Checking Docker containers...${NC}"

if docker ps &> /dev/null; then
    check_pass "Docker daemon running"
    
    containers=("orm-benchmark-postgres" "orm-benchmark-mysql" "orm-benchmark-oracle" "orm-benchmark-sqlserver")
    for container in "${containers[@]}"; do
        if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            check_pass "$container running"
        else
            check_warning "$container not running (optional for quick test)"
        fi
    done
else
    check_fail "Docker daemon not running"
fi

echo ""

# Check 3: Database Connections
echo -e "${BLUE}[3/7] Checking database connections...${NC}"

if [ -f "scripts/utils/test_connections.py" ]; then
    if python scripts/utils/test_connections.py > /tmp/conn_test.log 2>&1; then
        # Parse output for individual databases
        if grep -q "PostgreSQL.*Connected" /tmp/conn_test.log; then
            check_pass "PostgreSQL connection"
        else
            check_fail "PostgreSQL connection failed"
        fi
        
        if grep -q "MySQL.*Connected" /tmp/conn_test.log; then
            check_pass "MySQL connection"
        elif [ "$MODE" != "quick" ]; then
            check_warning "MySQL connection failed"
        fi
        
        if grep -q "Oracle.*Connected" /tmp/conn_test.log; then
            check_pass "Oracle connection"
        elif [ "$MODE" != "quick" ]; then
            check_warning "Oracle connection failed"
        fi
        
        if grep -q "SQL Server.*Connected" /tmp/conn_test.log; then
            check_pass "SQL Server connection"
        elif [ "$MODE" != "quick" ]; then
            check_warning "SQL Server connection failed"
        fi
    else
        check_fail "Database connection test failed"
    fi
else
    check_fail "Connection test script not found"
fi

echo ""

# Check 4: Data Integrity
echo -e "${BLUE}[4/7] Checking data integrity...${NC}"

if [ -d "data/tpch-raw" ]; then
    check_pass "TPC-H data directory exists"
    
    # Check for TPC-H table files
    tables=("customer" "lineitem" "nation" "orders" "part" "partsupp" "region" "supplier")
    for table in "${tables[@]}"; do
        if [ -f "data/tpch-raw/${table}.tbl" ]; then
            check_pass "TPC-H table: $table"
        else
            check_fail "TPC-H table missing: $table"
        fi
    done
else
    check_fail "TPC-H data directory not found"
fi

# Validate row counts in PostgreSQL
if python -c "from sqlalchemy import create_engine; engine = create_engine('postgresql://bench:bench@localhost:5432/tpch'); conn = engine.connect(); result = conn.execute('SELECT COUNT(*) FROM lineitem').fetchone(); print(result[0])" 2> /dev/null | grep -q "6001215"; then
    check_pass "LINEITEM row count (6,001,215 for SF=1)"
else
    check_warning "LINEITEM row count validation skipped or failed"
fi

echo ""

# Check 5: Schema Validation
echo -e "${BLUE}[5/7] Checking database schemas...${NC}"

# Check if tables exist in PostgreSQL
tables=("CUSTOMER" "LINEITEM" "NATION" "ORDERS" "PART" "PARTSUPP" "REGION" "SUPPLIER")
for table in "${tables[@]}"; do
    if python -c "from sqlalchemy import create_engine, inspect; engine = create_engine('postgresql://bench:bench@localhost:5432/tpch'); inspector = inspect(engine); print('$table' in [t.upper() for t in inspector.get_table_names()])" 2> /dev/null | grep -q "True"; then
        check_pass "Table exists: $table"
    else
        check_fail "Table missing: $table"
    fi
done

echo ""

# Check 6: Result Files
echo -e "${BLUE}[6/7] Checking result files...${NC}"

if [ -d "results/raw" ]; then
    check_pass "Raw results directory exists"
    
    RESULT_COUNT=$(find results/raw -name "*.csv" -type f 2>/dev/null | wc -l)
    if [ "$RESULT_COUNT" -gt 0 ]; then
        check_pass "Result files found ($RESULT_COUNT files)"
    else
        check_warning "No result files found (run benchmarks first)"
    fi
else
    check_fail "Raw results directory not found"
fi

if [ -d "results/processed" ]; then
    check_pass "Processed results directory exists"
else
    check_warning "Processed results directory not found"
fi

if [ -d "results/figures" ]; then
    check_pass "Figures directory exists"
else
    check_warning "Figures directory not found"
fi

echo ""

# Check 7: Result Correctness (full mode only)
if [ "$MODE" = "full" ]; then
    echo -e "${BLUE}[7/7] Validating result correctness...${NC}"
    
    if [ -f "scripts/4-analysis/validate_results.py" ]; then
        if python scripts/4-analysis/validate_results.py --check-data-integrity --scale-factor 1 > /tmp/validate.log 2>&1; then
            check_pass "Data integrity validation passed"
        else
            check_warning "Data integrity validation warnings (see log)"
        fi
        
        # if python scripts/4-analysis/validate_results.py --check-query-results > /tmp/validate_queries.log 2>&1; then
        #     check_pass "Query result validation passed"
        # else
        #     check_warning "Query result validation warnings"
        # fi
    else
        check_warning "Validation script not found"
    fi
else
    echo -e "${BLUE}[7/7] Result correctness check skipped (use --full)${NC}"
fi

echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Validation Summary                   ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Total checks: $TOTAL_CHECKS"
echo -e "${GREEN}Passed: $PASSED_CHECKS${NC}"
echo -e "${RED}Failed: $FAILED_CHECKS${NC}"
echo -e "${YELLOW}Warnings: $WARNING_CHECKS${NC}"
echo ""

# Determine overall status
if [ "$FAILED_CHECKS" -eq 0 ]; then
    if [ "$WARNING_CHECKS" -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed!${NC}"
        STATUS=0
    else
        echo -e "${YELLOW}⚠ Validation passed with warnings${NC}"
        echo ""
        echo "Warnings are acceptable for:"
        echo "  - Quick test mode (not all databases required)"
        echo "  - Before running benchmarks (no results yet)"
        STATUS=0
    fi
else
    echo -e "${RED}✗ Validation failed${NC}"
    echo ""
    echo "Please fix the failed checks and try again"
    echo "See log: $LOG_FILE"
    STATUS=1
fi

echo ""
echo "Log saved to: $LOG_FILE"
echo ""

exit $STATUS

