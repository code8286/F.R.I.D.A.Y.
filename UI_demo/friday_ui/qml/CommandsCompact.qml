// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// H, compact: standing instructions to the AI (brief 5H).
import QtQuick
import Friday

Item {
    id: h
    property bool live: true
    signal openRequested()
    signal newRequested()
    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property var st: Core.stats
    readonly property real rowH: 49 * u

    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: h.openRequested() }
    HoverHandler { id: hov }

    Text { x: h.pad - 2 * h.u; y: 22 * h.u; text: "H"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 32 * h.u }
    TextButton { anchors.right: parent.right; anchors.rightMargin: 30 * h.u; y: 35 * h.u; text: "+ New"; fontPx: 18; implicitWidth: 81 * h.u; implicitHeight: 33 * h.u
                 onClicked: h.newRequested() }
    Text { x: h.pad - 3 * h.u + (hov.hovered ? 4 * h.u : 0); y: 77 * h.u; text: "Commands"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * h.u
           Behavior on x { NumberAnimation { duration: Theme.d(Theme.fast) } } }
    Odometer { x: h.pad - 3 * h.u; y: 141 * h.u - height / 2; width: h.width - 2 * h.pad
               text: h.st.cmdStanding + " standing · " + h.st.cmdPaused + " paused"
               color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 15 * h.u }
    ListView {
        id: list
        y: 170.5 * h.u
        width: h.width
        height: h.height - y - 10 * h.u
        interactive: false
        clip: true
        model: Core.commands
        add: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                                              NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base) } } }
        remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
        displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
        delegate: CommandRow { width: list.width; height: h.rowH; live: h.live }
    }
}
