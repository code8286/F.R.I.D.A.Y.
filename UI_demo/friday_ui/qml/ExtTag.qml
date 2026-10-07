// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// "⚠ external": the item was written on a tainted turn (brief 6). Its text is rendered as plain text only.
import QtQuick
import Friday

Rectangle {
    property real u: Theme.u
    property color fg: Theme.accent
    implicitWidth: t.implicitWidth + 12 * u
    implicitHeight: 18 * u
    radius: height / 2
    color: "transparent"
    border.color: fg
    border.width: 1
    Text { id: t; anchors.centerIn: parent; text: "⚠ external"; color: parent.fg; font.family: Theme.mono; font.pixelSize: 10.5 * parent.u }
}
