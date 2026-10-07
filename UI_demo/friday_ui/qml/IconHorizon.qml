// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile A icon (black on coral): a horizon with a rising arc; three dots creep along it. A new notification pings the arc.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: ic
    property color fg: Theme.fgAccent
    property bool live: true
    property bool hovered: false
    width: 160; height: 90
    property real creep: 0
    function ping() { if (!Theme.reducedMotion) pingAnim.restart() }
    readonly property real cx0: 80
    readonly property real cy0: 65
    function px(deg, r) { return cx0 + r * Math.cos(deg * Math.PI / 180) }
    function py(deg, r) { return cy0 - r * Math.sin(deg * Math.PI / 180) }

    Rectangle { x: 0; y: ic.cy0; width: 160; height: 1.5; color: ic.fg }
    Item {
        id: arcs
        width: parent.width; height: parent.height
        transform: Scale { id: sc; origin.x: ic.cx0; origin.y: ic.cy0; xScale: 1; yScale: 1 }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath { strokeColor: ic.fg; strokeWidth: 1.5; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 60; radiusY: 60; startAngle: 180; sweepAngle: 180 } }
            ShapePath { strokeColor: Qt.rgba(ic.fg.r, ic.fg.g, ic.fg.b, 0.42); strokeWidth: 1.5; fillColor: "transparent"
                PathAngleArc { centerX: ic.cx0; centerY: ic.cy0; radiusX: 38; radiusY: 38; startAngle: 180; sweepAngle: 180 } }
        }
        Repeater {
            model: [ { a: 134, r: 5, o: 1 }, { a: 90, r: 7, o: 1 }, { a: 46, r: 5, o: 0.42 } ]
            delegate: Rectangle {
                required property var modelData
                readonly property real ang: Math.max(8, Math.min(172, modelData.a - ic.creep))
                width: modelData.r * 2; height: width; radius: width / 2
                color: Qt.rgba(ic.fg.r, ic.fg.g, ic.fg.b, modelData.o)
                x: ic.px(ang, 60) - width / 2; y: ic.py(ang, 60) - height / 2
            }
        }
    }
    Repeater {
        model: 11
        delegate: Rectangle { required property int index; width: 2.6; height: 2.6; radius: 1.3; color: ic.fg; x: 22 + index * 11.2; y: 82 }
    }
    SequentialAnimation on creep {
        running: ic.live && !Theme.reducedMotion
        loops: Animation.Infinite
        NumberAnimation { from: 0; to: 22; duration: 30000; easing.type: Easing.InOutSine }
        NumberAnimation { from: 22; to: 0; duration: 30000; easing.type: Easing.InOutSine }
    }
    SequentialAnimation {
        id: pingAnim
        ParallelAnimation {
            NumberAnimation { target: sc; property: "xScale"; to: 1.06; duration: 120; easing.type: Easing.OutCubic }
            NumberAnimation { target: sc; property: "yScale"; to: 1.06; duration: 120; easing.type: Easing.OutCubic }
        }
        ParallelAnimation {
            NumberAnimation { target: sc; property: "xScale"; to: 1; duration: 260; easing.type: Easing.OutBack }
            NumberAnimation { target: sc; property: "yScale"; to: 1; duration: 260; easing.type: Easing.OutBack }
        }
    }
    onHoveredChanged: if (hovered) ping()
}
