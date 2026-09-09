from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

InstallerState = Literal["not_installed", "downloading", "ready", "failed"]


@dataclass(frozen=True)
class DownloadAsset:
    name: str
    url: str
    sha256: str
    size_bytes: int
    relative_path: str


@dataclass(frozen=True)
class ModelProfile:
    id: str
    label: str
    description: str
    recommended: bool
    min_memory_bytes: int
    min_free_disk_bytes: int
    llm: DownloadAsset


@dataclass(frozen=True)
class RuntimeSpec:
    backend: Literal["metal", "cuda", "cpu", "unsupported"]
    label: str
    assets: tuple[DownloadAsset, ...]


_GIB = 1024**3

OCR_ASSETS = (
    DownloadAsset(
        name="Surya OCR model",
        url=(
            "https://huggingface.co/datalab-to/surya-ocr-2-gguf/resolve/"
            "6a3a4c30e5e74446d4f8b6afd05b2f2da970f470/surya-2.gguf?download=true"
        ),
        sha256="1f18abe17b1ed8b4e47ee9b1ad0e274c93daf5efbb6b29a04ff1712e37051e05",
        size_bytes=1_266_400_864,
        relative_path="ocr/surya-2.gguf",
    ),
    DownloadAsset(
        name="Surya OCR vision projector",
        url=(
            "https://huggingface.co/datalab-to/surya-ocr-2-gguf/resolve/"
            "6a3a4c30e5e74446d4f8b6afd05b2f2da970f470/surya-2-mmproj.gguf?download=true"
        ),
        sha256="98c0563673b1657ff6d021d1e5f04af06cbf61bb40c63ac613e8bb71b42fb2c0",
        size_bytes=204_986_688,
        relative_path="ocr/surya-2-mmproj.gguf",
    ),
)

MODEL_PROFILES = (
    ModelProfile(
        id="qwen3-4b-q4-k-m",
        label="Лёгкая · Qwen3 4B",
        description="Базовый локальный профиль для первого запуска.",
        recommended=True,
        min_memory_bytes=8 * _GIB,
        min_free_disk_bytes=6 * _GIB,
        llm=DownloadAsset(
            name="Qwen3 4B Q4_K_M",
            url=(
                "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/"
                "bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf?download=true"
            ),
            sha256="7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
            size_bytes=2_497_280_256,
            relative_path="llm/qwen3-4b-q4-k-m/Qwen3-4B-Q4_K_M.gguf",
        ),
    ),
    ModelProfile(
        id="qwen3-8b-q4-k-m",
        label="Сбалансированная · Qwen3 8B",
        description="Больше запас качества, требует больше памяти.",
        recommended=False,
        min_memory_bytes=16 * _GIB,
        min_free_disk_bytes=10 * _GIB,
        llm=DownloadAsset(
            name="Qwen3 8B Q4_K_M",
            url=(
                "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/"
                "7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf?download=true"
            ),
            sha256="d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
            size_bytes=5_027_783_488,
            relative_path="llm/qwen3-8b-q4-k-m/Qwen3-8B-Q4_K_M.gguf",
        ),
    ),
    ModelProfile(
        id="qwen3-30b-a3b-q4-k-m",
        label="Тяжёлая · Qwen3 30B-A3B",
        description="Только для машин с большим запасом RAM или VRAM.",
        recommended=False,
        min_memory_bytes=32 * _GIB,
        min_free_disk_bytes=28 * _GIB,
        llm=DownloadAsset(
            name="Qwen3 30B-A3B Q4_K_M",
            url=(
                "https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF/resolve/"
                "e4d4bafdfb96a411a163846265362aceb0b9c63a/Qwen3-30B-A3B-Q4_K_M.gguf?download=true"
            ),
            sha256="0d003f6662faee786ed5da3e31b29c978de5ae5d275c8794c606a7f3c01aa8f5",
            size_bytes=18_556_685_824,
            relative_path="llm/qwen3-30b-a3b-q4-k-m/Qwen3-30B-A3B-Q4_K_M.gguf",
        ),
    ),
)


class ModelStore:
    """Owns verified local model files and one background installation at a time."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _default_data_dir()
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._state = self._read_state()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            profile_states = [self._profile_snapshot(profile) for profile in MODEL_PROFILES]
            selected_profile = self._state.get("selected_profile")
            runtime = self.runtime_spec()
            preflight = (
                self._preflight(selected_profile) if isinstance(selected_profile, str) else None
            )
            return {
                "profiles": profile_states,
                "selectedProfile": selected_profile,
                "ocrReady": self._assets_ready(OCR_ASSETS),
                "runtime": {
                    "backend": runtime.backend,
                    "label": runtime.label,
                    "state": self._runtime_state(runtime),
                },
                "preflight": preflight,
            }

    def start_install(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ModelStoreError("another_download_is_running")
            self._state["install"] = {
                "profile_id": profile.id,
                "state": "downloading",
                "current_asset": None,
                "downloaded_bytes": 0,
                "total_bytes": sum(asset.size_bytes for asset in self._install_assets(profile)),
                "error": None,
            }
            self._write_state()
            self._worker = threading.Thread(target=self._install, args=(profile,), daemon=True)
            self._worker.start()
        return self.snapshot()

    def select(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        if not self._assets_ready((profile.llm,)):
            raise ModelStoreError("model_is_not_installed")
        with self._lock:
            self._state["selected_profile"] = profile.id
            self._write_state()
        return self.snapshot()

    def model_path(self) -> Path:
        with self._lock:
            selected_profile = self._state.get("selected_profile")
            if not isinstance(selected_profile, str):
                raise ModelStoreError("no_model_selected")
            profile = self._profile(selected_profile)
            path = self.root / profile.llm.relative_path
            if not _matches_sha256(path, profile.llm.sha256):
                raise ModelStoreError("selected_model_is_not_verified")
            return path

    def ocr_paths(self) -> tuple[Path, Path]:
        with self._lock:
            paths = tuple(self.root / asset.relative_path for asset in OCR_ASSETS)
            if not self._assets_ready(OCR_ASSETS):
                raise ModelStoreError("ocr_is_not_verified")
            return paths[0], paths[1]

    def runtime_server(self) -> Path:
        return self.runtime_binary("llama-server")

    def runtime_binary(self, name: str) -> Path:
        with self._lock:
            spec = self.runtime_spec()
            if spec.backend == "unsupported":
                raise ModelStoreError("unsupported_platform")
            candidates = list((self.root / "runtime" / spec.backend).rglob(_runtime_filename(name)))
            if len(candidates) != 1:
                raise ModelStoreError("local_runtime_is_not_verified")
            return candidates[0]

    def runtime_spec(self) -> RuntimeSpec:
        system = platform.system()
        machine = platform.machine().lower()
        if system == "Darwin" and machine in {"arm64", "aarch64"}:
            return RuntimeSpec(
                backend="metal",
                label="Apple Metal",
                assets=(
                    DownloadAsset(
                        name="llama.cpp Metal runtime",
                        url=(
                            "https://github.com/ggml-org/llama.cpp/releases/download/b10809/"
                            "llama-b10809-bin-macos-arm64.tar.gz"
                        ),
                        sha256="7d692df9e1e386e62f1c12b843903218041e6cd74c9415aa39a7ed3176f9eaa2",
                        size_bytes=11_123_196,
                        relative_path="runtime/metal/llama-macos-arm64.tar.gz",
                    ),
                ),
            )
        if system == "Windows" and machine in {"amd64", "x86_64"}:
            if _nvidia_gpu_present():
                return RuntimeSpec(
                    backend="cuda",
                    label="NVIDIA CUDA",
                    assets=(
                        DownloadAsset(
                            name="llama.cpp CUDA runtime",
                            url=(
                                "https://github.com/ggml-org/llama.cpp/releases/download/b10809/"
                                "llama-b10809-bin-win-cuda-12.4-x64.zip"
                            ),
                            sha256="c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9",
                            size_bytes=253_938_543,
                            relative_path="runtime/cuda/llama-win-cuda.zip",
                        ),
                        DownloadAsset(
                            name="CUDA runtime libraries",
                            url=(
                                "https://github.com/ggml-org/llama.cpp/releases/download/b10809/"
                                "cudart-llama-bin-win-cuda-12.4-x64.zip"
                            ),
                            sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
                            size_bytes=391_443_627,
                            relative_path="runtime/cuda/cudart-win-cuda.zip",
                        ),
                    ),
                )
            return RuntimeSpec(
                backend="cpu",
                label="CPU",
                assets=(
                    DownloadAsset(
                        name="llama.cpp CPU runtime",
                        url=(
                            "https://github.com/ggml-org/llama.cpp/releases/download/b10809/"
                            "llama-b10809-bin-win-cpu-x64.zip"
                        ),
                        sha256="9df3158ed228a641a4b127942d7f459f24c9e13f04682659d05c00c80099b6b5",
                        size_bytes=18_407_457,
                        relative_path="runtime/cpu/llama-win-cpu.zip",
                    ),
                ),
            )
        return RuntimeSpec(backend="unsupported", label="Unsupported platform", assets=())

    def _profile_snapshot(self, profile: ModelProfile) -> dict[str, object]:
        install = self._state.get("install", {})
        is_current = isinstance(install, dict) and install.get("profile_id") == profile.id
        verified = self._assets_ready((profile.llm,))
        state: InstallerState
        if verified:
            state = "ready"
        elif is_current and install.get("state") == "downloading":
            state = "downloading"
        elif is_current and install.get("state") == "failed":
            state = "failed"
        else:
            state = "not_installed"
        return {
            "id": profile.id,
            "label": profile.label,
            "description": profile.description,
            "recommended": profile.recommended,
            "state": state,
            "downloadedBytes": int(install.get("downloaded_bytes", 0)) if is_current else 0,
            "totalBytes": int(install.get("total_bytes", profile.llm.size_bytes))
            if is_current
            else profile.llm.size_bytes,
            "currentAsset": install.get("current_asset") if is_current else None,
            "error": install.get("error") if is_current else None,
            "sizeBytes": profile.llm.size_bytes,
            "minMemoryBytes": profile.min_memory_bytes,
            "minFreeDiskBytes": profile.min_free_disk_bytes,
        }

    def _install(self, profile: ModelProfile) -> None:
        assets = self._install_assets(profile)
        try:
            for asset in assets:
                if self._asset_ready(asset):
                    self._advance(asset, asset.size_bytes)
                    continue
                self._download(asset)
                if asset.relative_path.endswith((".zip", ".tar.gz")):
                    self._extract_runtime_archive(asset)
            with self._lock:
                self._state["selected_profile"] = profile.id
                self._state["install"] = {
                    "profile_id": profile.id,
                    "state": "ready",
                    "current_asset": None,
                    "downloaded_bytes": sum(asset.size_bytes for asset in assets),
                    "total_bytes": sum(asset.size_bytes for asset in assets),
                    "error": None,
                }
                self._write_state()
        except Exception as error:
            with self._lock:
                self._state["install"] = {
                    "profile_id": profile.id,
                    "state": "failed",
                    "current_asset": None,
                    "downloaded_bytes": int(
                        self._state.get("install", {}).get("downloaded_bytes", 0)
                    ),
                    "total_bytes": sum(asset.size_bytes for asset in assets),
                    "error": str(error),
                }
                self._write_state()

    def _download(self, asset: DownloadAsset) -> None:
        destination = self.root / asset.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        hasher = hashlib.sha256()
        copied = 0
        request = urllib.request.Request(asset.url, headers={"User-Agent": "medical-deid/0.1"})
        try:
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                temporary.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    hasher.update(chunk)
                    copied += len(chunk)
                    self._advance(asset, copied)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise ModelStoreError(f"download_failed:{asset.name}") from error
        if copied != asset.size_bytes or hasher.hexdigest() != asset.sha256:
            temporary.unlink(missing_ok=True)
            raise ModelStoreError(f"checksum_failed:{asset.name}")
        temporary.replace(destination)
        self._mark_verified(asset)

    def _advance(self, asset: DownloadAsset, copied: int) -> None:
        with self._lock:
            install = self._state.get("install")
            if not isinstance(install, dict):
                return
            completed = sum(
                candidate.size_bytes
                for candidate in self._install_assets(self._profile(str(install["profile_id"])))
                if candidate != asset and self._asset_ready(candidate)
            )
            install["current_asset"] = asset.name
            install["downloaded_bytes"] = completed + copied
            self._write_state()

    def _extract_runtime_archive(self, asset: DownloadAsset) -> None:
        archive = self.root / asset.relative_path
        runtime_root = self.root / "runtime" / self.runtime_spec().backend
        runtime_root.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                _safe_extract_zip(bundle, runtime_root)
        else:
            with tarfile.open(archive) as bundle:
                _safe_extract_tar(bundle, runtime_root)
        server = next(runtime_root.rglob(_runtime_filename("llama-server")), None)
        cli = next(runtime_root.rglob(_runtime_filename("llama-cli")), None)
        if server is None or cli is None:
            raise ModelStoreError("runtime_archive_does_not_contain_server")
        if os.name != "nt":
            server.chmod(server.stat().st_mode | 0o111)
            cli.chmod(cli.stat().st_mode | 0o111)

    def _install_assets(self, profile: ModelProfile) -> tuple[DownloadAsset, ...]:
        return (*self.runtime_spec().assets, *OCR_ASSETS, profile.llm)

    def _assets_ready(self, assets: tuple[DownloadAsset, ...]) -> bool:
        with self._lock:
            return all(self._asset_ready(asset) for asset in assets)

    def _asset_ready(self, asset: DownloadAsset) -> bool:
        with self._lock:
            path = self.root / asset.relative_path
            verified = self._state.get("verified_assets", {})
            record = verified.get(asset.relative_path) if isinstance(verified, dict) else None
            try:
                stat = path.stat() if path.is_file() else None
            except OSError:
                return False
            if (
                isinstance(record, dict)
                and stat is not None
                and record.get("sha256") == asset.sha256
                and record.get("size") == stat.st_size
                and record.get("mtimeNs") == stat.st_mtime_ns
            ):
                return True
            if not _matches_sha256(path, asset.sha256):
                return False
            self._mark_verified(asset)
            return True

    def _mark_verified(self, asset: DownloadAsset) -> None:
        with self._lock:
            path = self.root / asset.relative_path
            stat = path.stat()
            verified = self._state.setdefault("verified_assets", {})
            if not isinstance(verified, dict):
                raise ModelStoreError("invalid_model_state")
            verified[asset.relative_path] = {
                "sha256": asset.sha256,
                "size": stat.st_size,
                "mtimeNs": stat.st_mtime_ns,
            }
            self._write_state()

    def _runtime_state(self, spec: RuntimeSpec) -> InstallerState:
        if spec.backend == "unsupported":
            return "failed"
        if not spec.assets:
            return "not_installed"
        if self._assets_ready(spec.assets):
            try:
                self.runtime_server()
            except ModelStoreError:
                return "failed"
            return "ready"
        return "not_installed"

    def _preflight(self, profile_id: str) -> dict[str, object]:
        profile = self._profile(profile_id)
        runtime = self.runtime_spec()
        blockers: list[str] = []
        memory = _total_memory_bytes()
        self.root.mkdir(parents=True, exist_ok=True)
        free_disk = shutil.disk_usage(self.root).free
        if runtime.backend == "unsupported":
            blockers.append("unsupported_platform")
        if memory < profile.min_memory_bytes:
            blockers.append("insufficient_memory")
        model_is_ready = self._assets_ready((profile.llm,))
        if not model_is_ready and free_disk < profile.min_free_disk_bytes:
            blockers.append("insufficient_disk")
        if not self._assets_ready(OCR_ASSETS):
            blockers.append("ocr_not_installed")
        if not model_is_ready:
            blockers.append("model_not_installed")
        if self._runtime_state(runtime) != "ready":
            blockers.append("runtime_not_installed")
        return {
            "ok": not blockers,
            "backend": runtime.backend,
            "memoryBytes": memory,
            "freeDiskBytes": free_disk,
            "blockers": blockers,
        }

    def _profile(self, profile_id: str) -> ModelProfile:
        for profile in MODEL_PROFILES:
            if profile.id == profile_id:
                return profile
        raise ModelStoreError(f"unknown_model_profile:{profile_id}")

    def _read_state(self) -> dict[str, object]:
        try:
            return json.loads((self.root / "model-state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / "model-state.json.part"
        temporary.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.root / "model-state.json")


class ModelStoreError(RuntimeError):
    pass


def _default_data_dir() -> Path:
    explicit = os.environ.get("MEDICAL_DEID_DATA_DIR")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MedicalDeid"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "MedicalDeid"
    return Path.home() / ".local" / "share" / "MedicalDeid"


def _total_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong)] + [
                (field, ctypes.c_ulonglong)
                for field in (
                    "total_phys",
                    "available_phys",
                    "total_page_file",
                    "available_page_file",
                    "total_virtual",
                    "available_virtual",
                    "available_extended_virtual",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.total_phys)
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError):
        return 0


def _matches_sha256(path: Path, expected: str) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest() == expected


def _nvidia_gpu_present() -> bool:
    try:
        return (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            ).returncode
            == 0
        )
    except OSError:
        return False


def _runtime_filename(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _safe_extract_zip(bundle: zipfile.ZipFile, destination: Path) -> None:
    for member in bundle.infolist():
        target = destination / member.filename
        if (
            destination not in target.resolve().parents
            and target.resolve() != destination.resolve()
        ):
            raise ModelStoreError("unsafe_runtime_archive")
    bundle.extractall(destination)


def _safe_extract_tar(bundle: tarfile.TarFile, destination: Path) -> None:
    for member in bundle.getmembers():
        target = destination / member.name
        if (
            destination not in target.resolve().parents
            and target.resolve() != destination.resolve()
        ):
            raise ModelStoreError("unsafe_runtime_archive")
    bundle.extractall(destination, filter="data")
