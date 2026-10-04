"""Build the portable Docker kit: one zip that runs the app on another laptop.

Run through make-kit.cmd on the development laptop. See
docs/planning/spec-docker-kit.md.

    1. run the test suite; stop if anything fails
    2. build the image once per processor type (arm64 and amd64), tagged with a version
    3. save each image to qr-file-share-image-<cpu>.tar
    4. add the run files (docker-start.cmd, docker-stop.cmd, compose.yaml, ...)
    5. refuse to finish if any secret is in the kit or the image
    6. zip it into dist/qr-file-share-kit-<version>.zip

The kit contains no secrets. client_secret.json and .env never go in it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT_SRC = ROOT / "tools" / "kit"
DIST = ROOT / "dist"
KIT_NAME = "qr-file-share-kit"
IMAGE = "qr-file-share"
ARCHES = ("amd64", "arm64")

# Run files copied into the kit as they are.
KIT_FILES = {
    "docker-start.cmd": ROOT / "docker-start.cmd",
    "docker-stop.cmd": ROOT / "docker-stop.cmd",
    ".env.example": ROOT / ".env.example",
    "START-HERE.md": KIT_SRC / "START-HERE.md",
}

# Anything matching these must never be in the kit or the image.
FORBIDDEN = (".env", "client_secret*.json", "service-account*.json",
             "*.db", "*.db-wal", "*.db-shm", "google-token.json")


class KitError(RuntimeError):
    pass


# ---------------------------------------------------------------- pure helpers


def kit_version(git_sha: str, dirty: bool, today: date) -> str:
    """'2026.10.04-6af9929', or '...-dirty' when made from uncommitted changes."""
    v = f"{today:%Y.%m.%d}-{git_sha}"
    return v + "-dirty" if dirty else v


def render_compose(template: str, version: str) -> str:
    if "{{VERSION}}" not in template:
        raise KitError("tools/kit/compose.yaml has no {{VERSION}} placeholder")
    return template.replace("{{VERSION}}", version)


def build_order(native: str, arches: tuple[str, ...] = ARCHES) -> list[str]:
    """Non-native first, native last -- so the tag left on this laptop is one it can run."""
    others = [a for a in arches if a != native]
    return others + ([native] if native in arches else [])


def native_arch(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    raw = (env.get("PROCESSOR_ARCHITEW6432") or env.get("PROCESSOR_ARCHITECTURE") or "").upper()
    mapping = {"AMD64": "amd64", "ARM64": "arm64"}
    if raw not in mapping:
        raise KitError(f"unsupported build machine processor: {raw or 'unknown'}")
    return mapping[raw]


def forbidden_files(folder: Path) -> list[Path]:
    hits = []
    for p in folder.rglob("*"):
        if p.is_file() and any(fnmatch.fnmatch(p.name, pat) for pat in FORBIDDEN):
            hits.append(p)
    return hits


def tar_architecture(tar_path: Path) -> str:
    """Read the CPU type recorded inside a `docker save` file."""
    with tarfile.open(tar_path) as tf:
        manifest = json.load(tf.extractfile("manifest.json"))
        config = json.load(tf.extractfile(manifest[0]["Config"]))
    return config["architecture"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ the steps


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def out(cmd: list[str]) -> str:
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def step(n: int, total: int, text: str) -> None:
    print(f"\n[{n}/{total}] {text}", flush=True)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Build the portable Docker kit.")
    parser.add_argument("--arch", choices=ARCHES, action="append",
                        help="build only this processor type (repeatable); default: all")
    parser.add_argument("--reuse-image", metavar="TAG",
                        help="package this already-built local image instead of building "
                             "(no internet needed); only with a single --arch")
    args = parser.parse_args(argv)
    arches = tuple(args.arch or ARCHES)
    if args.reuse_image and len(arches) != 1:
        parser.error("--reuse-image needs exactly one --arch")
    total = 5
    try:
        out(["docker", "info", "--format", "{{.ServerVersion}}"])
    except (OSError, subprocess.CalledProcessError):
        print("Docker Desktop is not running. Start it, wait for 'Engine running', try again.")
        return 1

    step(1, total, "Running the test suite -- a kit is never made from failing code")
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-o", "addopts="],
                           cwd=ROOT)
    if tests.returncode != 0:
        print("\nTests failed. No kit was made.")
        return 1

    sha = out(["git", "rev-parse", "--short", "HEAD"])
    dirty = bool(out(["git", "status", "--porcelain"]))
    version = kit_version(sha, dirty, date.today())
    tag = f"{IMAGE}:{version}"
    native = native_arch()
    print(f"\n  Kit version: {version}")
    if dirty:
        print("  NOTE: made from uncommitted changes -- commit first for a kit you can trace.")

    staging = DIST / KIT_NAME
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    step(2, total, "Building and saving the app for each processor type (ARM is emulated -- a few minutes)")
    print(f"  Processor types: {', '.join(arches)}")
    for arch in build_order(native, arches):
        print(f"\n  -- {arch} --", flush=True)
        # Plain single-platform images (no attestations), so `docker load` works on any
        # Docker Desktop, whichever image store it uses.
        if args.reuse_image:
            # Packaging an image already built from this code (e.g. when Docker Hub is
            # unreachable). The architecture check below still applies.
            run(["docker", "tag", args.reuse_image, tag])
        else:
            run(["docker", "buildx", "build", "--platform", f"linux/{arch}",
                 "--provenance=false", "--sbom=false", "--load", "-t", tag, "."])
        got = out(["docker", "image", "inspect", "-f", "{{.Architecture}}", tag])
        if got != arch:
            raise KitError(f"built {got}, expected {arch}")

        print(f"  saving {arch} image", flush=True)
        tar = staging / f"qr-file-share-image-{arch}.tar"
        run(["docker", "save", "-o", str(tar), tag])
        if tar_architecture(tar) != arch:
            raise KitError(f"{tar.name} does not contain an {arch} image")
        if arch != native:
            run(["docker", "rmi", tag], stdout=subprocess.DEVNULL)

    step(3, total, "Adding the run files")
    for name, src in KIT_FILES.items():
        shutil.copy2(src, staging / name)
    (staging / "compose.yaml").write_text(
        render_compose((KIT_SRC / "compose.yaml").read_text(encoding="utf-8"), version),
        encoding="utf-8",
    )
    (staging / "VERSION").write_bytes(f"{version}\r\n".encode("ascii"))

    step(4, total, "Checking that no secret is in the kit or the image")
    hits = forbidden_files(staging)
    if hits:
        raise KitError(f"secret files found in the kit: {[h.name for h in hits]}")
    found = out(["docker", "run", "--rm", "--entrypoint", "sh", tag, "-c",
                 "find / -xdev \\( -name .env -o -name 'client_secret*.json' -o -name '*.db' "
                 "-o -name google-token.json \\) 2>/dev/null | grep -v '^/usr/lib' || true"])
    if found:
        raise KitError(f"secret-like files inside the image: {found}")
    print("  none found")

    step(5, total, "Zipping")
    zip_path = DIST / f"{KIT_NAME}-{version}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                z.write(f, f"{KIT_NAME}/{f.relative_to(staging).as_posix()}")
    shutil.rmtree(staging)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"""
  ----------------------------------------------------
   Kit ready : {zip_path.relative_to(ROOT)}
   Size      : {size_mb:.0f} MB
   Version   : {version}
   SHA-256   : {sha256_of(zip_path)}
  ----------------------------------------------------
   On the other laptop: unzip it, add client_secret.json,
   double-click docker-start.cmd. See START-HERE.md inside.
""")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KitError, subprocess.CalledProcessError) as exc:
        print(f"\nERROR: {exc}\nNo kit was made.")
        sys.exit(1)
