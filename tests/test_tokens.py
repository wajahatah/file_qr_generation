"""Where the Google sign-in token is kept (app/tokens.py)."""

from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace

import pytest

from app.tokens import FileStore, KeyringStore, build_token_store


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, s, u):
        return self.store.get((s, u))

    def set_password(self, s, u, v):
        self.store[(s, u)] = v

    def delete_password(self, s, u):
        self.store.pop((s, u), None)


# ------------------------------------------------------------------ file store


def test_file_store_round_trip(tmp_path):
    store = FileStore(tmp_path / "data" / "google-token.json")
    assert store.get() is None
    store.set("refresh-abc")
    assert store.get() == "refresh-abc"
    store.set("refresh-def")
    assert store.get() == "refresh-def"


def test_file_store_holds_only_the_token(tmp_path):
    path = tmp_path / "t.json"
    FileStore(path).set("refresh-abc")
    assert json.loads(path.read_text(encoding="utf-8")) == {"refresh_token": "refresh-abc"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes; Docker runs on Linux")
def test_file_store_is_private_to_the_app_user(tmp_path):
    path = tmp_path / "t.json"
    FileStore(path).set("refresh-abc")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_file_store_write_is_atomic(tmp_path):
    path = tmp_path / "t.json"
    FileStore(path).set("refresh-abc")
    assert not (tmp_path / "t.json.tmp").exists(), "no half-written temp file left behind"


def test_file_store_delete_is_idempotent(tmp_path):
    store = FileStore(tmp_path / "t.json")
    store.set("x")
    store.delete()
    store.delete()
    assert store.get() is None


@pytest.mark.parametrize("content", ["not json", "[]", '{"other": 1}', '{"refresh_token": ""}'])
def test_file_store_treats_a_damaged_file_as_not_signed_in(tmp_path, content):
    path = tmp_path / "t.json"
    path.write_text(content, encoding="utf-8")
    assert FileStore(path).get() is None


# --------------------------------------------------------------- keyring store


def test_keyring_store_round_trip():
    kr = FakeKeyring()
    store = KeyringStore(kr)
    store.set("refresh-abc")
    assert store.get() == "refresh-abc"
    store.delete()
    assert store.get() is None and kr.store == {}


def test_keyring_store_survives_a_broken_backend():
    class Broken:
        def get_password(self, *a):
            raise RuntimeError("no backend")

        def delete_password(self, *a):
            raise RuntimeError("no backend")

    store = KeyringStore(Broken())
    assert store.get() is None
    store.delete()  # must not raise


# -------------------------------------------------------------------- choosing


def test_native_uses_credential_manager_and_docker_uses_the_file(tmp_path):
    native = build_token_store(SimpleNamespace(token_store="keyring", token_file=tmp_path / "x"))
    docker = build_token_store(SimpleNamespace(token_store="file", token_file=tmp_path / "t.json"))
    assert isinstance(native, KeyringStore)
    assert isinstance(docker, FileStore) and docker.path == tmp_path / "t.json"
