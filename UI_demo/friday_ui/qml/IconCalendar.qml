// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile B icon: a 7x5 month dot grid. Today is filled; a ring hops from dot to dot every 2 s; hover ripples outward.
import QtQuick
import Friday

Item {
    id: ic
    property color fg: Theme.fgTile
    property bool hovered: false
    property bool live: true
    property real now: Core.now
    width: 164; height: 132
    readonly property var cal: {
        var d = new Date(now * 1000)
        var first = new Date(d.getFullYear(), d.getMonth(), 1)
        var lead = (first.getDay() + 6) % 7
        var dim = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
        var todayCell = lead + d.getDate() - 1
        return { lead: lead, days: dim, today: Math.min(34, todayCell) }
    }
    function cx(i) { return 9 + (i % 7) * 24.2 }
    function cy(i) { return 22 + Math.floor(i / 7) * 26 }

    Rectangle { x: 0; y: 0; width: parent.width; height: 1.5; color: ic.fg }

    Repeater {
        id: dots
        model: 35
        delegate: Rectangle {
            id: dot
            required property int index
            readonly property bool inMonth: index >= ic.cal.lead && index < ic.cal.lead + ic.cal.days
            readonly property bool isToday: index === ic.cal.today
            width: isToday ? 13 : 5.2; height: width; radius: width / 2
            x: ic.cx(index) - width / 2; y: ic.cy(index) - height / 2
            color: inMonth ? ic.fg : "#474745"
            property real pop: 1
            scale: pop
            SequentialAnimation {
                id: ripple
                PauseAnimation { duration: 28 * Math.hypot((dot.index % 7) - (ic.cal.today % 7), Math.floor(dot.index / 7) - Math.floor(ic.cal.today / 7)) }
                NumberAnimation { target: dot; property: "pop"; to: 1.4; duration: 120; easing.type: Easing.OutCubic }
                NumberAnimation { target: dot; property: "pop"; to: 1.0; duration: 220; easing.type: Easing.OutBack }
            }
            Connections { target: ic; function onHoveredChanged() { if (ic.hovered && !Theme.reducedMotion) ripple.restart() } }
        }
    }
    // the orbiting ring
    property int ringCell: cal.today
    Rectangle {
        width: 26; height: 26; radius: 13
        color: "transparent"; border.color: ic.fg; border.width: 1.5
        x: ic.cx(ic.ringCell) - 13; y: ic.cy(ic.ringCell) - 13
        Behavior on x { NumberAnimation { duration: Theme.d(600); easing.type: Easing.InOutCubic } }
        Behavior on y { NumberAnimation { duration: Theme.d(600); easing.type: Easing.InOutCubic } }
    }
    Timer {
        interval: 2000; repeat: true; running: ic.live && !Theme.reducedMotion
        property int step: 0
        onTriggered: {
            step = (step + 1) % 4
            var row = Math.floor(ic.cal.today / 7) * 7
            var target = ic.cal.today + step
            if (step === 3 || target >= row + 7 || target >= ic.cal.lead + ic.cal.days) { step = 0; target = ic.cal.today }
            ic.ringCell = target
        }
    }
}
