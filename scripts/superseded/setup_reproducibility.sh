#!/bin/bash
#
# setup_reproducibility.sh
# One-command setup for ORM benchmark reproducibility package
#
# Usage: ./setup_reproducibility.sh [--quick]
#   --quick: Quick setup (skip optional components)
#
# This script:
# 1. Checks system requirements
# 2. Sets up Docker containers
# 3. Generates TPC-H data
# 4. Loads data into databases
# 5. Verifies setup is complete
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCALE_FACTOR=1
QUICK_MODE=false
LOG_FILE="logs/setup_$(date +%Y%m%d_%H%M%S).log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --scale-factor)
            SCALE_FACTOR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: ./setup_reproducibility.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick           Quick setup (PostgreSQL only, SF=1)"
            echo "  --scale-factor N  TPC-H scale factor (default: 1)"
            echo "  --help            Show this help"
            echo ""
            echo "Examples:"
            echo "  ./setup_reproducibility.sh                 # Full setup"
            echo "  ./setup_reproducibility.sh --quick         # Quick setup"
            echo "  ./setup_reproducibility.sh --scale-factor 10  # 10GB dataset"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Create logs directory
mkdir -p logs

# Redirect output to log file
exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  ORM Benchmark Reproducibility Setup  ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Date: $(date)"
echo "Mode: $([ "$QUICK_MODE" = true ] && echo "Quick" || echo "Full")"
echo "Scale Factor: $SCALE_FACTOR"
echo "Log: $LOG_FILE"
echo ""

# Step 1: Check System Requirements
echo -e "${BLUE}Step 1/7: Checking system requirements...${NC}"

check_command() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}✗ $1 not found${NC}"
        echo "  Please install $1 and try again"
        exit 1
    else
        echo -e "${GREEN}✓ $1 found${NC}"
    fi
}

check_command docker
check_command docker-compose
check_command python3
check_command git

# Check Docker is running
if ! docker ps &> /dev/null; then
    echo -e "${RED}✗ Docker is not running${NC}"
    echo "  Please start Docker and try again"
    exit 1
else
    echo -e "${GREEN}✓ Docker is running${NC}"
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.8"
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}✗ Python version must be >= 3.8 (found $PYTHON_VERSION)${NC}"
    exit 1
else
    echo -e "${GREEN}✓ Python $PYTHON_VERSION (>= 3.8)${NC}"
fi

# Check disk space (need at least 50GB for full setup, 10GB for quick)
REQUIRED_SPACE=$([ "$QUICK_MODE" = true ] && echo "10" || echo "50")
AVAILABLE_SPACE=$(df -BG . | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_SPACE" -lt "$REQUIRED_SPACE" ]; then
    echo -e "${YELLOW}⚠ Warning: Low disk space (${AVAILABLE_SPACE}GB available, ${REQUIRED_SPACE}GB recommended)${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓ Sufficient disk space (${AVAILABLE_SPACE}GB available)${NC}"
fi

# Check memory (need at least 8GB for quick, 16GB for full)
REQUIRED_MEM=$([ "$QUICK_MODE" = true ] && echo "8" || echo "16")
TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
if [ "$TOTAL_MEM" -lt "$REQUIRED_MEM" ]; then
    echo -e "${YELLOW}⚠ Warning: Low memory (${TOTAL_MEM}GB available, ${REQUIRED_MEM}GB recommended)${NC}"
else
    echo -e "${GREEN}✓ Sufficient memory (${TOTAL_MEM}GB)${NC}"
fi

echo ""

# Step 2: Setup Python Virtual Environment
echo -e "${BLUE}Step 2/7: Setting up Python virtual environment...${NC}"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}✓ Virtual environment exists${NC}"
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✓ Dependencies installed${NC}"

echo ""

# Step 3: Start Docker Containers
echo -e "${BLUE}Step 3/7: Starting Docker containers...${NC}"

if [ "$QUICK_MODE" = true ]; then
    echo "Starting PostgreSQL only (quick mode)..."
    docker-compose up -d postgres
else
    echo "Starting all database containers..."
    docker-compose up -d
fi

echo -e "${GREEN}✓ Containers started${NC}"
echo ""

# Step 4: Wait for Databases
echo -e "${BLUE}Step 4/7: Waiting for databases to be ready...${NC}"
echo "This may take 2-5 minutes..."

./scripts/1-setup/wait_for_databases.sh

echo -e "${GREEN}✓ Databases ready${NC}"
echo ""

# Step 5: Generate TPC-H Data
echo -e "${BLUE}Step 5/7: Generating TPC-H data (SF=${SCALE_FACTOR})...${NC}"

if [ ! -f "data/tpch-raw/lineitem.tbl" ] || [ "$SCALE_FACTOR" != "1" ]; then
    echo "Generating data (this may take 1-10 minutes depending on scale factor)..."
    ./scripts/1-setup/generate_tpch_data.sh $SCALE_FACTOR
    echo -e "${GREEN}✓ Data generated${NC}"
else
    echo -e "${GREEN}✓ Data already exists${NC}"
fi

echo ""

# Step 6: Load Data into Databases
echo -e "${BLUE}Step 6/7: Loading data into databases...${NC}"

if [ "$QUICK_MODE" = true ]; then
    echo "Loading data into PostgreSQL only..."
    ./scripts/1-setup/load_data_postgres.sh
else
    echo "Loading data into all databases (this may take 10-30 minutes)..."
    ./scripts/1-setup/load_data_all.sh
fi

echo -e "${GREEN}✓ Data loaded${NC}"
echo ""

# Step 7: Verify Setup
echo -e "${BLUE}Step 7/7: Verifying setup...${NC}"

echo "Testing database connections..."
python scripts/utils/test_connections.py

echo ""
echo "Verifying data integrity..."
python scripts/4-analysis/validate_results.py --check-counts --scale-factor $SCALE_FACTOR

echo ""
echo -e "${GREEN}✓ Setup verification complete${NC}"

# Summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo ""
if [ "$QUICK_MODE" = true ]; then
    echo "  1. Run quick test (30 minutes):"
    echo "     ./run_reproducibility.sh --quick-test"
    echo ""
    echo "  2. Or run full reproduction (~7 days):"
    echo "     ./run_reproducibility.sh --full"
else
    echo "  1. Run full reproduction (~7 days):"
    echo "     ./run_reproducibility.sh --full"
    echo ""
    echo "  2. Or run quick test first (30 minutes):"
    echo "     ./run_reproducibility.sh --quick-test"
fi
echo ""
echo "  3. Monitor progress:"
echo "     tail -f logs/benchmark_*.log"
echo ""
echo "  4. Validate results:"
echo "     ./validate_reproducibility.sh"
echo ""
echo "Log saved to: $LOG_FILE"
echo ""
echo -e "${YELLOW}Note: Keep the virtual environment activated:${NC}"
echo "      source venv/bin/activate"
echo ""

