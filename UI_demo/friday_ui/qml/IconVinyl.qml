// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile F icon: a record and tonearm. Spins at 33 1/3 rpm only while playing (spin-up 400 ms, spin-down 800 ms);
// the tonearm lifts 6 degrees on pause. Clicking it toggles play/pause.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property bool playing: false
    property bool live: true
    property bool hovered: false
    width: 166; height: 160
    readonly property real cx0: 74
    readonly property real cy0: 85
    property real speed: playing && live && !Theme.reducedMotion ? 1 : 0     // 0..1 of 0.555 rev/s
    Behavior on speed { NumberAnimation { duration: ic.playing ? 400 : 800; easing.type: ic.playing ? Easing.OutCubic : Easing.OutQuad } }
    property real angle: 0
    FrameAnimation {
        running: ic.speed > 0.001
        onTriggered: ic.angle = (ic.angle + ic.speed * 0.555 * 360 * frameTime) % 360
    }

    Item {
        id: disc
        width: parent.width; height: parent.height
        transform: Rotation { origin.x: ic.cx0; origin.y: ic.cy0; angle: ic.angle }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 72; radiusY: 72; startAngle: 0; sweepAngle: 360 } }
            ShapePath { strokeColor: "#6E6E6B"; strokeWidth: 1; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 61; radiusY: 61; startAngle: 0; sweepAngle: 360 } }
            ShapePath { strokeColor: "#6E6E6B"; strokeWidth: 1; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 49; radiusY: 49; startAngle: 0; sweepAngle: 360 } }
            ShapePath { strokeColor: "#BDBDB9"; strokeWidth: 1; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 38; radiusY: 38; startAngle: 0; sweepAngle: 360 } }
        }
        Rectangle { width: 40; height: 40; radius: 20; color: ic.fg; x: ic.cx0 - 20; y: ic.cy0 - 20 }
        Rectangle { width: 5; height: 5; radius: 2.5; color: "#000000"; x: ic.cx0 - 2.5; y: ic.cy0 - 2.5 }
        Rectangle { width: 3; height: 3; radius: 1.5; color: "#9A9A96"; x: ic.cx0 - 1.5; y: ic.cy0 - 13 }   // shows the spin
    }
    // reflection (does not rotate)
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath { strokeColor: "#9A9A96"; strokeWidth: 2.6; fillColor: "transparent"; capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 55; radiusY: 55; startAngle: -112; sweepAngle: 40 } }
    }
    // tonearm
    Item {
        id: arm
        width: parent.width; height: parent.height
        transform: Rotation { origin.x: 158; origin.y: 8; angle: ic.playing ? 0 : -6
            Behavior on angle { NumberAnimation { duration: Theme.d(400); easing.type: Easing.InOutCubic } } }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                startX: 157.5; startY: 14; PathLine { x: 150; y: 92 } PathLine { x: 127; y: 110 } }
        }
        Rectangle { x: 152; y: 2; width: 12; height: 12; radius: 6; color: "transparent"; border.color: ic.fg; border.width: 1.5 }
    }
}
