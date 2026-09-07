#!/usr/bin/env python3
"""
TPC-C Data Generator

Generates minimal TPC-C data for benchmarking.
This is a simplified generator for testing purposes.
For full TPC-C compliance, use the official TPC-C benchmark kit.
"""
import os
import sys
import random
import string
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# TPC-C parameters
NUM_WAREHOUSES = 10
DISTRICTS_PER_WAREHOUSE = 10
CUSTOMERS_PER_DISTRICT = 3000
ITEMS = 100000
ORDERS_PER_DISTRICT = 3000


def random_string(length, prefix=""):
    """Generate random string."""
    chars = string.ascii_letters + string.digits
    return prefix + ''.join(random.choice(chars) for _ in range(length - len(prefix)))


def random_phone():
    """Generate random phone number."""
    return f"{random.randint(100, 999)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"


def generate_warehouse(w_id):
    """Generate warehouse data."""
    return f"{w_id}|{random_string(10)}|{random_string(20)}|{random_string(20)}|{random_string(20)}|{random_string(2)}|{random_string(9)}|{random.uniform(0.0, 0.2):.4f}|{random.uniform(300000.0, 500000.0):.2f}\n"


def generate_district(w_id, d_id):
    """Generate district data."""
    return f"{d_id}|{w_id}|{random_string(10)}|{random_string(20)}|{random_string(20)}|{random_string(20)}|{random_string(2)}|{random_string(9)}|{random.uniform(0.0, 0.2):.4f}|{random.uniform(30000.0, 50000.0):.2f}|{random.randint(3001, 10000)}\n"


def generate_customer(w_id, d_id, c_id):
    """Generate customer data."""
    first = random_string(8, "C")
    middle = random_string(2)
    last = random_string(16, "CUSTOMER")
    credit = random.choice(['GC', 'BC'])
    since = datetime.now() - timedelta(days=random.randint(1, 3650))
    
    return f"{c_id}|{d_id}|{w_id}|{first}|{middle}|{last}|{random_string(20)}|{random_string(20)}|{random_string(20)}|{random_string(2)}|{random_string(9)}|{random_phone()}|{since.strftime('%Y-%m-%d %H:%M:%S')}|{credit}|{random.uniform(50000.0, 100000.0):.2f}|{random.uniform(0.0, 0.5):.4f}|{random.uniform(-5000.0, 5000.0):.2f}|{random.uniform(0.0, 50000.0):.2f}|{random.randint(0, 50)}|{random.randint(0, 50)}|{random_string(500)}\n"


def generate_item(i_id):
    """Generate item data."""
    return f"{i_id}|{random.randint(1, 10000)}|{random_string(24)}|{random.uniform(1.0, 100.0):.2f}|{random_string(50)}\n"


def generate_stock(w_id, i_id):
    """Generate stock data."""
    dist_fields = '|'.join([random_string(24) for _ in range(10)])
    return f"{i_id}|{w_id}|{random.randint(10, 100)}|{dist_fields}|{random.randint(0, 100000)}|{random.randint(0, 10000)}|{random.randint(0, 1000)}|{random_string(50)}\n"


def generate_order(w_id, d_id, o_id, c_id, entry_date):
    """Generate order data."""
    carrier_id = random.randint(1, 10) if random.random() > 0.1 else None
    ol_cnt = random.randint(5, 15)
    carrier_id_str = str(carrier_id) if carrier_id is not None else ""
    return f"{o_id}|{d_id}|{w_id}|{c_id}|{entry_date.strftime('%Y-%m-%d %H:%M:%S')}|{carrier_id_str}|{ol_cnt}|{random.randint(0, 1)}\n"


def generate_order_line(w_id, d_id, o_id, ol_number, i_id):
    """Generate order line data."""
    delivery_d = datetime.now() - timedelta(days=random.randint(0, 30)) if random.random() > 0.1 else None
    quantity = random.randint(1, 10)
    amount = random.uniform(1.0, 1000.0)
    
    delivery_str = delivery_d.strftime('%Y-%m-%d %H:%M:%S') if delivery_d else ""
    return f"{o_id}|{d_id}|{w_id}|{ol_number}|{i_id}|{w_id}|{delivery_str}|{quantity}|{amount:.2f}|{random_string(24)}\n"


def generate_new_order(w_id, d_id, o_id):
    """Generate new order entry."""
    return f"{o_id}|{d_id}|{w_id}\n"


def generate_history(w_id, d_id, c_id):
    """Generate history entry."""
    h_date = datetime.now() - timedelta(days=random.randint(0, 365))
    amount = random.uniform(1.0, 5000.0)
    return f"{c_id}|{d_id}|{w_id}|{d_id}|{w_id}|{h_date.strftime('%Y-%m-%d %H:%M:%S')}|{amount:.2f}|{random_string(24)}\n"


def main():
    """Main data generation function."""
    output_dir = Path(project_root) / 'data' / 'tpcc-raw'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("TPC-C Data Generator")
    print("=" * 70)
    print(f"Output directory: {output_dir}")
    print(f"Warehouses: {NUM_WAREHOUSES}")
    print(f"Districts per warehouse: {DISTRICTS_PER_WAREHOUSE}")
    print(f"Customers per district: {CUSTOMERS_PER_DISTRICT}")
    print(f"Items: {ITEMS}")
    print("=" * 70)
    print()
    
    # Generate warehouses
    print("Generating warehouses...")
    with open(output_dir / 'warehouse.tbl', 'w') as f:
        for w_id in range(1, NUM_WAREHOUSES + 1):
            f.write(generate_warehouse(w_id))
    print(f"  ✓ Generated {NUM_WAREHOUSES} warehouses")
    
    # Generate districts
    print("Generating districts...")
    with open(output_dir / 'district.tbl', 'w') as f:
        for w_id in range(1, NUM_WAREHOUSES + 1):
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                f.write(generate_district(w_id, d_id))
    print(f"  ✓ Generated {NUM_WAREHOUSES * DISTRICTS_PER_WAREHOUSE} districts")
    
    # Generate items
    print("Generating items...")
    with open(output_dir / 'item.tbl', 'w') as f:
        for i_id in range(1, ITEMS + 1):
            f.write(generate_item(i_id))
    print(f"  ✓ Generated {ITEMS} items")
    
    # Generate stock
    print("Generating stock...")
    with open(output_dir / 'stock.tbl', 'w') as f:
        for w_id in range(1, NUM_WAREHOUSES + 1):
            for i_id in range(1, ITEMS + 1):
                f.write(generate_stock(w_id, i_id))
    print(f"  ✓ Generated {NUM_WAREHOUSES * ITEMS} stock entries")
    
    # Generate customers
    print("Generating customers...")
    with open(output_dir / 'customer.tbl', 'w') as f:
        for w_id in range(1, NUM_WAREHOUSES + 1):
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                for c_id in range(1, CUSTOMERS_PER_DISTRICT + 1):
                    f.write(generate_customer(w_id, d_id, c_id))
    print(f"  ✓ Generated {NUM_WAREHOUSES * DISTRICTS_PER_WAREHOUSE * CUSTOMERS_PER_DISTRICT} customers")
    
    # Generate orders and order lines
    print("Generating orders and order lines...")
    order_count = 0
    order_line_count = 0
    
    with open(output_dir / 'order.tbl', 'w') as order_file, \
         open(output_dir / 'order_line.tbl', 'w') as order_line_file, \
         open(output_dir / 'new_order.tbl', 'w') as new_order_file:
        
        for w_id in range(1, NUM_WAREHOUSES + 1):
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                for o_id in range(1, ORDERS_PER_DISTRICT + 1):
                    c_id = random.randint(1, CUSTOMERS_PER_DISTRICT)
                    entry_date = datetime.now() - timedelta(days=random.randint(0, 365))
                    
                    order_file.write(generate_order(w_id, d_id, o_id, c_id, entry_date))
                    order_count += 1
                    
                    # Generate order lines
                    ol_cnt = random.randint(5, 15)
                    for ol_number in range(1, ol_cnt + 1):
                        i_id = random.randint(1, ITEMS)
                        order_line_file.write(generate_order_line(w_id, d_id, o_id, ol_number, i_id))
                        order_line_count += 1
                    
                    # Some orders are new orders
                    if random.random() > 0.7:
                        new_order_file.write(generate_new_order(w_id, d_id, o_id))
    
    print(f"  ✓ Generated {order_count} orders")
    print(f"  ✓ Generated {order_line_count} order lines")
    
    # Generate history
    print("Generating history...")
    history_count = 0
    with open(output_dir / 'history.tbl', 'w') as f:
        for w_id in range(1, NUM_WAREHOUSES + 1):
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                for _ in range(1000):  # 1000 history entries per district
                    c_id = random.randint(1, CUSTOMERS_PER_DISTRICT)
                    f.write(generate_history(w_id, d_id, c_id))
                    history_count += 1
    print(f"  ✓ Generated {history_count} history entries")
    
    # Clean files (remove trailing pipes)
    print("\nCleaning data files...")
    for file in output_dir.glob('*.tbl'):
        with open(file, 'r') as f_in, open(f"{file}.clean", 'w') as f_out:
            for line in f_in:
                f_out.write(line.rstrip().rstrip('|') + '\n')
        print(f"  ✓ Cleaned {file.name}")
    
    print("\n" + "=" * 70)
    print("Data generation complete!")
    print("=" * 70)
    print(f"\nData files are in: {output_dir}")
    print("\nNext steps:")
    print("  1. Run database setup scripts to create TPC-C schema")
    print("  2. Load data into databases")
    print("  3. Run benchmarks with: BENCHMARK_TYPE=tpcc ./run_all_benchmarks.sh")


if __name__ == '__main__':
    main()

