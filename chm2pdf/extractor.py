"""CHM extraction backends: pychm (cross-platform) and hh.exe (Windows)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from .utils import LogFn


class ChmExtractor(ABC):
    """Base class for CHM extraction backends."""

    @abstractmethod
    def extract(self, chm_path: Path, output_dir: Path, log: LogFn) -> None:
        """Extract all files from *chm_path* into *output_dir*."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if this backend can be used on the current system."""


# ---------------------------------------------------------------------------
# pychm backend (cross-platform)
# ---------------------------------------------------------------------------

class PyChmExtractor(ChmExtractor):
    """Uses the ``chm`` Python package (wraps chmlib) for extraction."""

    def available(self) -> bool:
        try:
            import chm  # noqa: F401
            return True
        except ImportError:
            return False

    def extract(self, chm_path: Path, output_dir: Path, log: LogFn) -> None:
        import chm
        import chm.chm as chm_mod

        cfile = chm_mod.CHMFile()
        if not cfile.LoadCHM(str(chm_path)):
            raise RuntimeError(f"pychm could not open: {chm_path}")

        count = 0

        def _enumerator(chm_file, ui, context):
            nonlocal count
            path = ui.path
            if isinstance(path, bytes):
                path = path.decode("utf-8", errors="replace")
            # Skip internal metadata entries (start with /, ::, #, $)
            if not path or path.startswith("/#") or path.startswith("/$"):
                return chm_mod.CHM_ENUMERATOR_CONTINUE
            # Normalize to relative path
            rel = path.lstrip("/")
            if not rel or rel.endswith("/"):
                # Directory entry — ensure it exists
                (output_dir / rel).mkdir(parents=True, exist_ok=True)
                return chm_mod.CHM_ENUMERATOR_CONTINUE
            # File entry — extract
            dest = output_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                result, data = chm_file.ResolveObject(path)
                if result == chm_mod.CHM_RESOLVE_SUCCESS:
                    result2, content = chm_file.RetrieveObject(data)
                    if content:
                        dest.write_bytes(content)
                        count += 1
            except Exception:
                pass  # Skip unresolvable entries
            return chm_mod.CHM_ENUMERATOR_CONTINUE

        cfile.EnumerateDir("/", _enumerator)
        cfile.CloseCHM()

        if count == 0:
            raise RuntimeError(
                "pychm extraction produced no files. "
                "The CHM may be corrupted or empty."
            )
        log(f"Extracted {count} files via pychm.")


# ---------------------------------------------------------------------------
# hh.exe backend (Windows only)
# ---------------------------------------------------------------------------

COMMON_HH_LOCATIONS = [
    r"C:\Windows\hh.exe",
    r"C:\Windows\System32\hh.exe",
]


def _find_hh_exe(explicit_path: str = "") -> str:
    """Resolve hh.exe: explicit path → PATH → common locations."""
    if explicit_path and Path(explicit_path).is_file():
        return explicit_path
    found = shutil.which("hh.exe")
    if found:
        return found
    for p in COMMON_HH_LOCATIONS:
        if Path(p).exists():
            return p
    return ""


class HhExeExtractor(ChmExtractor):
    """Uses Windows ``hh.exe -decompile`` for extraction."""

    def __init__(self, hh_path: str = ""):
        self._hh_path = hh_path

    @property
    def hh_path(self) -> str:
        return _find_hh_exe(self._hh_path)

    def available(self) -> bool:
        return sys.platform == "win32" and bool(self.hh_path)

    def extract(self, chm_path: Path, output_dir: Path, log: LogFn) -> None:
        hh = self.hh_path
        if not hh:
            raise RuntimeError(
                "hh.exe not found. Install pychm for cross-platform support, "
                "or provide the path to hh.exe."
            )

        cmd = [hh, "-decompile", str(output_dir), str(chm_path)]
        log(f"Command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        # hh.exe often returns 1 even on success — check extracted file count
        if result.stdout.strip():
            log(result.stdout.strip())
        if result.stderr.strip():
            log(result.stderr.strip())

        extracted = [p for p in output_dir.rglob("*") if p.is_file()]
        if not extracted:
            raise RuntimeError(
                "hh.exe extraction produced no files. "
                "Check that the CHM file is readable and not corrupted."
            )
        if result.returncode not in (0, 1):
            log(f"Warning: hh.exe exited with code {result.returncode} "
                f"(extracted {len(extracted)} files anyway).")
        log(f"Extracted {len(extracted)} files via hh.exe.")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_extractor(hh_path: str = "") -> ChmExtractor:
    """Return the best available extractor: pychm first, then hh.exe."""
    pychm = PyChmExtractor()
    if pychm.available():
        return pychm
    hhexe = HhExeExtractor(hh_path)
    if hhexe.available():
        return hhexe
    raise RuntimeError(
        "No CHM extraction backend available. "
        "Install pychm (`pip install pychm`) for cross-platform support, "
        "or run on Windows where hh.exe is available."
    )
