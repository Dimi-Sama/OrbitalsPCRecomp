# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs (AGPL v3, see NOTICE.txt).
"""Zstandard for NUP, using the Python 3.14 API and its backport."""

import hashlib
import importlib
import io
import sys
import sysconfig
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.8.0"
LINUX_TAG = "manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64"
PYPI = "https://files.pythonhosted.org/packages/"
# Published wheel paths and SHA-256 digests, pinned to backports.zstd 1.8.0 on PyPI.
WHEELS = {
    ("cp312", "win-amd64"): ("win_amd64", "a5/78/2f497fd2bbf46099e46650f75467967d21f25bb921c894d28d493bbfb7e4",
                             "1eddf59fedaf19dd3a8e9c597add7eb6f0d51d4467a0924b2dcd2c118ed18ff5"),
    ("cp313", "win-amd64"): ("win_amd64", "12/0e/5c5a916cea73b455850083ccf76078de655face3dfe4126848570c57a6dd",
                             "b583990d554cc6f6141c5c43b6db3c7da87a214253e08339d917ee3baa3021b6"),
    ("cp312", "linux-x86_64"): (LINUX_TAG, "3f/08/a9d59fb9e20215ede0c8ea4d729373dc0592aee45776cdd86c92c3c6242c",
                                "f9e9aa28a44db1897fb637f037175566f3b75890d4bae6cae7ba34f1df1e0804"),
    ("cp313", "linux-x86_64"): (LINUX_TAG, "5d/6d/3c422b33d40aaca6e9d9fdd47f1a047ac499de749c887ab3dab62f731fb2",
                                "44a9004f9e809ea56910d326d21946650369db59eb86edc0c76840f21530704c"),
}
MAX_WHEEL = 1 << 20


class CodecError(ValueError):
    """The Zstandard decoder could not be installed or loaded."""


def install_wheel(cache, tag, platform):
    wheel = WHEELS.get((tag, platform))
    if wheel is None:
        raise CodecError("Compressed NUP archives need CPython 3.12–3.13 x64 or Python 3.14+ with Zstandard.")
    wheel_platform, directory, digest = wheel
    name = f"backports_zstd-{VERSION}-{tag}-{tag}-{wheel_platform}"
    target = cache / name
    if target.is_dir():
        return target
    try:
        with urllib.request.urlopen(f"{PYPI}{directory}/{name}.whl", timeout=30) as response:
            data = response.read(MAX_WHEEL + 1)
    except OSError as error:
        raise CodecError("Could not download the Zstandard decoder. Check your connection and retry.") from error
    if len(data) > MAX_WHEEL or hashlib.sha256(data).hexdigest() != digest:
        raise CodecError("The Zstandard decoder download failed its SHA-256 check.")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zstd-", dir=cache) as work:
        stage = Path(work) / "wheel"
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(stage)
        try:
            stage.rename(target)
        except OSError:
            if not target.is_dir():
                raise
    return target


def load_zstd(cache, on_download):
    try:
        from compression import zstd
    except ImportError:
        if sys.implementation.name != "cpython" or sysconfig.get_config_var("Py_GIL_DISABLED"):
            raise CodecError("Use Python 3.14+ with Zstandard to open compressed NUP archives.") from None
        tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
        on_download()
        target = install_wheel(cache, tag, sysconfig.get_platform())
        sys.path.insert(0, str(target))
        try:
            importlib.invalidate_caches()
            zstd = importlib.import_module("backports.zstd")
        except ImportError as error:
            raise CodecError("Could not load the Zstandard decoder. Use Python 3.14+ with Zstandard.") from error
        finally:
            sys.path.remove(str(target))
    return zstd
