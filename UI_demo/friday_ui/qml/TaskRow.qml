// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// One AI task row (compact form): status glyph, title, source chip, ETA / next run, shimmer while running.
import QtQuick
import Friday

Item {
    id: r
    required property var model
    property bool recent: false
    property bool live: true
    readonly property real u: Theme.u
    readonly property string status: model.status || "queued"
    readonly property bool awaiting: status === "awaiting"
    readonly property color txt: recent ? "#6E6E6B" : Theme.fgTile

    StatusGlyph { x: 31 * r.u; anchors.verticalCenter: parent.verticalCenter; status: r.status; live: r.live
                  fg: r.recent ? "#6E6E6B" : Theme.fgTile }
    Text {
        x: 66 * r.u; anchors.verticalCenter: parent.verticalCenter
        width: chip.x - x - 12 * r.u
        text: r.model.title || ""; textFormat: Text.PlainText; elide: Text.ElideRight
        color: r.txt; font.family: Theme.display; font.pixelSize: 18 * r.u
    }
    Chip {
        id: chip
        anchors.right: meta.left; anchors.rightMargin: 12 * r.u; anchors.verticalCenter: parent.verticalCenter
        text: r.awaiting ? "confirm" : (r.model.source || "")
        fg: r.awaiting ? Theme.accent : (r.recent ? "#6E6E6B" : Theme.fgTile)
        line: r.awaiting ? Theme.accent : (r.recent ? "#2E2E2C" : "#4A4A48")
    }
    Text {
        id: meta
        anchors.right: parent.right; anchors.rightMargin: 30 * r.u; anchors.verticalCenter: parent.verticalCenter
        text: r.model.meta || ""
        color: r.recent ? "#5E5E5B" : Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * r.u
    }
    // separator; while running an indeterminate shimmer travels along it (or a determinate bar)
    Item {
        x: 30 * r.u; width: parent.width - 60 * r.u
        anchors.bottom: parent.bottom; height: 1
        clip: true
        Rectangle { anchors.fill: parent; color: Theme.hairline }
        Rectangle {
            visible: r.status === "running" && (r.model.progress === undefined || r.model.progress < 0)
            height: 1.5 * r.u; y: -0.25 * r.u
            width: parent.width * 0.55
            property real t: 0
            x: -width + t * (parent.width + width)
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.6; color: Qt.rgba(1, 1, 1, 0.85) }
                GradientStop { position: 1.0; color: "transparent" } }
            NumberAnimation on t { running: r.live && r.status === "running" && !Theme.reducedMotion; from: 0; to: 1; duration: 1500; loops: Animation.Infinite }
        }
        Rectangle {
            visible: r.status === "running" && r.model.progress !== undefined && r.model.progress >= 0
            height: 1.5 * r.u; width: parent.width * Math.max(0, r.model.progress || 0); color: Theme.fgTile
            Behavior on width { NumberAnimation { duration: Theme.d(Theme.base) } }
        }
    }
}
