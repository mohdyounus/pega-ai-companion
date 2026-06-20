"""
jar_extractor.py
Extracts PEGA rule export JARs (.jar / .zip archives).

PEGA export JARs contain:
  - META-INF/contents.txt   → rule inventory manifest
  - META-INF/MANIFEST.MF    → artifact metadata
  - instances_NNNNN.bin     → Java-serialised rule data
  - Templates.bin           → template data
  - BaseTemplates.bin       → base template data
"""

from __future__ import annotations
import logging
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class JarExtractor:
    """
    Extracts a PEGA export JAR/ZIP and returns paths to the extracted contents.
    Safe to re-run — skips extraction if output already exists (unless force=True).
    """

    def __init__(self, export_dir: str, work_dir: str = "./pega_work"):
        self.export_dir = Path(export_dir)
        self.work_dir = Path(work_dir)

    def extract_all(self, force: bool = False) -> list[dict]:
        """
        Find all JARs in export_dir, extract each, return list of extraction results.

        Each result dict contains:
            jar_path      : original JAR path
            extract_dir   : where contents were extracted
            contents_txt  : path to META-INF/contents.txt
            bin_files     : list of .bin file paths
            manifest      : dict of MANIFEST.MF key-values
        """
        jar_files = (
            list(self.export_dir.glob("*.jar"))
            + list(self.export_dir.glob("*.zip"))
        )

        if not jar_files:
            raise FileNotFoundError(
                f"No .jar or .zip files found in {self.export_dir}. "
                "Export your PEGA rules via App Studio → Export and place them here."
            )

        results = []
        for jar_path in jar_files:
            result = self._extract_jar(jar_path, force=force)
            if result:
                results.append(result)
                logger.info(
                    f"Extracted {jar_path.name} → {len(result['bin_files'])} .bin file(s), "
                    f"contents.txt: {'found' if result['contents_txt'] else 'missing'}"
                )
        return results

    def extract_one(self, jar_path: str, force: bool = False) -> dict:
        return self._extract_jar(Path(jar_path), force=force)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_jar(self, jar_path: Path, force: bool = False) -> dict | None:
        extract_dir = self.work_dir / jar_path.stem

        if extract_dir.exists() and not force:
            logger.info(f"Already extracted: {jar_path.name}")
        else:
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)

            if not zipfile.is_zipfile(jar_path):
                logger.warning(f"Not a valid ZIP/JAR: {jar_path}")
                return None

            with zipfile.ZipFile(jar_path, "r") as zf:
                zf.extractall(extract_dir)

        contents_txt = extract_dir / "META-INF" / "contents.txt"
        bin_files = list(extract_dir.glob("*.bin"))
        manifest = self._parse_manifest(extract_dir / "META-INF" / "MANIFEST.MF")

        return {
            "jar_path": jar_path,
            "extract_dir": extract_dir,
            "contents_txt": contents_txt if contents_txt.exists() else None,
            "bin_files": bin_files,
            "manifest": manifest,
        }

    @staticmethod
    def _parse_manifest(manifest_path: Path) -> dict:
        if not manifest_path.exists():
            return {}
        result = {}
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
        return result
