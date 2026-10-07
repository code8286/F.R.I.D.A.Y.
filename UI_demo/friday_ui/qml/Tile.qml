// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Shared tile anatomy and the open/close morph (brief 1.2, 3.2).
//  - compact children go in the default property (the grid state)
//  - `expanded` is a Component shown when the tile is morphed open over the right section
import QtQuick
import Friday

Item {
    id: tile
    property string letter: ""
    property string title: ""
    property bool accent: false
    property bool inverted: false
    property int order: 0                 // launch order: A = 0 ... H = 7
    property rect slotRect: Qt.rect(0, 0, 100, 100)
    property rect openRect: Qt.rect(0, 0, 100, 100)
    property bool isOpen: false
    property bool dimmed: false
    property bool focusRing: false
    property real enter: 1
    property bool showTitle: true
    property bool offline: !Core.connected
    property alias hovered: hover.hovered
    property Component expanded
    property real titleLineHeight: 52
    property real titleBottom: 22         // px below the title box (reference units)
    property real breathe: 0              // 0..1 brightness pulse (tile A while a confirmation waits)
    property bool titleInvert: false      // reminder due: the title row inverts for 1.2 s
    default property alias compactData: compactLayer.data
    property alias expandedItem: expLoader.item
    signal activated()
    signal closeRequested()

    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property color bg: accent ? Theme.accent : (inverted ? Theme.fgTile : Theme.tile)
    readonly property color fg: accent ? Theme.fgAccent : (inverted ? "#000000" : Theme.fgTile)
    readonly property color dim: accent ? Qt.rgba(0.04, 0.04, 0.04, 0.66) : (inverted ? "#4A4A48" : Theme.dimOnTile)
    readonly property real titleTop: titleText.y            // compact content anchors above this
    property bool animateGeom: false
    property real reveal: isOpen ? 1 : 0  // expanded content 0..1 (declarative: delayed on open, quick on close)
    Behavior on reveal { SequentialAnimation {
        PauseAnimation { duration: tile.isOpen && !Theme.reducedMotion ? Theme.slow * 0.6 : 0 }
        NumberAnimation { duration: tile.isOpen ? Theme.d(Theme.base) : Theme.d(Theme.fast); easing.type: Easing.OutCubic } } }
    property bool pressedLook: false

    x: isOpen ? openRect.x : slotRect.x
    y: (isOpen ? openRect.y : slotRect.y) + (1 - enter) * 12 * u
    width: isOpen ? openRect.width : slotRect.width
    height: isOpen ? openRect.height : slotRect.height
    z: isOpen ? 20 : (animateGeom ? 19 : 1)
    opacity: enter * (dimmed ? 0 : 1) * (offline ? 0.6 : 1)
    scale: (0.96 + 0.04 * enter) * (dimmed ? 0.98 : 1) * (pressedLook ? 0.985 : 1)
    enabled: !dimmed && enter > 0.5
    visible: opacity > 0.002

    Behavior on x { enabled: tile.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: tile.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on width { enabled: tile.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on height { enabled: tile.animateGeom; NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
    Behavior on opacity { enabled: tile.enter >= 1; NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
    Behavior on scale { enabled: tile.enter >= 1; NumberAnimation { duration: Theme.d(Theme.fast); easing.type: Easing.OutCubic } }

    onIsOpenChanged: {
        animateGeom = !Theme.reducedMotion
        geomTimer.restart()
    }
    Timer { id: geomTimer; interval: Theme.slow + 30; onTriggered: tile.animateGeom = false }
    // focus ring: 2 px accent, 3 px outside the tile
    Rectangle {
        visible: tile.focusRing && !tile.isOpen
        anchors.fill: parent
        anchors.margins: -5 * tile.u
        radius: bgRect.radius + 5 * tile.u
        color: "transparent"
        border.color: Theme.accent
        border.width: 2
    }

    Rectangle {
        id: bgRect
        anchors.fill: parent
        radius: 22 * tile.u
        color: tile.bg
        Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } }
        Rectangle {               // breathing brightness (confirmation waiting)
            anchors.fill: parent
            radius: parent.radius
            color: tile.accent ? "#FFFFFF" : Theme.fgTile
            opacity: tile.breathe * 0.16
            visible: opacity > 0.001
        }
    }

    MouseArea {
        id: tileMouse
        anchors.fill: parent
        enabled: !tile.isOpen
        cursorShape: Qt.PointingHandCursor
        onPressed: tile.pressedLook = true
        onReleased: tile.pressedLook = false
        onCanceled: tile.pressedLook = false
        onClicked: tile.activated()
    }
    HoverHandler { id: hover; enabled: !tile.isOpen }

    // ---------------------------------------------------------------- compact layer
    Item {
        id: compactLayer
        anchors.fill: parent
        opacity: tile.isOpen ? 0 : (1 - tile.reveal)
        visible: opacity > 0.01
    }

    Rectangle {
        visible: tile.showTitle && opacity > 0.01
        opacity: tile.titleInvert && !tile.isOpen ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.d(Theme.fast) } }
        x: titleText.x - 12 * tile.u; y: titleText.y - 4 * tile.u
        width: titleText.implicitWidth + 24 * tile.u; height: titleText.height + 10 * tile.u
        radius: 10 * tile.u
        color: Theme.fgTile
    }
    // title (bottom-left); nudges 4 px right on hover
    Text {
        id: titleText
        visible: tile.showTitle
        opacity: compactLayer.opacity
        x: tile.pad + (tile.hovered && !tile.isOpen ? 4 * tile.u : 0)
        y: tile.height - height - tile.titleBottom * tile.u
        text: tile.title
        color: tile.titleInvert && !tile.isOpen ? "#000000" : tile.fg
        font.family: Theme.display
        font.pixelSize: 46 * tile.u
        lineHeightMode: Text.FixedHeight
        lineHeight: tile.titleLineHeight * tile.u
        Behavior on x { NumberAnimation { duration: Theme.d(Theme.fast); easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } }
    }

    // ---------------------------------------------------------------- expanded layer
    Loader {
        id: expLoader
        anchors.fill: parent
        active: tile.isOpen || tile.reveal > 0
        sourceComponent: tile.expanded
        opacity: tile.reveal
        visible: opacity > 0.01
    }

    // letter (top-left). In the open state it is the way back.
    Item {
        id: letterBox
        x: tile.pad; y: 22 * tile.u
        width: letterText.implicitWidth + (tile.isOpen ? backHint.implicitWidth + 14 * tile.u : 0)
        height: letterText.implicitHeight
        z: 5
        Text {
            id: letterText
            text: tile.letter
            color: tile.fg
            font.family: Theme.display
            font.pixelSize: 32 * tile.u
        }
        Text {
            id: backHint
            visible: tile.isOpen
            opacity: tile.reveal
            anchors.left: letterText.right
            anchors.leftMargin: 14 * tile.u
            anchors.verticalCenter: letterText.verticalCenter
            text: "‹ back · esc"
            color: backMouse.containsMouse ? tile.fg : tile.dim
            font.family: Theme.mono
            font.pixelSize: 13 * tile.u
        }
        MouseArea {
            id: backMouse
            anchors.fill: parent
            anchors.margins: -8 * tile.u
            enabled: tile.isOpen
            hoverEnabled: true
            cursorShape: tile.isOpen ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: tile.closeRequested()
        }
    }

    // offline tag
    Rectangle {
        visible: tile.offline
        anchors.right: parent.right; anchors.top: parent.top
        anchors.rightMargin: tile.pad; anchors.topMargin: 26 * tile.u
        width: offText.implicitWidth + 14 * tile.u; height: 18 * tile.u; radius: height / 2
        color: "transparent"; border.color: tile.dim; border.width: 1
        z: 6
        Text { id: offText; anchors.centerIn: parent; text: "offline"; color: tile.dim; font.family: Theme.mono; font.pixelSize: 11 * tile.u }
    }
}
