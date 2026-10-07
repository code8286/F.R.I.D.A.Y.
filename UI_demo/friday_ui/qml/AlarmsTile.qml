// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile E: alarms (brief 5E). The core's scheduler rings them even with the UI closed; this tile only mirrors it.
import QtQuick
import QtQuick.Controls.Basic
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "Alarms"
    property bool live: true
    readonly property var st: Core.stats
    readonly property string ringingId: st.alarmRinging || ""
    readonly property bool ringing: ringingId !== ""
    property bool flashOn: false
    inverted: ringing && flashOn
    showTitle: !ringing
    Timer { interval: 500; repeat: true; running: tile.ringing; onTriggered: tile.flashOn = Theme.reducedMotion ? true : !tile.flashOn
            onRunningChanged: tile.flashOn = running }

    IconClock {
        anchors.right: parent.right; anchors.rightMargin: 46 * tile.u
        y: 44 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        fg: tile.fg; sector: tile.inverted ? "#C8C8C4" : "#3A3A38"
        hovered: tile.hovered; live: tile.live && !tile.isOpen; ringing: tile.ringing
    }
    Text {
        x: tile.pad; y: tile.height - 142 * tile.u - height / 2
        text: tile.st.alarmNextAt ? Fmt.pattern(tile.st.alarmNextDays) : "no alarms set"
        color: tile.dim; font.family: Theme.mono; font.pixelSize: 15 * tile.u
    }
    Row {
        x: tile.pad; y: tile.height - 107 * tile.u - height / 2
        visible: !!tile.st.alarmNextAt
        Text { text: Fmt.hm(tile.st.alarmNextHour || 0, tile.st.alarmNextMinute || 0); color: tile.fg; font.family: Theme.mono; font.pixelSize: 19 * tile.u }
        Odometer { width: implicitWidth + 40 * tile.u; text: " · " + Fmt.relIn((tile.st.alarmNextAt || 0) - Core.now); color: tile.dim; font.family: Theme.mono; font.pixelSize: 19 * tile.u }
    }
    // ringing: Stop and Snooze replace the title
    Row {
        visible: tile.ringing && !tile.isOpen
        x: tile.pad; y: tile.height - 36 * tile.u - height
        spacing: 12 * tile.u
        TextButton { text: "Stop"; fg: tile.fg; filled: true; fontPx: 20; implicitHeight: 46 * tile.u; implicitWidth: 120 * tile.u
                     onClicked: Core.action("alarm.stop", { "id": tile.ringingId }) }
        TextButton { text: "Snooze 9 min"; fg: tile.fg; fontPx: 18; implicitHeight: 46 * tile.u
                     onClicked: Core.action("alarm.snooze", { "id": tile.ringingId }) }
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            property bool editing: false

            Text { x: tile.pad; y: 66 * ex.u; text: "Alarms"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text { x: tile.pad; y: 128 * ex.u
                   text: tile.st.alarmNextAt ? ("next " + Fmt.hm(tile.st.alarmNextHour, tile.st.alarmNextMinute) + " " + tile.st.alarmNextLabel + " · " + Fmt.relIn(tile.st.alarmNextAt - Core.now)) : "no alarm is on"
                   color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }
            TextButton { anchors.right: parent.right; anchors.rightMargin: tile.pad; y: 70 * ex.u; text: ex.editing ? "Cancel" : "+ Add alarm"; fontPx: 17
                         onClicked: ex.editing = !ex.editing }

            // ringing banner
            Rectangle {
                id: banner
                visible: tile.ringing
                x: tile.pad; y: 168 * ex.u
                width: ex.width - 2 * tile.pad; height: visible ? 86 * ex.u : 0
                radius: 14 * ex.u
                color: tile.flashOn ? Theme.fgTile : "#1A1A1A"
                Behavior on color { ColorAnimation { duration: 120 } }
                Text { x: 22 * ex.u; anchors.verticalCenter: parent.verticalCenter; text: "Ringing · " + (tile.st.alarmRingingLabel || "Alarm")
                       color: tile.flashOn ? "#000000" : Theme.fgTile; font.family: Theme.display; font.pixelSize: 26 * ex.u }
                Row {
                    anchors.right: parent.right; anchors.rightMargin: 20 * ex.u; anchors.verticalCenter: parent.verticalCenter
                    spacing: 12 * ex.u
                    TextButton { text: "Stop"; fg: tile.flashOn ? "#000000" : Theme.fgTile; filled: true; fontPx: 18; implicitHeight: 44 * ex.u; implicitWidth: 110 * ex.u
                                 onClicked: Core.action("alarm.stop", { "id": tile.ringingId }) }
                    TextButton { text: "Snooze 9 min"; fg: tile.flashOn ? "#000000" : Theme.fgTile; fontPx: 16; implicitHeight: 44 * ex.u
                                 onClicked: Core.action("alarm.snooze", { "id": tile.ringingId }) }
                }
            }

            // add / edit
            Rectangle {
                id: editor
                x: tile.pad; y: banner.y + banner.height + (banner.visible ? 16 * ex.u : 0)
                width: ex.width - 2 * tile.pad
                height: ex.editing ? 230 * ex.u : 0
                clip: true
                radius: 14 * ex.u
                color: "#0E0E0E"; border.color: ex.editing ? Theme.hairline : "transparent"
                Behavior on height { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                property var days: [0, 1, 2, 3, 4]
                Row {
                    x: 24 * ex.u; y: 20 * ex.u
                    spacing: 6 * ex.u
                    TimeWheel { id: hh; itemCount: 24; current: 7 }
                    Text { text: ":"; color: Theme.fgTile; font.family: Theme.mono; font.pixelSize: 44 * ex.u; anchors.verticalCenter: parent.verticalCenter }
                    TimeWheel { id: mm; itemCount: 60; current: 0 }
                }
                Column {
                    x: 300 * ex.u; y: 26 * ex.u
                    spacing: 16 * ex.u
                    Field { id: label; width: Math.min(420 * ex.u, editor.width - 340 * ex.u); placeholderText: "Label (Wake up, Gym, ...)"; monoFont: false; px: 19 }
                    Row {
                        spacing: 8 * ex.u
                        Repeater {
                            model: 7
                            Rectangle {
                                required property int index
                                readonly property bool on: editor.days.indexOf(index) >= 0
                                width: 36 * ex.u; height: 36 * ex.u; radius: width / 2
                                color: on ? Theme.fgTile : "transparent"; border.color: on ? Theme.fgTile : "#4A4A48"
                                Text { anchors.centerIn: parent; text: Fmt.LETTERS[index]; color: parent.on ? "#000000" : Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    onClicked: { var d = editor.days.slice(); var i = d.indexOf(index); if (i >= 0) d.splice(i, 1); else d.push(index); d.sort(); editor.days = d } }
                            }
                        }
                    }
                    Row {
                        spacing: 12 * ex.u
                        Text { anchors.verticalCenter: parent.verticalCenter; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u
                               text: Fmt.repeatText(editor.days) + " · rings " + Fmt.relIn(Core.nextAlarmAt(hh.current, mm.current, editor.days) - Core.now) }
                        TextButton { text: "Save"; filled: true; fontPx: 16; implicitHeight: 32 * ex.u
                            onClicked: { Core.action("alarm.add", { "hour": hh.current, "minute": mm.current, "label": label.text || "Alarm", "days": editor.days }); ex.editing = false; label.text = "" } }
                    }
                }
            }

            ListView {
                id: list
                x: tile.pad; y: editor.y + editor.height + 18 * ex.u
                width: ex.width - 2 * tile.pad
                height: ex.height - y - 24 * ex.u
                clip: true
                model: Core.alarms
                boundsBehavior: Flickable.StopAtBounds
                add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) } }
                remove: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) }
                                                         NumberAnimation { property: "scale"; to: 0.97; duration: Theme.d(Theme.base) } } }
                displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                delegate: Item {
                    id: arow
                    required property var model
                    width: list.width; height: 96 * ex.u
                    opacity: model.enabled ? 1 : 0.4
                    Behavior on opacity { NumberAnimation { duration: Theme.d(Theme.base) } }
                    Text { id: big; x: 0; anchors.verticalCenter: parent.verticalCenter; text: Fmt.hm(arow.model.hour, arow.model.minute)
                           color: arow.model.ringing ? Theme.accent : Theme.fgTile; font.family: Theme.mono; font.pixelSize: 50 * ex.u }
                    Column {
                        x: big.width + 30 * ex.u; anchors.verticalCenter: parent.verticalCenter
                        spacing: 4 * ex.u
                        Text { text: arow.model.label; textFormat: Text.PlainText; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 20 * ex.u }
                        Text { text: Fmt.repeatText(arow.model.days) + (arow.model.enabled ? " · " + Fmt.relIn(Core.nextAlarmAt(arow.model.hour, arow.model.minute, arow.model.days) - Core.now) : " · off")
                               color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                    }
                    Row {
                        anchors.right: tog.left; anchors.rightMargin: 40 * ex.u; anchors.verticalCenter: parent.verticalCenter
                        spacing: 10 * ex.u
                        Repeater {
                            model: 7
                            Text { required property int index
                                   readonly property bool on: !arow.model.days || arow.model.days.length === 0 || arow.model.days.indexOf(index) >= 0
                                   text: Fmt.LETTERS[index]; color: on ? Theme.fgTile : "#3E3E3C"; font.family: Theme.mono; font.pixelSize: 15 * ex.u }
                        }
                    }
                    Toggle { id: tog; anchors.right: del.left; anchors.rightMargin: 18 * ex.u; anchors.verticalCenter: parent.verticalCenter
                             checked: arow.model.enabled; onToggled: Core.action("alarm.toggle", { "id": arow.model.id }) }
                    GlyphButton { id: del; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; glyph: "×"
                                  onClicked: Core.action("alarm.delete", { "id": arow.model.id }) }
                    Hairline { anchors.bottom: parent.bottom; width: parent.width }
                }
            }
        }
    }
}
