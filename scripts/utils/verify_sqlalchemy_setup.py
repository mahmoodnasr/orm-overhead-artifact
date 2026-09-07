#!/usr/bin/env python3
"""
Verification script for SQLAlchemy implementation

Tests:
1. SQLAlchemy installation
2. Model imports
3. Database connection utilities
4. Query imports
5. Benchmark script syntax
"""

import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_sqlalchemy_installation():
    """Test SQLAlchemy is installed."""
    try:
        import sqlalchemy
        print(f"✓ SQLAlchemy {sqlalchemy.__version__} installed")
        return True
    except ImportError as e:
        print(f"✗ SQLAlchemy not installed: {e}")
        return False


def test_models_import():
    """Test SQLAlchemy models can be imported."""
    try:
        from sqlalchemy_app.models import (
            Region, Nation, Supplier, Part, PartSupp,
            Customer, Orders, LineItem, Base
        )
        print("✓ All 8 TPC-H models imported successfully")
        
        # Check model attributes
        assert hasattr(LineItem, 'shipdate')
        assert hasattr(Customer, 'mktsegment')
        assert hasattr(Orders, 'orderdate')
        print("✓ Model attributes verified")
        
        return True
    except Exception as e:
        print(f"✗ Model import failed: {e}")
        return False


def test_database_utilities():
    """Test database connection utilities."""
    try:
        from sqlalchemy_app.database import (
            db_manager, get_session, get_connection_string, DB_CONFIGS
        )
        print("✓ Database utilities imported")
        
        # Test connection string generation
        conn_str = get_connection_string('postgresql')
        assert 'postgresql+psycopg2://' in conn_str
        print("✓ Connection string generation works")
        
        # Check database configs exist
        assert 'postgresql' in DB_CONFIGS
        assert 'mysql' in DB_CONFIGS
        print("✓ Database configurations present")
        
        return True
    except Exception as e:
        print(f"✗ Database utilities test failed: {e}")
        return False


def test_query_imports():
    """Test query modules can be imported."""
    try:
        from sqlalchemy_app.queries import (
            get_query_module,
            get_all_queries,
            get_query_name
        )
        print("✓ Query utilities imported")
        
        # Test query loading
        all_queries = get_all_queries()
        assert len(all_queries) == 22
        print(f"✓ All 22 queries available: {all_queries}")
        
        # Test individual query import
        q01 = get_query_module(1)
        assert hasattr(q01, 'run_query_orm')
        assert hasattr(q01, 'run_query_sql')
        assert hasattr(q01, 'get_query_info')
        print("✓ Query module structure verified")
        
        # Test query info
        info = q01.get_query_info()
        assert info['number'] == 1
        print(f"✓ Query metadata: {info['name']}")
        
        return True
    except Exception as e:
        print(f"✗ Query import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_benchmark_script():
    """Test benchmark script can be imported."""
    try:
        # Just check if file exists and is syntactically valid
        script_path = project_root / 'scripts' / 'run_benchmark_multi_orm.py'
        assert script_path.exists()
        
        # Try to compile it
        with open(script_path) as f:
            code = f.read()
        compile(code, str(script_path), 'exec')
        
        print("✓ Benchmark script syntax valid")
        return True
    except Exception as e:
        print(f"✗ Benchmark script test failed: {e}")
        return False


def test_file_structure():
    """Verify all expected files exist."""
    expected_files = [
        'sqlalchemy_app/__init__.py',
        'sqlalchemy_app/models.py',
        'sqlalchemy_app/database.py',
        'sqlalchemy_app/queries/__init__.py',
        'scripts/run_benchmark_multi_orm.py',
        'scripts/convert_queries_to_sqlalchemy.py',
        'docs/SQLALCHEMY_GUIDE.md',
        'docs/QUICKSTART_SQLALCHEMY.md',
        'docs/SQLALCHEMY_IMPLEMENTATION_SUMMARY.md',
    ]
    
    # Check query files
    for i in range(1, 23):
        expected_files.append(f'sqlalchemy_app/queries/q{i:02d}.py')
    
    missing = []
    for file_path in expected_files:
        full_path = project_root / file_path
        if not full_path.exists():
            missing.append(file_path)
    
    if missing:
        print(f"✗ Missing files: {missing}")
        return False
    else:
        print(f"✓ All {len(expected_files)} expected files present")
        return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("SQLAlchemy Implementation Verification")
    print("=" * 60)
    print()
    
    tests = [
        ("SQLAlchemy Installation", test_sqlalchemy_installation),
        ("Model Import", test_models_import),
        ("Database Utilities", test_database_utilities),
        ("Query Import", test_query_imports),
        ("Benchmark Script", test_benchmark_script),
        ("File Structure", test_file_structure),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\nTest: {name}")
        print("-" * 60)
        result = test_func()
        results.append((name, result))
        print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! SQLAlchemy implementation is ready.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check errors above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())

