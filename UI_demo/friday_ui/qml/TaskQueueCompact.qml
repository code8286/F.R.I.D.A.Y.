// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// G, compact: what FRIDAY itself is doing or about to do (brief 5G).
import QtQuick
import Friday

Item {
    id: g
    property bool live: true
    signal openRequested()
    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property var st: Core.stats
    readonly property real rowH: 49 * u

    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: g.openRequested() }
    HoverHandler { id: hov }

    Text { x: g.pad; y: 22 * g.u; text: "G"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 32 * g.u }
    IconQueue { anchors.right: parent.right; anchors.rightMargin: 35 * g.u; y: 53 * g.u; scale: g.u; transformOrigin: Item.TopRight; live: g.live }
    Text { x: g.pad - 2 * g.u + (hov.hovered ? 4 * g.u : 0); y: 75 * g.u; text: "Task Queue"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * g.u
           Behavior on x { NumberAnimation { duration: Theme.d(Theme.fast) } } }
    Odometer { x: g.pad; y: 141 * g.u - height / 2; width: g.width - 2 * g.pad
               text: g.st.tasksRunning + " running · " + g.st.tasksQueued + " queued · " + g.st.tasksAwaiting + " awaiting"
               color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 15 * g.u }

    Column {
        id: body
        y: 170.5 * g.u
        width: g.width
        ListView {
            id: active
            width: parent.width
            height: Math.min(count, 4) * g.rowH
            interactive: false
            clip: true
            model: Core.tasksActive
            add: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                                                  NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base) } } }
            remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
            displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
            Behavior on height { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
            delegate: TaskRow { width: active.width; height: g.rowH; live: g.live }
        }
        Item { width: 1; height: 32.5 * g.u
               SectionLabel { x: g.pad - 3 * g.u; y: 22 * g.u - height / 2; text: "RECENT" } }
        ListView {
            id: recentList
            width: parent.width
            height: Math.min(count, 1) * g.rowH
            interactive: false
            clip: true
            model: Core.tasksRecent
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) } }
            delegate: TaskRow { width: recentList.width; height: g.rowH; recent: true; live: g.live }
        }
        Item { width: 1; height: 32.5 * g.u
               SectionLabel { x: g.pad - 3 * g.u; y: 21.5 * g.u - height / 2; text: "ROUTINES" } }
        Repeater {
            model: Core.routines
            delegate: Item {
                id: rr
                required property var model
                width: body.width; height: g.rowH
                Text { x: g.pad - 3 * g.u; anchors.verticalCenter: parent.verticalCenter; text: rr.model.title; textFormat: Text.PlainText
                       color: rr.model.enabled ? Theme.fgTile : "#7A7A77"; font.family: Theme.display; font.pixelSize: 18 * g.u
                       Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } } }
                Toggle { anchors.right: parent.right; anchors.rightMargin: 30 * g.u; anchors.verticalCenter: parent.verticalCenter
                         checked: rr.model.enabled; onToggled: Core.action("routine.toggle", { "id": rr.model.id }) }
                Hairline { x: 30 * g.u; width: parent.width - 60 * g.u; anchors.bottom: parent.bottom }
            }
        }
    }
}
