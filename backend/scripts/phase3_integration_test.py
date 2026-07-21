"""Phase 3 Integration Test — 覆盖全部 8 个任务端到端"""

import json
import os
import sys
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image as PILImage

from app.core.database import SessionLocal
from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask
from app.models.audit_log import AuditLog
from app.models.data_resource import DataResource
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.dataset_version import DatasetVersion
from app.models.label_schema import LabelSchema
from app.models.user import User
from app.services.normal_data_service import (
    download_copy,
    get_dataset_detail,
    import_with_annotations,
    list_public_datasets,
    preview_dataset_samples,
)
from app.services.normal_dataset_service import (
    archive_dataset,
    change_visibility,
    compare_versions,
    create_dataset,
    export_dataset,
    freeze_dataset,
    get_dataset_versions,
    preview_by_filters,
    publish_dataset,
    restore_dataset,
    save_new_version,
    split_dataset,
    submit_for_review,
    unfreeze_dataset,
)
from app.utils.format_converter import FormatConverter
from app.utils.split_strategy import (
    calculate_split_distribution,
    random_split,
    stratified_split,
)

# ── Test state ──
passed = 0
failed = 0
test_dataset_id = None
test_user_id = None
test_reviewer_id = None
test_schema_id = None
test_resources = []


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}")


def setup_test_data(db):
    """准备测试数据：用户、标签体系、标注任务、数据资源、标注"""
    global test_user_id, test_reviewer_id, test_schema_id, test_resources

    # 用户
    users = db.query(User).limit(3).all()
    if len(users) < 2:
        print("  [SKIP] 需要至少 2 个用户才能运行测试")
        return False
    test_user_id = users[0].user_id
    test_reviewer_id = users[1].user_id
    print(f"  测试用户: owner={test_user_id} reviewer={test_reviewer_id}")

    # 标签体系
    schema = LabelSchema.get_active(db)
    if schema is None:
        from app.services import admin_label_service
        schema = admin_label_service.create_schema(db, "Phase3_Test_Labels")
        schema = admin_label_service.add_category(db, schema.schema_id, "car", "c", True, False, False)
        schema = admin_label_service.add_category(db, schema.schema_id, "person", "p", True, True, False)
    test_schema_id = schema.schema_id
    print(f"  标签体系: schema_id={test_schema_id}")

    # 检查是否已有数据资源
    existing = db.query(DataResource).filter(
        DataResource.owner_id == test_user_id
    ).count()
    if existing >= 5:
        test_resources = (
            db.query(DataResource)
            .filter(DataResource.owner_id == test_user_id)
            .limit(10)
            .all()
        )
        print(f"  复用已有数据: {len(test_resources)} 条")
        return True

    # 创建测试图片和标注
    print("  创建测试数据...")
    from app.core.storage import upload_file
    from fastapi import UploadFile

    resources = []
    for i in range(5):
        buf = BytesIO()
        PILImage.new("RGB", (640, 480)).save(buf, format="JPEG")
        buf.seek(0)
        name = f"phase3_test_{i}.jpg"
        file_bytes = buf.read()

        resource = DataResource(
            name=name,
            owner_id=test_user_id,
            modality="visible",
            file_path=upload_file(file_bytes, f"test/phase3_{i}.jpg", "image/jpeg"),
            meta_info={
                "width": 640,
                "height": 480,
                "channels": 3,
                "scene": "urban" if i % 2 == 0 else "rural",
                "weather": "clear",
                "time_of_day": "day",
            },
            captured_at=1700000000.0 + i,
        )
        resource.save(db)
        resources.append(resource)
    test_resources = resources

    # 创建标注任务 + 标注
    task = AnnotationTask(
        name="Phase3_Test_Task",
        data_range={},
        schema_id=test_schema_id,
        assignee_ids=[test_user_id],
        created_by=test_user_id,
        skip_review=False,
        status="in_progress",
    )
    task.save(db)

    # 获取活跃类别
    cats = LabelSchema.get_active_categories(db, test_schema_id)
    cat_ids = [c["id"] for c in cats[:2]] if len(cats) >= 2 else ["cat_001", "cat_002"]

    for i, res in enumerate(resources[:3]):
        bboxes = [
            {
                "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.3,
                "category_id": cat_ids[i % len(cat_ids)],
            }
        ]
        ann = Annotation(
            task_id=task.task_id,
            resource_id=res.resource_id,
            bboxes=bboxes,
            version=1,
            review_status="approved",
            created_by=test_user_id,
        )
        ann.save(db)

    # 更新标注状态
    for res in resources[:3]:
        res.annotation_status = "annotated"
        res.save(db)

    print(f"  创建完成: {len(resources)} 数据资源, 3 条标注")
    return True


def test_task1_filter_and_create(db):
    """Task 1: 多条件筛选构建"""
    print("\n=== Task 1: 多条件筛选构建 ===")

    # 1a. 预览
    filters = {"modality": "visible", "scene": "urban"}
    result = preview_by_filters(db, filters, test_user_id)
    check(result["total_count"] > 0, f"Preview hit count: {result['total_count']}")
    check(isinstance(result["sample_thumbnails"], list), "Preview returns thumbnails list")

    # 多模态筛选
    filters2 = {"modality": ["visible", "infrared"]}
    result2 = preview_by_filters(db, filters2, test_user_id)
    check(result2["total_count"] > 0, f"Multi-modality preview: {result2['total_count']}")

    # AND/OR 逻辑
    filters3 = {"modality": "visible", "weather": "clear", "logic_operator": "AND"}
    result3 = preview_by_filters(db, filters3, test_user_id)
    check(result3["total_count"] > 0, "AND logic filter works")

    # 1b. 创建数据集
    global test_dataset_id
    dataset = create_dataset(
        db,
        name="Phase3_Integration_Test_Dataset",
        description="Test dataset for Phase 3",
        filters={"modality": "visible"},
        owner_id=test_user_id,
    )
    test_dataset_id = dataset.dataset_id
    check(dataset.dataset_id > 0, f"Create dataset: dataset_id={dataset.dataset_id}")
    check(dataset.status == "draft", f"Dataset status is draft: {dataset.status}")

    item_count = db.query(DatasetItem).filter(
        DatasetItem.dataset_id == test_dataset_id
    ).count()
    check(item_count > 0, f"DatasetItem count: {item_count}")


def test_task2_split(db):
    """Task 2: 训练/验证/测试集分层划分"""
    print("\n=== Task 2: 分层划分 ===")

    # 2a. random_split 单元测试
    items = list(range(100))
    result = random_split(items, (0.7, 0.2, 0.1))
    check(len(result["train"]) == 70, f"Random split: train={len(result['train'])}")
    check(len(result["val"]) == 20, f"Random split: val={len(result['val'])}")
    check(len(result["test"]) == 10, f"Random split: test={len(result['test'])}")

    # 空列表
    empty = random_split([], (0.7, 0.2, 0.1))
    check(len(empty["train"]) == 0, "Random split empty list")

    # 2b. stratified_split
    s_result = stratified_split(items, (0.7, 0.2, 0.1), db, stratify_by="scene")
    total = len(s_result["train"]) + len(s_result["val"]) + len(s_result["test"])
    check(total == 100, f"Stratified split total: {total}")
    check(len(s_result["train"]) > 0, f"Stratified train: {len(s_result['train'])}")

    # 降级测试（样本不足时降级为随机）
    few_items = [1, 2, 3]
    s_few = stratified_split(few_items, (0.7, 0.2, 0.1), db, stratify_by="scene")
    tf = len(s_few["train"]) + len(s_few["val"]) + len(s_few["test"])
    check(tf == 3, f"Stratified fallback total: {tf}")

    # 2c. 数据集划分
    split_ratios = {"train": 70, "val": 20, "test": 10}
    dist = split_dataset(db, test_dataset_id, split_ratios, "random")
    check(dist["total"] > 0, f"Split distribution total: {dist['total']}")
    check("train" in dist, "Split result has train")
    check("val" in dist, "Split result has val")
    check("test" in dist, "Split result has test")

    # 验证数据集 split_config 已更新
    dataset = db.query(Dataset).filter(Dataset.dataset_id == test_dataset_id).first()
    check(dataset.split_config is not None, "Dataset split_config updated")
    check(dataset.split_config.get("strategy") == "random", "Split strategy recorded")


def test_task3_freeze_publish(db):
    """Task 3: 冻结与发布流程"""
    print("\n=== Task 3: 冻结与发布流程 ===")

    # 3a. 冻结
    dataset = freeze_dataset(db, test_dataset_id)
    check(dataset.status == "frozen", f"Freeze: status={dataset.status}")

    # 重复冻结应报错
    try:
        freeze_dataset(db, test_dataset_id)
        check(False, "Double freeze should error")
    except Exception:
        check(True, "Double freeze raises error")

    # 3b. 提交审核
    dataset = submit_for_review(db, test_dataset_id)
    check(dataset.review_status == "submitted", f"Submit review: {dataset.review_status}")

    # 重复提交应报错
    try:
        submit_for_review(db, test_dataset_id)
        check(False, "Double submit should error")
    except Exception:
        check(True, "Double submit raises error")

    # 3c. 发布
    dataset = publish_dataset(db, test_dataset_id, "private")
    check(dataset.status == "published", f"Publish: status={dataset.status}")
    check(dataset.visibility == "private", f"Publish visibility: {dataset.visibility}")

    # 3d. 修改可见范围
    dataset = change_visibility(db, test_dataset_id, "public")
    check(dataset.visibility == "public", f"Change visibility: {dataset.visibility}")

    # 恢复为 private
    dataset = change_visibility(db, test_dataset_id, "private")
    check(dataset.visibility == "private", "Change visibility back to private")

    # 解冻测试：需要另一个 frozen 数据集，这里直接测 admin 流程
    # 仅验证 unfreeze 函数存在且可调用
    try:
        unfreeze_dataset(db, test_dataset_id)
        check(False, "Unfreeze published should fail")
    except Exception:
        check(True, "Unfreeze published dataset blocked")


def test_task4_export(db):
    """Task 4: 多格式虚拟导出器"""
    print("\n=== Task 4: 多格式导出 ===")

    # 4a. COCO 导出
    coco = FormatConverter.to_coco(db, test_dataset_id)
    check("images" in coco, "COCO has images")
    check("annotations" in coco, "COCO has annotations")
    check("categories" in coco, "COCO has categories")
    check(len(coco["images"]) > 0, f"COCO images: {len(coco['images'])}")
    check(FormatConverter.validate_output("coco", coco), "COCO validate passes")

    # 空数据集 COCO
    empty_coco = FormatConverter.to_coco(db, 99999)
    check(len(empty_coco["images"]) == 0, "COCO empty dataset")

    # 4b. VOC 导出
    voc = FormatConverter.to_voc(db, test_dataset_id)
    if len(voc) > 0:
        check("<annotation>" in voc[0][1], "VOC XML valid")
        # 至少有一个文件包含标注（部分资源可能无标注）
        any_has_name = any("<name>" in xml for _, xml in voc)
        check(any_has_name, "VOC has category name in at least one file")
        check(FormatConverter.validate_output("voc", voc), "VOC validate passes")

    # 4c. YOLO 导出
    txt_files, yaml_content = FormatConverter.to_yolo(db, test_dataset_id)
    check(isinstance(txt_files, list), "YOLO txt files list")
    check("nc:" in yaml_content, "YOLO yaml has nc")
    check("names:" in yaml_content, "YOLO yaml has names")
    check(FormatConverter.validate_output("yolo", (txt_files, yaml_content)), "YOLO validate passes")

    # 4d. ZIP 导出
    export = export_dataset(db, test_dataset_id, "coco", "train", test_user_id)
    check("download_url" in export, "Export has download_url")
    check(export["format"] == "coco", "Export format correct")
    check(export["expires_in"] == 3600, "Export expires_in 3600")

    # VOC + YOLO 导出
    export_voc = export_dataset(db, test_dataset_id, "voc", None, test_user_id)
    check("download_url" in export_voc, "VOC export has download_url")

    export_yolo = export_dataset(db, test_dataset_id, "yolo", None, test_user_id)
    check("download_url" in export_yolo, "YOLO export has download_url")

    # 无效格式
    try:
        export_dataset(db, test_dataset_id, "invalid", None, test_user_id)
        check(False, "Invalid format should error")
    except Exception:
        check(True, "Invalid format raises error")


def test_task5_versions(db):
    """Task 5: 版本管理与差异对比"""
    print("\n=== Task 5: 版本管理与差异对比 ===")

    # 5a. 保存新版本
    v1 = save_new_version(db, test_dataset_id, "Initial snapshot", test_user_id, "minor")
    check(v1["version"].startswith("v"), f"Save version: {v1['version']}")
    check(v1["sample_count"] > 0, f"Version sample_count: {v1['sample_count']}")
    check(v1["change_log"] == "Initial snapshot", "Version change_log saved")

    # 保存第二个版本
    v2 = save_new_version(db, test_dataset_id, "Second snapshot", test_user_id, "minor")
    check(v2["version"] != v1["version"], f"Version bumped: {v1['version']} → {v2['version']}")

    # 5b. 版本列表
    versions = get_dataset_versions(db, test_dataset_id)
    check(len(versions) >= 2, f"Version list: {len(versions)}")
    check("split_config" in versions[0], "Version has split_config")
    check("sample_count" in versions[0], "Version has sample_count")

    # 5c. 差异对比
    diff = compare_versions(db, test_dataset_id, v1["version"], v2["version"])
    check(diff["v1"] == v1["version"], f"Diff v1: {diff['v1']}")
    check(diff["v2"] == v2["version"], f"Diff v2: {diff['v2']}")
    check("summary" in diff, "Diff has summary")
    check(isinstance(diff["added"], list), "Diff added is list")
    check(isinstance(diff["removed"], list), "Diff removed is list")

    # 差异条目含 name 字段
    if diff["added"]:
        check("name" in diff["added"][0], "Diff entry has name field")

    # 不存在的版本
    try:
        compare_versions(db, test_dataset_id, "v99.99", v1["version"])
        check(False, "Non-existent version should error")
    except Exception:
        check(True, "Non-existent version raises error")


def test_task6_archive(db):
    """Task 6: 归档与恢复"""
    print("\n=== Task 6: 归档与恢复 ===")

    # 6a. 归档
    dataset = archive_dataset(db, test_dataset_id, test_user_id)
    check(dataset.archive_status == "archived", f"Archive: {dataset.archive_status}")

    # 重复归档应报错
    try:
        archive_dataset(db, test_dataset_id, test_user_id)
        check(False, "Double archive should error")
    except Exception:
        check(True, "Double archive raises error")

    # 6b. 恢复
    dataset = restore_dataset(db, test_dataset_id, test_user_id)
    check(dataset.archive_status == "active", f"Restore: {dataset.archive_status}")

    # 未归档恢复应报错
    try:
        restore_dataset(db, test_dataset_id, test_user_id)
        check(False, "Restore non-archived should error")
    except Exception:
        check(True, "Restore non-archived raises error")

    # 6c. 批量归档（条件筛选）
    from app.services.normal_dataset_service import batch_archive

    batch_result = batch_archive(
        db,
        {"owner_id": test_user_id, "modality": "visible"},
        test_user_id,
    )
    check(batch_result["matched_count"] >= 1, f"Batch archive matched: {batch_result['matched_count']}")
    check(isinstance(batch_result["archived_count"], int), "Batch archive returns count")

    # 恢复以便后续测试
    restore_dataset(db, test_dataset_id, test_user_id)


def test_task7_marketplace(db):
    """Task 7: 数据集市场与下载"""
    print("\n=== Task 7: 数据集市场与下载 ===")

    # 先确保测试数据集公开
    ds = db.query(Dataset).filter(Dataset.dataset_id == test_dataset_id).first()
    if ds.visibility != "public":
        Dataset.set_visibility(db, test_dataset_id, "public")

    # 7a. 浏览市场
    items, total = list_public_datasets(db, {}, page=1, size=50)
    check(total > 0, f"Market total: {total}")
    if total > 0:
        item = items[0]
        check("dataset_type" in item, "Market item has dataset_type")
        check("modality" in item, "Market item has modality")
        check("sample_count" in item, "Market item has sample_count")

    # 筛选
    items_f, total_f = list_public_datasets(db, {"keyword": "Phase3"}, page=1, size=10)
    check(isinstance(items_f, list), "Keyword filter returns list")

    # 7b. 数据集详情
    detail = get_dataset_detail(db, test_dataset_id)
    check(detail["dataset_id"] == test_dataset_id, f"Detail dataset_id: {detail['dataset_id']}")
    check("subsets" in detail, "Detail has subsets")
    check(isinstance(detail["subsets"]["train"], int), "Detail subsets has train count")

    # 7c. 样本预览
    preview = preview_dataset_samples(db, test_dataset_id, page=1, size=5)
    check("samples" in preview, "Preview has samples")
    check("total" in preview, "Preview has total")
    if preview["samples"]:
        sample = preview["samples"][0]
        check("file_url" in sample, "Sample has file_url")
        check("bboxes" in sample, "Sample has bboxes")

    # 7d. 复制数据集
    copy = download_copy(db, test_dataset_id, test_user_id)
    check(copy["copy_id"] > 0, f"Copy dataset: copy_id={copy['copy_id']}")
    check(copy["sample_count"] > 0, f"Copy sample_count: {copy['sample_count']}")

    # 清理副本
    copy_ds = db.query(Dataset).filter(Dataset.dataset_id == copy["copy_id"]).first()
    if copy_ds:
        db.query(DatasetItem).filter(DatasetItem.dataset_id == copy["copy_id"]).delete()
        copy_ds.delete(db)


def test_task8_dead_link(db):
    """Task 8: 死链巡检脚本"""
    print("\n=== Task 8: 死链巡检 ===")

    # 8a. MinIO 文件检查（测试数据应存在）
    from app.core.storage import ensure_bucket
    from minio import Minio
    from app.core.config import settings

    client = Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
    ensure_bucket()

    # 模拟：用 stat_object 检查测试资源
    if test_resources:
        resource = test_resources[0]
        from scripts.dead_link_checker import check_minio_file

        result = check_minio_file(resource.file_path)
        check(result["exists"] is True, f"MinIO stat: file exists={result['exists']}")

        # 不存在的文件
        fake = check_minio_file("/detection-platform/test/nonexistent.jpg")
        check(fake["exists"] is False, "MinIO stat: missing file detected")

    # 8b. 报告生成
    from scripts.dead_link_checker import generate_report

    report_data = {
        "total": 10, "alive": 9, "dead": 1,
        "minio_dead": 1, "http_dead": 0,
        "dead_rate": 10.0, "updated_count": 1,
        "elapsed_seconds": 1.23,
        "checked_at": "2026-07-15T00:00:00",
        "dead_links": [
            {"resource_id": 1, "name": "test.jpg", "file_path": "/bucket/path",
             "modality": "visible", "method": "minio", "status_code": "-",
             "error": "Object does not exist"},
        ],
    }
    report = generate_report(report_data)
    check("巡检报告" in report, "Report has title")
    check("死链详情" in report, "Report has dead links section")
    check("10" in report, "Report has total count")
    check("test.jpg" in report, "Report has dead link detail")


def cleanup(db):
    """清理测试数据"""
    if test_dataset_id:
        # 删除版本记录
        db.query(DatasetVersion).filter(
            DatasetVersion.dataset_id == test_dataset_id
        ).delete()

        # 删除数据集条目
        db.query(DatasetItem).filter(
            DatasetItem.dataset_id == test_dataset_id
        ).delete()

        # 删除数据集
        dataset = db.query(Dataset).filter(
            Dataset.dataset_id == test_dataset_id
        ).first()
        if dataset:
            dataset.delete(db)

    # 删除测试审计日志
    db.query(AuditLog).filter(
        AuditLog.target_type == "dataset",
        AuditLog.target_id == test_dataset_id,
    ).delete()


def main():
    global passed, failed
    print("=" * 60)
    print("Phase 3 Integration Test")
    print("=" * 60)

    db = SessionLocal()
    try:
        # ── Setup ──
        print("\n--- Setup ---")
        if not setup_test_data(db):
            print("Setup failed, aborting.")
            return

        # ═══════════════ Run All Tasks ═══════════════
        test_task1_filter_and_create(db)
        test_task2_split(db)
        test_task3_freeze_publish(db)
        test_task4_export(db)
        test_task5_versions(db)
        test_task6_archive(db)
        test_task7_marketplace(db)
        test_task8_dead_link(db)

        # ── Cleanup ──
        print("\n--- Cleanup ---")
        cleanup(db)
        print("  Test data cleaned up.")

    except Exception as e:
        print(f"\n[ERROR] Test aborted: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()

    # ── Summary ──
    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    if failed == 0:
        print("Phase 3 Integration Test: ALL PASSED")
    else:
        print(f"Phase 3 Integration Test: {failed} FAILURES")
        sys.exit(1)


if __name__ == "__main__":
    main()
