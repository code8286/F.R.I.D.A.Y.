// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Small text-glyph button for row actions (×, ▶, ‖, ✎ ...).
import QtQuick
import Friday

Item {
    id: gb
    property string glyph: "×"
    property color fg: Theme.dimOnTile
    property color hoverFg: Theme.fgTile
    property real u: Theme.u
    property real px: 16
    property string tip: ""
    signal clicked()
    implicitWidth: 26 * u
    implicitHeight: 26 * u
    Rectangle { anchors.fill: parent; radius: width / 2; color: ma.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent" }
    Text {
        anchors.centerIn: parent
        text: gb.glyph
        color: ma.containsMouse ? gb.hoverFg : gb.fg
        font.family: Theme.mono
        font.pixelSize: gb.px * gb.u
    }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: gb.clicked() }
}
