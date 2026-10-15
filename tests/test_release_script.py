""".github/scripts/release.py: тело релиза из CHANGELOG.md и latest.json."""
import importlib.util
import json
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core.updater import parse_update, platform_key

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release_script", ROOT / ".github" / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [1.2] - pending

### Добавлено
- новое

## [1.1] - 01.10.2026

### Исправлено
- старое
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_changelog_section_stops_at_next_version():
    assert release.changelog_section("1.2", CHANGELOG) == "### Добавлено\n- новое"
    assert release.changelog_section("1.1", CHANGELOG) == "### Исправлено\n- старое"
    assert release.changelog_section("1.3", CHANGELOG) == ""


def test_notes_require_section_for_tag(repo):
    with pytest.raises(SystemExit, match=r"\[1\.3\]"):
        release.main(["notes", "1.3", "notes.md"])
    release.main(["notes", "1.3", "notes.md", "--allow-missing"])
    assert (repo / "notes.md").read_text(encoding="utf-8").startswith("Тестовая сборка.")


def test_manifest_is_readable_by_app(repo):
    sums = repo / "sums"
    sums.mkdir()
    for suffix in ("windows-setup.exe", "windows-portable.zip", "macos.zip", "linux.AppImage"):
        name = f"LogDog-1.2-{suffix}"
        (sums / f"{name}.sha256").write_text(f"{'B' * 64}  {name}\n", encoding="utf-8")

    release.main(["manifest", "1.2", "v1.2", "TimBeket/LogDog", str(sums), "latest.json"])

    data = json.loads((repo / "latest.json").read_text(encoding="utf-8"))
    assert set(data["installers"]) == {"windows_setup", "windows", "macos", "linux"}
    assert data["installers"]["windows"]["file"] == "LogDog-1.2-windows-portable.zip"
    assert data["installers"]["windows_setup"]["file"] == "LogDog-1.2-windows-setup.exe"
    info = parse_update(data, "1.1")
    assert info.changelog == "### Добавлено\n- новое"
    assert info.page_url == "https://github.com/TimBeket/LogDog/releases/tag/v1.2"
    assert info.asset.sha256 == "b" * 64
    assert info.asset.url == f"https://github.com/TimBeket/LogDog/releases/download/v1.2/{info.asset.file}"
    assert info.asset.file.startswith("LogDog-1.2-" + platform_key())


def test_manifest_fails_when_platform_missing(repo):
    sums = repo / "sums"
    sums.mkdir()
    (sums / "LogDog-1.2-windows-portable.zip.sha256").write_text(f"{'b' * 64}  LogDog-1.2-windows-portable.zip\n")
    with pytest.raises(SystemExit, match="macos"):
        release.main(["manifest", "1.2", "v1.2", "TimBeket/LogDog", str(sums), "latest.json"])


def test_lock_matches_requirements():
    """CI ставит только из requirements-lock.txt: зависимость, добавленная в
    requirements*.txt без перегенерации lock, в сборку не попадёт (а iOS-часть
    при отсутствии pymobiledevice3 молча отключается, а не падает)."""
    pinned = {}
    for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9._-]+)==(\S+)", line)
        if m:
            pinned[canonicalize_name(m[1])] = m[2]
    for name in ("requirements.txt", "requirements-test.txt", "requirements-build.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            req = Requirement(line)
            version = pinned.get(canonicalize_name(req.name))
            assert version is not None, f"{req.name} из {name} нет в requirements-lock.txt"
            assert req.specifier.contains(version, prereleases=True), (
                f"{req.name}=={version} в requirements-lock.txt не подходит под «{line}» из {name}")
