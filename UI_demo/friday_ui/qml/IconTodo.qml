// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile D icon: three rounded bars with check circles. Idle: the top check fills and empties. Hover: checks draw in sequence.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property bool hovered: false
    property bool live: true
    width: 150; height: 116
    property var fills: [1, 0, 0]
    property real f0: 1
    property real f1: 0
    property real f2: 0

    Repeater {
        model: 3
        delegate: Item {
            required property int index
            y: index * 42
            width: 150; height: 31
            readonly property real fill: index === 0 ? ic.f0 : index === 1 ? ic.f1 : ic.f2
            Rectangle { anchors.fill: parent; radius: height / 2; color: "transparent"; border.color: ic.fg; border.width: 1.5 }
            Rectangle {
                x: 15.5 - 9.5; y: 15.5 - 9.5; width: 19; height: 19; radius: 9.5
                color: Qt.rgba(ic.fg.r, ic.fg.g, ic.fg.b, Math.min(1, parent.fill * 1.4)); border.color: ic.fg; border.width: 1.5
            }
            Item {
                x: 6; y: 6; width: 19 * parent.fill; height: 19; clip: true
                Shape {
                    width: 19; height: 19
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath { strokeColor: "#000000"; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                        startX: 5; startY: 10; PathLine { x: 8.3; y: 13.2 } PathLine { x: 14; y: 6.6 } }
                }
            }
            Rectangle { visible: index === 0; x: 35; y: 15; width: 96; height: 1.5; color: "#5A5A57"; opacity: parent.fill }
        }
    }
    SequentialAnimation {
        running: ic.live && !Theme.reducedMotion && !hoverSeq.running
        loops: Animation.Infinite
        PauseAnimation { duration: 3800 }
        NumberAnimation { target: ic; property: "f0"; to: 0; duration: 900; easing.type: Easing.InOutCubic }
        PauseAnimation { duration: 1600 }
        NumberAnimation { target: ic; property: "f0"; to: 1; duration: 900; easing.type: Easing.InOutCubic }
    }
    onHoveredChanged: {
        if (hovered && !Theme.reducedMotion) { hoverSeq.restart() }
        else if (!hovered) { hoverSeq.stop(); back.restart() }
    }
    SequentialAnimation {
        id: hoverSeq
        PropertyAction { target: ic; property: "f1"; value: 0 }
        PropertyAction { target: ic; property: "f2"; value: 0 }
        NumberAnimation { target: ic; property: "f0"; to: 1; duration: Theme.fast }
        NumberAnimation { target: ic; property: "f1"; to: 1; duration: Theme.fast; easing.type: Easing.OutCubic }
        NumberAnimation { target: ic; property: "f2"; to: 1; duration: Theme.fast; easing.type: Easing.OutCubic }
    }
    ParallelAnimation {
        id: back
        NumberAnimation { target: ic; property: "f1"; to: 0; duration: Theme.base }
        NumberAnimation { target: ic; property: "f2"; to: 0; duration: Theme.base }
        NumberAnimation { target: ic; property: "f0"; to: 1; duration: Theme.base }
    }
}
