// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Task status glyphs (brief 5G): queued, running, awaiting, done, failed / cancelled, paused.
import QtQuick
import QtQuick.Shapes
import Friday

Item {
    id: g
    property string status: "queued"
    property color fg: Theme.fgTile
    property color dim: "#3A3A38"
    property real u: Theme.u
    property bool live: true
    implicitWidth: 20 * u
    implicitHeight: 20 * u
    readonly property real r: 8 * u
    readonly property real lw: Math.max(1.3, 1.6 * u)

    // queued / paused: hollow circle
    Rectangle {
        visible: g.status === "queued" || g.status === "paused"
        anchors.centerIn: parent
        width: g.r * 2; height: width; radius: width / 2
        color: "transparent"; border.color: g.status === "paused" ? g.dim : g.fg; border.width: g.lw
        Rectangle { visible: g.status === "paused"; anchors.centerIn: parent; width: 5 * g.u; height: 5 * g.u; color: "transparent"
            Rectangle { x: 0; width: 1.6 * g.u; height: parent.height; color: Theme.dimOnTile }
            Rectangle { x: parent.width - width; width: 1.6 * g.u; height: parent.height; color: Theme.dimOnTile } }
    }
    // running: dim ring with a rotating arc
    Item {
        visible: g.status === "running"
        anchors.fill: parent
        Rectangle { anchors.centerIn: parent; width: g.r * 2; height: width; radius: width / 2; color: "transparent"; border.color: g.dim; border.width: g.lw }
        Shape {
            id: arc
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: g.fg; strokeWidth: g.lw; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: g.width / 2; centerY: g.height / 2; radiusX: g.r; radiusY: g.r; startAngle: 120; sweepAngle: 150 }
            }
            RotationAnimation on rotation { running: g.status === "running" && g.live && !Theme.reducedMotion; from: 0; to: 360; duration: 1100; loops: Animation.Infinite }
        }
    }
    // awaiting confirmation: pulsing accent dot
    Item {
        visible: g.status === "awaiting"
        anchors.fill: parent
        Rectangle { anchors.centerIn: parent; width: g.r * 2; height: width; radius: width / 2; color: "transparent"; border.color: Theme.accent; border.width: g.lw }
        Rectangle {
            id: dot
            anchors.centerIn: parent; width: 9 * g.u; height: width; radius: width / 2; color: Theme.accent
            SequentialAnimation on opacity {
                running: g.status === "awaiting" && g.live && !Theme.reducedMotion; loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
            }
        }
    }
    // done: circle + check that draws itself
    Item {
        visible: g.status === "done"
        anchors.fill: parent
        Rectangle { anchors.centerIn: parent; width: g.r * 2; height: width; radius: width / 2; color: "transparent"; border.color: g.fg; border.width: g.lw }
        Item {
            height: parent.height; clip: true
            width: g.status === "done" ? parent.width : 0
            Behavior on width { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
            Shape {
                width: g.width; height: g.height
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: g.fg; strokeWidth: g.lw; fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                    startX: g.width * 0.33; startY: g.height * 0.52
                    PathLine { x: g.width * 0.46; y: g.height * 0.64 }
                    PathLine { x: g.width * 0.68; y: g.height * 0.38 }
                }
            }
        }
    }
    // failed / cancelled: a cross that shakes three times
    Item {
        id: cross
        visible: g.status === "failed" || g.status === "cancelled"
        width: parent.width; height: parent.height
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: g.status === "failed" ? Theme.accent : g.fg; strokeWidth: g.lw; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                startX: g.width * 0.3; startY: g.height * 0.3
                PathLine { x: g.width * 0.7; y: g.height * 0.7 }
                PathMove { x: g.width * 0.7; y: g.height * 0.3 }
                PathLine { x: g.width * 0.3; y: g.height * 0.7 }
            }
        }
        onVisibleChanged: if (visible && !Theme.reducedMotion) shake.restart()
        SequentialAnimation {
            id: shake
            loops: 3
            NumberAnimation { target: cross; property: "x"; to: 2.5 * g.u; duration: 45 }
            NumberAnimation { target: cross; property: "x"; to: -2.5 * g.u; duration: 90 }
            NumberAnimation { target: cross; property: "x"; to: 0; duration: 45 }
        }
    }
}
