from __future__ import annotations

import io
import runpy
import tarfile
import zipfile
from pathlib import Path

import pytest

validate_release = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "validate_release.py")
)["validate_release"]


def _release(tmp_path, *, wheel_version="0.2.0", sdist_name="gridforge-spatial"):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "gridforge-spatial"\nversion = "0.2.0"\n')
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "gridforge_spatial-0.2.0-py3-none-any.whl", "w") as archive:
        archive.writestr(
            "gridforge_spatial-0.2.0.dist-info/METADATA",
            f"Name: gridforge-spatial\nVersion: {wheel_version}\n",
        )
    metadata = f"Name: {sdist_name}\nVersion: 0.2.0\n".encode()
    with tarfile.open(dist / "gridforge_spatial-0.2.0.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("gridforge_spatial-0.2.0/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    return project, dist


def test_accepts_future_release_version(tmp_path):
    project, dist = _release(tmp_path)
    validate_release("v0.2.0", project, dist)


@pytest.mark.parametrize("tag", ["v0.1.0", "refs/tags/v0.2.0", "v0.2.0;echo unsafe"])
def test_rejects_wrong_selected_tag(tmp_path, tag):
    project, dist = _release(tmp_path)
    with pytest.raises(ValueError):
        validate_release(tag, project, dist)


def test_rejects_renamed_wheel_with_stale_metadata(tmp_path):
    project, dist = _release(tmp_path, wheel_version="0.1.0")
    with pytest.raises(ValueError, match="embedded distribution version"):
        validate_release("v0.2.0", project, dist)


def test_rejects_foreign_sdist_with_matching_filename(tmp_path):
    project, dist = _release(tmp_path, sdist_name="other-project")
    with pytest.raises(ValueError, match="embedded distribution name"):
        validate_release("v0.2.0", project, dist)


def test_rejects_extra_artifacts(tmp_path):
    project, dist = _release(tmp_path)
    (dist / "other.whl").touch()
    with pytest.raises(ValueError, match="exactly one wheel"):
        validate_release("v0.2.0", project, dist)
