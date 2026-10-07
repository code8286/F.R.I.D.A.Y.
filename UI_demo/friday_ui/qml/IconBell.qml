// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile C icon: a bell of three nested arches, a rim and a clapper. Idle: a tiny swing every 8 s. Due: rings.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property color dim: Theme.dimOnTile
    property bool live: true
    property bool hovered: false
    width: 136; height: 142
    function ring() { if (!Theme.reducedMotion) { idle.stop(); ringing.restart() } }

    Item {
        id: bell
        width: parent.width; height: parent.height
        transform: Rotation { id: rot; origin.x: 58; origin.y: 4; angle: 0 }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                startX: 58; startY: 4; PathLine { x: 58; y: 15 } }
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                startX: 21; startY: 111
                PathCubic { control1X: 21; control1Y: 56; control2X: 40; control2Y: 24; x: 58; y: 18 }
                PathCubic { control1X: 76; control1Y: 24; control2X: 95; control2Y: 56; x: 95; y: 111 } }
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                startX: 31; startY: 111
                PathCubic { control1X: 31; control1Y: 64; control2X: 45; control2Y: 36; x: 58; y: 30 }
                PathCubic { control1X: 71; control1Y: 36; control2X: 85; control2Y: 64; x: 85; y: 111 } }
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                startX: 41; startY: 111
                PathCubic { control1X: 41; control1Y: 72; control2X: 50; control2Y: 48; x: 58; y: 42 }
                PathCubic { control1X: 66; control1Y: 48; control2X: 75; control2Y: 72; x: 75; y: 111 } }
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                PathAngleArc { centerX: 58; centerY: 115; radiusX: 46; radiusY: 5.5; startAngle: 0; sweepAngle: 360 } }
        }
        Rectangle {
            id: clapper
            width: 14; height: 14; radius: 7; color: ic.fg
            x: 58 - 7; y: 131 - 7
        }
    }
    // sound waves
    Shape {
        id: waves
        anchors.fill: parent
        opacity: 0.9
        preferredRendererType: Shape.CurveRenderer
        ShapePath { strokeColor: ic.dim; strokeWidth: 1.4; fillColor: "transparent"; capStyle: ShapePath.RoundCap
            startX: 103; startY: 31; PathQuad { controlX: 113; controlY: 44; x: 111; y: 63 } }
        ShapePath { strokeColor: ic.dim; strokeWidth: 1.4; fillColor: "transparent"; capStyle: ShapePath.RoundCap
            startX: 111; startY: 22; PathQuad { controlX: 125; controlY: 40; x: 121; y: 66 } }
    }
    SequentialAnimation {
        id: idle
        running: ic.live && !Theme.reducedMotion
        loops: Animation.Infinite
        PauseAnimation { duration: 7000 }
        NumberAnimation { target: rot; property: "angle"; to: 4; duration: 220; easing.type: Easing.InOutSine }
        NumberAnimation { target: rot; property: "angle"; to: -4; duration: 380; easing.type: Easing.InOutSine }
        NumberAnimation { target: rot; property: "angle"; to: 0; duration: 300; easing.type: Easing.OutSine }
    }
    SequentialAnimation {
        id: ringing
        onStopped: if (ic.live && !Theme.reducedMotion) idle.restart()
        ParallelAnimation {
            SequentialAnimation {
                NumberAnimation { target: rot; property: "angle"; to: 16; duration: 70 }
                NumberAnimation { target: rot; property: "angle"; to: -14; duration: 120 }
                NumberAnimation { target: rot; property: "angle"; to: 11; duration: 110 }
                NumberAnimation { target: rot; property: "angle"; to: -8; duration: 100 }
                NumberAnimation { target: rot; property: "angle"; to: 6; duration: 100 }
                NumberAnimation { target: rot; property: "angle"; to: -4; duration: 100 }
                NumberAnimation { target: rot; property: "angle"; to: 2; duration: 100 }
                NumberAnimation { target: rot; property: "angle"; to: 0; duration: 120 }
            }
            SequentialAnimation {
                loops: 4
                NumberAnimation { target: waves; property: "opacity"; to: 0.2; duration: 100 }
                NumberAnimation { target: waves; property: "opacity"; to: 1.0; duration: 100 }
            }
        }
    }
    Connections { target: ic; function onHoveredChanged() { if (ic.hovered && !Theme.reducedMotion && !ringing.running) hoverSwing.restart() } }
    SequentialAnimation {
        id: hoverSwing
        NumberAnimation { target: rot; property: "angle"; to: 7; duration: 120; easing.type: Easing.OutSine }
        NumberAnimation { target: rot; property: "angle"; to: -5; duration: 200; easing.type: Easing.InOutSine }
        NumberAnimation { target: rot; property: "angle"; to: 0; duration: 220; easing.type: Easing.OutBack }
    }
}
