// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// One reminder: text, time, done, snooze menu (5 min, 15 min, 1 h, tomorrow), delete.
import QtQuick
import Friday
import "fmt.js" as Fmt

Item {
    id: row
    required property var model
    property bool overdue: false
    readonly property real u: Theme.u
    property bool menu: false

    Rectangle { anchors.fill: parent; color: hov.hovered ? "#0D0D0D" : "transparent"; radius: 8 * row.u }
    HoverHandler { id: hov; onHoveredChanged: if (!hovered) row.menu = false }
    Rectangle { x: 4 * row.u; anchors.verticalCenter: parent.verticalCenter; width: 8 * row.u; height: width; radius: width / 2
                color: row.overdue ? Theme.accent : "transparent"; border.color: row.overdue ? Theme.accent : Theme.fgTile; border.width: 1.2 }
    Text {
        x: 30 * row.u; anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x - actions.width - timeText.width - 40 * row.u
        text: row.model.text || ""; textFormat: Text.PlainText; elide: Text.ElideRight
        color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 19 * row.u
    }
    ExtTag { visible: !!row.model.untrusted; anchors.right: timeText.left; anchors.rightMargin: 12 * row.u; anchors.verticalCenter: parent.verticalCenter }
    Text {
        id: timeText
        anchors.right: actions.left; anchors.rightMargin: 20 * row.u; anchors.verticalCenter: parent.verticalCenter
        text: Fmt.dayLabel(row.model.at, Core.now) + " " + Fmt.hhmm(row.model.at)
        color: row.overdue ? Theme.accent : Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * row.u
    }
    Row {
        id: actions
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        spacing: 4 * row.u
        Row {
            visible: row.menu
            spacing: 6 * row.u
            anchors.verticalCenter: parent.verticalCenter
            Repeater {
                model: [ { k: "5m", t: "5 min" }, { k: "15m", t: "15 min" }, { k: "1h", t: "1 h" }, { k: "tomorrow", t: "tomorrow" } ]
                Chip { required property var modelData; text: modelData.t; fontPx: 12; implicitHeight: 24 * row.u; anchors.verticalCenter: parent.verticalCenter
                       MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                   onClicked: { row.menu = false; Core.action("reminder.snooze", { "id": row.model.id, "choice": parent.modelData.k }) } } }
            }
        }
        GlyphButton { glyph: "zz"; px: 13; anchors.verticalCenter: parent.verticalCenter; onClicked: row.menu = !row.menu }
        GlyphButton { glyph: "✓"; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("reminder.done", { "id": row.model.id }) }
        GlyphButton { glyph: "×"; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("reminder.delete", { "id": row.model.id }) }
    }
    Hairline { anchors.bottom: parent.bottom; width: parent.width }
}
