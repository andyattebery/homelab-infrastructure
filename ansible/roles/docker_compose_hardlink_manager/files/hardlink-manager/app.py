import logging
import os
import subprocess

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("hardlink-manager")

ALLOWED_PATH_PREFIX = os.environ.get("ALLOWED_PATH_PREFIX", "/mnt/data/")
FIND_TIMEOUT = int(os.environ.get("FIND_TIMEOUT", "300"))
ORPHAN_SUFFIXES = (".hlbak", ".partial.old")

app = FastAPI()


class DetectRequest(BaseModel):
    file_path: str
    search_root: str


class ReplaceRequest(BaseModel):
    new_primary: str
    old_ext: str
    new_ext: str
    siblings: list[str]


def validate_path(path: str) -> None:
    resolved = os.path.realpath(path)
    if not resolved.startswith(ALLOWED_PATH_PREFIX):
        raise HTTPException(
            status_code=400,
            detail=f"Path {path} resolves outside allowed prefix {ALLOWED_PATH_PREFIX}",
        )


def run_cmd(
    args: list[str],
    check: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        check=check,
        encoding="utf-8",
        errors="surrogateescape",
        timeout=timeout,
    )


def get_inode(path: str) -> int:
    result = run_cmd(["stat", "-c", "%i", path])
    return int(result.stdout.strip())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/detect")
def detect(req: DetectRequest):
    validate_path(req.file_path)
    validate_path(req.search_root)

    try:
        inode = get_inode(req.file_path)
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"stat failed: {e.stderr.strip()}"}

    try:
        result = run_cmd(
            [
                "find", req.search_root,
                "-inum", str(inode),
                "-print0",
            ],
            check=False,
            timeout=FIND_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"find timed out after {FIND_TIMEOUT}s"}

    resolved_source = os.path.realpath(req.file_path)
    all_siblings = [
        p for p in result.stdout.split("\0")
        if p and os.path.realpath(p) != resolved_source
    ]
    orphans = [p for p in all_siblings if any(p.endswith(s) for s in ORPHAN_SUFFIXES)]
    siblings = [p for p in all_siblings if not any(p.endswith(s) for s in ORPHAN_SUFFIXES)]
    if orphans:
        logger.warning("Filtered %d orphan(s): %s", len(orphans), orphans)

    if result.returncode != 0 and not siblings:
        return {"status": "error", "message": f"find failed: {result.stderr.strip()}"}

    response: dict = {"status": "ok", "inode": inode, "siblings": siblings}
    if result.returncode != 0 and result.stderr.strip():
        response["warnings"] = result.stderr.strip()

    logger.info("detect: %s inode=%d siblings=%d", req.file_path, inode, len(siblings))
    return response


def _replace_sibling(
    sibling: str,
    new_primary: str,
    primary_inode: int,
    old_ext: str,
    new_ext: str,
) -> dict:
    backup_path = sibling + ".hlbak"

    if any(sibling.endswith(s) for s in ORPHAN_SUFFIXES):
        return {"sibling": sibling, "result": "error",
                "message": "Refusing to process orphan file as sibling"}

    if old_ext != new_ext:
        if not sibling.endswith(old_ext):
            return {"sibling": sibling, "result": "error",
                    "message": f"Sibling does not end with {old_ext}"}
        new_sibling_path = sibling[: -len(old_ext)] + new_ext
    else:
        new_sibling_path = sibling

    # Idempotency: if target already exists with correct inode, skip
    if os.path.exists(new_sibling_path):
        try:
            existing_inode = get_inode(new_sibling_path)
        except subprocess.CalledProcessError:
            existing_inode = None
        if existing_inode == primary_inode:
            logger.info("Target already correct: %s (inode=%d)", new_sibling_path, primary_inode)
            if os.path.exists(backup_path):
                try:
                    run_cmd(["rm", backup_path])
                except subprocess.CalledProcessError:
                    pass
            return {"sibling": sibling, "new_path": new_sibling_path, "result": "ok"}
        if new_sibling_path != sibling:
            logger.warning("Removing stale file at target: %s (inode=%d, expected=%d)",
                            new_sibling_path, existing_inode or -1, primary_inode)
            try:
                run_cmd(["rm", new_sibling_path])
            except subprocess.CalledProcessError as e:
                return {"sibling": sibling, "new_path": new_sibling_path, "result": "error",
                        "message": f"Failed to remove stale target: {e.stderr.strip()}"}

    have_backup = os.path.exists(backup_path)
    have_sibling = os.path.exists(sibling)

    if have_backup and not have_sibling:
        logger.warning("Found orphan backup, reusing: %s", backup_path)
    elif have_sibling:
        try:
            run_cmd(["mv", sibling, backup_path])
        except subprocess.CalledProcessError as e:
            return {"sibling": sibling, "result": "error",
                    "message": f"Backup mv failed: {e.stderr.strip()}"}
    else:
        return {"sibling": sibling, "result": "error",
                "message": "Sibling not found and no backup exists"}

    try:
        run_cmd(["ln", new_primary, new_sibling_path])
    except subprocess.CalledProcessError as e:
        logger.error("ln failed for %s, restoring backup", new_sibling_path)
        _try_restore(backup_path, sibling)
        return {"sibling": sibling, "result": "error",
                "message": f"ln failed: {e.stderr.strip()}"}

    try:
        new_inode = get_inode(new_sibling_path)
    except subprocess.CalledProcessError as e:
        return {"sibling": sibling, "new_path": new_sibling_path, "result": "error",
                "message": f"Verification stat failed: {e.stderr.strip()}"}

    if new_inode != primary_inode:
        logger.error(
            "Inode mismatch: primary=%d new=%d, restoring %s",
            primary_inode, new_inode, sibling,
        )
        try:
            run_cmd(["rm", new_sibling_path])
        except subprocess.CalledProcessError:
            pass
        _try_restore(backup_path, sibling)
        return {"sibling": sibling, "new_path": new_sibling_path, "result": "error",
                "message": f"Inode mismatch: expected {primary_inode}, got {new_inode}"}

    try:
        run_cmd(["rm", backup_path])
    except subprocess.CalledProcessError:
        logger.warning("Failed to remove backup %s (non-fatal)", backup_path)

    logger.info("Replaced: %s -> %s (inode=%d)", sibling, new_sibling_path, primary_inode)
    return {"sibling": sibling, "new_path": new_sibling_path, "result": "ok"}


def _try_restore(backup_path: str, original_path: str) -> None:
    try:
        run_cmd(["mv", backup_path, original_path])
    except subprocess.CalledProcessError:
        logger.error("Failed to restore backup %s -> %s", backup_path, original_path)


@app.post("/replace")
def replace(req: ReplaceRequest):
    validate_path(req.new_primary)
    for s in req.siblings:
        validate_path(s)

    if req.old_ext != req.new_ext:
        for ext in (req.old_ext, req.new_ext):
            if not ext or not ext.startswith("."):
                return {"status": "error",
                        "message": f"Invalid extension: {ext!r} (must be non-empty and start with '.')"}

    try:
        primary_inode = get_inode(req.new_primary)
    except subprocess.CalledProcessError as e:
        return {"status": "error",
                "message": f"stat on new_primary failed: {e.stderr.strip()}"}

    details = [
        _replace_sibling(s, req.new_primary, primary_inode, req.old_ext, req.new_ext)
        for s in req.siblings
    ]
    errors = sum(1 for d in details if d["result"] != "ok")
    return {
        "status": "ok" if errors == 0 else "error",
        "replaced": len(details) - errors,
        "errors": errors,
        "details": details,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
