// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile A (accent): the next thing from any source, plus notifications and confirmation cards (brief 5A).
// Approve / Deny send confirm.respond; the core decides. Untrusted messages are plain text with an external tag.
import QtQuick
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "Upcoming"
    accent: true
    property bool live: true
    readonly property var st: Core.stats
    readonly property bool confirmWaiting: (st.confirms || 0) > 0

    // a pending confirmation makes the tile "breathe" (2 s)
    SequentialAnimation on breathe {
        running: tile.confirmWaiting && !Theme.reducedMotion
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 1000; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 1000; easing.type: Easing.InOutSine }
        onStopped: tile.breathe = 0
    }
    property int lastCount: 0
    Component.onCompleted: lastCount = Core.notifications.count
    Connections { target: Core.notifications
        function onCountChanged() { if (Core.notifications.count > tile.lastCount) horizon.ping(); tile.lastCount = Core.notifications.count } }

    IconHorizon {
        id: horizon
        anchors.right: parent.right; anchors.rightMargin: 40 * tile.u
        y: 92 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        fg: Theme.fgAccent; hovered: tile.hovered; live: tile.live && !tile.isOpen
    }
    Text {
        x: tile.pad - 3 * tile.u; y: tile.height - 169 * tile.u - height / 2
        text: tile.st.upNextAt ? Fmt.countdown(tile.st.upNextAt - Core.now) : "--:--:--"
        color: tile.fg; font.family: Theme.mono; font.pixelSize: 62 * tile.u
    }
    Odometer {
        x: tile.pad; y: tile.height - 118 * tile.u - height / 2
        width: tile.width - 2 * tile.pad
        text: tile.st.upNextTitle ? tile.st.upNextTitle + (tile.st.upNextLabel ? " · " + tile.st.upNextLabel : "") : "Nothing in the next 24 h"
        color: tile.fg; elide: Text.ElideRight
        font.family: Theme.display; font.pixelSize: 19 * tile.u
    }
    Rectangle {
        visible: (tile.st.unread || 0) > 0
        anchors.right: parent.right; anchors.rightMargin: 29 * tile.u
        y: tile.height - 52 * tile.u - height / 2
        width: badge.implicitWidth + 28 * tile.u; height: 32 * tile.u; radius: height / 2
        color: "#000000"
        Text { id: badge; anchors.centerIn: parent; text: (tile.st.confirms > 0 ? "! " : "") + tile.st.unread + " new"; color: Theme.accent; font.family: Theme.mono; font.pixelSize: 17 * tile.u }
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            readonly property real colGap: 40 * ex.u
            readonly property real leftW: (width - 2 * tile.pad - colGap) * 0.44
            readonly property real rightX: tile.pad + leftW + colGap
            readonly property real rightW: width - rightX - tile.pad

            Text { x: tile.pad; y: 66 * ex.u; text: "Upcoming"; color: Theme.fgAccent; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text { x: tile.pad; y: 128 * ex.u; color: Qt.rgba(0, 0, 0, 0.62); font.family: Theme.mono; font.pixelSize: 14 * ex.u
                   text: "next 24 h from B calendar · C reminders · E alarms (merged in the UI)" }

            // --------------------------------- timeline
            Rectangle {
                id: tlBox
                x: tile.pad; y: 176 * ex.u
                width: ex.leftW; height: ex.height - y - 30 * ex.u
                radius: 16 * ex.u; color: Qt.rgba(0, 0, 0, 0.06)
                Text { x: 22 * ex.u; y: 18 * ex.u; text: Fmt.countdown(tile.st.upNextAt - Core.now); color: Theme.fgAccent; font.family: Theme.mono; font.pixelSize: 40 * ex.u
                       visible: !!tile.st.upNextAt }
                Text { x: 22 * ex.u; y: 72 * ex.u; text: tile.st.upNextTitle ? "until " + tile.st.upNextTitle : ""; color: Qt.rgba(0, 0, 0, 0.66); font.family: Theme.display; font.pixelSize: 17 * ex.u }
                Rectangle { id: spine; x: 38 * ex.u; y: 120 * ex.u; width: 1.5 * ex.u; height: parent.height - y - 20 * ex.u; color: Theme.fgAccent }
                ListView {
                    id: tl
                    x: 22 * ex.u; y: 130 * ex.u
                    width: parent.width - 44 * ex.u; height: parent.height - y - 20 * ex.u
                    clip: true
                    model: Core.upcoming
                    spacing: 6 * ex.u
                    add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) } }
                    displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                    delegate: Item {
                        id: up
                        required property var model
                        required property int index
                        width: tl.width; height: 62 * ex.u
                        Rectangle { x: 16 * ex.u - width / 2 + 0.75 * ex.u; y: 6 * ex.u; width: 26 * ex.u; height: width; radius: width / 2; color: Theme.accent; border.color: Theme.fgAccent; border.width: 1.5 * ex.u
                                    Text { anchors.centerIn: parent; text: up.model.sourceLetter; color: Theme.fgAccent; font.family: Theme.display; font.pixelSize: 13 * ex.u } }
                        Text { x: 46 * ex.u; y: 4 * ex.u; text: Fmt.hhmm(up.model.at) + "  ·  " + Fmt.relIn(up.model.at - Core.now); color: Qt.rgba(0, 0, 0, 0.66); font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                        Text { x: 46 * ex.u; y: 24 * ex.u; width: parent.width - x; elide: Text.ElideRight; textFormat: Text.PlainText
                               text: up.model.title + (up.model.label ? "  ·  " + up.model.label : ""); color: Theme.fgAccent; font.family: Theme.display; font.pixelSize: 19 * ex.u }
                    }
                }
                // "now" marker slides down the spine as the first item approaches (last hour)
                Rectangle {
                    x: spine.x - width / 2 + 0.75 * ex.u
                    readonly property real lead: tile.st.upNextAt ? Math.max(0, Math.min(1, (tile.st.upNextAt - Core.now) / 3600)) : 1
                    y: spine.y + (1 - lead) * 10 * ex.u - height / 2
                    Behavior on y { NumberAnimation { duration: 900 } }
                    width: 12 * ex.u; height: width; radius: width / 2; color: Theme.fgAccent
                    Text { x: -40 * ex.u; anchors.verticalCenter: parent.verticalCenter; text: "now"; color: Theme.fgAccent; font.family: Theme.mono; font.pixelSize: 11 * ex.u }
                }
            }

            // --------------------------------- notifications
            Text { x: ex.rightX; y: 176 * ex.u; text: "Notifications"; color: Theme.fgAccent; font.family: Theme.display; font.pixelSize: 26 * ex.u }
            Text { x: ex.rightX; y: 212 * ex.u; text: tile.st.unread + " unread · " + tile.st.confirms + " awaiting approval"; color: Qt.rgba(0, 0, 0, 0.62); font.family: Theme.mono; font.pixelSize: 13 * ex.u }
            TextButton { x: ex.rightX + ex.rightW - width; y: 180 * ex.u; text: "Mark all read"; fg: Theme.fgAccent; bgHover: Qt.rgba(0, 0, 0, 0.08); fontPx: 14; implicitHeight: 28 * ex.u
                         onClicked: Core.action("notification.read_all", {}) }
            ListView {
                id: nl
                x: ex.rightX; y: 246 * ex.u
                width: ex.rightW; height: ex.height - y - 30 * ex.u
                clip: true
                spacing: 10 * ex.u
                model: Core.notifications
                boundsBehavior: Flickable.StopAtBounds
                add: Transition { ParallelAnimation {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                    NumberAnimation { property: "y"; from: Theme.reducedMotion ? 0 : -46 * ex.u; duration: Theme.d(Theme.slow); easing.type: Theme.reducedMotion ? Easing.Linear : Easing.OutBack; easing.overshoot: 1.2 } } }
                remove: Transition { ParallelAnimation {
                    NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) }
                    NumberAnimation { property: "x"; to: Theme.reducedMotion ? 0 : 60 * ex.u; duration: Theme.d(Theme.base) } } }
                displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                delegate: NotificationCard { width: nl.width }
            }
        }
    }
}
