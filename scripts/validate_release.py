"""Validate prebuilt release identities without importing the package."""

from __future__ import annotations

import argparse
import re
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path


def validate_release(tag: str, project_file: Path, distributions: Path) -> None:
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None:
        raise ValueError("expected release tag in vX.Y.Z form")
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    version = tag[1:]
    if project["name"] != "gridforge-spatial" or project["version"] != version:
        raise ValueError("selected release tag does not match project identity/version")
    wheels = list(distributions.glob("*.whl"))
    sdists = list(distributions.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1 or len(list(distributions.iterdir())) != 2:
        raise ValueError("expected exactly one wheel and one source distribution")
    if not wheels[0].name.startswith(f"gridforge_spatial-{version}-"):
        raise ValueError("wheel filename does not match selected version")
    if sdists[0].name != f"gridforge_spatial-{version}.tar.gz":
        raise ValueError("source distribution filename does not match selected version")

    with zipfile.ZipFile(wheels[0]) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("expected exactly one wheel METADATA")
        wheel_metadata = archive.read(metadata_paths[0])
    with tarfile.open(sdists[0], "r:gz") as archive:
        metadata_paths = [
            member
            for member in archive.getmembers()
            if member.name == f"gridforge_spatial-{version}/PKG-INFO" and member.isfile()
        ]
        if len(metadata_paths) != 1:
            raise ValueError("expected source distribution root PKG-INFO")
        stream = archive.extractfile(metadata_paths[0])
        if stream is None:
            raise ValueError("source distribution PKG-INFO is unreadable")
        sdist_metadata = stream.read()
    for metadata in (wheel_metadata, sdist_metadata):
        message = BytesParser().parsebytes(metadata)
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
        if len(names) != 1 or re.sub(r"[-_.]+", "-", names[0]).lower() != project["name"]:
            raise ValueError("embedded distribution name does not match project")
        if versions != [version]:
            raise ValueError("embedded distribution version does not match selected tag")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    validate_release(args.tag, args.project, args.dist)
    print(f"Validated embedded wheel/sdist metadata for {args.tag}")
