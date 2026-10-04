"""The portable Docker kit: the builder's rules and the kit's run files.

The real build-and-run of a kit is done separately (spec-docker-kit section 6); these
pin the rules that keep a kit safe and runnable.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_kit as K  # noqa: E402

TEMPLATE = (ROOT / "tools" / "kit" / "compose.yaml").read_text(encoding="utf-8")
KIT_COMPOSE = yaml.safe_load(K.render_compose(TEMPLATE, "2026.10.04-abc1234"))
APP = KIT_COMPOSE["services"]["app"]
PROJECT_COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
LAUNCHER = (ROOT / "docker-start.cmd").read_text(encoding="utf-8")


# ------------------------------------------------------------------ version


def test_version_is_date_and_commit():
    assert K.kit_version("6af9929", False, date(2026, 10, 4)) == "2026.10.04-6af9929"


def test_uncommitted_changes_are_marked():
    assert K.kit_version("6af9929", True, date(2026, 10, 4)) == "2026.10.04-6af9929-dirty"


# ------------------------------------------------------------ kit compose.yaml


def test_kit_never_builds_and_never_downloads():
    assert "build" not in APP
    assert APP["pull_policy"] == "never"
    assert APP["image"] == "qr-file-share:2026.10.04-abc1234"


def test_template_must_carry_the_version_placeholder():
    with pytest.raises(K.KitError):
        K.render_compose("image: qr-file-share:latest", "v1")


def test_kit_ports_are_on_this_laptop_only():
    for mapping in APP["ports"]:
        assert mapping.startswith("127.0.0.1:"), mapping
    assert "127.0.0.1:8766:8766" in APP["ports"]


def test_kit_and_project_share_one_data_volume():
    """Same project name and volume, so installing a newer kit keeps the QR codes."""
    assert KIT_COMPOSE["name"] == PROJECT_COMPOSE["name"] == "qr-file-share"
    assert APP["volumes"] == PROJECT_COMPOSE["services"]["app"]["volumes"] == ["qr-data:/data"]


def test_kit_matches_the_project_on_everything_that_matters():
    """The two compose files must not drift apart on security or behaviour."""
    proj = PROJECT_COMPOSE["services"]["app"]
    for key in ("ports", "environment", "secrets", "restart", "volumes"):
        assert APP[key] == proj[key], key
    assert "env_file" not in APP
    assert KIT_COMPOSE["secrets"] == PROJECT_COMPOSE["secrets"]


# ------------------------------------------------------------ build rules


@pytest.mark.parametrize("native,order", [("amd64", ["arm64", "amd64"]), ("arm64", ["amd64", "arm64"])])
def test_native_image_is_built_last(native, order):
    """The tag left on the build laptop must be one it can actually run."""
    assert K.build_order(native) == order


@pytest.mark.parametrize(
    "env,arch",
    [
        ({"PROCESSOR_ARCHITECTURE": "AMD64"}, "amd64"),
        ({"PROCESSOR_ARCHITECTURE": "ARM64"}, "arm64"),
        ({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"}, "amd64"),
    ],
)
def test_native_arch_detection(env, arch):
    assert K.native_arch(env) == arch


def test_unsupported_build_machine_is_refused():
    with pytest.raises(K.KitError):
        K.native_arch({"PROCESSOR_ARCHITECTURE": "x86"})


@pytest.mark.parametrize(
    "name", [".env", "client_secret.json", "client_secret_123.json", "file_qr.db",
             "file_qr.db-wal", "google-token.json", "service-account.json"],
)
def test_secret_files_are_caught(tmp_path, name):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / name).write_text("x")
    (tmp_path / "docker-start.cmd").write_text("x")
    assert [p.name for p in K.forbidden_files(tmp_path)] == [name]


def test_clean_kit_passes(tmp_path):
    for name in ("docker-start.cmd", "compose.yaml", ".env.example", "VERSION", "START-HERE.md"):
        (tmp_path / name).write_text("x")
    assert K.forbidden_files(tmp_path) == []


def test_env_example_is_not_mistaken_for_a_secret():
    assert not any(__import__("fnmatch").fnmatch(".env.example", p) for p in K.FORBIDDEN)


def test_architecture_is_read_from_inside_the_image_file(tmp_path):
    """The check that a saved file really holds the processor type it is named for."""
    tar = tmp_path / "img.tar"
    with tarfile.open(tar, "w") as tf:
        for name, data in [
            ("manifest.json", json.dumps([{"Config": "blobs/sha256/cfg"}]).encode()),
            ("blobs/sha256/cfg", json.dumps({"architecture": "arm64", "os": "linux"}).encode()),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    assert K.tar_architecture(tar) == "arm64"


def test_kit_carries_every_run_file():
    assert set(K.KIT_FILES) == {"docker-start.cmd", "docker-stop.cmd", ".env.example", "START-HERE.md"}
    for src in K.KIT_FILES.values():
        assert src.exists(), src


# ----------------------------------------------------------- the launcher


def test_launcher_builds_only_in_the_project_folder():
    i = LAUNCHER.index('if exist "Dockerfile" (')
    block = LAUNCHER[i:LAUNCHER.index(") else (", i)]
    assert "docker compose up -d --build" in block
    assert LAUNCHER.count("--build") == 1, "the kit path must never build"


def test_launcher_loads_the_image_for_this_laptops_processor():
    for needle in ("qr-file-share-image-%CPU%.tar", "docker load -i", "PROCESSOR_ARCHITECTURE",
                   "PROCESSOR_ARCHITEW6432", "set /p KIT_VERSION=<VERSION"):
        assert needle in LAUNCHER, needle


def test_launcher_skips_loading_when_that_version_is_already_loaded():
    assert "docker image inspect qr-file-share:%KIT_VERSION%" in LAUNCHER


def test_launcher_main_flow_cannot_fall_into_the_subroutine():
    """cmd.exe runs straight on into a label, so the main flow must exit first."""
    lines = LAUNCHER.splitlines()
    label = lines.index(":load_kit_image")  # the label line itself, not the `call`
    commands = [l.strip() for l in lines[:label]
                if l.strip() and not l.strip().upper().startswith("REM")]
    assert commands[-1].lower() == "exit /b 0"


def test_launcher_and_start_here_are_windows_files():
    for name in ("docker-start.cmd", "make-kit.cmd"):
        data = (ROOT / name).read_bytes()
        assert data.count(b"\r\n") == data.count(b"\n"), name


def test_start_here_names_the_files_the_kit_actually_contains():
    guide = (ROOT / "tools" / "kit" / "START-HERE.md").read_text(encoding="utf-8")
    for name in ("docker-start.cmd", "docker-stop.cmd", "client_secret.json"):
        assert name in guide


def test_dist_is_gitignored():
    assert "dist/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_a_single_processor_kit_can_be_built():
    """Used under time pressure: Intel/AMD only, without the slow emulated ARM build."""
    assert K.build_order("amd64", ("amd64",)) == ["amd64"]
    assert K.build_order("amd64", ("arm64",)) == ["arm64"]
