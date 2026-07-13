"""
Verify SQLAlchemy Models against PostgreSQL database
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, SessionLocal
from app.models import (
    Base, User, DataResource, DataVersion, DataSource,
    LabelSchema, AnnotationTask, Annotation, Dataset, DatasetItem,
    Model, ModelVersion, TrainTask, InferTask,
    EvalTask, EvalResult, AuditLog,
)
from sqlalchemy import inspect, text

TABLE_NAMES = [
    "users", "data_resources", "data_versions", "data_sources",
    "label_schemas", "annotation_tasks", "annotations",
    "datasets", "dataset_items",
    "models", "model_versions",
    "train_tasks", "infer_tasks", "eval_tasks", "eval_results",
    "audit_logs",
]

def verify():
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    expected = set(TABLE_NAMES)

    print("=" * 60)
    print("1. Check table existence in database")
    print("=" * 60)

    all_ok = True
    for table in sorted(expected):
        exists = "[OK]" if table in db_tables else "[MISSING]"
        if table not in db_tables:
            all_ok = False
        print(f"  {exists}  {table}")

    extra = db_tables - expected
    if extra:
        print(f"\n  [WARN] Extra tables in database: {extra}")

    print(f"\n  -> Expected {len(expected)} tables, found {len(db_tables)} in database")

    print("\n" + "=" * 60)
    print("2. Check Model <-> Table mapping")
    print("=" * 60)

    model_map = {
        User: "users",
        DataResource: "data_resources",
        DataVersion: "data_versions",
        DataSource: "data_sources",
        LabelSchema: "label_schemas",
        AnnotationTask: "annotation_tasks",
        Annotation: "annotations",
        Dataset: "datasets",
        DatasetItem: "dataset_items",
        Model: "models",
        ModelVersion: "model_versions",
        TrainTask: "train_tasks",
        InferTask: "infer_tasks",
        EvalTask: "eval_tasks",
        EvalResult: "eval_results",
        AuditLog: "audit_logs",
    }

    for model, table_name in model_map.items():
        mapped_table = model.__tablename__
        match = "[OK]" if mapped_table == table_name else f"[MISMATCH] mapped to {mapped_table}"
        if mapped_table != table_name:
            all_ok = False
        print(f"  {match}  {model.__name__} -> {table_name}")

    print("\n" + "=" * 60)
    print("3. Basic query test (SELECT COUNT on each table)")
    print("=" * 60)

    db = SessionLocal()
    try:
        for table in sorted(expected):
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                print(f"  [OK]  {table}: {count} rows")
            except Exception as e:
                print(f"  [FAIL]  {table}: {e}")
                all_ok = False

        # Test: create a user via ORM
        print("\n" + "=" * 60)
        print("4. ORM write test (create test user)")
        print("=" * 60)

        import bcrypt
        pwd_hash = bcrypt.hashpw(b"test123456", bcrypt.gensalt()).decode()
        test_user = User(
            username="test_verify",
            password_hash=pwd_hash,
            email="test_verify@example.com",
            role="normal",
        )
        db.add(test_user)
        db.commit()
        db.refresh(test_user)
        print(f"  [OK]  Created user: user_id={test_user.user_id}, username={test_user.username}")

        # ORM query
        found = User.get_by_username(db, "test_verify")
        print(f"  [OK]  get_by_username: {found.username}, role={found.role}")

        # Cleanup
        db.delete(test_user)
        db.commit()
        print(f"  [OK]  Test data cleaned up")

    finally:
        db.close()

    print("\n" + "=" * 60)
    if all_ok:
        print("[SUCCESS] All checks passed! 16 DDL tables + 16 Models verified.")
    else:
        print("[FAIL] Some checks failed, see above.")
    print("=" * 60)

    return all_ok

if __name__ == "__main__":
    ok = verify()
    sys.exit(0 if ok else 1)
