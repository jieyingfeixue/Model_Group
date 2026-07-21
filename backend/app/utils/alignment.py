"""多模态时间戳对齐算法 — 三种策略实现

策略 1: nearest_neighbor — 最近邻时间窗匹配，O(n+m)
策略 2: downsample       — 降采样对齐，统一到最低帧率
策略 3: interpolate       — 插值补齐（nearest 前帧复制 / linear 线性插值）
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# 策略 1: 最近邻时间窗匹配
# ═══════════════════════════════════════════════════════════════════════════════

def align_by_nearest(
    primary_timestamps: list[float],
    secondary_timestamps: dict[str, list[float]],
    time_window_ms: float = 50.0,
) -> dict[str, Any]:
    """最近邻时间窗匹配。

    以基准传感器（primary）的时间戳为锚点，对每个 secondary 传感器，
    在 ±time_window_ms 窗内寻找时间差最小的帧作为配对。

    双指针滑动，O(n + m * k)，k 为 secondary 传感器数量。

    Args:
        primary_timestamps: 基准传感器时间戳列表（Unix 秒，浮点）
        secondary_timestamps: 其他传感器 {"infrared": [...], "mmwave": [...]}
        time_window_ms: 时间窗阈值，单位毫秒，默认 50.0

    Returns:
        {
            "pairs": [
                {
                    "primary_ts": 1700000000.500,
                    "primary_index": 0,
                    "matches": {
                        "infrared": {"ts": 1700000000.520, "index": 3, "offset_ms": 20.0},
                        "mmwave":  {"ts": 1700000000.510, "index": 2, "offset_ms": 10.0},
                    },
                },
                ...
            ],
            "report": {
                "strategy": "nearest_neighbor",
                "time_window_ms": 50.0,
                "sensors": {
                    "primary": {"original": 100, "paired": 95, "dropped": 5},
                    "infrared": {"original": 80, "paired": 95, "dropped": 0},
                    ...
                },
                "pairs_count": 95,
                "avg_offset_ms": 12.3,
                "max_offset_ms": 48.7,
            },
        }
    """
    time_window_s = time_window_ms / 1000.0
    sensor_names = list(secondary_timestamps.keys())

    # 初始化各传感器指针
    pointers = {name: 0 for name in sensor_names}
    sensor_counts = {name: len(secondary_timestamps[name]) for name in sensor_names}

    # 记录每个传感器的配对/丢弃统计
    dropped_primary = 0
    # 记录每个 secondary 帧是否已被配对（至少一次）
    matched_secondary: dict[str, list[bool]] = {
        name: [False] * sensor_counts[name] for name in sensor_names
    }

    # 所有配对偏移量，用于报告统计
    all_offsets: list[float] = []

    pairs: list[dict[str, Any]] = []

    for p_idx, primary_ts in enumerate(primary_timestamps):
        pair_entry: dict[str, Any] = {
            "primary_ts": primary_ts,
            "primary_index": p_idx,
            "matches": {},
        }
        has_any_match = False

        for sensor_name in sensor_names:
            timestamps = secondary_timestamps[sensor_name]
            ptr = pointers[sensor_name]
            count = sensor_counts[sensor_name]

            # 移动指针：跳过所有在时间窗外左侧的帧
            while ptr < count and timestamps[ptr] < primary_ts - time_window_s:
                ptr += 1

            if ptr >= count or timestamps[ptr] > primary_ts + time_window_s:
                # 当前指针指向的帧已经在时间窗右侧，无匹配
                pointers[sensor_name] = ptr
                continue

            # 在时间窗内找最近帧
            best_idx = ptr
            best_offset = abs(timestamps[ptr] - primary_ts)

            search_ptr = ptr + 1
            while (
                search_ptr < count
                and timestamps[search_ptr] <= primary_ts + time_window_s
            ):
                offset = abs(timestamps[search_ptr] - primary_ts)
                if offset < best_offset:
                    best_offset = offset
                    best_idx = search_ptr
                search_ptr += 1

            # 记录配对
            offset_ms = (timestamps[best_idx] - primary_ts) * 1000.0
            pair_entry["matches"][sensor_name] = {
                "ts": timestamps[best_idx],
                "index": best_idx,
                "offset_ms": round(offset_ms, 3),
            }
            has_any_match = True
            matched_secondary[sensor_name][best_idx] = True
            all_offsets.append(abs(offset_ms))

        if has_any_match:
            pairs.append(pair_entry)
        else:
            dropped_primary += 1

    # ── 生成报告 ──
    sensors_report = {
        "primary": {
            "original": len(primary_timestamps),
            "paired": len(pairs),
            "dropped": dropped_primary,
        }
    }
    for name in sensor_names:
        total = sensor_counts[name]
        # 统计被至少配对过一次的唯一帧数
        unique_used = sum(1 for used in matched_secondary[name] if used)
        sensors_report[name] = {
            "original": total,
            "paired": unique_used,
            "dropped": total - unique_used,
        }

    report: dict[str, Any] = {
        "strategy": "nearest_neighbor",
        "time_window_ms": time_window_ms,
        "sensors": sensors_report,
        "pairs_count": len(pairs),
    }
    if all_offsets:
        report["avg_offset_ms"] = round(
            sum(all_offsets) / len(all_offsets), 3
        )
        report["max_offset_ms"] = round(max(all_offsets), 3)
    else:
        report["avg_offset_ms"] = 0.0
        report["max_offset_ms"] = 0.0

    return {"pairs": pairs, "report": report}


# ═══════════════════════════════════════════════════════════════════════════════
# 策略 2: 降采样对齐
# ═══════════════════════════════════════════════════════════════════════════════

def align_by_downsample(
    all_timestamps: dict[str, list[float]],
    target_fps: float | None = None,
) -> dict[str, Any]:
    """降采样对齐。

    将所有传感器统一降至目标帧率。若未指定 target_fps，自动取所有传感器中
    最低的帧率为目标帧率，按统一时间间隔等距采样。

    Args:
        all_timestamps: 所有传感器时间戳 {"visible": [...], "infrared": [...]}
        target_fps: 目标帧率（Hz），默认取所有传感器最低帧率

    Returns:
        {
            "pairs": [
                {"visible": {"ts": ..., "index": 0}, "infrared": {"ts": ..., "index": 1}, ...},
                ...
            ],
            "report": {
                "strategy": "downsample",
                "target_fps": 10.0,
                "sensors": {
                    "visible": {"original": 100, "sampled": 50},
                    ...
                },
                "interval_s": 0.1,
                "pairs_count": 50,
            },
        }
    """
    sensor_names = list(all_timestamps.keys())

    # 计算各传感器原始帧率
    original_counts = {name: len(all_timestamps[name]) for name in sensor_names}
    original_fps: dict[str, float] = {}
    for name in sensor_names:
        tss = all_timestamps[name]
        if len(tss) >= 2:
            duration = tss[-1] - tss[0]
            original_fps[name] = (len(tss) - 1) / duration if duration > 0 else 0.0
        else:
            original_fps[name] = 0.0

    # 确定目标帧率
    valid_fps = [f for f in original_fps.values() if f > 0]
    if target_fps is None:
        target_fps = min(valid_fps) if valid_fps else 1.0

    # 取所有传感器时间戳的全局起止范围
    all_ts_flat: list[float] = []
    for tss in all_timestamps.values():
        all_ts_flat.extend(tss)
    if not all_ts_flat:
        return {"pairs": [], "report": {"strategy": "downsample", "error": "no_timestamps"}}

    global_start = min(all_ts_flat)
    global_end = max(all_ts_flat)
    interval_s = 1.0 / target_fps if target_fps > 0 else 0.1

    # 生成采样时间点
    sample_count = int((global_end - global_start) / interval_s) + 1
    sample_times = [global_start + i * interval_s for i in range(sample_count)]

    # 对每个采样时间点，在每个传感器中找最近帧
    pairs: list[dict[str, Any]] = []
    sampled_counts = {name: 0 for name in sensor_names}

    for sample_ts in sample_times:
        frame: dict[str, Any] = {}
        all_found = True

        for name in sensor_names:
            tss = all_timestamps[name]
            if not tss:
                all_found = False
                break
            nearest = _find_nearest_index(tss, sample_ts)
            frame[name] = {"ts": tss[nearest], "index": nearest}
            sampled_counts[name] += 1

        if all_found:
            pairs.append(frame)

    # ── 报告 ──
    sensors_report = {}
    for name in sensor_names:
        sensors_report[name] = {
            "original": original_counts[name],
            "fps": round(original_fps.get(name, 0), 2),
            "sampled": sampled_counts[name],
        }

    report: dict[str, Any] = {
        "strategy": "downsample",
        "target_fps": round(target_fps, 2),
        "interval_s": round(interval_s, 4),
        "sensors": sensors_report,
        "pairs_count": len(pairs),
    }

    return {"pairs": pairs, "report": report}


# ═══════════════════════════════════════════════════════════════════════════════
# 策略 3: 插值补齐
# ═══════════════════════════════════════════════════════════════════════════════

def align_by_interpolate(
    primary_timestamps: list[float],
    secondary_timestamps: dict[str, list[float]],
    strategy: str = "nearest",
) -> dict[str, Any]:
    """插值补齐。

    以 primary 传感器帧率为基准，对每个 secondary 传感器在 primary 的每个采样点
    进行插值补齐。低帧率传感器通过前帧复制或线性插值"填充"到与基准相同帧数。

    Args:
        primary_timestamps: 基准传感器时间戳列表
        secondary_timestamps: 其他传感器时间戳
        strategy: "nearest" — 前帧复制（直接复制最近一帧）
                  "linear"  — 在两帧之间按时间比例线性插值时间戳

    Returns:
        {
            "pairs": [
                {
                    "primary_ts": 1700000000.500,
                    "primary_index": 0,
                    "interpolated": {
                        "infrared": {
                            "ts": 1700000000.520, "index": 3,
                            "is_interpolated": false, "method": "original",
                        },
                    },
                },
                ...
            ],
            "report": {
                "strategy": "interpolate",
                "interpolation_strategy": "nearest",
                "sensors": {
                    "primary": {"original": 100},
                    "infrared": {"original": 80, "interpolated": 20, "total": 100},
                },
                "pairs_count": 100,
            },
        }
    """
    if strategy not in ("nearest", "linear"):
        raise ValueError(f"Unknown interpolation strategy: {strategy}")

    sensor_names = list(secondary_timestamps.keys())
    original_counts = {name: len(secondary_timestamps[name]) for name in sensor_names}

    # 记录每个 secondary 帧是否被直接使用（vs 插值生成）
    interpolated_count: dict[str, int] = {name: 0 for name in sensor_names}
    direct_count: dict[str, int] = {name: 0 for name in sensor_names}

    pairs: list[dict[str, Any]] = []

    for p_idx, primary_ts in enumerate(primary_timestamps):
        pair_entry: dict[str, Any] = {
            "primary_ts": primary_ts,
            "primary_index": p_idx,
            "interpolated": {},
        }

        for sensor_name in sensor_names:
            tss = secondary_timestamps[sensor_name]
            if not tss:
                continue

            if strategy == "nearest":
                # 前帧复制：找时间上最近的前一帧（不超越当前时间）
                result = _interpolate_nearest(tss, primary_ts)
            else:
                # 线性插值：在两帧之间按时间比例估计
                result = _interpolate_linear(tss, primary_ts)

            pair_entry["interpolated"][sensor_name] = result
            if result.get("is_interpolated"):
                interpolated_count[sensor_name] += 1
            else:
                direct_count[sensor_name] += 1

        pairs.append(pair_entry)

    # ── 报告 ──
    sensors_report = {
        "primary": {"original": len(primary_timestamps)},
    }
    for name in sensor_names:
        sensors_report[name] = {
            "original": original_counts[name],
            "direct": direct_count[name],
            "interpolated": interpolated_count[name],
            "total": direct_count[name] + interpolated_count[name],
        }

    report: dict[str, Any] = {
        "strategy": "interpolate",
        "interpolation_strategy": strategy,
        "sensors": sensors_report,
        "pairs_count": len(pairs),
    }

    return {"pairs": pairs, "report": report}


# ═══════════════════════════════════════════════════════════════════════════════
# 对齐报告生成（统一入口）
# ═══════════════════════════════════════════════════════════════════════════════

def generate_alignment_report(
    strategy: str,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
) -> dict[str, Any]:
    """生成统一格式的对齐报告 JSON。

    Args:
        strategy: 对齐策略名称
        input_summary: 输入数据摘要 {"visible": {"count": 100, "fps": 30.0}, ...}
        output_summary: 输出结果摘要 {"pairs_count": 95, "dropped": {...}, ...}

    Returns:
        对齐报告 dict，可直接写入 alignment_groups.report JSONB 字段
    """
    return {
        "strategy": strategy,
        "input": input_summary,
        "output": output_summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _find_nearest_index(timestamps: list[float], target: float) -> int:
    """在有序时间戳列表中找最接近 target 的索引（二分查找）。"""
    if not timestamps:
        return -1

    lo, hi = 0, len(timestamps) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if timestamps[mid] < target:
            lo = mid + 1
        else:
            hi = mid

    # 比较 lo 和 lo-1 哪个更接近
    if lo > 0 and abs(timestamps[lo - 1] - target) < abs(timestamps[lo] - target):
        return lo - 1
    return lo


def _interpolate_nearest(
    timestamps: list[float], target: float
) -> dict[str, Any]:
    """前帧复制：找不晚于 target 的最近帧。

    若 target 早于第一帧，则取第一帧（标记为 is_interpolated）。
    若 target 晚于最后一帧，则取最后一帧。
    """
    if target < timestamps[0]:
        return {
            "ts": timestamps[0],
            "index": 0,
            "is_interpolated": True,
            "method": "nearest_duplicate",
        }
    if target == timestamps[0]:
        return {
            "ts": timestamps[0],
            "index": 0,
            "is_interpolated": False,
            "method": "original",
        }

    # 找 <= target 的最大帧
    idx = _find_nearest_index(timestamps, target)
    if timestamps[idx] > target:
        # nearest 是后面的帧，用前帧
        idx = max(0, idx - 1)

    is_interp = abs(timestamps[idx] - target) > 0.001  # 1ms 容差
    return {
        "ts": timestamps[idx],
        "index": idx,
        "is_interpolated": is_interp,
        "method": "nearest_duplicate" if is_interp else "original",
    }


def _interpolate_linear(
    timestamps: list[float], target: float
) -> dict[str, Any]:
    """线性插值。

    在 target 前后两帧之间按时间比例计算一个虚拟时间戳位置。
    实际帧内容需由调用方按 ratio 在前后帧像素间插值。
    """
    if target < timestamps[0]:
        return {
            "ts": timestamps[0],
            "index": 0,
            "is_interpolated": True,
            "method": "linear_extrapolate",
        }
    if target == timestamps[0]:
        return {
            "ts": timestamps[0],
            "index": 0,
            "is_interpolated": False,
            "method": "original",
        }

    if target > timestamps[-1]:
        return {
            "ts": timestamps[-1],
            "index": len(timestamps) - 1,
            "is_interpolated": True,
            "method": "linear_extrapolate",
        }
    if target == timestamps[-1]:
        return {
            "ts": timestamps[-1],
            "index": len(timestamps) - 1,
            "is_interpolated": False,
            "method": "original",
        }

    # 二分查找 target 所在区间
    lo, hi = 0, len(timestamps) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if timestamps[mid] < target:
            lo = mid
        else:
            hi = mid

    # target 在 [lo, hi] 之间
    t_before = timestamps[lo]
    t_after = timestamps[hi]
    ratio = (target - t_before) / (t_after - t_before) if t_after != t_before else 0.0

    # 选择更近的一帧作为基准索引，同时保留插值比率供像素级插值使用
    if ratio <= 0.5:
        chosen_idx = lo
    else:
        chosen_idx = hi

    return {
        "ts": timestamps[chosen_idx],
        "index": chosen_idx,
        "is_interpolated": True,
        "method": "linear",
        "interpolation_ratio": round(ratio, 4),
        "boundary": {"before_ts": t_before, "after_ts": t_after, "ratio": round(ratio, 4)},
    }
