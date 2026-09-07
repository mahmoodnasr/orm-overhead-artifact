#!/bin/bash
# Cleanup script - removes generated data and results

set -e

echo "==============================================="
echo "Cleanup Script"
echo "==============================================="

read -p "This will delete all generated data and results. Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

echo ""
echo "Removing generated data..."
if [ -d "data/tpch-raw" ]; then
    rm -rf data/tpch-raw/*.tbl
    rm -f data/tpch-raw/checksums.txt
    echo "  ✓ Removed TPC-H data files"
fi

echo ""
echo "Removing results..."
if [ -d "results" ]; then
    rm -rf results/raw/*
    rm -rf results/plans/*
    rm -rf results/figures/*
    rm -rf results/concurrency/*
    echo "  ✓ Removed result files"
fi

echo ""
echo "Removing TPC-H dbgen..."
if [ -d "tpch-dbgen" ]; then
    rm -rf tpch-dbgen
    echo "  ✓ Removed dbgen directory"
fi

echo ""
echo "Stopping Docker containers..."
docker-compose down -v
echo "  ✓ Containers stopped"

echo ""
echo "==============================================="
echo "✓ Cleanup complete!"
echo "==============================================="

