// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Column 3: ONE rounded rectangle split into two equal halves, G (AI task queue) on top and H (AI commands)
// below (brief 1.1, 5G, 5H). Opening either half morphs the whole column over the right section.
import QtQuick
import Friday

Item {
    id: col
    property rect slotRect: Qt.rect(0, 0, 100, 100)
    property rect openRect: Qt.rect(0, 0, 100, 100)
    property string openPane: ""
    property bool dimmed: false
    property real enterG: 1
    property real enterH: 1
    property string focusPane: ""
    property bool live: true
    property bool offline: !Core.connected
    signal activated(string key)
    signal closeRequested()

    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property bool isOpen: openPane !== ""
    property bool animateGeom: false
    property real reveal: isOpen ? 1 : 0
    Behavior on reveal { SequentialAnimation {
        PauseAnimation { duration: col.isOpen && !Theme.reducedMotion ? Theme.slow * 0.6 : 0 }
        NumberAnimation { duration: col.isOpen ? Theme.d(Theme.base) : Theme.d(Theme.fast); easing.type: Easing.OutCubic } } }
    onRevealChanged: if (reveal <= 0 && !isOpen) shownPane = ""
    property string shownPane: ""
    property bool newCommand: false

    x: isOpen ? openRect.x : slotRect.x
    y: isOpen ? openRect.y : slotRect.y
    width: isOpen ? openRect.width : slotRect.width
    height: isOpen ? openRect.height : slotRect.height
    z: isOpen ? 20 : (animateGeom ? 19 : 1)
    opacity: (dimmed ? 0 : 1) * (offline ? 0.6 : 1) * Math.max(enterG, 0.0001)
    scale: (dimmed ? 0.98 : 1)
    enabled: !dimmed
    visible: opacity > 0.002
    Behavior on x { enabled: col.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: col.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on width { enabled: col.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on height { enabled: col.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on opacity { enabled: col.enterG >= 1; NumberAnimation { duration: Theme.d(Theme.base) } }
    Behavior on scale { NumberAnimation { duration: Theme.d(Theme.base) } }

    onOpenPaneChanged: {
        animateGeom = !Theme.reducedMotion
        geomTimer.restart()
        if (openPane !== "") shownPane = openPane
        else newCommand = false
    }
    Timer { id: geomTimer; interval: Theme.slow + 30; onTriggered: col.animateGeom = false }
    // focus ring around the focused half
    Rectangle {
        visible: col.focusPane !== "" && !col.isOpen
        x: -5 * col.u; width: col.width + 10 * col.u
        y: (col.focusPane === "G" ? 0 : col.height / 2) - 5 * col.u
        height: col.height / 2 + 10 * col.u
        radius: 27 * col.u
        color: "transparent"; border.color: Theme.accent; border.width: 2
    }

    Rectangle { id: bg; anchors.fill: parent; radius: 22 * col.u; color: Theme.tile }

    // ---------------------------------------------------------------- compact halves
    Item {
        id: compact
        anchors.fill: parent
        opacity: col.isOpen ? 0 : 1 - col.reveal
        visible: opacity > 0.01
        Rectangle { y: col.height / 2; x: 0; width: col.width; height: 1; color: Theme.hairline }

        TaskQueueCompact {
            id: gHalf
            width: col.width; height: col.height / 2
            opacity: col.enterG; transform: Translate { y: (1 - col.enterG) * 12 * col.u }
            live: col.live && !col.isOpen
            onOpenRequested: col.activated("G")
        }
        CommandsCompact {
            id: hHalf
            y: col.height / 2
            width: col.width; height: col.height / 2
            opacity: col.enterH; transform: Translate { y: (1 - col.enterH) * 12 * col.u }
            live: col.live && !col.isOpen
            onOpenRequested: col.activated("H")
            onNewRequested: { col.newCommand = true; col.activated("H") }
        }
    }

    // ---------------------------------------------------------------- expanded
    Loader {
        anchors.fill: parent
        active: col.shownPane === "G"
        opacity: col.reveal
        visible: opacity > 0.01
        sourceComponent: TaskQueueExpanded { live: col.live; onOpenA: col.activated("A") }
    }
    Loader {
        anchors.fill: parent
        active: col.shownPane === "H"
        opacity: col.reveal
        visible: opacity > 0.01
        sourceComponent: CommandsExpanded { live: col.live; startEditing: col.newCommand }
    }
    // letter / back for the open state
    Item {
        visible: col.isOpen
        x: col.pad; y: 22 * col.u; z: 5
        width: lt.implicitWidth + back.implicitWidth + 14 * col.u; height: lt.implicitHeight
        Text { id: lt; text: col.shownPane; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 32 * col.u }
        Text { id: back; anchors.left: lt.right; anchors.leftMargin: 14 * col.u; anchors.verticalCenter: lt.verticalCenter; opacity: col.reveal
               text: "‹ back · esc"; color: bma.containsMouse ? Theme.fgTile : Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * col.u }
        MouseArea { id: bma; anchors.fill: parent; anchors.margins: -8 * col.u; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: col.closeRequested() }
    }
    Rectangle {
        visible: col.offline
        anchors.right: parent.right; anchors.top: parent.top; anchors.rightMargin: 80 * col.u; anchors.topMargin: 26 * col.u
        width: offT.implicitWidth + 14 * col.u; height: 18 * col.u; radius: height / 2; color: "transparent"; border.color: Theme.dimOnTile; z: 6
        Text { id: offT; anchors.centerIn: parent; text: "offline"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 11 * col.u }
    }
}
