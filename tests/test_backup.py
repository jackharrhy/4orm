import sqlite3
from contextlib import closing

from app import backup


def test_backup_terminal_state_matches_actual_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("create table content(value text)")
        conn.execute("insert into content values ('preserved')")
    result = backup.run_backup(source, tmp_path / "uploads", tmp_path / "saved")
    assert result["state"] == "completed"
    with closing(
        sqlite3.connect(tmp_path / "saved" / result["timestamp"] / "4orm.db")
    ) as conn:
        assert conn.execute("select value from content").fetchone() == ("preserved",)

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(backup, "backup_database", fail)
    result = backup.run_backup(source, tmp_path / "uploads", tmp_path / "failed")
    assert result["state"] == "failed"
    assert result["error"] == "disk unavailable"
    assert not (tmp_path / "failed" / result["timestamp"]).exists()


def test_scheduler_state_reports_stopping_until_the_worker_exits(tmp_path, monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()

    def blocked_backup(*args):
        started.set()
        release.wait(timeout=2)
        return {"state": "completed"}

    monkeypatch.setattr(backup, "run_backup", blocked_backup)
    scheduler = backup.BackupScheduler(
        tmp_path / "db", tmp_path / "uploads", tmp_path / "backups"
    )
    assert scheduler.state == "stopped"
    try:
        scheduler.start()
        assert started.wait(timeout=1)
        worker = scheduler._thread
        scheduler.start()
        assert scheduler._thread is worker
        assert scheduler.state == "running"
        scheduler._stop_event.set()
        assert scheduler.state == "stopping"
    finally:
        release.set()
        scheduler.stop()
    assert scheduler.state == "stopped"
