// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Outlined pill button ("+ New", "Approve", "Deny", "Stop", ...).
import QtQuick
import Friday

Rectangle {
    id: b
    property string text: ""
    property color fg: Theme.fgTile
    property color bgHover: Qt.rgba(1, 1, 1, 0.08)
    property bool filled: false
    property bool mono: false
    property real u: Theme.u
    property real fontPx: 18
    property bool enabledLook: true
    signal clicked()
    implicitWidth: lbl.implicitWidth + 30 * u
    implicitHeight: 33 * u
    radius: height / 2
    color: filled ? fg : (ma.containsMouse ? bgHover : "transparent")
    border.color: fg
    border.width: Math.max(1.2, 1.5 * u)
    opacity: enabledLook ? 1 : 0.4
    scale: ma.pressed ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: Theme.d(Theme.fast) } }
    Text {
        id: lbl
        anchors.centerIn: parent
        text: b.text
        textFormat: Text.PlainText
        color: b.filled ? (Qt.colorEqual(b.fg, Theme.fgTile) ? "#000000" : Theme.fgAccent) : b.fg
        font.family: b.mono ? Theme.mono : Theme.display
        font.pixelSize: b.fontPx * b.u
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: if (b.enabledLook) b.clicked() }
}
