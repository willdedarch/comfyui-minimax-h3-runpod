#!/usr/bin/env python3
"""Download only selected groups using pinned revisions and verify full SHA256."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil

from runtime_env import configure_environment

PACKAGE = Path(__file__).resolve().parents[1]

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def selected_models(groups):
    manifest = json.loads((PACKAGE / "models.lock.json").read_text())
    known = set(manifest["groups"])
    requested = {group.strip() for group in groups.split(",") if group.strip()}
    if not requested:
        raise ValueError("Select at least one model group")
    if requested - known:
        raise ValueError(f"Unknown model groups: {requested - known}; valid: {sorted(known)}")
    models = [m for m in manifest["models"] if requested.intersection(m["groups"])]
    destinations = set()
    for model in models:
        destination = PurePosixPath(model["destination"])
        if (destination.is_absolute() or ".." in destination.parts
                or "\\" in model["destination"] or ":" in model["destination"]
                or not destination.parts or destination.parts[0] != "models"):
            raise ValueError(f"Invalid model destination: {model['destination']}")
        if model["destination"] in destinations:
            raise ValueError(f"Duplicate model destination: {model['destination']}")
        destinations.add(model["destination"])
        if (not re.fullmatch(r"[a-f0-9]{64}", model["sha256_published"])
                or not re.fullmatch(r"[a-f0-9]{40}", model["revision"])
                or type(model["size_bytes"]) is not int or model["size_bytes"] <= 0):
            raise ValueError(f"Invalid model checksum, revision or size: {model['destination']}")
    return models


@contextmanager
def download_lock(root):
    """One bootstrap at a time per volume; OS releases the lock after a crash."""
    with (root / ".h3max-download.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            raise RuntimeError("Another model bootstrap is using this volume; wait for it to finish and retry") from exc
        try:
            yield
        finally:
            release()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(os.getenv("H3MAX_ROOT", "/workspace/h3max")))
    parser.add_argument("--groups", default=os.getenv("H3MAX_MODEL_GROUPS", "h3"))
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    models = selected_models(args.groups)
    print(json.dumps({"files": len(models), "total_GB": round(sum(m["size_bytes"] for m in models)/1e9, 2),
                      "groups": args.groups, "root": str(args.root)}, ensure_ascii=False), flush=True)
    if args.plan:
        return
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Resolve every target before disk checks, imports or any remote download.
    for model in models:
        if not (root / model["destination"]).resolve().is_relative_to(root):
            raise ValueError("Model destination escapes the configured root")
    with download_lock(root):
        download_models(root, models, verify_only=args.verify_only)


def download_models(root, models, *, verify_only=False):
    configure_environment(root)
    missing_bytes = sum(m["size_bytes"] for m in models if not (root / m["destination"]).is_file())
    if not verify_only and shutil.disk_usage(root).free < missing_bytes + 5 * 1024**3:
        raise RuntimeError("Insufficient free storage for selected weights plus 5 GiB reserve.")
    if not verify_only:
        from huggingface_hub import hf_hub_download
    # Explicitly use the runtime variable even if implicit HF auth was disabled.
    # A blank value lets the Hub use its normal public/cached-token behavior.
    token = os.environ.get("HF_TOKEN", "").strip() or None
    receipt_path = root / "model-receipts.json"
    try:
        receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if not isinstance(receipts, dict):
            raise ValueError("Receipt root must be an object")
    except (ValueError, UnicodeError):
        print("Receipt cache is unreadable; existing models will be hashed again.", flush=True)
        receipts = {}
    for m in models:
        target = root / m["destination"]
        if not target.resolve().is_relative_to(root):
            raise ValueError("Model destination escapes the configured root")
        expected = m["sha256_published"]
        if target.exists():
            stat = target.stat()
            cached = receipts.get(m["destination"], {})
            if (not verify_only and stat.st_size == m["size_bytes"]
                    and cached == {"sha256": expected, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}):
                print(f"Verified cached: {target.name}", flush=True)
                continue
            if stat.st_size != m["size_bytes"] or sha256(target) != expected:
                raise RuntimeError(f"Existing file failed verification; inspect or rename it before retrying: {target}")
        else:
            if verify_only:
                raise RuntimeError(f"Missing model: {target}")
            print(f"Downloading {m['repository']}/{m['file']}", flush=True)
            # Temporary local_dir avoids a second full weight copy in HF's global cache.
            staging = root / ".downloads" / m["repository"].replace("/", "--")
            downloaded = Path(hf_hub_download(repo_id=m["repository"], filename=m["file"],
                               revision=m["revision"], local_dir=staging, token=token))
            if downloaded.stat().st_size != m["size_bytes"] or sha256(downloaded) != expected:
                raise RuntimeError(f"Downloaded model failed SHA256/size verification: {downloaded}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(downloaded, target)
        stat = target.stat()
        receipts[m["destination"]] = {"sha256": expected, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        temporary = receipt_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipts, indent=2) + "\n")
        os.replace(temporary, receipt_path)
        print(f"SHA256 OK: {target.name}", flush=True)

if __name__ == "__main__":
    main()
