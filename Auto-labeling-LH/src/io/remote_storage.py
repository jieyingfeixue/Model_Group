"""SFTP-backed dataset storage with explicit local caching."""

from __future__ import annotations

import posixpath
import stat
import os
import csv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator

from src.core.paths import writable_root


@dataclass(frozen=True)
class RemoteEntry:
    path: str
    size: int
    mtime: int
    is_dir: bool


@dataclass(frozen=True)
class UploadResult:
    uploaded_files: int
    skipped_files: int
    failed_files: int
    uploaded_bytes: int


class RemoteDatasetStore:
    """Connect to the NAS and synchronize files to a local cache."""

    def __init__(self, config: dict):
        self.host = str(config.get("host", ""))
        self.port = int(config.get("port", 22))
        self.username = str(config.get("username", ""))
        self.password = str(config.get("password", ""))
        self.remote_root = self._normalize_remote(
            str(config.get("root", "/homes/LH_Dataset"))
        )
        configured_cache = Path(
            str(config.get("cache_root", "./temp/remote_dataset_cache"))
        )
        self.cache_root = (
            configured_cache
            if configured_cache.is_absolute()
            else writable_root() / configured_cache
        ).resolve()
        self._ssh = None
        self._sftp = None

    @classmethod
    def from_app_config(cls, config: dict) -> "RemoteDatasetStore | None":
        remote = config.get("remote_storage", {}) or {}
        return cls(remote) if remote.get("enabled", False) else None

    def __enter__(self) -> "RemoteDatasetStore":
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    @staticmethod
    def _normalize_remote(path: str) -> str:
        value = "/" + str(PurePosixPath(path)).lstrip("/")
        return posixpath.normpath(value)

    def connect(self) -> None:
        if self._sftp is not None:
            return
        if not all((self.host, self.username, self.password)):
            raise ValueError("remote SFTP host, username, and password are required")
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )
        self._ssh = ssh
        self._sftp = ssh.open_sftp()

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._ssh is not None:
            self._ssh.close()
            self._ssh = None

    def test_connection(self) -> list[str]:
        self.connect()
        return sorted(self._sftp.listdir(self.remote_root))

    def remote_path(self, relative: str | Path) -> str:
        value = str(relative).replace("\\", "/").lstrip("/")
        return posixpath.join(self.remote_root, value)

    def local_path(self, relative: str | Path) -> Path:
        return self.cache_root / Path(str(relative))

    def listdir(self, relative: str | Path) -> list[str]:
        self.connect()
        return sorted(self._sftp.listdir(self.remote_path(relative)))

    def pull_file(self, relative: str | Path) -> Path:
        self.connect()
        remote = self.remote_path(relative)
        local = self.local_path(relative)
        remote_stat = self._sftp.stat(remote)
        if local.exists() and local.stat().st_size == int(remote_stat.st_size):
            return local
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_suffix(local.suffix + ".download")
        self._sftp.get(remote, str(temporary))
        temporary.replace(local)
        return local

    def prepare_lh_index(self) -> dict[str, Path]:
        """Cache annotation JSON and create a lightweight sensor directory tree."""
        allowed = {".json"}
        for directory in (
            "LH_data_all_sensor_annotations",
            "LH_data_all_sensor_annotations_autofill",
            "LH_data_all_sensor_annotations_depth",
        ):
            self.pull_tree(
                directory,
                include=lambda entry: Path(entry.path).suffix.lower() in allowed,
            )

        sensor_root = self.local_path("LH_data_all_sensor")
        annotation_roots = (
            self.local_path("LH_data_all_sensor_annotations"),
            self.local_path("LH_data_all_sensor_annotations_autofill"),
        )
        for annotation_root in annotation_roots:
            if not annotation_root.exists():
                continue
            for json_path in annotation_root.rglob("*.json"):
                relative = json_path.relative_to(annotation_root)
                parts = relative.parts
                segment_index = next(
                    (
                        index
                        for index, part in enumerate(parts)
                        if part.startswith("segment_")
                    ),
                    None,
                )
                if segment_index is None:
                    continue
                sensor_root.joinpath(*parts[: segment_index + 1]).mkdir(
                    parents=True, exist_ok=True
                )
                capture_dir = sensor_root.joinpath(*parts[:2])
                capture_dir.mkdir(parents=True, exist_ok=True)
                (capture_dir / ".remote_bin_available").touch(exist_ok=True)
        return {
            "dataset_root": sensor_root,
            "labelme_root": annotation_roots[0],
            "autofill_root": annotation_roots[1],
            "depth_root": self.local_path(
                "LH_data_all_sensor_annotations_depth"
            ),
        }

    def prepare_lh_frame(self, seq_id: str, frame_id: str) -> None:
        """Download one frame's image, navigation, match CSV, and matched MAT."""
        self.prepare_lh_image(seq_id, frame_id)

        sensor_base = PurePosixPath("LH_data_all_sensor")
        seq = PurePosixPath(str(seq_id).replace("\\", "/"))
        segment_relative = sensor_base / seq
        self._prepare_lh_frame_metadata(segment_relative, seq, frame_id)

    def prepare_lh_image(self, seq_id: str, frame_id: str) -> None:
        """Download only camera images needed by a browser thumbnail."""
        sensor_base = PurePosixPath("LH_data_all_sensor")
        seq = PurePosixPath(str(seq_id).replace("\\", "/"))
        segment_relative = sensor_base / seq
        camera_dirs = (
            "hikrobot_camera__DA8679037__image_raw",
            "hikrobot_camera__DA8679038__image_raw",
        )
        for camera_dir in camera_dirs:
            relative = (
                segment_relative / "images" / camera_dir / f"{frame_id}.jpg"
            )
            try:
                self.pull_file(relative)
            except OSError:
                continue

    def _prepare_lh_frame_metadata(
        self,
        segment_relative: PurePosixPath,
        seq: PurePosixPath,
        frame_id: str,
    ) -> None:
        metadata_files = (
            "gps/nav100__fix/nav100__fix.csv",
            "heading/nav100__heading/nav100__heading.csv",
            "nav100_state/nav100__state/nav100__state.csv",
            "radar_camera_match_ts.csv",
        )
        for filename in metadata_files:
            try:
                self.pull_file(segment_relative / PurePosixPath(filename))
            except OSError:
                continue

        parts = seq.parts
        if len(parts) < 2:
            return
        capture_relative = sensor_base / parts[0] / parts[1]
        for filename in (
            "target_depth_db.json",
            "match_mat_camera.csv",
            "radar_camera_match.json",
        ):
            try:
                self.pull_file(capture_relative / filename)
            except OSError:
                continue

        match_csv = self.local_path(
            segment_relative / "radar_camera_match_ts.csv"
        )
        if not match_csv.exists():
            return
        matched_mat = None
        frame_time = _filename_time(frame_id)
        try:
            with match_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            candidates = []
            for row in rows:
                mat_name = str(row.get("mat_filename", "")).strip()
                raw_time = str(row.get("camera_rel_time_sec", "")).strip()
                if not mat_name or not raw_time:
                    continue
                candidates.append((abs(float(raw_time) - frame_time), mat_name))
            if candidates:
                matched_mat = min(candidates)[1]
        except (OSError, ValueError):
            return
        if not matched_mat:
            return
        try:
            capture_children = self.listdir(capture_relative)
        except OSError:
            return
        radar_dir = next(
            (
                name for name in capture_children
                if name.endswith("_radar") or name == "mmwave_mat_1218style"
            ),
            None,
        )
        if radar_dir:
            try:
                self.pull_file(capture_relative / radar_dir / matched_mat)
            except OSError:
                pass

    def iter_tree(self, relative: str | Path = "") -> Iterator[RemoteEntry]:
        self.connect()
        stack = [self.remote_path(relative)]
        while stack:
            directory = stack.pop()
            for row in self._sftp.listdir_attr(directory):
                path = posixpath.join(directory, row.filename)
                is_dir = stat.S_ISDIR(row.st_mode)
                yield RemoteEntry(
                    path, int(row.st_size), int(row.st_mtime), is_dir
                )
                if is_dir:
                    stack.append(path)

    def pull_tree(
        self,
        relative: str | Path,
        *,
        include: Callable[[RemoteEntry], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        files = 0
        byte_count = 0
        for entry in self.iter_tree(relative):
            rel = posixpath.relpath(entry.path, self.remote_root)
            local = self.local_path(rel)
            if entry.is_dir:
                local.mkdir(parents=True, exist_ok=True)
                continue
            if include is not None and not include(entry):
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            if (
                local.exists()
                and local.stat().st_size == entry.size
                and int(local.stat().st_mtime) >= entry.mtime
            ):
                continue
            if progress is not None:
                progress(rel)
            temp = local.with_suffix(local.suffix + ".download")
            self._sftp.get(entry.path, str(temp))
            temp.replace(local)
            files += 1
            byte_count += entry.size
        return files, byte_count

    def push_file(
        self,
        local_path: Path,
        relative: str | Path,
        *,
        skip_same_size: bool = True,
    ) -> bool:
        self.connect()
        remote = self.remote_path(relative)
        self._mkdir_remote(posixpath.dirname(remote))
        if skip_same_size:
            try:
                if int(self._sftp.stat(remote).st_size) == local_path.stat().st_size:
                    return False
            except OSError:
                pass
        temporary = remote + ".upload"
        self._sftp.put(str(local_path), temporary)
        try:
            self._sftp.remove(remote)
        except OSError:
            pass
        self._sftp.rename(temporary, remote)
        return True

    def push_tree(
        self,
        local_root: Path,
        remote_relative: str | Path,
        *,
        dry_run: bool = False,
        retries: int = 3,
        progress: Callable[[str, str, int], None] | None = None,
    ) -> UploadResult:
        local_root = Path(local_root)
        if not local_root.is_dir():
            raise FileNotFoundError(f"local upload directory not found: {local_root}")
        uploaded = skipped = failed = uploaded_bytes = 0
        local_files = []
        inaccessible = []

        def _on_walk_error(error: OSError) -> None:
            inaccessible.append(str(error))

        for directory, _subdirs, filenames in os.walk(
            local_root, onerror=_on_walk_error
        ):
            for filename in filenames:
                local_files.append(Path(directory) / filename)
        for message in inaccessible:
            failed += 1
            if progress is not None:
                progress("inaccessible", message, 0)

        for local_path in sorted(local_files):
            relative = local_path.relative_to(local_root)
            remote_file = (
                PurePosixPath(str(remote_relative).replace("\\", "/"))
                / PurePosixPath(relative.as_posix())
            )
            remote_path = self.remote_path(remote_file)
            size = local_path.stat().st_size
            try:
                same_size = int(self._sftp.stat(remote_path).st_size) == size
            except OSError:
                same_size = False
            if same_size:
                skipped += 1
                if progress is not None:
                    progress("skip", relative.as_posix(), size)
                continue
            if dry_run:
                uploaded += 1
                uploaded_bytes += size
                if progress is not None:
                    progress("would-upload", relative.as_posix(), size)
                continue
            error = None
            for attempt in range(max(1, retries)):
                try:
                    self.push_file(
                        local_path, remote_file, skip_same_size=False
                    )
                    error = None
                    break
                except Exception as exc:
                    error = exc
                    self.close()
                    if attempt + 1 < max(1, retries):
                        self.connect()
            if error is not None:
                failed += 1
                if progress is not None:
                    progress("failed", relative.as_posix(), size)
                continue
            uploaded += 1
            uploaded_bytes += size
            if progress is not None:
                progress("upload", relative.as_posix(), size)
        return UploadResult(uploaded, skipped, failed, uploaded_bytes)

    def _mkdir_remote(self, directory: str) -> None:
        current = "/"
        for part in PurePosixPath(directory).parts:
            if part == "/":
                continue
            current = posixpath.join(current, part)
            try:
                self._sftp.stat(current)
            except OSError:
                self._sftp.mkdir(current)


def _filename_time(name: str) -> float:
    marker = name.rsplit("_t", 1)
    return float(marker[-1]) if len(marker) == 2 else 0.0
