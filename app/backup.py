"""Automated backup system with SQLite backup and hardlink deduplication."""

import logging
import os
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("4orm.backup")

BACKUP_INTERVAL_SECONDS = 3600  # 1 hour
MAX_BACKUPS = 48  # Keep 48 hourly backups (2 days)


def backup_database(src_db_path: Path, dest_db_path: Path) -> None:
    """Safely backup a SQLite database using the backup API."""
    dest_db_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(src_db_path))
    dst = sqlite3.connect(str(dest_db_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def backup_uploads_hardlink(uploads_dir: Path, dest_dir: Path) -> int:
    """Copy uploads using hardlinks for deduplication.

    Returns the number of files linked/copied.
    """
    if not uploads_dir.exists():
        return 0

    count = 0
    dest_dir.mkdir(parents=True, exist_ok=True)

    for user_dir in uploads_dir.iterdir():
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        dest_user_dir = dest_dir / user_dir.name
        dest_user_dir.mkdir(parents=True, exist_ok=True)

        for f in user_dir.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            dest_file = dest_user_dir / f.name
            if dest_file.exists():
                continue
            try:
                os.link(str(f), str(dest_file))
            except OSError:
                # Hardlink failed (cross-device?), fall back to copy
                shutil.copy2(str(f), str(dest_file))
            count += 1

    return count


def prune_old_backups(backup_dir: Path, max_backups: int = MAX_BACKUPS) -> int:
    """Remove oldest backups beyond max_backups. Returns count removed."""
    if not backup_dir.exists():
        return 0

    snapshots = sorted(
        [d for d in backup_dir.iterdir() if d.is_dir() and d.name != "latest"],
        key=lambda d: d.name,
    )

    removed = 0
    while len(snapshots) > max_backups:
        oldest = snapshots.pop(0)
        shutil.rmtree(oldest)
        removed += 1

    return removed


def run_backup(
    db_path: Path,
    uploads_dir: Path,
    backup_dir: Path,
    max_backups: int = MAX_BACKUPS,
) -> dict:
    """Run a single backup. Returns a status dict."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    snapshot_dir = backup_dir / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "timestamp": timestamp,
        "db_backed_up": False,
        "files_linked": 0,
        "pruned": 0,
        "error": None,
    }

    try:
        # Backup database
        if db_path.exists():
            backup_database(db_path, snapshot_dir / "4orm.db")
            result["db_backed_up"] = True

        # Hardlink uploads
        result["files_linked"] = backup_uploads_hardlink(
            uploads_dir, snapshot_dir / "uploads"
        )

        # Prune old backups
        result["pruned"] = prune_old_backups(backup_dir, max_backups)

        logger.info(
            "Backup complete: %s (db=%s, files=%d, pruned=%d)",
            timestamp,
            result["db_backed_up"],
            result["files_linked"],
            result["pruned"],
        )
    except Exception as e:
        result["error"] = str(e)
        logger.error("Backup failed: %s", e, exc_info=True)
        # Clean up failed snapshot
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    return result


class BackupScheduler:
    """Background thread that runs periodic backups."""

    def __init__(
        self,
        db_path: Path,
        uploads_dir: Path,
        backup_dir: Path,
        interval: int = BACKUP_INTERVAL_SECONDS,
        max_backups: int = MAX_BACKUPS,
    ):
        self.db_path = db_path
        self.uploads_dir = uploads_dir
        self.backup_dir = backup_dir
        self.interval = interval
        self.max_backups = max_backups
        self._thread = None
        self._stop_event = threading.Event()
        self.last_result = None

    def start(self):
        """Start the backup scheduler in a daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Backup scheduler started (interval=%ds)", self.interval)

    def stop(self):
        """Stop the backup scheduler."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Backup scheduler stopped")

    def _run(self):
        """Run backups periodically."""
        # Run first backup immediately
        self.last_result = run_backup(
            self.db_path, self.uploads_dir, self.backup_dir, self.max_backups
        )

        while not self._stop_event.wait(self.interval):
            self.last_result = run_backup(
                self.db_path, self.uploads_dir, self.backup_dir, self.max_backups
            )

    def run_now(self) -> dict:
        """Trigger an immediate backup (called from a route)."""
        self.last_result = run_backup(
            self.db_path, self.uploads_dir, self.backup_dir, self.max_backups
        )
        return self.last_result

    def list_backups(self) -> list[dict]:
        """List all backup snapshots with basic info."""
        if not self.backup_dir.exists():
            return []

        snapshots = []
        for d in sorted(self.backup_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            db_exists = (d / "4orm.db").exists()
            db_size = (d / "4orm.db").stat().st_size if db_exists else 0
            uploads_dir = d / "uploads"
            file_count = (
                sum(1 for _ in uploads_dir.rglob("*") if _.is_file())
                if uploads_dir.exists()
                else 0
            )
            snapshots.append(
                {
                    "name": d.name,
                    "db_size": db_size,
                    "file_count": file_count,
                }
            )

        return snapshots
