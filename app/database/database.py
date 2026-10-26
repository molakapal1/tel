"""مدیریت اتصال پایگاه داده SQLite و مهاجرت ساختار.

بخش ۲۱ سند: عملیات مهم باید با تراکنش مناسب انجام شوند و تغییرات ساختار
با روش مشخص و قابل تکرار (نسخه‌بندی اسکیمای DDL) اعمال شود.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .models import MIGRATIONS


class Database:
    """پوشش امن SQLite با قفل سراسری و پشتیبانی تراکنش.

    توجه: SQLite با یک فایل واحد کار می‌کند؛ قفل سطح فرایند برای جلوگیری از
    تداخل نخ‌های مختلف (پایش اینستاگرام، موتور دانلود، هندلرهای تلگرام)
    لازم است.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        parent = Path(self.path).parent
        if parent.name and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=10000")

    # ---------- ابزار پایه ----------
    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        """اجرای یک دستور (بدون تراکنش صریح؛ commit خودکار)."""
        with self._lock, self._conn:
            cur = self._conn.execute(sql, args)
            return cur

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = cur.fetchall()
            cur.close()
            return rows

    def query_one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def scalar(self, sql: str, args: tuple = ()):
        row = self.query_one(sql, args)
        return row[0] if row is not None else None

    @contextmanager
    def tx(self):
        """تراکنش صریح برای عملیات مهم (بخش ۲۱.۲).

        نمونه: تأیید سفارش + فعال‌سازی اشتراک به‌صورت اتمیک.
        """
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(sql, seq)

    # ---------- مهاجرت ----------
    def migrate(self) -> int:
        """اعمال مهاجرت‌های نسخه‌بندی‌شده ساختار (idempotent)."""
        self.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))"
        )
        applied = {r["version"] for r in self.query("SELECT version FROM schema_migrations")}
        for version, statements in MIGRATIONS:
            if version in applied:
                continue
            with self._lock, self._conn:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in statements:
                        self._conn.execute(stmt)
                    self._conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                    )
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise
        latest = self.scalar("SELECT MAX(version) FROM schema_migrations")
        return int(latest or 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- پشتیبان‌گیری (بخش ۲۱.۵) ----------
    def backup_to(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            src = sqlite3.connect(self.path)
            dst = sqlite3.connect(str(dest))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        return dest

    def healthcheck(self) -> bool:
        try:
            return self.scalar("SELECT 1") == 1
        except Exception:
            return False
