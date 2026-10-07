// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// On/off switch. The thumb slides with OutBack (brief 5E).
import QtQuick
import Friday

Item {
    id: tg
    property bool checked: false
    property real u: Theme.u
    signal toggled()
    implicitWidth: 38 * u
    implicitHeight: 20 * u
    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: tg.checked ? Theme.fgTile : "#1C1C1C"
        border.color: tg.checked ? Theme.fgTile : "#4A4A48"
        border.width: Math.max(1, 1 * tg.u)
        Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } }
    }
    Rectangle {
        id: thumb
        width: tg.height - 6 * tg.u
        height: width
        radius: width / 2
        y: 3 * tg.u
        x: tg.checked ? tg.width - width - 3 * tg.u : 3 * tg.u
        color: tg.checked ? "#000000" : "#55554F"
        border.color: tg.checked ? "#000000" : "transparent"
        Behavior on x { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Theme.reducedMotion ? Easing.Linear : Easing.OutBack; easing.overshoot: 1.6 } }
        Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } }
    }
    MouseArea { anchors.fill: parent; anchors.margins: -6 * tg.u; cursorShape: Qt.PointingHandCursor; onClicked: tg.toggled() }
}
