// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// AI task, expanded form: click to see the live steps; hover for pause / resume / cancel; drag a queued row to reorder.
import QtQuick
import Friday

Item {
    id: c
    required property var model
    required property int index
    property ListView list
    property bool recent: false
    property bool live: true
    signal openA()
    readonly property real u: Theme.u
    readonly property string status: model.status || "queued"
    property bool open: false
    property bool askCancel: false
    property bool dragging: false
    readonly property var steps: model.steps || []
    height: head.height + (open ? details.implicitHeight + 16 * u : 0)
    Behavior on height { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
    clip: true

    Rectangle { anchors.fill: parent; radius: 10 * c.u; color: c.dragging ? "#1A1A1A" : (c.open ? "#0E0E0E" : (hov.hovered ? "#0B0B0B" : "transparent")) }
    HoverHandler { id: hov; onHoveredChanged: if (!hovered) c.askCancel = false }

    Item {
        id: head
        width: parent.width; height: 58 * c.u
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: c.open = !c.open }
        Text {
            visible: c.status === "queued" && !c.recent
            x: 4 * c.u; anchors.verticalCenter: parent.verticalCenter
            text: "⋮⋮"; color: dragMa.containsMouse || c.dragging ? Theme.fgTile : "#3E3E3C"; font.family: Theme.mono; font.pixelSize: 14 * c.u
            MouseArea {
                id: dragMa
                anchors.fill: parent; anchors.margins: -8 * c.u; hoverEnabled: true; cursorShape: Qt.SizeVerCursor; preventStealing: true
                onPressed: c.dragging = true
                onReleased: c.dragging = false
                onCanceled: c.dragging = false
                onPositionChanged: (m) => {
                    if (!c.dragging || !c.list) return
                    var p = mapToItem(c.list.contentItem, m.x, m.y)
                    var to = c.list.indexAt(10, p.y)
                    if (to >= 0 && to !== c.index) Core.action("agent_task.reorder", { "id": c.model.id, "index": to })
                }
            }
        }
        StatusGlyph { x: 30 * c.u; anchors.verticalCenter: parent.verticalCenter; status: c.status; live: c.live; fg: c.recent ? "#7A7A77" : Theme.fgTile }
        Text { x: 64 * c.u; anchors.verticalCenter: parent.verticalCenter; width: actions.x - x - 16 * c.u
               text: c.model.title || ""; textFormat: Text.PlainText; elide: Text.ElideRight
               color: c.recent ? "#7A7A77" : Theme.fgTile; font.family: Theme.display; font.pixelSize: 20 * c.u }
        Row {
            id: actions
            anchors.right: parent.right; anchors.rightMargin: 10 * c.u; anchors.verticalCenter: parent.verticalCenter
            spacing: 10 * c.u
            Row {
                visible: hov.hovered && !c.recent && !c.askCancel && c.status !== "awaiting"
                spacing: 2 * c.u
                anchors.verticalCenter: parent.verticalCenter
                GlyphButton { visible: c.status === "running" || c.status === "queued"; glyph: "‖"; onClicked: Core.action("agent_task.pause", { "id": c.model.id }) }
                GlyphButton { visible: c.status === "paused"; glyph: "▶"; px: 13; onClicked: Core.action("agent_task.resume", { "id": c.model.id }) }
                GlyphButton { glyph: "×"; onClicked: c.status === "running" ? c.askCancel = true : Core.action("agent_task.cancel", { "id": c.model.id }) }
            }
            Row {
                visible: c.askCancel
                spacing: 8 * c.u
                anchors.verticalCenter: parent.verticalCenter
                Text { text: "Cancel?"; color: Theme.fgTile; font.family: Theme.mono; font.pixelSize: 14 * c.u; anchors.verticalCenter: parent.verticalCenter }
                TextButton { text: "Yes"; fontPx: 13; implicitHeight: 26 * c.u; fg: Theme.accent; onClicked: { c.askCancel = false; Core.action("agent_task.cancel", { "id": c.model.id }) } }
                TextButton { text: "No"; fontPx: 13; implicitHeight: 26 * c.u; onClicked: c.askCancel = false }
            }
            Chip { anchors.verticalCenter: parent.verticalCenter; text: c.status === "awaiting" ? "confirm" : (c.model.source || "")
                   fg: c.status === "awaiting" ? Theme.accent : (c.recent ? "#7A7A77" : Theme.fgTile); line: c.status === "awaiting" ? Theme.accent : "#4A4A48" }
            Text { anchors.verticalCenter: parent.verticalCenter; text: c.model.meta || ""; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * c.u
                   width: 64 * c.u; horizontalAlignment: Text.AlignRight }
            Text { anchors.verticalCenter: parent.verticalCenter; text: c.open ? "▾" : "▸"; color: "#5E5E5B"; font.pixelSize: 12 * c.u }
        }
        Item {
            x: 20 * c.u; width: parent.width - 40 * c.u; anchors.bottom: parent.bottom; height: 1.5 * c.u; clip: true
            Rectangle { width: parent.width; height: 1; color: Theme.hairline }
            Rectangle {
                visible: c.status === "running" && (c.model.progress === undefined || c.model.progress < 0)
                height: 1.5 * c.u; width: parent.width * 0.4
                property real t: 0
                x: -width + t * (parent.width + width)
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.6; color: Qt.rgba(1, 1, 1, 0.85) } GradientStop { position: 1; color: "transparent" } }
                NumberAnimation on t { running: c.live && c.status === "running" && !Theme.reducedMotion; from: 0; to: 1; duration: 1500; loops: Animation.Infinite }
            }
            Rectangle { visible: c.status === "running" && c.model.progress >= 0; height: 1.5 * c.u; width: parent.width * Math.max(0, c.model.progress || 0); color: Theme.fgTile
                        Behavior on width { NumberAnimation { duration: Theme.d(Theme.base) } } }
        }
    }
    Column {
        id: details
        visible: c.open
        x: 64 * c.u; y: head.height + 8 * c.u
        width: parent.width - x - 24 * c.u
        spacing: 6 * c.u
        Text { width: parent.width; text: c.model.detail || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * c.u }
        TextButton { visible: c.status === "awaiting"; text: "Awaiting your approval → open A"; fg: Theme.accent; fontPx: 14; implicitHeight: 30 * c.u; onClicked: c.openA() }
        Repeater {
            model: c.steps
            delegate: Row {
                id: step
                required property var modelData
                required property int index
                spacing: 10 * c.u
                opacity: 0
                Component.onCompleted: if (index === c.steps.length - 1 && !Theme.reducedMotion) fadeIn.start(); else opacity = 1
                NumberAnimation { id: fadeIn; target: step; property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                Text { width: 18 * c.u; text: step.modelData.state === "done" ? "✓" : (step.modelData.state === "running" ? "›" : "…")
                       color: step.modelData.state === "running" ? Theme.fgTile : "#6E6E6B"; font.family: Theme.mono; font.pixelSize: 14 * c.u }
                Text { text: step.modelData.text; textFormat: Text.PlainText; color: step.modelData.state === "running" ? Theme.fgTile : Theme.dimOnTile
                       font.family: Theme.mono; font.pixelSize: 14 * c.u }
            }
        }
        Text { visible: c.steps.length === 0; text: "not started"; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 13 * c.u }
    }
}
