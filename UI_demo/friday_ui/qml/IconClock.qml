// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile E icon: a clock face with 12 ticks; one hand sweeps a revolution every 60 s. Hover: one quick spin. Ringing: shakes.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property color sector: "#3A3A38"
    property bool live: true
    property bool hovered: false
    property bool ringing: false
    width: 146; height: 146
    readonly property real c: 73
    property real sweep: 115
    property real spin: 0

    Item {
        id: face
        width: parent.width; height: parent.height
        transform: Rotation { id: shakeRot; origin.x: ic.c; origin.y: ic.c; angle: 0 }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: "transparent"; fillColor: ic.sector
                startX: ic.c; startY: ic.c
                PathLine { x: ic.c; y: ic.c - 50 }
                PathAngleArc { centerX: ic.c; centerY: ic.c; radiusX: 50; radiusY: 50; startAngle: -90; sweepAngle: 63 }
                PathLine { x: ic.c; y: ic.c } }
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                PathAngleArc { centerX: ic.c; centerY: ic.c; radiusX: 72; radiusY: 72; startAngle: 0; sweepAngle: 360 } }
        }
        Repeater {
            model: 12
            delegate: Rectangle {
                required property int index
                visible: index !== 0
                width: 1.5; height: index % 3 === 0 ? 10 : 6
                color: ic.fg
                x: ic.c - width / 2
                y: ic.c - 62
                transform: Rotation { origin.x: 0.75; origin.y: 62; angle: index * 30 }
            }
        }
        // fixed hand at 12
        Rectangle { width: 1.8; height: 64; x: ic.c - 0.9; y: ic.c - 64; color: ic.fg }
        // sweeping hand
        Rectangle {
            width: 1.8; height: 44; x: ic.c - 0.9; y: ic.c - 44; color: ic.fg
            antialiasing: true
            transform: Rotation { origin.x: 0.9; origin.y: 44; angle: ic.sweep + ic.spin }
        }
        Rectangle { width: 8; height: 8; radius: 4; x: ic.c - 4; y: ic.c - 4; color: ic.fg }
    }
    NumberAnimation on sweep { running: ic.live && !Theme.reducedMotion; from: 115; to: 475; duration: 60000; loops: Animation.Infinite }
    onHoveredChanged: if (hovered && !Theme.reducedMotion) spinAnim.restart()
    NumberAnimation { id: spinAnim; target: ic; property: "spin"; from: 0; to: 360; duration: 700; easing.type: Easing.InOutCubic }
    SequentialAnimation {
        running: ic.ringing && !Theme.reducedMotion
        loops: Animation.Infinite
        onStopped: shakeRot.angle = 0
        NumberAnimation { target: shakeRot; property: "angle"; to: 7; duration: 45 }
        NumberAnimation { target: shakeRot; property: "angle"; to: -7; duration: 90 }
        NumberAnimation { target: shakeRot; property: "angle"; to: 0; duration: 45 }
    }
}
