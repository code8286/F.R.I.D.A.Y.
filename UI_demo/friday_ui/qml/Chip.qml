// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Small mono pill used for sources, triggers and tiers.
import QtQuick
import Friday

Rectangle {
    id: chip
    property string text: ""
    property color fg: Theme.fgTile
    property color line: "#4A4A48"
    property bool filled: false
    property real u: Theme.u
    property real fontPx: 12
    implicitWidth: label.implicitWidth + 18 * u
    implicitHeight: 20 * u
    radius: height / 2
    color: filled ? fg : "transparent"
    border.color: line
    border.width: Math.max(1, u)
    Text {
        id: label
        anchors.centerIn: parent
        text: chip.text
        textFormat: Text.PlainText
        color: chip.filled ? "#000000" : chip.fg
        font.family: Theme.mono
        font.pixelSize: chip.fontPx * chip.u
    }
}
