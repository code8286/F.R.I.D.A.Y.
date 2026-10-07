# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""List models for QML. Every item has a stable `id`; `sync()` turns a target list into the minimal set of
insert / remove / move / change notifications, so QML list transitions (add, remove, displaced) always animate."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Slot


class ItemModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, keys: list[str], parent: Any = None):
        super().__init__(parent)
        self._keys = ["id"] + [k for k in keys if k != "id"]
        self._roles = {int(Qt.ItemDataRole.UserRole) + 1 + i: QByteArray(k.encode()) for i, k in enumerate(self._keys)}
        self._role_of = {k: int(Qt.ItemDataRole.UserRole) + 1 + i for i, k in enumerate(self._keys)}
        self._items: list[dict] = []

    # ------------------------------------------------------------------ Qt model API
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self) -> dict:  # noqa: N802
        return self._roles

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        ba = self._roles.get(role)
        if ba is None:
            return None
        return self._items[index.row()].get(bytes(ba).decode())

    def _count(self) -> int:
        return len(self._items)

    count = Property(int, _count, notify=countChanged)

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict:
        return dict(self._items[row]) if 0 <= row < len(self._items) else {}

    @Slot(str, result=int)
    def indexOf(self, item_id: str) -> int:  # noqa: N802
        for i, it in enumerate(self._items):
            if it.get("id") == item_id:
                return i
        return -1

    def items(self) -> list[dict]:
        return [dict(i) for i in self._items]

    # ------------------------------------------------------------------ diff
    def sync(self, target: list[dict]) -> None:
        before = len(self._items)
        want = {t["id"] for t in target}
        for i in range(len(self._items) - 1, -1, -1):
            if self._items[i]["id"] not in want:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._items[i]
                self.endRemoveRows()
        for i, t in enumerate(target):
            cur = self._items[i]["id"] if i < len(self._items) else None
            if cur != t["id"]:
                j = next((k for k in range(i + 1, len(self._items)) if self._items[k]["id"] == t["id"]), -1)
                if j >= 0:
                    self.beginMoveRows(QModelIndex(), j, j, QModelIndex(), i)
                    self._items.insert(i, self._items.pop(j))
                    self.endMoveRows()
                else:
                    self.beginInsertRows(QModelIndex(), i, i)
                    self._items.insert(i, dict(t))
                    self.endInsertRows()
                    continue
            old = self._items[i]
            if old != t:
                roles = [self._role_of[k] for k in self._keys if old.get(k) != t.get(k)]
                self._items[i] = dict(t)
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, roles)
        if len(self._items) != before:
            self.countChanged.emit()
