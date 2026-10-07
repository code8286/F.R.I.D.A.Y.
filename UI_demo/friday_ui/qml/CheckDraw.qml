// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Round checkbox whose tick draws itself left to right (brief 5D).
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: cb
    property bool checked: false
    property color fg: Theme.fgTile
    property color fill: Theme.fgTile
    property color tickColor: "#000000"
    property real u: Theme.u
    property real draw: checked ? 1 : 0
    signal clicked()
    implicitWidth: 20 * u
    implicitHeight: 20 * u
    Behavior on draw { NumberAnimation { duration: Theme.d(Theme.fast); easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: cb.draw > 0.01 ? Qt.rgba(cb.fill.r, cb.fill.g, cb.fill.b, Math.min(1, cb.draw * 1.5)) : "transparent"
        border.color: cb.fg
        border.width: Math.max(1.2, 1.5 * cb.u)
    }
    Item {
        id: clipper
        x: 0; y: 0; height: parent.height
        width: parent.width * cb.draw
        clip: true
        Shape {
            width: cb.width; height: cb.height
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: cb.tickColor
                strokeWidth: Math.max(1.4, 1.8 * cb.u)
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                startX: cb.width * 0.28; startY: cb.height * 0.52
                PathLine { x: cb.width * 0.44; y: cb.height * 0.68 }
                PathLine { x: cb.width * 0.73; y: cb.height * 0.35 }
            }
        }
    }
    MouseArea { anchors.fill: parent; anchors.margins: -6 * cb.u; cursorShape: Qt.PointingHandCursor; onClicked: cb.clicked() }
}
