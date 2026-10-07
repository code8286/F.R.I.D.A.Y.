// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile G icon: three stacked rounded bars that advance one slot every 3 s, like a queue.
import QtQuick
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property bool live: true
    width: 30; height: 40
    property real shift: 0          // 0..1 during the advance
    Repeater {
        model: 4
        delegate: Rectangle {
            required property int index
            // slot positions: 0 = top ... 2 = bottom; index 3 enters from below
            readonly property real slotY: (index - ic.shift) * 11
            y: slotY
            width: 30; height: 7.5; radius: 3.75
            readonly property bool atBottom: slotY > 18
            color: atBottom ? ic.fg : "transparent"
            border.color: index === 0 ? Qt.rgba(ic.fg.r, ic.fg.g, ic.fg.b, 0.6) : ic.fg
            border.width: 1.3
            opacity: index === 0 ? 1 - ic.shift : index === 3 ? ic.shift : 1
        }
    }
    Rectangle { x: 13.5; y: 35; width: 3; height: 3; radius: 1.5; color: ic.fg; opacity: 0.8 }
    SequentialAnimation {
        running: ic.live && !Theme.reducedMotion
        loops: Animation.Infinite
        PauseAnimation { duration: 2600 }
        NumberAnimation { target: ic; property: "shift"; from: 0; to: 1; duration: 400; easing.type: Easing.InOutCubic }
        PropertyAction { target: ic; property: "shift"; value: 0 }
    }
}
