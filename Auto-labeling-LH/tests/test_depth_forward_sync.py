import csv
import json
from pathlib import Path

from src.fusion.depth_forward_sync import (
    ForwardSyncRequest,
    build_world_anchor,
    forward_sync_depth,
)


def _write_nav(segment: Path) -> None:
    gps = segment / "gps" / "nav100__fix" / "nav100__fix.csv"
    heading = segment / "heading" / "nav100__heading" / "nav100__heading.csv"
    gps.parent.mkdir(parents=True)
    heading.parent.mkdir(parents=True)
    with gps.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_time_sec", "latitude", "longitude", "altitude"],
        )
        writer.writeheader()
        writer.writerow(
            {"relative_time_sec": 0, "latitude": 31.0, "longitude": 118.0, "altitude": 100}
        )
        writer.writerow(
            {"relative_time_sec": 2, "latitude": 31.0, "longitude": 118.0002, "altitude": 100}
        )
    with heading.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["relative_time_sec", "value"]
        )
        writer.writeheader()
        writer.writerow({"relative_time_sec": 0, "value": 90})
        writer.writerow({"relative_time_sec": 2, "value": 90})


def _write_label(path: Path, depth=None, duplicate: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shape = {
        "label": "Power tower",
        "shape_type": "rectangle",
        "points": [[850, 300], [1050, 800]],
        "attributes": {"depth_m": depth},
    }
    path.write_text(
        json.dumps(
            {
                "imageWidth": 1920,
                "imageHeight": 1200,
                "shapes": [shape, dict(shape)] if duplicate else [shape],
            }
        ),
        encoding="utf-8",
    )


def test_forward_sync_recomputes_depth_from_each_aircraft_pose(tmp_path: Path):
    source_root = tmp_path / "annotations"
    depth_root = tmp_path / "depth"
    dataset_root = tmp_path / "dataset"
    relative_dir = (
        Path("4_30")
        / "capture"
        / "capture_part000"
        / "segment_000"
        / "images"
        / "camera"
    )
    source_files = [
        source_root / relative_dir / f"camera_{index:06d}_t{timestamp:.3f}.json"
        for index, timestamp in enumerate((0.0, 1.0, 2.0), start=1)
    ]
    for path in source_files:
        _write_label(path)
    _write_nav(dataset_root / "4_30" / "capture" / "capture_part000" / "segment_000")
    anchor = build_world_anchor(
        depth_m=1000.0,
        vehicle_lat=31.0,
        vehicle_lon=118.0,
        camera_heading_deg=0.0,
        bbox=(850, 300, 1050, 800),
        image_width=1920,
    )
    current_output = depth_root / source_files[0].relative_to(source_root)
    _write_label(current_output, depth=1000.0)

    result = forward_sync_depth(
        ForwardSyncRequest(
            source_path=source_files[0],
            output_path=current_output,
            source_root=source_root,
            depth_root=depth_root,
            dataset_root=dataset_root,
            shape_index=0,
            anchor=anchor,
            source_frame=source_files[0].stem,
        )
    )

    depths = []
    for source in source_files[1:]:
        data = json.loads(
            (depth_root / source.relative_to(source_root)).read_text(encoding="utf-8")
        )
        depths.append(data["shapes"][0]["attributes"]["depth_m"])
    assert result.updated_frames == 2
    assert depths[0] != depths[1]
    original = json.loads(current_output.read_text(encoding="utf-8"))
    assert original["shapes"][0]["attributes"]["depth_m"] == 1000.0


def test_forward_sync_updates_duplicate_depth_shapes(tmp_path: Path):
    source_root = tmp_path / "annotations"
    depth_root = tmp_path / "depth"
    dataset_root = tmp_path / "dataset"
    relative_dir = (
        Path("4_30") / "capture" / "capture_part000" / "segment_000"
        / "images" / "camera"
    )
    source = source_root / relative_dir / "camera_000001_t0.000.json"
    following = source_root / relative_dir / "camera_000002_t1.000.json"
    _write_label(source)
    _write_label(following)
    _write_nav(dataset_root / "4_30" / "capture" / "capture_part000" / "segment_000")
    duplicate_output = depth_root / following.relative_to(source_root)
    _write_label(duplicate_output, duplicate=True)
    anchor = build_world_anchor(
        depth_m=1000.0,
        vehicle_lat=31.0,
        vehicle_lon=118.0,
        camera_heading_deg=0.0,
        bbox=(850, 300, 1050, 800),
        image_width=1920,
    )

    forward_sync_depth(
        ForwardSyncRequest(
            source_path=source,
            output_path=depth_root / source.relative_to(source_root),
            source_root=source_root,
            depth_root=depth_root,
            dataset_root=dataset_root,
            shape_index=0,
            anchor=anchor,
            source_frame=source.stem,
        )
    )

    document = json.loads(duplicate_output.read_text(encoding="utf-8"))
    depths = [shape["attributes"]["depth_m"] for shape in document["shapes"]]
    assert depths[0] is not None
    assert depths[0] == depths[1]
