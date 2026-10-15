"""Локальная сборка LogDog (PyInstaller, по LogDog.spec) — результат в dist/.

Релизные сборки делает GitHub Actions (.github/workflows/release.yml),
локально собирать нужно только для проверки самой сборки.
"""
import subprocess
import sys

from core.version import VERSION


def main():
    print(f"Building LogDog {VERSION} with PyInstaller...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", "dist", "LogDog.spec"]
    print("Running command:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("Build finished successfully! Check /dist directory.")


if __name__ == "__main__":
    main()
