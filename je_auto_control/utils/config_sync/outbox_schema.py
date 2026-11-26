"""Identify and initialize only an owned SQLite sync-outbox database."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from je_auto_control.utils.config_sync.contract import ConfigStoreError
from je_auto_control.utils.config_sync.workspace_schema import WORKSPACE_TABLES

if TYPE_CHECKING:
    from sqlite3 import Connection

_APPLICATION = 1094931289
_TABLES = (
    "CREATE TABLE sync_namespaces (endpoint TEXT NOT NULL, user_id TEXT NOT NULL, origin TEXT NOT NULL, "
    "epoch INTEGER NOT NULL DEFAULT 0, confirmed_revision INTEGER NOT NULL DEFAULT 0, snapshot TEXT, "
    "PRIMARY KEY (endpoint, user_id))",
    "CREATE TABLE sync_operations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT NOT NULL, "
    "user_id TEXT NOT NULL, operation_id TEXT NOT NULL, wire TEXT NOT NULL, digest TEXT NOT NULL, "
    "status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
    "next_attempt REAL NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0, prepared TEXT, "
    "lease_owner TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0, "
    "error TEXT NOT NULL DEFAULT '', delivered_revision INTEGER, UNIQUE(endpoint, user_id, operation_id))",
)
_CONTROL_TABLE = (
    "CREATE TABLE sync_controls (endpoint TEXT NOT NULL, user_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
    "kind TEXT NOT NULL, wire TEXT NOT NULL, digest TEXT NOT NULL, prepared TEXT, "
    "status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
    "next_attempt REAL NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0, "
    "lease_owner TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0, "
    "error TEXT NOT NULL DEFAULT '', receipt_revision INTEGER, PRIMARY KEY(endpoint,user_id))"
)
# ``recorded_at`` (version 4) is when the receipt was confirmed, so receipts can be pruned by age.
_CONTROL_RECEIPTS = (
    "CREATE TABLE sync_control_receipts (endpoint TEXT NOT NULL, user_id TEXT NOT NULL, operation_id TEXT NOT NULL, "
    "wire TEXT NOT NULL, digest TEXT NOT NULL, revision INTEGER NOT NULL, recorded_at REAL NOT NULL DEFAULT 0, "
    "PRIMARY KEY(endpoint,user_id,operation_id))"
)
_RECEIPT_COLUMNS = {"endpoint", "user_id", "operation_id", "wire", "digest", "revision"}
_VERSION = 4


def initialize_outbox(connection: Connection, clock: Callable[[], float] = time.time) -> None:
    """Reject foreign/future databases before modifying tables; serialize first-use initialization.

    An older owned database is migrated in place; receipts it already holds are
    stamped with ``clock()``, the migration time, so none is pruned as old at once.
    """
    if _version(connection) == (_APPLICATION, _VERSION):
        return
    connection.execute("BEGIN IMMEDIATE")
    version = _version(connection)
    if version == (_APPLICATION, _VERSION):
        connection.execute("COMMIT")
        return
    if version in {(_APPLICATION, 1), (_APPLICATION, 2), (_APPLICATION, 3)}:
        _migrate(connection, version[1], clock)
    else:
        _create(connection, version)
    connection.execute(f"PRAGMA user_version = {_VERSION}")
    connection.execute("COMMIT")


def _create(connection: Connection, version: tuple[int, int]) -> None:
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    if version != (0, 0) or tables:
        raise ConfigStoreError("not a supported sync-outbox database")
    for statement in _TABLES:
        connection.execute(statement)
    connection.execute(_CONTROL_TABLE)
    connection.execute(_CONTROL_RECEIPTS)
    for statement in WORKSPACE_TABLES:
        connection.execute(statement)
    connection.execute(f"PRAGMA application_id = {_APPLICATION}")


def _migrate(connection: Connection, version: int, clock: Callable[[], float]) -> None:
    _require_owned_tables(connection, version)
    if version == 1:
        connection.execute(_CONTROL_TABLE)
        connection.execute(_CONTROL_RECEIPTS)
    else:
        connection.execute("ALTER TABLE sync_control_receipts ADD COLUMN recorded_at REAL NOT NULL DEFAULT 0")
        connection.execute("UPDATE sync_control_receipts SET recorded_at = ?", (float(clock()),))
    if version < 3:
        for statement in WORKSPACE_TABLES:
            connection.execute(statement)


def _version(connection: Connection) -> tuple[int, int]:
    return (connection.execute("PRAGMA application_id").fetchone()[0],
            connection.execute("PRAGMA user_version").fetchone()[0])


def _require_owned_tables(connection: Connection, version: int) -> None:
    expected = {
        "sync_namespaces": {"endpoint", "user_id", "origin", "epoch", "confirmed_revision", "snapshot"},
        "sync_operations": {"sequence", "endpoint", "user_id", "operation_id", "wire", "digest", "status", "attempts",
                            "next_attempt", "last_attempt", "prepared", "lease_owner", "lease_until", "error",
                            "delivered_revision"},
    }
    if version >= 2:
        expected.update({
            "sync_controls": {"endpoint", "user_id", "operation_id", "kind", "wire", "digest", "prepared", "status",
                              "attempts", "next_attempt", "last_attempt", "lease_owner", "lease_until", "error",
                              "receipt_revision"},
            "sync_control_receipts": set(_RECEIPT_COLUMNS),
        })
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                  "AND name NOT LIKE 'sqlite_%'")}
    if version >= 3:        # the workspace tables of version 3 are its own; only the receipts change
        tables -= {"sync_workspace_leases", "sync_workspace_bindings", "sync_workspace_baselines"}
    if tables != set(expected):
        raise ConfigStoreError("invalid owned outbox schema")
    for name, columns in expected.items():
        # Names are fixed schema literals above, never user-supplied SQL identifiers.
        actual = {row[1] for row in connection.execute(f"PRAGMA table_info({name})")}
        if actual != columns:
            raise ConfigStoreError("invalid owned outbox columns")
