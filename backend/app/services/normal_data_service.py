"""数据管理 Service — upload_data / list_my_data"""

import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy.orm import Session

import zipfile
from io import BytesIO

from app.core.storage import upload_file
from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask
from app.models.data_resource import DataResource
from app.models.alignment_group import AlignmentGroup, AlignmentGroupItem
from app.models.label_schema import LabelSchema
from app.utils.alignment import align_by_nearest, align_by_downsample, align_by_interpolate
from app.utils.format_parser import match_categories, parse_coco, parse_voc, parse_yolo


def upload_data(
    db: Session,
    files: list[UploadFile],
    meta_info: dict[str, Any],
    owner_id: int,
    captured_at: float | None = None,
) -> list[DataResource]:
    """上传图片到 MinIO，提取元信息，写入 data_resources 表。

    流程：
    1. 每张图片通过 Pillow 提取 width/height/channels/file_size
    2. 合并用户提供的 meta_info（用户字段优先）
    3. 上传到 MinIO → 获得 file_path
    4. DataResource(...).save(db) → 返回记录列表

    Args:
        files: 上传文件列表
        meta_info: 用户提供的附加元信息（scene/weather/device 等）
        owner_id: 上传者 ID
        captured_at: 采集时间戳（Unix 秒），可空

    Returns:
        创建的 DataResource 列表

    Raises:
        HTTPException 400: 文件列表为空
    """

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择一个文件上传",
        )

    resources: list[DataResource] = []

    for file in files:
        # 1. 读取文件内容
        content = file.filename or ""
        file_bytes = b""

        try:
            file_bytes = file.file.read()
        except Exception:
            file_bytes = b""

        if not file_bytes:
            continue

        # 2. Pillow 提取图片元信息
        extracted: dict[str, Any] = {"file_size": len(file_bytes)}
        try:
            img = Image.open(__import__("io").BytesIO(file_bytes))
            extracted["width"] = img.width
            extracted["height"] = img.height

            if img.mode == "RGB":
                extracted["channels"] = 3
            elif img.mode == "RGBA":
                extracted["channels"] = 4
            elif img.mode == "L":
                extracted["channels"] = 1
            else:
                extracted["channels"] = len(img.getbands()) if img.getbands() else 3
        except Exception:
            pass

        # 3. 合并 meta_info：自动提取的为基础，用户提供的覆盖
        merged_meta = {**extracted, **meta_info}

        # 4. 上传到 MinIO
        ext = os.path.splitext(content)[1] if content else ".bin"
        object_name = f"images/{uuid.uuid4().hex}{ext}"
        content_type = file.content_type or "application/octet-stream"

        file_path = upload_file(file_bytes, object_name, content_type)

        # 5. 写入数据库
        resource = DataResource(
            name=content,
            owner_id=owner_id,
            modality=meta_info.get("modality", "visible"),
            file_path=file_path,
            captured_at=captured_at,
            meta_info=merged_meta,
        )
        resource.save(db)
        resources.append(resource)

    return resources


def list_my_data(
    db: Session,
    owner_id: int,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[DataResource], int]:
    """按条件分页查询当前用户的数据资源。

    filters 支持: modality, annotation_status, status, scene, start_time, end_time

    API: GET /api/data
    """
    filters = filters or {}

    # 时间范围转换为 datetime
    if start_time := filters.get("start_time"):
        try:
            filters["start_time"] = datetime.fromisoformat(start_time)
        except ValueError:
            del filters["start_time"]
    if end_time := filters.get("end_time"):
        try:
            filters["end_time"] = datetime.fromisoformat(end_time)
        except ValueError:
            del filters["end_time"]

    return DataResource.get_by_owner(db, owner_id, filters, page, size)


def multi_modal_align(
    db: Session,
    resource_ids: list[int],
    strategy: str,
    params: dict[str, Any] | None,
    user_id: int,
) -> dict[str, Any]:
    """多模态时间戳对齐。

    1. 查询所有 resource_ids 对应的 DataResource，校验 captured_at 存在
    2. 按 modality 分组，各组内按 captured_at 升序排列
    3. 默认以 visible 为基准传感器，若无 visible 则选帧数最多的模态
    4. 调用 alignment.py 中对应的策略函数
    5. 写入 alignment_groups + alignment_group_items，返回结果

    Args:
        resource_ids: 参与对齐的资源 ID 列表（至少 2 个，至少 2 种模态）
        strategy: nearest_neighbor / downsample / interpolate
        params: 策略参数 {time_window_ms, target_fps, interpolation_strategy}
        user_id: 操作用户 ID

    Returns:
        {"group_id": int, "strategy": str, "pairs_count": int, "report": dict, "created_at": datetime}

    Raises:
        HTTPException 400: 资源不足 / 缺少 captured_at / 模态单一
    """
    params = params or {}

    # ── 1. 查询资源并校验 ──
    if len(resource_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要 2 个数据资源参与对齐",
        )

    resources = (
        db.query(DataResource)
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )

    if len(resources) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅找到 {len(resources)} 个有效资源，至少需要 2 个",
        )

    # 校验 captured_at
    missing_ts = [r.resource_id for r in resources if r.captured_at is None]
    if missing_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"以下资源的 captured_at 缺失，无法对齐: {missing_ts}",
        )

    # ── 2. 按 modality 分组 + 排序 ──
    # sensor_groups: {"visible": [(res_id, ts), ...], "infrared": [...], ...}
    sensor_groups: dict[str, list[tuple[int, float]]] = {}
    for r in resources:
        sensor_groups.setdefault(r.modality, []).append(
            (r.resource_id, r.captured_at)  # type: ignore[arg-type]
        )

    if len(sensor_groups) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"需要至少 2 种模态参与对齐，当前仅有: {list(sensor_groups.keys())}",
        )

    # 各组内按时间戳升序排列
    for modality in sensor_groups:
        sensor_groups[modality].sort(key=lambda x: x[1])

    # ── 3. 选择基准传感器 ──
    if "visible" in sensor_groups:
        primary_modality = "visible"
    else:
        primary_modality = max(sensor_groups, key=lambda m: len(sensor_groups[m]))

    primary_pairs = sensor_groups.pop(primary_modality)
    primary_ids = [p[0] for p in primary_pairs]
    primary_ts = [p[1] for p in primary_pairs]

    # secondary: {"infrared": [ts1, ts2, ...], ...}
    secondary_ts: dict[str, list[float]] = {}
    secondary_ids: dict[str, list[int]] = {}
    for modality, pairs in sensor_groups.items():
        secondary_ts[modality] = [p[1] for p in pairs]
        secondary_ids[modality] = [p[0] for p in pairs]

    # ── 4. 调用对齐算法 ──
    if strategy == "nearest_neighbor":
        time_window_ms = float(params.get("time_window_ms", 50.0))
        result = align_by_nearest(primary_ts, secondary_ts, time_window_ms=time_window_ms)
    elif strategy == "downsample":
        target_fps = params.get("target_fps")
        target_fps = float(target_fps) if target_fps is not None else None
        # 重建 all_timestamps 包含 primary
        all_ts = {primary_modality: primary_ts, **secondary_ts}
        result = align_by_downsample(all_ts, target_fps=target_fps)
    elif strategy == "interpolate":
        interp_strategy = str(params.get("interpolation_strategy", "nearest"))
        result = align_by_interpolate(primary_ts, secondary_ts, strategy=interp_strategy)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的对齐策略: {strategy}",
        )

    # ── 5. 写入 alignment_groups ──
    group = AlignmentGroup(
        strategy=strategy,
        params=params,
        report=result["report"],
        created_by=user_id,
    )
    group.save(db)

    # ── 6. 写入 alignment_group_items ──
    pairs = result["pairs"]

    def _find_resource_id(sensor: str, index: int) -> int:
        """将索引映射回 resource_id"""
        if sensor == primary_modality:
            return primary_ids[index]
        return secondary_ids[sensor][index]

    # 跟踪已插入的 (group_id, resource_id)，避免重复
    inserted: set[int] = set()

    if strategy == "downsample":
        # downsample pairs 结构不同: [{visible: {ts, index}, infrared: {ts, index}}, ...]
        for frame in pairs:
            for sensor, entry in frame.items():
                rid = _find_resource_id(sensor, entry["index"])
                if rid not in inserted:
                    inserted.add(rid)
                    AlignmentGroupItem(
                        group_id=group.group_id,
                        resource_id=rid,
                        sensor_type=sensor,
                        is_primary=(sensor == primary_modality),
                    ).save(db)
    else:
        # nearest_neighbor / interpolate pairs: [{primary_ts, primary_index, matches|interpolated}, ...]
        for pair_entry in pairs:
            # 写入 primary 帧
            p_rid = _find_resource_id(primary_modality, pair_entry["primary_index"])
            if p_rid not in inserted:
                inserted.add(p_rid)
                AlignmentGroupItem(
                    group_id=group.group_id,
                    resource_id=p_rid,
                    sensor_type=primary_modality,
                    is_primary=True,
                ).save(db)

            # 写入 secondary 帧
            secondary_dict = pair_entry.get("matches") or pair_entry.get("interpolated") or {}
            for sensor, entry in secondary_dict.items():
                s_rid = _find_resource_id(sensor, entry["index"])
                if s_rid not in inserted:
                    inserted.add(s_rid)
                    AlignmentGroupItem(
                        group_id=group.group_id,
                        resource_id=s_rid,
                        sensor_type=sensor,
                        is_primary=False,
                    ).save(db)

    # ── 7. 返回结果 ──
    return {
        "group_id": group.group_id,
        "strategy": strategy,
        "pairs_count": len(pairs),
        "report": result["report"],
        "created_at": group.created_at,
    }


def import_with_annotations(
    db: Session,
    files: list[UploadFile],
    annotation_file: UploadFile,
    format: str,
    owner_id: int,
    meta_info: dict[str, Any] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    """上传带标注的数据。图片存入 MinIO，解析标注文件并导入 annotations 表。

    流程：
    1. upload_data() 上传图片 → DataResource 列表
    2. 根据 format 选择解析器
    3. 按 file_name 匹配标注 → DataResource
    4. 类别名自动匹配 label_schema 活跃类别
    5. 无 task_id 则自动创建导入任务
    6. Annotation.save_new_version() 写入标注

    Args:
        files: 图片文件列表
        annotation_file: 标注文件（COCO JSON / VOC ZIP / YOLO ZIP）
        format: coco / voc / yolo
        owner_id: 上传者 ID
        meta_info: 附加元信息
        task_id: 关联的标注任务 ID（可选，不传则自动创建）

    Returns:
        {resources: [...], task_id: int, annotations_count: int, unmatched_categories: [...], warnings: [...]}
    """
    meta_info = meta_info or {}
    warnings: list[str] = []

    # ── 1. 上传图片 ──
    resources = upload_data(db, files, meta_info, owner_id)
    if not resources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图片上传失败",
        )

    # ── 2. 解析标注文件 ──
    annotation_bytes = b""
    try:
        annotation_bytes = annotation_file.file.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法读取标注文件",
        ) from None

    bboxes_by_file: dict[str, list[dict[str, Any]]] = {}

    if format == "coco":
        try:
            json_str = annotation_bytes.decode("utf-8")
            bboxes_by_file = parse_coco(json_str)
        except (ValueError, UnicodeDecodeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"COCO JSON 解析失败: {e}",
            ) from e

    elif format == "voc":
        try:
            with zipfile.ZipFile(BytesIO(annotation_bytes)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".xml"):
                        xml_str = zf.read(name).decode("utf-8")
                        # 匹配同名的图片文件（去掉 .xml 后缀）
                        base_name = name.rsplit(".", 1)[0] if "." in name else name
                        parsed = parse_voc(xml_str, file_name=base_name)
                        for fn, bboxes in parsed.items():
                            bboxes_by_file.setdefault(fn, []).extend(bboxes)
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"VOC ZIP 解析失败: {e}",
            ) from e

    elif format == "yolo":
        try:
            with zipfile.ZipFile(BytesIO(annotation_bytes)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".txt"):
                        txt_str = zf.read(name).decode("utf-8")
                        base_name = name.rsplit(".", 1)[0] if "." in name else name
                        parsed = parse_yolo(txt_str, file_name=base_name)
                        for fn, bboxes in parsed.items():
                            bboxes_by_file.setdefault(fn, []).extend(bboxes)
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"YOLO ZIP 解析失败: {e}",
            ) from e

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的标注格式: {format}，支持 coco/voc/yolo",
        )

    if not bboxes_by_file:
        warnings.append("标注文件中未解析出任何标注数据")

    # ── 3. 按 file_name 匹配 ──
    resource_map: dict[str, DataResource] = {}
    for r in resources:
        # 不带扩展名的文件名
        name_no_ext = r.name.rsplit(".", 1)[0] if "." in r.name else r.name
        resource_map[r.name] = r
        resource_map[name_no_ext] = r
        resource_map[r.name.lower()] = r
        resource_map[name_no_ext.lower()] = r

    # ── 4. 类别名匹配 ──
    label_schema = LabelSchema.get_active(db)
    if label_schema and label_schema.categories:
        bboxes_by_file, unmatched = match_categories(
            bboxes_by_file,
            LabelSchema.get_active_categories(db, label_schema.schema_id),
        )
        if unmatched:
            warnings.append(f"以下类别名未匹配到标签体系: {unmatched}")

    # ── 5. 自动创建任务 ──
    if task_id is None:
        import_task = AnnotationTask.create(
            db,
            name=f"导入-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            data_range={},
            schema_id=label_schema.schema_id if label_schema else 1,
            assignee_ids=[owner_id],
            created_by=owner_id,
            skip_review=True,
            status="in_progress",
        )
        task_id = import_task.task_id
    else:
        # 校验 task_id 存在
        task = db.query(AnnotationTask).filter(AnnotationTask.task_id == task_id).first()
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"标注任务 task_id={task_id} 不存在",
            )

    # ── 6. 写入标注 ──
    matched_count = 0
    skipped_count = 0

    for file_name, bboxes in bboxes_by_file.items():
        # 模糊匹配资源
        resource = (
            resource_map.get(file_name)
            or resource_map.get(file_name.lower())
            or resource_map.get(file_name.rsplit(".", 1)[0] if "." in file_name else file_name)
            or resource_map.get(file_name.rsplit(".", 1)[0].lower() if "." in file_name else file_name.lower())
        )

        if resource is None:
            skipped_count += 1
            continue

        if not bboxes:
            continue

        Annotation.save_new_version(
            db,
            task_id=task_id,
            resource_id=resource.resource_id,
            bboxes=bboxes,
            user_id=owner_id,
        )
        # 更新数据资源标注状态为"已标注"（设计报告要求）
        if resource.annotation_status == "unannotated":
            resource.annotation_status = "annotated"
            resource.save(db)
        matched_count += 1

    if skipped_count > 0:
        warnings.append(f"{skipped_count} 个标注文件未能匹配到上传的图片")

    return {
        "resources": resources,
        "task_id": task_id,
        "annotations_count": matched_count,
        "unmatched_categories": [],
        "warnings": warnings,
    }
