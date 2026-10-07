// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// G, expanded: running jobs with their live steps, the queue (drag to reorder), recent results and routines.
import QtQuick
import Friday

Item {
    id: ex
    property bool live: true
    signal openA()
    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property var st: Core.stats
    readonly property real leftW: (width - 2 * pad) * 0.62

    IconQueue { anchors.right: parent.right; anchors.rightMargin: 35 * ex.u; y: 53 * ex.u; scale: ex.u; transformOrigin: Item.TopRight; live: ex.live }
    Text { x: ex.pad; y: 66 * ex.u; text: "Task Queue"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
    Text { x: ex.pad; y: 128 * ex.u; text: ex.st.tasksRunning + " running · " + ex.st.tasksQueued + " queued · " + ex.st.tasksAwaiting + " awaiting · click a row for its live steps"
           color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }

    Flickable {
        id: flick
        x: ex.pad - 12 * ex.u; y: 176 * ex.u
        width: ex.leftW; height: ex.height - y - 26 * ex.u
        contentHeight: body.height + 40 * ex.u
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: body
            width: flick.width
            SectionLabel { x: 12 * ex.u; text: "ACTIVE · " + Core.tasksActive.count; bottomPadding: 8 * ex.u }
            ListView {
                id: act
                width: parent.width; height: contentHeight
                interactive: false
                model: Core.tasksActive
                add: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                                                      NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base) } } }
                remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
                displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                move: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                delegate: TaskCard { width: act.width; list: act; live: ex.live; onOpenA: ex.openA() }
            }
            Item { width: 1; height: 28 * ex.u }
            SectionLabel { x: 12 * ex.u; text: "RECENT · last 10"; bottomPadding: 8 * ex.u }
            ListView {
                id: rec
                width: parent.width; height: contentHeight
                interactive: false
                model: Core.tasksRecent
                add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) } }
                remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
                displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                delegate: TaskCard { width: rec.width; recent: true; list: rec; live: ex.live }
            }
        }
    }

    Column {
        x: ex.pad + ex.leftW + 40 * ex.u; y: 176 * ex.u
        width: ex.width - x - ex.pad
        spacing: 0
        SectionLabel { text: "ROUTINES"; bottomPadding: 8 * ex.u }
        Repeater {
            model: Core.routines
            delegate: Item {
                id: rr
                required property var model
                width: parent.width; height: 56 * ex.u
                Text { anchors.verticalCenter: parent.verticalCenter; text: rr.model.title; textFormat: Text.PlainText; width: parent.width - 60 * ex.u; elide: Text.ElideRight
                       color: rr.model.enabled ? Theme.fgTile : "#7A7A77"; font.family: Theme.display; font.pixelSize: 19 * ex.u }
                Toggle { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; checked: rr.model.enabled
                         onToggled: Core.action("routine.toggle", { "id": rr.model.id }) }
                Hairline { anchors.bottom: parent.bottom; width: parent.width }
            }
        }
        Item { width: 1; height: 30 * ex.u }
        Text { width: parent.width; wrapMode: Text.Wrap; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 12 * ex.u; lineHeight: 1.35
               text: "This is FRIDAY's own work: agent jobs, routine runs and multi-step tool sequences. Anything a task does still passes the policy engine; T2+ steps wait here with a coral dot until you approve them in A." }
    }
}
