// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// 1-3 small ticks; click to cycle.
import QtQuick
import Friday

Item {
    id: pt
    property int prio: 2
    property real u: Theme.u
    property color fg: Theme.fgTile
    signal cycled()
    implicitWidth: 3 * 7 * u
    implicitHeight: 16 * u
    Row {
        anchors.centerIn: parent
        spacing: 4 * pt.u
        Repeater {
            model: 3
            Rectangle { required property int index; width: 2.2 * pt.u; height: (7 + index * 3) * pt.u; anchors.bottom: parent.bottom
                        color: index < pt.prio ? pt.fg : "#3A3A38"; Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } } }
        }
    }
    MouseArea { anchors.fill: parent; anchors.margins: -6 * pt.u; cursorShape: Qt.PointingHandCursor; onClicked: pt.cycled() }
}
