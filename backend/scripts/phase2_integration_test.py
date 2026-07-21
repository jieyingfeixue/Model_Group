"""Phase 2 Integration Test — covers all 7 tasks end-to-end"""

from app.core.database import SessionLocal
from app.models.user import User
from app.models.label_schema import LabelSchema
from app.models.annotation_task import AnnotationTask
from app.models.annotation import Annotation
from app.models.data_resource import DataResource
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.alignment_group import AlignmentGroup, AlignmentGroupItem
from app.services import admin_label_service, normal_annotation_service
from app.services import normal_data_service, reviewer_dataset_service, reviewer_annotation_service

from io import BytesIO
import json
from fastapi import UploadFile
from PIL import Image as PILImage


def test_all():
    db = SessionLocal()
    passed = 0
    failed = 0

    def check(condition, label):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {label}")
        else:
            failed += 1
            print(f"  [FAIL] {label}")

    try:
        # ── Setup ──
        users = db.query(User).limit(3).all()
        owner_id = users[0].user_id
        reviewer_id = users[1].user_id
        assignee_id = users[2].user_id
        print(f"Users: owner={owner_id} reviewer={reviewer_id} assignee={assignee_id}")

        # ═══════════════ TASK 2: Label Schema CRUD ═══════════════
        print("\n=== Task 2: Label Schema CRUD ===")
        ls = admin_label_service.create_schema(db, "Phase2_Test_Labels")
        check(ls.schema_id > 0, "Create schema")

        ls = admin_label_service.add_category(db, ls.schema_id, "car", "c", True, False, False)
        check(ls.categories[0]["id"] == "cat_001", "Add category cat_001")

        ls = admin_label_service.add_category(db, ls.schema_id, "pedestrian", "p", True, True, False)
        ls = admin_label_service.add_category(db, ls.schema_id, "cyclist", "y", True, False, False)
        check(len(ls.categories) == 3, "Add 3 categories total")

        ls = admin_label_service.update_category(db, ls.schema_id, "cat_003", {"shortcut": "b"})
        check(ls.categories[2]["shortcut"] == "b", "Update category shortcut")

        ls = admin_label_service.deprecate_category(db, ls.schema_id, "cat_003", "merge", "cat_002")
        dep = [c for c in ls.categories if c["id"] == "cat_003"][0]
        check(dep["status"] == "deprecated", "Deprecate category")

        cats = admin_label_service.get_active_categories(db, ls.schema_id)
        check(len(cats) == 2, "Active categories exclude deprecated")

        json_str = admin_label_service.export_schema(db, ls.schema_id)
        check("car" in json_str, "Export JSON")

        imported = admin_label_service.import_schema(db, "Imported", json_str)
        check(imported.schema_id > 0, "Import schema")
        imported.delete(db)

        # ═══════════════ TASK 1+7: Upload & Alignment ═══════════════
        print("\n=== Task 1/7: Upload & Alignment ===")

        # Upload visible images with timestamps
        test_resources = []
        for i in range(3):
            buf = BytesIO()
            PILImage.new("RGB", (640, 480)).save(buf, format="JPEG")
            buf.seek(0)
            f = UploadFile(filename=f"vis_{i}.jpg", file=BytesIO(buf.read()), headers={"content-type": "image/jpeg"})
            test_resources.append(f)

        res_vis = normal_data_service.upload_data(
            db, test_resources, {"scene": "urban", "device": "cam_a"}, owner_id,
            captured_at=1700000000.0
        )
        check(len(res_vis) == 3, "Upload 3 visible images")

        # Upload infrared images
        ir_files = []
        for i in range(3):
            buf = BytesIO()
            PILImage.new("RGB", (640, 480)).save(buf, format="JPEG")
            buf.seek(0)
            f = UploadFile(filename=f"ir_{i}.jpg", file=BytesIO(buf.read()), headers={"content-type": "image/jpeg"})
            ir_files.append(f)

        res_ir = normal_data_service.upload_data(
            db, ir_files, {"modality": "infrared", "scene": "urban", "device": "ir_cam"}, owner_id,
            captured_at=1700000000.01
        )
        check(len(res_ir) == 3, "Upload 3 infrared images")

        all_rids = [r.resource_id for r in res_vis + res_ir]
        for rid in all_rids:
            r = db.query(DataResource).filter(DataResource.resource_id == rid).first()
            check(r.captured_at is not None, f"captured_at stored: {r.name}")

        # Alignment
        result = normal_data_service.multi_modal_align(
            db, all_rids, "nearest_neighbor", {"time_window_ms": 50.0}, owner_id
        )
        check(result["group_id"] > 0, "Alignment: group created")
        check(result["pairs_count"] > 0, f"Alignment: {result['pairs_count']} pairs")

        ag = db.query(AlignmentGroup).filter(AlignmentGroup.group_id == result["group_id"]).first()
        items = AlignmentGroupItem.get_by_group(db, ag.group_id)
        check(len(items) > 0, f"Alignment items stored: {len(items)}")

        # ═══════════════ TASK 3: Annotation Multi-version ═══════════════
        print("\n=== Task 3: Annotation Multi-version ===")

        task = normal_annotation_service.create_annotation_task(
            db, "Phase2_Anno", {"modality": "visible"}, ls.schema_id,
            [assignee_id], owner_id, reviewer_id=reviewer_id
        )
        check(task.status == "draft", "Create annotation task")

        bboxes1 = [{"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.3, "category_id": "cat_001", "depth": 15.0}]
        ann = normal_annotation_service.save_annotation(
            db, task.task_id, res_vis[0].resource_id, bboxes1, assignee_id
        )
        check(ann.version == 1, "Save v1")
        db.refresh(task)
        check(task.status == "in_progress", "Task auto-switch to in_progress")

        bboxes2 = bboxes1 + [{"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.1, "category_id": "cat_002", "depth": 8.0}]
        ann2 = normal_annotation_service.save_annotation(
            db, task.task_id, res_vis[0].resource_id, bboxes2, assignee_id
        )
        check(ann2.version == 2, "Save v2 (append)")

        history = normal_annotation_service.get_annotation_history(
            db, task.task_id, res_vis[0].resource_id
        )
        check(len(history) == 2, f"History: {len(history)} versions")

        submitted = normal_annotation_service.submit_annotation(
            db, task.task_id, res_vis[0].resource_id, assignee_id
        )
        check(submitted.review_status == "submitted", "Submit annotation")
        db.refresh(task)
        check(task.status == "submitted", "Task status: submitted")

        try:
            normal_annotation_service.save_annotation(
                db, task.task_id, res_vis[0].resource_id, bboxes1, assignee_id
            )
            check(False, "Should block save after submit")
        except Exception:
            check(True, "Save blocked after submit")

        progress = normal_annotation_service.get_annotation_progress(db, task.task_id)
        check(progress["annotated"] == 1, f"Progress: annotated={progress['annotated']}")
        check(progress["total"] > 0, f"Progress: total={progress['total']} (data_range)")

        # ═══════════════ TASK 4: Dataset Review ═══════════════
        print("\n=== Task 4: Dataset Review ===")

        ds = Dataset.create(db, name="Phase2_DS", owner_id=owner_id, status="frozen", review_status="submitted")
        di = DatasetItem(dataset_id=ds.dataset_id, resource_id=res_vis[0].resource_id, subset="test")
        di.save(db)
        check(ds.dataset_id > 0, "Dataset created")

        pending, total = reviewer_dataset_service.get_pending_datasets(db)
        check(total >= 1, f"Pending datasets: {total}")

        ds = reviewer_dataset_service.claim_dataset_review(db, ds.dataset_id, reviewer_id)
        check(ds.review_status == "reviewing", "Claim dataset")

        checklist = reviewer_dataset_service.get_review_checklist_result(db, ds.dataset_id)
        checks = checklist["checks"]
        check(len(checks) == 7, f"Checklist: {len(checks)} checks")
        failed_checks = sum(1 for c in checks.values() if not c["passed"])
        print(f"    Checklist: {failed_checks} automated failures detected (expected)")

        ds = reviewer_dataset_service.unclaim_dataset_review(db, ds.dataset_id, reviewer_id)
        check(ds.review_status == "submitted", "Unclaim dataset")

        ds = reviewer_dataset_service.claim_dataset_review(db, ds.dataset_id, reviewer_id)
        ds = reviewer_dataset_service.review_dataset(db, ds.dataset_id, reviewer_id, "approved")
        check(ds.review_status == "approved", "Verdict: review_status")
        check(ds.status == "published", "Verdict: auto-publish")

        # ═══════════════ TASK 5: Annotation Review ═══════════════
        print("\n=== Task 5: Annotation Review ===")

        pending, total = reviewer_annotation_service.get_pending_annotation_tasks(db)
        check(total >= 1, f"Pending annotation tasks: {total}")

        task2 = reviewer_annotation_service.claim_annotation_review(db, task.task_id, reviewer_id)
        check(task2.status == "reviewing", "Claim annotation task")

        sampling = reviewer_annotation_service.setup_sampling(
            db, task.task_id, reviewer_id, ratio=1.0, mode="random"
        )
        check(sampling["sampled_count"] == 1, f"Sampling: {sampling['sampled_count']}/{sampling['total']}")

        ann_reviewed = reviewer_annotation_service.review_annotation(
            db, submitted.annotation_id, "approved"
        )
        check(ann_reviewed.review_status == "approved", "Review: approved")

        summary = reviewer_annotation_service.get_sampling_result(db, task.task_id)
        check(summary["passed"] == 1, f"Summary: passed={summary['passed']}")
        check(summary["pass_rate"] == 1.0, f"Summary: pass_rate={summary['pass_rate']}")

        task3 = reviewer_annotation_service.finalize_review(
            db, task.task_id, reviewer_id, "dismiss_only"
        )
        check(task3.status == "completed", "Finalize: completed")

        # ═══════════════ TASK 6: Quality Check + Stats ═══════════════
        print("\n=== Task 6: Quality Check + Stats ===")

        buf = BytesIO()
        PILImage.new("RGB", (1920, 1080)).save(buf, format="JPEG")
        buf.seek(0)
        f_qc = UploadFile(filename="qc.jpg", file=BytesIO(buf.read()), headers={"content-type": "image/jpeg"})
        [qc_r] = normal_data_service.upload_data(
            db, [f_qc], {"width": 1920, "height": 1080}, owner_id
        )

        qc_task = normal_annotation_service.create_annotation_task(
            db, "QC_Task", {"modality": "visible"}, ls.schema_id, [assignee_id], owner_id
        )
        qc_ann = Annotation(
            task_id=qc_task.task_id, resource_id=qc_r.resource_id,
            bboxes=[
                {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.3, "category_id": "cat_001"},
                {"x": 2.0, "y": 0.3, "w": 0.001, "h": 0.15, "category_id": "cat_001", "depth": 600.0},
            ],
            version=1, created_by=assignee_id
        )
        qc_ann.save(db)

        qc_result = reviewer_annotation_service.run_quality_check(db, qc_task.task_id)
        check(qc_result["error_labels_summary"]["issues_found"] >= 2,
              f"Quality check: {qc_result['error_labels_summary']['issues_found']} issues (out_of_bounds + depth_out_of_range)")

        # Stats
        qc_task.status = "completed"
        qc_task.reviewer_id = reviewer_id
        qc_task.save(db)
        qc_ann.review_status = "approved"
        qc_ann.save(db)
        stats = reviewer_annotation_service.get_reviewer_stats(db, reviewer_id)
        check("dataset_review" in stats, "Stats: dataset dimension")
        check(stats["annotation_review"]["total"] > 0, f"Stats: anno_total={stats['annotation_review']['total']}")

        # ═══════════════ TASK 7: Import with Annotations ═══════════════
        print("\n=== Task 7: Import with Annotations ===")

        coco_json = json.dumps({
            "images": [{"id": 1, "file_name": "import_test.jpg", "width": 640, "height": 480}],
            "categories": [{"id": 1, "name": "car"}],
            "annotations": [{"image_id": 1, "category_id": 1, "bbox": [100, 200, 150, 120]}]
        })
        ann_file = UploadFile(
            filename="annotations.json", file=BytesIO(coco_json.encode()),
            headers={"content-type": "application/json"}
        )

        buf = BytesIO()
        PILImage.new("RGB", (640, 480)).save(buf, format="JPEG")
        buf.seek(0)
        img_file = UploadFile(
            filename="import_test.jpg", file=BytesIO(buf.read()),
            headers={"content-type": "image/jpeg"}
        )

        import_result = normal_data_service.import_with_annotations(
            db, [img_file], ann_file, "coco", owner_id
        )
        check(import_result["annotations_count"] == 1,
              f"Import: {import_result['annotations_count']} annotations")
        check(len(import_result["resources"]) == 1, "Import: 1 resource")

        for r in import_result["resources"]:
            db.refresh(r)
            if "import_test" in (r.name or ""):
                check(r.annotation_status == "annotated",
                      f"annotation_status={r.annotation_status} (should be annotated)")

        # Store cleanup IDs
        import_task_id = import_result["task_id"]
        import_rids = [r.resource_id for r in import_result["resources"]]

        # ═══════════════ CLEANUP ═══════════════
        print("\n=== Cleanup ===")
        # Annotations
        db.query(Annotation).filter(Annotation.task_id.in_([task.task_id, qc_task.task_id, import_task_id])).delete(synchronize_session="fetch")
        # Tasks
        db.query(AnnotationTask).filter(AnnotationTask.task_id.in_([task.task_id, qc_task.task_id, import_task_id])).delete(synchronize_session="fetch")
        # Dataset
        db.query(DatasetItem).filter(DatasetItem.dataset_id == ds.dataset_id).delete()
        db.query(Dataset).filter(Dataset.dataset_id == ds.dataset_id).delete()
        # Alignment
        db.query(AlignmentGroupItem).filter(AlignmentGroupItem.group_id == ag.group_id).delete()
        db.query(AlignmentGroup).filter(AlignmentGroup.group_id == ag.group_id).delete()
        # Resources
        all_del_rids = all_rids + [qc_r.resource_id] + import_rids
        db.query(DataResource).filter(DataResource.resource_id.in_(all_del_rids)).delete(synchronize_session="fetch")
        # Schema
        db.query(LabelSchema).filter(LabelSchema.schema_id == ls.schema_id).delete()
        check(True, "Cleanup complete")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    finally:
        db.close()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = test_all()
    exit(0 if success else 1)
