# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Speech models: where they live and the one explicit way to fetch them (`friday fetch-models`).

The running core never downloads anything. Models are downloaded only when YOU run `friday fetch-models`, into
`<data dir>/models`, and are loaded from there with network access disabled.

Download safety: HTTPS only, a size cap, a SHA-256 check when `voice.vosk_model_sha256` is set (the hash is always
printed so you can pin it), and a hardened unzip (no absolute paths, no `..`, no symlinks, capped total size) into a
temporary folder that is moved into place only when everything succeeded.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..core.config import Config
from ..core.errors import FridayError

MAX_ZIP_BYTES = 250_000_000
MAX_UNPACKED_BYTES = 800_000_000
MAX_ENTRIES = 5000
DOWNLOAD_DEADLINE_S = 900.0       # an overall limit, so a trickling server cannot hold the command forever


class ModelError(FridayError):
    pass


def models_dir(cfg: Config) -> Path:
    return cfg.data_dir / "models"


def vosk_model_path(cfg: Config) -> Path:
    if cfg.voice.wake_model:
        return Path(cfg.voice.wake_model).expanduser()
    name = Path(urlparse(cfg.voice.vosk_model_url).path).name.removesuffix(".zip") or "vosk-model-small-en-us-0.15"
    return models_dir(cfg) / name


def whisper_model_path(cfg: Config) -> Path:
    if cfg.voice.stt_model:
        return Path(cfg.voice.stt_model).expanduser()
    return models_dir(cfg) / f"faster-whisper-{cfg.voice.stt_model_size or 'small.en'}"


# --------------------------------------------------------------------------- safe unzip
def safe_extract(zf: zipfile.ZipFile, dest: Path, *, max_total: int = MAX_UNPACKED_BYTES, max_entries: int = MAX_ENTRIES) -> None:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ModelError("the archive has too many files")
    if sum(i.file_size for i in infos) > max_total:
        raise ModelError("the archive is too large when unpacked")
    root = dest.resolve()
    for info in infos:
        name = info.filename
        if not name or name.startswith(("/", "\\")) or ".." in Path(name.replace("\\", "/")).parts or ":" in name.split("/")[0]:
            raise ModelError(f"unsafe path in archive: {name!r}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise ModelError(f"the archive contains a symlink: {name!r}")
        target = (root / name).resolve()
        if root != target and root not in target.parents:
            raise ModelError(f"unsafe path in archive: {name!r}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)


# --------------------------------------------------------------------------- downloads
Opener = Callable[[urllib.request.Request, float], Any]


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Model hosts redirect to CDNs, which is fine, but never to plain http (or anything else)."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if urlparse(newurl).scheme != "https":
            raise urllib.error.URLError(f"refusing a redirect to a non-https address ({urlparse(newurl).scheme or 'none'})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(req: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(_HttpsOnlyRedirects)
    return opener.open(req, timeout=timeout)


def whisper_ready(path: Path) -> bool:
    """A faster-whisper model folder is usable only when its weights file is there (a half-finished download is not)."""
    return path.is_dir() and (path / "model.bin").is_file()


def _managed(cfg: Config, target: Path) -> bool:
    """True if `target` lives inside the folder `friday fetch-models` owns, so --force may replace it."""
    try:
        return models_dir(cfg).resolve() in target.resolve().parents
    except OSError:
        return False


def fetch_vosk(cfg: Config, out: Callable[[str], None] = print, *, opener: Opener = _open, force: bool = False) -> Path:
    url = cfg.voice.vosk_model_url
    if urlparse(url).scheme != "https":
        raise ModelError("voice.vosk_model_url must be an https:// URL")
    target = vosk_model_path(cfg)
    if target.is_dir() and any(target.iterdir()) and not force:
        out(f"Vosk model already present: {target}")
        return target
    if force and target.exists() and not _managed(cfg, target):
        raise ModelError(f"{target} is outside FRIDAY's models folder, so --force will not delete it. Remove it yourself first.")
    base = target.parent
    base.mkdir(parents=True, exist_ok=True)
    out(f"Downloading the Vosk wake-phrase model from {urlparse(url).netloc} (about 40 MB)...")
    digest = hashlib.sha256()
    fd, tmp_name = tempfile.mkstemp(prefix="vosk-", suffix=".zip", dir=base)
    os.close(fd)
    tmp_zip = Path(tmp_name)
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_S
    try:
        try:
            resp = opener(urllib.request.Request(url, headers={"User-Agent": "friday-assistant"}), 60.0)
            with resp, open(tmp_zip, "wb") as fh:
                size = 0
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_ZIP_BYTES:
                        raise ModelError("download is larger than expected; aborting")
                    if time.monotonic() > deadline:
                        raise ModelError("the download is taking too long; aborting")
                    digest.update(block)
                    fh.write(block)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ModelError(f"download failed: {getattr(exc, 'reason', exc)}") from exc
        got = digest.hexdigest()
        pin = cfg.voice.vosk_model_sha256.strip().lower()
        if pin and got != pin:
            raise ModelError(f"SHA-256 mismatch (expected {pin}, got {got}); the file was discarded")
        out(f"SHA-256 {got}" + ("  (matches your pin)" if pin else "  (not pinned: set voice.vosk_model_sha256 to this to pin it)"))
        stage = Path(tempfile.mkdtemp(prefix="vosk-unpack-", dir=base))
        try:
            try:
                with zipfile.ZipFile(tmp_zip) as zf:
                    safe_extract(zf, stage)
            except zipfile.BadZipFile as exc:
                raise ModelError(f"the download is not a valid zip file: {exc}") from exc
            entries = [p for p in stage.iterdir()]
            src = entries[0] if len(entries) == 1 and entries[0].is_dir() else stage
            if not (src / "am").is_dir() and not (src / "conf").is_dir():
                raise ModelError("the archive does not look like a Vosk model")
            if target.exists():
                shutil.rmtree(target)
            os.replace(src, target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    finally:
        tmp_zip.unlink(missing_ok=True)
    out(f"Vosk model ready: {target}")
    return target


def fetch_whisper(cfg: Config, out: Callable[[str], None] = print, *, downloader: Callable[..., Any] | None = None, force: bool = False) -> Path:
    target = whisper_model_path(cfg)
    if whisper_ready(target) and not force:
        out(f"Speech model already present: {target}")
        return target
    if target.exists() and (force or not whisper_ready(target)) and not _managed(cfg, target):
        raise ModelError(f"{target} is outside FRIDAY's models folder and is not a complete model; fix voice.stt_model or remove it yourself.")
    if downloader is None:
        try:
            from faster_whisper.utils import download_model as downloader
        except ImportError as exc:
            raise ModelError("the 'faster-whisper' package is not installed (pip install faster-whisper), so its model cannot be fetched") from exc
    size = cfg.voice.stt_model_size or "small.en"
    out(f"Downloading the faster-whisper '{size}' model from Hugging Face (about 250 MB)...")
    base = target.parent
    base.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="whisper-dl-", dir=base))
    try:
        try:
            downloader(size, output_dir=str(stage))
        except Exception as exc:  # noqa: BLE001 - network, disk, unknown size name...
            raise ModelError(f"download failed: {exc}") from exc
        if not whisper_ready(stage):
            raise ModelError("the download finished but model.bin is missing; nothing was installed")
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    out(f"Speech model ready: {target}")
    return target
