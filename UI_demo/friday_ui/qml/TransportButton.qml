// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// prev / play / pause / next glyphs, drawn as line art.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: tb
    property string kind: "play"
    property bool ring: false
    property real size: 1.0
    property color fg: Theme.fgTile
    property real u: Theme.u
    signal clicked()
    readonly property real s: 20 * u * size
    implicitWidth: (ring ? 37 : 26) * u * size
    implicitHeight: implicitWidth
    scale: ma.pressed ? 0.92 : (ma.containsMouse ? 1.06 : 1)
    Behavior on scale { NumberAnimation { duration: Theme.d(Theme.fast) } }

    Rectangle { visible: tb.ring; anchors.fill: parent; radius: width / 2; color: "transparent"; border.color: tb.fg; border.width: Math.max(1.2, 1.5 * tb.u) }
    Item {
        anchors.centerIn: parent
        width: tb.s; height: tb.s
        // pause
        Row { visible: tb.kind === "pause"; anchors.centerIn: parent; spacing: tb.s * 0.18
              Rectangle { width: tb.s * 0.16; height: tb.s * 0.6; color: tb.fg; radius: 1 }
              Rectangle { width: tb.s * 0.16; height: tb.s * 0.6; color: tb.fg; radius: 1 } }
        Shape {
            visible: tb.kind !== "pause"
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: tb.fg; strokeColor: "transparent"
                startX: tb.kind === "prev" ? tb.s * 0.86 : (tb.kind === "next" ? tb.s * 0.14 : tb.s * 0.32)
                startY: tb.s * 0.18
                PathLine { x: tb.kind === "prev" ? tb.s * 0.32 : (tb.kind === "next" ? tb.s * 0.68 : tb.s * 0.82); y: tb.s * 0.5 }
                PathLine { x: tb.kind === "prev" ? tb.s * 0.86 : (tb.kind === "next" ? tb.s * 0.14 : tb.s * 0.32); y: tb.s * 0.82 }
                PathLine { x: tb.kind === "prev" ? tb.s * 0.86 : (tb.kind === "next" ? tb.s * 0.14 : tb.s * 0.32); y: tb.s * 0.18 }
            }
        }
        Rectangle { visible: tb.kind === "prev"; x: tb.s * 0.14; y: tb.s * 0.18; width: tb.s * 0.12; height: tb.s * 0.64; color: tb.fg }
        Rectangle { visible: tb.kind === "next"; x: tb.s * 0.74; y: tb.s * 0.18; width: tb.s * 0.12; height: tb.s * 0.64; color: tb.fg }
    }
    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -4 * tb.u; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tb.clicked() }
}
