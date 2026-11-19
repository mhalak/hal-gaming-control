import json
import uuid
import zipfile
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from gaming_control.update_control import parse_request, version_tuple
from updater import verify_manifest, extract_package
# Recovery is covered by test_update_transaction.py (crash injection at every journal phase).

def test_request_schema():
    request = {"version":"1.2.3", "request_id":str(uuid.uuid4()), "expires_at":1060}
    assert parse_request(json.dumps(request), now=1000) == request
    for invalid in [request | {"url":"https://evil.example"}, request | {"version":"../bad"},
                    request | {"expires_at":999}, request | {"expires_at":1300}]:
        with pytest.raises(ValueError):
            parse_request(json.dumps(invalid), now=1000)
    assert version_tuple("1.10.0") > version_tuple("1.2.9")

def test_signature_and_version():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    raw = json.dumps({"version":"1.2.3","filename":"windows-agent-1.2.3.zip","sha256":"a"*64,"size":123}).encode()
    sig = key.sign(raw)
    assert verify_manifest(raw,sig,public,"1.2.3")["size"] == 123
    with pytest.raises(Exception):
        verify_manifest(raw+b" ",sig,public,"1.2.3")
    with pytest.raises(ValueError):
        verify_manifest(raw,sig,public,"1.2.4")

def test_archive_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive,"w") as z:
        z.writestr("../outside.txt","bad")
    with pytest.raises(ValueError):
        extract_package(archive,tmp_path / "payload")
    assert not (tmp_path / "outside.txt").exists()

def test_archive_accepts_layout(tmp_path):
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive,"w") as z:
        z.writestr("SmartHouseGamingControl.exe","dummy")
        z.writestr("_internal/safe.dll","dummy")
    target = tmp_path / "payload"
    extract_package(archive,target)
    assert (target / "_internal/safe.dll").is_file()

@pytest.mark.parametrize("name", ["AUX.txt", "dir/COM1.log", "dir/LPT²", "a:b", "trailing. ", "a\\b", "/absolute"])
def test_windows_unsafe_member(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name.replace("\\", "/"), "bad")
    if "\\" in name:
        # Patch equal-length filename bytes in both headers, bypassing ZipInfo normalization.
        archive.write_bytes(archive.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    with pytest.raises(ValueError):
        extract_package(archive, tmp_path / "payload")
