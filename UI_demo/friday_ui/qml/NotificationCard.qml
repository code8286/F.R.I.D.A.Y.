// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// A notification on the coral tile. Confirmation cards carry the code-built action text, its tier and Approve / Deny.
import QtQuick
import Friday
import "fmt.js" as Fmt

Item {
    id: card
    required property var model
    readonly property real u: Theme.u
    readonly property bool isConfirm: model.kind === "confirm"
    readonly property string resolved: model.resolved || ""
    height: box.height

    Rectangle {
        id: box
        width: card.width
        height: col.implicitHeight + 28 * card.u
        radius: 14 * card.u
        color: card.isConfirm ? "#000000" : Qt.rgba(0, 0, 0, card.model.read ? 0.05 : 0.10)
        border.color: card.isConfirm ? "#000000" : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.d(Theme.base) } }

        Column {
            id: col
            x: 18 * card.u; y: 14 * card.u
            width: parent.width - 36 * card.u - 30 * card.u
            spacing: 6 * card.u
            Row {
                spacing: 10 * card.u
                Rectangle { visible: !card.model.read && !card.isConfirm; width: 7 * card.u; height: width; radius: width / 2; color: Theme.fgAccent; anchors.verticalCenter: parent.verticalCenter }
                Text { text: (card.isConfirm ? "CONFIRM" : (card.model.kind || "").toUpperCase()) + " · " + Fmt.ago(Core.now - (card.model.ts || Core.now))
                       color: card.isConfirm ? Theme.accent : Qt.rgba(0, 0, 0, 0.6); font.family: Theme.mono; font.pixelSize: 11 * card.u; font.letterSpacing: 1.2 * card.u }
                Chip { visible: card.isConfirm; text: "T" + (card.model.tier || 2); fg: Theme.accent; line: Theme.accent; fontPx: 11; implicitHeight: 18 * card.u; anchors.verticalCenter: parent.verticalCenter }
                ExtTag { visible: !!card.model.untrusted; fg: card.isConfirm ? Theme.accent : Theme.fgAccent; anchors.verticalCenter: parent.verticalCenter }
            }
            Text { width: parent.width; text: card.isConfirm ? (card.model.action || "Approve this action?") : (card.model.title || "")
                   textFormat: Text.PlainText; wrapMode: Text.Wrap
                   color: card.isConfirm ? Theme.fgTile : Theme.fgAccent; font.family: Theme.display; font.pixelSize: 19 * card.u }
            Text { width: parent.width; text: card.model.text || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; maximumLineCount: card.isConfirm ? 4 : 3; elide: Text.ElideRight
                   color: card.isConfirm ? Theme.dimOnTile : Qt.rgba(0, 0, 0, 0.72); font.family: card.isConfirm ? Theme.mono : Theme.display; font.pixelSize: (card.isConfirm ? 13 : 16) * card.u }
            Row {
                visible: card.isConfirm
                spacing: 10 * card.u
                topPadding: 6 * card.u
                TextButton { visible: card.resolved === ""; text: "Approve"; filled: true; fg: Theme.accent; fontPx: 15; implicitHeight: 32 * card.u
                             onClicked: Core.action("confirm.respond", { "id": card.model.id, "approve": true }) }
                TextButton { visible: card.resolved === ""; text: "Deny"; fg: Theme.fgTile; fontPx: 15; implicitHeight: 32 * card.u
                             onClicked: Core.action("confirm.respond", { "id": card.model.id, "approve": false }) }
                Text { visible: card.resolved !== ""; text: card.resolved === "approved" ? "Approved ✓ · the core is running it" : "Denied · nothing was run"
                       color: card.resolved === "approved" ? Theme.fgTile : Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * card.u }
            }
        }
        GlyphButton { anchors.right: parent.right; anchors.rightMargin: 8 * card.u; y: 8 * card.u; glyph: "×"
                      fg: card.isConfirm ? Theme.dimOnTile : Qt.rgba(0, 0, 0, 0.55); hoverFg: card.isConfirm ? Theme.fgTile : Theme.fgAccent
                      onClicked: Core.action("notification.dismiss", { "id": card.model.id }) }
        DragHandler {
            target: box
            xAxis.enabled: true; yAxis.enabled: false
            xAxis.minimum: 0
            onActiveChanged: if (!active) { if (box.x > 120 * card.u) Core.action("notification.dismiss", { "id": card.model.id }); else snap.restart() }
        }
        NumberAnimation { id: snap; target: box; property: "x"; to: 0; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic }
    }
}
