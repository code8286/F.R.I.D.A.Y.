// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile C: reminders (brief 5C). Overdue / Today / Later, snooze menu, due state rings the bell.
import QtQuick
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "Reminders"
    property bool live: true
    readonly property var st: Core.stats

    Timer { id: invertTimer; interval: 1200; onTriggered: tile.titleInvert = false }
    Connections {
        target: Core
        function onCoreEvent(name, p) {
            if (name === "reminder.due") { bell.ring(); tile.titleInvert = true; invertTimer.restart() }
        }
    }

    IconBell {
        id: bell
        anchors.right: parent.right; anchors.rightMargin: 42 * tile.u
        y: 44 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        hovered: tile.hovered; live: tile.live && !tile.isOpen
    }
    Row {
        x: tile.pad; y: tile.height - 106 * tile.u - height / 2
        width: tile.width - 2 * tile.pad
        clip: true
        Text { text: tile.st.remToday + " today · " + (tile.st.remNextText ? "next " : "nothing else today"); color: tile.dim; font.family: Theme.mono; font.pixelSize: 19 * tile.u }
        Odometer { width: implicitWidth + 30 * tile.u; text: tile.st.remNextText ? tile.st.remNextText + " " + Fmt.hhmm(tile.st.remNextAt) : ""
                   color: tile.fg; font.family: Theme.mono; font.pixelSize: 19 * tile.u }
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            property string when: "1h"
            readonly property var whenOptions: [ { k: "10m", t: "in 10 min" }, { k: "1h", t: "in 1 h" }, { k: "tonight", t: "tonight 20:00" }, { k: "tomorrow", t: "tomorrow 09:00" } ]
            function whenTs(k) {
                if (k === "10m") return Core.now + 600
                if (k === "1h") return Core.now + 3600
                if (k === "tonight") { var t = Core.todayAt(20, 0); return t > Core.now ? t : t + 86400 }
                return Core.snoozeTarget("tomorrow")
            }

            Text { x: tile.pad; y: 66 * ex.u; text: "Reminders"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text { x: tile.pad; y: 128 * ex.u; text: tile.st.remToday + " today · " + tile.st.remOverdue + " overdue · they also ring on voice and Telegram"
                   color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }

            Item {
                x: tile.pad; y: 172 * ex.u
                width: ex.width - 2 * tile.pad; height: 44 * ex.u
                Text { text: "+"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 20 * ex.u; anchors.verticalCenter: input.verticalCenter }
                Field {
                    id: input
                    x: 28 * ex.u; width: parent.width * 0.45
                    anchors.verticalCenter: parent.verticalCenter
                    placeholderText: "Remind me to…"
                    monoFont: false; px: 19
                    onAccepted: { if (text.trim() === "") return; Core.action("reminder.add", { "text": text.trim(), "at": ex.whenTs(ex.when) }); text = "" }
                }
                Row {
                    anchors.left: input.right; anchors.leftMargin: 20 * ex.u; anchors.verticalCenter: parent.verticalCenter
                    spacing: 8 * ex.u
                    Repeater {
                        model: ex.whenOptions
                        Chip { required property var modelData; text: modelData.t; filled: ex.when === modelData.k; fg: Theme.fgTile
                               fontPx: 12; implicitHeight: 26 * ex.u; anchors.verticalCenter: parent.verticalCenter
                               MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: ex.when = parent.modelData.k } }
                    }
                    TextButton { text: "Add"; fontPx: 15; implicitHeight: 28 * ex.u; anchors.verticalCenter: parent.verticalCenter; onClicked: input.accepted() }
                }
            }

            Flickable {
                id: flick
                x: tile.pad; y: 236 * ex.u
                width: ex.width - 2 * tile.pad
                height: ex.height - y - 26 * ex.u
                contentHeight: body.height + 40 * ex.u
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: body
                    width: flick.width
                    Repeater {
                        model: [ { label: "OVERDUE", m: Core.remOverdue, warn: true }, { label: "TODAY", m: Core.remToday, warn: false }, { label: "LATER", m: Core.remLater, warn: false } ]
                        delegate: Column {
                            id: grp
                            required property var modelData
                            width: body.width
                            SectionLabel { text: modelData.label + " · " + modelData.m.count; color: modelData.warn && modelData.m.count > 0 ? Theme.accent : "#6E6E6B"
                                           topPadding: 14 * ex.u; bottomPadding: 8 * ex.u }
                            Hairline { width: parent.width }
                            ListView {
                                id: lv
                                width: parent.width
                                height: contentHeight
                                interactive: false
                                model: grp.modelData.m
                                add: Transition { ParallelAnimation {
                                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                                    NumberAnimation { property: "x"; from: Theme.reducedMotion ? 0 : -40 * ex.u; to: 0; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } } }
                                remove: Transition { ParallelAnimation {
                                    NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) }
                                    NumberAnimation { property: "x"; to: Theme.reducedMotion ? 0 : 80 * ex.u; duration: Theme.d(Theme.base); easing.type: Easing.InCubic } } }
                                displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                                delegate: ReminderRow { width: lv.width; height: 54 * ex.u; overdue: grp.modelData.warn }
                            }
                        }
                    }
                }
            }
        }
    }
}
