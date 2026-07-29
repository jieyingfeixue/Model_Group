import json

from src.io.adapters import lh_adapter
from src.io.sensor_profile import SensorProfile


def _write_label(path, timestamp):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "imageWidth": 1920,
        "imageHeight": 1200,
        "shapes": [{
            "label": "Power tower",
            "shape_type": "rectangle",
            "points": [[1, 2], [3, 4]],
        }],
        "imagePath": f"camera_t{timestamp:.3f}.jpg",
    }), encoding="utf-8")


def test_label_cache_uses_full_segment_path_for_repeated_segment_names(tmp_path):
    camera = "hikrobot_camera__DA8679037__image_raw"
    first = (
        tmp_path / "4_29" / "capture_a" / "part_a"
        / "segment_000_000000.000_000010.000" / "images" / camera
        / "camera_t000001.000.json"
    )
    second = (
        tmp_path / "4_29" / "capture_b" / "part_b"
        / "segment_000_000000.000_000010.000" / "images" / camera
        / "camera_t000002.000.json"
    )
    _write_label(first, 1.0)
    _write_label(second, 2.0)
    lh_adapter._LABELME_MULTI_CACHE.clear()

    cache = lh_adapter._get_labelme_cache(tmp_path)

    assert len(cache) == 2
    assert {
        entries[0][1].stem for entries in cache.values()
    } == {"camera_t000001.000", "camera_t000002.000"}


def test_list_sequences_requires_capture_bin_and_image_annotation(
    tmp_path, monkeypatch
):
    dataset = tmp_path / "dataset"
    annotations = tmp_path / "annotations"
    camera = "hikrobot_camera__DA8679037__image_raw"

    accepted = (
        dataset / "4_29" / "with_cameras_capture_good" / "part"
        / "segment_000_000000.000_000010.000"
    )
    no_bin = (
        dataset / "4_29" / "with_cameras_capture_no_bin" / "part"
        / "segment_000_000000.000_000010.000"
    )
    no_annotation = (
        dataset / "4_29" / "with_cameras_capture_no_annotation" / "part"
        / "segment_000_000000.000_000010.000"
    )
    for segment in (accepted, no_bin, no_annotation):
        segment.mkdir(parents=True)

    (accepted.parents[1] / "capture.bin").write_bytes(b"bin")
    (no_annotation.parents[1] / "capture.bin").write_bytes(b"bin")
    for segment in (accepted, no_bin):
        relative = segment.relative_to(dataset)
        _write_label(
            annotations / relative / "images" / camera
            / "camera_t000001.000.json",
            1.0,
        )

    monkeypatch.setattr(
        "src.core.config.load_config",
        lambda: {
            "annotations": {
                "labelme_root": str(annotations),
                "autofill_root": "",
            }
        },
    )
    lh_adapter._LABELME_SEGMENT_CACHE.clear()

    profile = object.__new__(SensorProfile)
    sequences = lh_adapter.list_sequences(dataset, profile)

    assert sequences == [accepted.relative_to(dataset).as_posix()]
