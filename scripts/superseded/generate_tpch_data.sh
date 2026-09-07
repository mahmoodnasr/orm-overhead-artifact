#!/bin/bash
# TPC-H Data Generation Script
# Downloads TPC-H dbgen tool and generates data at specified scale factor

set -e

SCALE_FACTOR=${1:-1}
OUTPUT_DIR=${2:-"data/tpch-raw"}

echo "==============================================="
echo "TPC-H Data Generation"
echo "Scale Factor: $SCALE_FACTOR (${SCALE_FACTOR}GB)"
echo "Output Directory: $OUTPUT_DIR"
echo "==============================================="

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check if dbgen exists
if [ ! -f "tpch-dbgen/dbgen" ]; then
    echo "Downloading and building TPC-H dbgen..."
    
    # Clone TPC-H dbgen repository
    if [ ! -d "tpch-dbgen" ]; then
        git clone https://github.com/electrum/tpch-dbgen.git
    fi
    
    cd tpch-dbgen
    
    # Build dbgen
    make clean || true
    make
    
    cd ..
    
    echo "✓ dbgen built successfully"
fi

# Generate data
echo ""
echo "Generating TPC-H data (this may take a while)..."
cd tpch-dbgen

./dbgen -s $SCALE_FACTOR -v

echo ""
echo "✓ Data generation complete"

# Move .tbl files to output directory
echo ""
echo "Moving .tbl files to $OUTPUT_DIR..."
mv *.tbl "../$OUTPUT_DIR/"

cd ..

# Generate checksums
echo ""
echo "Generating checksums..."
cd "$OUTPUT_DIR"
sha256sum *.tbl > checksums.txt

echo ""
echo "File sizes:"
ls -lh *.tbl

echo ""
echo "==============================================="
echo "✓ TPC-H data generation complete!"
echo "Files located in: $OUTPUT_DIR"
echo "==============================================="

echo ""
echo "Next steps:"
echo "  1. Load data into PostgreSQL: ./scripts/load_data_postgres.sh"
echo "  2. Load data into MySQL: ./scripts/load_data_mysql.sh"
echo "  3. Load data into Oracle: ./scripts/load_data_oracle.sh"
echo "  4. Load data into SQL Server: ./scripts/load_data_sqlserver.sh"
