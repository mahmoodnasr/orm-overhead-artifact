#!/bin/bash
#
# run_reproducibility.sh
# Execute ORM benchmark experiments for paper reproduction
#
# Usage: ./run_reproducibility.sh [MODE]
#   --quick-test: Quick validation (30 min, 2 queries, 1 DB)
#   --medium: Medium test (4 hours, 6 queries, 2 DBs)
#   --full: Full reproduction (7 days, all 432 configurations)
#
# Configurations:
#   Full: 4 DBMSs × 2 Schema × 2 ORMs × 22 Queries × 5 Reps = 432 configs
#   Medium: 2 DBMSs × 2 Schema × 2 ORMs × 6 Queries × 5 Reps = 120 configs
#   Quick: 1 DBMS × 1 Schema × 1 ORM × 2 Queries × 3 Reps = 6 configs
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
MODE="quick-test"
LOG_FILE="logs/benchmark_$(date +%Y%m%d_%H%M%S).log"
PROGRESS_FILE="logs/progress_$(date +%Y%m%d_%H%M%S).txt"
START_TIME=$(date +%s)

# Parse arguments
if [ $# -gt 0 ]; then
    MODE="$1"
fi

# Validate mode
case $MODE in
    --quick-test|quick-test|quick)
        MODE="quick-test"
        ;;
    --medium|medium)
        MODE="medium"
        ;;
    --full|full)
        MODE="full"
        ;;
    --help|-h)
        echo "Usage: ./run_reproducibility.sh [MODE]"
        echo ""
        echo "Modes:"
        echo "  --quick-test   Quick validation (30 min, 2 queries, PostgreSQL)"
        echo "  --medium       Medium test (4 hours, 6 queries, 2 databases)"
        echo "  --full         Full reproduction (7 days, all 432 configurations)"
        echo ""
        echo "Examples:"
        echo "  ./run_reproducibility.sh --quick-test"
        echo "  ./run_reproducibility.sh --full"
        echo ""
        echo "Output:"
        echo "  Results: results/raw/"
        echo "  Logs: logs/benchmark_*.log"
        echo "  Progress: logs/progress_*.txt"
        exit 0
        ;;
    *)
        echo -e "${RED}Error: Invalid mode '$MODE'${NC}"
        echo "Use --help for usage information"
        exit 1
        ;;
esac

# Create directories
mkdir -p logs results/raw

# Redirect output
exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  ORM Benchmark Reproduction Run       ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Mode: $MODE"
echo "Start: $(date)"
echo "Log: $LOG_FILE"
echo "Progress: $PROGRESS_FILE"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
else
    echo -e "${RED}✗ Virtual environment not found${NC}"
    echo "  Run ./setup_reproducibility.sh first"
    exit 1
fi

# Check databases are running
echo ""
echo -e "${BLUE}Checking database connections...${NC}"
if ! python scripts/utils/test_connections.py > /dev/null 2>&1; then
    echo -e "${RED}✗ Database connection failed${NC}"
    echo "  Make sure databases are running:"
    echo "  docker-compose up -d"
    exit 1
fi
echo -e "${GREEN}✓ Databases ready${NC}"

# Progress tracking
total_configs=0
completed_configs=0

update_progress() {
    completed_configs=$((completed_configs + 1))
    local percent=$((completed_configs * 100 / total_configs))
    local elapsed=$(($(date +%s) - START_TIME))
    local rate=$(echo "scale=2; $completed_configs / ($elapsed / 3600)" | bc)
    local remaining=$((total_configs - completed_configs))
    local eta=$(echo "scale=0; $remaining / $rate" | bc)
    
    echo "[$completed_configs/$total_configs] ($percent%) | Elapsed: ${elapsed}s | Rate: ${rate} cfg/hour | ETA: ${eta}h" > "$PROGRESS_FILE"
    
    if [ $((completed_configs % 10)) -eq 0 ]; then
        echo -e "${BLUE}Progress: $completed_configs/$total_configs ($percent%)${NC}"
    fi
}

# Run benchmarks based on mode
echo ""
echo -e "${BLUE}Starting benchmark execution...${NC}"
echo ""

case $MODE in
    quick-test)
        echo "Quick Test Mode:"
        echo "  - 1 DBMS (PostgreSQL)"
        echo "  - 1 Schema (indexed)"
        echo "  - 1 ORM (Django)"
        echo "  - 2 Queries (1, 6)"
        echo "  - 3 Repetitions"
        echo "  - Expected time: ~30 minutes"
        echo ""
        
        total_configs=6
        
        python scripts/2-benchmark/run_benchmark.py \
            --database default \
            --orms django \
            --schema-configs indexed \
            --queries 1,6 \
            --repetitions 3 \
            --output results/raw/ \
            --progress-callback update_progress
        
        ;;
    
    medium)
        echo "Medium Test Mode:"
        echo "  - 2 DBMSs (PostgreSQL, MySQL)"
        echo "  - 2 Schemas (indexed, non_indexed)"
        echo "  - 2 ORMs (Django, SQLAlchemy)"
        echo "  - 6 Queries (1, 6, 8, 9, 12, 14)"
        echo "  - 5 Repetitions"
        echo "  - Expected time: ~4 hours"
        echo ""
        
        total_configs=120
        
        DATABASES="default mysql"
        SCHEMAS="indexed non_indexed"
        ORMS="django sqlalchemy"
        QUERIES="1,6,8,9,12,14"
        
        for db in $DATABASES; do
            for schema in $SCHEMAS; do
                for orm in $ORMS; do
                    echo -e "${YELLOW}Running: $db / $schema / $orm${NC}"
                    
                    python scripts/2-benchmark/run_benchmark.py \
                        --database $db \
                        --orms $orm \
                        --schema-configs $schema \
                        --queries $QUERIES \
                        --repetitions 5 \
                        --output results/raw/ || echo "Warning: $db $schema $orm failed"
                    
                    update_progress
                done
            done
        done
        
        ;;
    
    full)
        echo "Full Reproduction Mode:"
        echo "  - 4 DBMSs (PostgreSQL, MySQL, Oracle, SQL Server)"
        echo "  - 2 Schemas (indexed, non_indexed)"
        echo "  - 2 ORMs (Django, SQLAlchemy)"
        echo "  - 22 Queries (all TPC-H queries)"
        echo "  - 5 Repetitions"
        echo "  - Expected time: ~7 days"
        echo ""
        echo -e "${YELLOW}⚠ Warning: This will take approximately 7 days to complete${NC}"
        read -p "Continue? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted"
            exit 0
        fi
        
        total_configs=1760  # 4 × 2 × 2 × 22 × 5
        
        DATABASES="default mysql oracle sqlserver"
        SCHEMAS="indexed non_indexed"
        ORMS="django sqlalchemy"
        
        for db in $DATABASES; do
            echo -e "${BLUE}===== Database: $db =====${NC}"
            
            for schema in $SCHEMAS; do
                echo -e "${BLUE}=== Schema: $schema ===${NC}"
                
                # Manage indexes
                if [ "$schema" = "indexed" ]; then
                    python scripts/1-setup/manage_indexes.py --action create --database $db
                else
                    python scripts/1-setup/manage_indexes.py --action drop --database $db
                fi
                
                for orm in $ORMS; do
                    echo -e "${YELLOW}Running: $db / $schema / $orm${NC}"
                    
                    python scripts/2-benchmark/run_benchmark.py \
                        --database $db \
                        --orms $orm \
                        --schema-configs $schema \
                        --all \
                        --repetitions 5 \
                        --output results/raw/ \
                        --log-level INFO || echo "Warning: $db $schema $orm failed"
                    
                    update_progress
                done
            done
        done
        
        # Run concurrency tests
        echo ""
        echo -e "${BLUE}Running concurrency tests...${NC}"
        
        for db in $DATABASES; do
            python scripts/2-benchmark/run_concurrency_benchmark.py \
                --database $db \
                --levels 1,10,25,50,100 \
                --queries 1,6,8 \
                --duration 60 || echo "Warning: Concurrency test for $db failed"
        done
        
        ;;
esac

# Completion
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
HOURS=$((ELAPSED / 3600))
MINUTES=$(((ELAPSED % 3600) / 60))

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Benchmark Execution Complete!        ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Mode: $MODE"
echo "Configurations: $total_configs"
echo "Duration: ${HOURS}h ${MINUTES}m"
echo "Results: results/raw/"
echo "Log: $LOG_FILE"
echo ""

# Generate summary
echo -e "${BLUE}Generating summary statistics...${NC}"
python scripts/4-analysis/generate_paper_aligned_results.py \
    --input results/raw/ \
    --output results/processed/

echo -e "${GREEN}✓ Summary generated: results/processed/summary_statistics.csv${NC}"

echo ""
echo "Next steps:"
echo ""
echo "  1. Validate results:"
echo "     ./validate_reproducibility.sh"
echo ""
echo "  2. Generate figures:"
echo "     python scripts/4-analysis/generate_figures.py --all"
echo ""
echo "  3. Compare to paper results:"
echo "     python scripts/4-analysis/validate_results.py --compare-to-paper"
echo ""

