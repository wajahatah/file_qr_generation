# Spec — Portable Docker Kit for Another Laptop (Phase 1d)

- **Status:** APPROVED 2026-10-04 — IMPLEMENTED
- **Author:** Claude (Opus 5.5), on behalf of Wajahat Ahmed
- **Date:** 2026-10-04
- **Builds on:** [spec-docker.md](spec-docker.md) (approved, implemented)
- **Goal, in the user's words:** "run it in another laptop … I just put the key and run
  the docker commands without doing any complication and system start working."

---

## 1. Summary

A **kit**: one zip made on this laptop, holding the ready-built image and two
double-click files. On the other laptop: install Docker (once), unzip the kit, add
`client_secret.json`, double-click `docker-start.cmd`. Nothing is built there — no
source code, no Python, no internet needed for the app itself to start.

---

## 2. State BEFORE

- `docker-start.cmd` **builds** the image from source (`docker compose up -d --build`).
  It only works inside the full project folder, with `Dockerfile` and `app/`.
- No way to move the built image to another machine.
- The image is `linux/amd64`, ~86 MB, and contains no secrets (inspected).

---

## 3. State AFTER

### 3.1 Making the kit (this laptop)

Double-click **`make-kit.cmd`** in the project folder. It:

1. runs the test suite and stops if anything fails — a kit is never made from broken
   code;
2. builds the image and tags it with a version, e.g. `qr-file-share:2026.10.04-6af9929`
   (date + git commit);
3. saves it with `docker save` into the kit;
4. copies in the run files;
5. checks the kit contains **no** `.env`, `client_secret*.json`, database or token;
6. zips it: **`qr-file-share-kit-2026.10.04-6af9929.zip`** (in a `dist\` folder,
   gitignored).

### 3.2 The kit

```
qr-file-share-kit\
├── START-HERE.md               ← five steps, plain words
├── docker-start.cmd            ← double-click to run
├── docker-stop.cmd
├── compose.yaml                ← image only: never builds, never pulls from the internet
├── .env.example
├── qr-file-share-image.tar     ← the app, ready to run (~90 MB)
└── VERSION
```

### 3.3 Using it (other laptop)

1. Install WSL and Docker Desktop (commands already provided; they go in `START-HERE.md`).
2. Unzip the kit anywhere, e.g. `C:\QR File Share`.
3. Put `client_secret.json` in that folder.
4. Double-click `docker-start.cmd`.
5. Sign in with the admin token shown, **Connect Google Drive**, done.

### 3.4 One launcher, two situations

`docker-start.cmd` is a single file that works in both places, so the two can never
drift apart:

| Folder has | It does |
|---|---|
| `Dockerfile` (the project, this laptop) | builds from source — today's behaviour, unchanged |
| `qr-file-share-image.tar` (a kit) | loads the image from the file if that version is not loaded yet, then starts it. Never builds, never pulls. |

### 3.5 Updating the other laptop later

Make a new kit, unzip it **over** the old folder (keeping `.env` and
`client_secret.json`), double-click `docker-start.cmd`. The new version is loaded and
started; issued QR codes, settings and the Google sign-in are kept, because they live
in the Docker volume, not in the kit.

---

## 4. Things to know

- **Each laptop is its own app.** Each keeps its own list of QR codes, its own Google
  sign-in, and removes only its own expired QR codes. There are no QR codes on this
  laptop yet, so nothing needs moving.
- **CPU type.** The image is built for Intel/AMD (`amd64`). An ARM laptop (Snapdragon,
  e.g. "Copilot+ PC") needs an `arm64` build — open question 1.
- **Same Google key works on any laptop.** `client_secret.json` is not tied to a
  machine. Your Gmail is already a test user, so sign-in works there too.
- The kit holds no secrets, so it can be copied by USB, Google Drive or email. The
  key file travels separately.

---

## 5. Changes by file

| File | Change |
|---|---|
| `make-kit.cmd` | **New.** Builds, tests, saves, checks for secrets, zips. |
| `tools/kit/START-HERE.md`, `tools/kit/compose.yaml` | **New.** The kit's guide and image-only compose file. |
| `docker-start.cmd` | Detects kit vs project folder (§3.4). Project behaviour unchanged. |
| `.gitignore` | Add `dist/`. |
| `tests/test_docker_files.py` | Kit compose never builds/pulls and publishes to 127.0.0.1 only; launcher handles both folders. |
| Docs | `HOW-TO-RUN.md`, setup guide §9, technical docs, README. |

---

## 6. Test plan

- Automated: the kit `compose.yaml` has no `build`, has `pull_policy: never`, ports on
  `127.0.0.1` only, same volume name as the project (so data carries across updates);
  `docker-start.cmd` has both branches; all existing tests pass unchanged.
- **Real end-to-end on this laptop, simulating the other one:** make the kit; **delete
  the image from Docker** so it must come from the file; unzip into an empty folder
  with only a dummy key; double-click `docker-start.cmd` → it loads, starts, opens the
  browser; check zone, health, not reachable from the network. Then make a second kit
  and check an update keeps data. Cleaned up afterwards.
- Not testable here: the other laptop itself — first run there is the real check.

---

## 7. Open questions

1. **What CPU does the other laptop have?** Check in PowerShell:
   `$env:PROCESSOR_ARCHITECTURE` → `AMD64` (Intel/AMD — most laptops) or `ARM64`.
2. **How to move it?** *(Recommended: the zip file.)* Alternative: push the image to an
   online registry (Docker Hub / GitHub) and pull it on the other laptop — easier
   updates, but needs an account and a login on both laptops.

---

## 8. Approval

- [x] Approved by Wajahat — 2026-10-04. CPU of the other laptop: not sure. Transfer: download
  from GitHub.

### Implementation notes (post-build)

1. **Transfer is a GitHub Release asset**, not a repository file: GitHub caps
   repository files at 100 MB.
2. **Built and verified as Intel/AMD-only for the first deploy.** The emulated ARM
   build had run 15+ minutes when the user had a 30-minute deploy window; it was
   stopped and `--arch` added. Most Windows laptops are Intel/AMD; an ARM laptop can
   use the project folder, whose `docker-start.cmd` builds natively. A both-processor
   kit is one `make-kit.cmd` run away.
3. **Docker Hub became unreachable** mid-build (network), so `--reuse-image` was added.
   The local image was first proven byte-identical to the current code (all 25 files
   hashed), then packaged; architecture and secret checks still ran.
4. Kit messages: an ARM laptop given an Intel-only kit is told exactly that, not
   "file missing".

**Verified:** 310 tests (plus 1 Linux-only); kit built (81 MB, secret check clean); **other-laptop
simulation** — image deleted from Docker, kit unzipped into an empty folder with only a
dummy key, `docker-start.cmd` loaded the image from the file and started the app in
21 s with no internet; healthy, Docker mode, correct zone. Cleaned up.
