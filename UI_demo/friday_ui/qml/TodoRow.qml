// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// One to-do row: check draw + strike-through, drag to reorder, swipe left (or ×) to delete, untrusted = plain + tag.
import QtQuick
import Friday
import "fmt.js" as Fmt

Item {
    id: row
    required property int index
    required property var model
    property ListView list
    signal deleted(string id, string text)
    readonly property real u: Theme.u
    readonly property bool done: !!model.done
    property bool ticking: false
    readonly property bool showChecked: done !== ticking
    property bool dragging: false
    clip: false

    Timer {
        id: commit
        interval: row.done ? 380 : 600
        onTriggered: { Core.action("todo.toggle", { "id": row.model.id, "done": !row.done }); row.ticking = false }
    }

    Item {
        id: content
        width: row.width; height: row.height
        Rectangle { anchors.fill: parent; color: row.dragging ? "#161616" : (hov.hovered ? "#0D0D0D" : "transparent"); radius: 8 * row.u }

        // drag handle (open items only)
        Text {
            id: handle
            visible: !row.done
            x: 0; anchors.verticalCenter: parent.verticalCenter
            text: "⋮⋮"; color: dragMa.containsMouse || row.dragging ? Theme.fgTile : "#4A4A48"
            font.family: Theme.mono; font.pixelSize: 15 * row.u
            MouseArea {
                id: dragMa
                anchors.fill: parent; anchors.margins: -8 * row.u
                hoverEnabled: true
                cursorShape: Qt.SizeVerCursor
                preventStealing: true
                onPressed: row.dragging = true
                onReleased: row.dragging = false
                onCanceled: row.dragging = false
                onPositionChanged: (m) => {
                    if (!row.dragging || !row.list) return
                    var p = mapToItem(row.list.contentItem, m.x, m.y)
                    var to = Math.max(0, Math.min(row.list.count - 1, Math.floor(p.y / row.height)))
                    if (to !== row.index) Core.action("todo.reorder", { "id": row.model.id, "index": to })
                }
            }
        }
        CheckDraw {
            id: check
            x: 30 * row.u; anchors.verticalCenter: parent.verticalCenter
            checked: row.showChecked
            onClicked: { if (commit.running) return; row.ticking = true; commit.start() }
        }
        Item {
            id: textBox
            x: 66 * row.u
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - x - rightBox.width - 20 * row.u
            height: label.implicitHeight
            Text {
                id: label
                width: parent.width
                text: row.model.text || ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: row.showChecked ? Theme.dimOnTile : Theme.fgTile
                font.family: Theme.display
                font.pixelSize: 19 * row.u
                Behavior on color { ColorAnimation { duration: Theme.d(Theme.base) } }
            }
            Rectangle {   // strike-through, drawn left to right
                y: label.height * 0.54
                height: Math.max(1, 1.5 * row.u)
                width: row.showChecked ? Math.min(label.paintedWidth, label.width) : 0
                color: Theme.dimOnTile
                Behavior on width { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
            }
        }
        Row {
            id: rightBox
            anchors.right: parent.right; anchors.rightMargin: 4 * row.u
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14 * row.u
            ExtTag { visible: !!row.model.untrusted; anchors.verticalCenter: parent.verticalCenter }
            Text {
                visible: !!row.model.due
                anchors.verticalCenter: parent.verticalCenter
                text: row.model.due ? (Fmt.dayLabel(row.model.due, Core.now) + " " + Fmt.hhmm(row.model.due)) : ""
                color: row.model.due && row.model.due < Core.now && !row.done ? Theme.accent : Theme.dimOnTile
                font.family: Theme.mono; font.pixelSize: 13 * row.u
            }
            PriorityTicks {
                anchors.verticalCenter: parent.verticalCenter
                prio: row.model.priority || 1
                fg: row.done ? Theme.dimOnTile : Theme.fgTile
                onCycled: Core.action("todo.update", { "id": row.model.id, "priority": (row.model.priority || 1) % 3 + 1 })
            }
            GlyphButton { glyph: "×"; anchors.verticalCenter: parent.verticalCenter
                          onClicked: { row.deleted(row.model.id, row.model.text); Core.action("todo.delete", { "id": row.model.id }) } }
        }
        Hairline { anchors.bottom: parent.bottom; width: parent.width }
        HoverHandler { id: hov }
        DragHandler {
            id: swipe
            target: content
            xAxis.enabled: true; yAxis.enabled: false
            xAxis.maximum: 0
            onActiveChanged: {
                if (!active) {
                    if (content.x < -110 * row.u) { row.deleted(row.model.id, row.model.text); Core.action("todo.delete", { "id": row.model.id }) }
                    else back.restart()
                }
            }
        }
        NumberAnimation { id: back; target: content; property: "x"; to: 0; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic }
    }
    Text {
        visible: content.x < -20 * row.u
        anchors.right: parent.right; anchors.rightMargin: 10 * row.u; anchors.verticalCenter: parent.verticalCenter
        text: "delete"; color: content.x < -110 * row.u ? Theme.accent : Theme.dimOnTile
        font.family: Theme.mono; font.pixelSize: 13 * row.u; z: -1
    }
    SequentialAnimation {
        id: shake
        loops: 3
        NumberAnimation { target: content; property: "x"; to: 6 * row.u; duration: 45 }
        NumberAnimation { target: content; property: "x"; to: -6 * row.u; duration: 90 }
        NumberAnimation { target: content; property: "x"; to: 0; duration: 45 }
    }
    Connections {
        target: Core
        function onCoreEvent(name, p) { if (name === "action.rejected" && p.itemId === row.model.id) { row.ticking = false; if (!Theme.reducedMotion) shake.restart() } }
    }
}
