// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile F: now playing from the Spotify desktop app via the core's media provider (brief 5F). T0/T1, no confirmation.
import QtQuick
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "Music"
    property bool live: true
    readonly property var m: Core.media
    readonly property bool session: !!m.session
    readonly property bool playing: !!m.playing
    readonly property real duration: m.duration || 1
    property real pos: 0
    Timer { interval: 250; repeat: true; triggeredOnStart: true; running: tile.live; onTriggered: tile.pos = Core.mediaPosition() }
    Connections { target: Core; function onMediaChanged() { tile.pos = Core.mediaPosition() } }

    IconVinyl {
        anchors.right: parent.right; anchors.rightMargin: 36 * tile.u
        y: 38 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        playing: tile.playing; hovered: tile.hovered; live: tile.live && !tile.isOpen
        MouseArea { x: 0; y: 10; width: 150; height: 150; cursorShape: Qt.PointingHandCursor
                    onClicked: tile.session ? Core.action("media.play_pause", {}) : Core.action("media.launch", {}) }
    }
    Marquee {
        x: tile.pad; y: tile.height - 144 * tile.u - height / 2
        width: tile.width - 2 * tile.pad
        text: tile.session ? (tile.m.title || "") : "Spotify not running · Open"
        color: tile.fg; font.family: Theme.mono; font.pixelSize: 19 * tile.u
        live: tile.live && !tile.isOpen
    }
    Text {
        x: tile.pad; y: tile.height - 107 * tile.u - height / 2
        width: tile.width - 2 * tile.pad; elide: Text.ElideRight
        text: tile.session ? ((tile.m.artist || "") + " · " + Fmt.mmss(tile.pos) + " / " + Fmt.mmss(tile.duration)) : "click the disc to launch it"
        color: tile.dim; font.family: Theme.mono; font.pixelSize: 19 * tile.u
    }
    // transport (works without opening the tile)
    Row {
        visible: !tile.isOpen
        anchors.right: parent.right; anchors.rightMargin: 30 * tile.u
        y: tile.height - 50 * tile.u - height / 2
        spacing: 12 * tile.u
        TransportButton { kind: "prev"; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("media.prev", {}) }
        TransportButton { kind: tile.playing ? "pause" : "play"; ring: true; anchors.verticalCenter: parent.verticalCenter
                          onClicked: tile.session ? Core.action("media.play_pause", {}) : Core.action("media.launch", {}) }
        TransportButton { kind: "next"; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("media.next", {}) }
    }
    // progress along the bottom edge
    Item {
        visible: tile.session
        x: 13 * tile.u; width: tile.width - 26 * tile.u
        y: tile.height - 4 * tile.u; height: 4 * tile.u
        opacity: 1 - tile.reveal
        Rectangle { anchors.fill: parent; color: "#222222" }
        Rectangle { height: parent.height; width: parent.width * Math.min(1, tile.pos / tile.duration); color: Theme.fgTile }
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            readonly property real artS: Math.min(height - 240 * u, width * 0.42)
            property string shownTrack: tile.m.track_id || ""
            property string prevTrack: ""

            Text { x: tile.pad; y: 66 * ex.u; text: "Music"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text { x: tile.pad; y: 128 * ex.u; text: (tile.m.source || "media session") + " · no API key, works on free accounts"
                   color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }

            // album art, 1-bit ordered dither; slides on track change
            Item {
                id: artBox
                x: tile.pad; y: 180 * ex.u
                width: ex.artS; height: ex.artS
                clip: true
                Rectangle { anchors.fill: parent; color: "#0A0A0A"; radius: 14 * ex.u; border.color: Theme.hairline }
                Image { id: artOld; width: parent.width; height: parent.height; smooth: false; source: ex.prevTrack ? "image://art/" + ex.prevTrack : ""; opacity: 0 }
                Image { id: artNew; width: parent.width; height: parent.height; smooth: false; source: ex.shownTrack ? "image://art/" + ex.shownTrack : "" }
                Text { visible: !tile.session; anchors.centerIn: parent; text: "no media session"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }
            }
            Connections {
                target: Core
                function onCoreEvent(name, p) {
                    if (name !== "media.track") return
                    ex.prevTrack = ex.shownTrack
                    ex.shownTrack = p.track_id
                    if (!Theme.reducedMotion) swap.restart()
                }
            }
            ParallelAnimation {
                id: swap
                NumberAnimation { target: artOld; property: "x"; from: 0; to: -ex.artS * 0.5; duration: Theme.slow; easing.type: Easing.InCubic }
                NumberAnimation { target: artOld; property: "opacity"; from: 1; to: 0; duration: Theme.slow }
                NumberAnimation { target: artNew; property: "x"; from: ex.artS * 0.5; to: 0; duration: Theme.slow; easing.type: Easing.OutCubic }
                NumberAnimation { target: artNew; property: "opacity"; from: 0; to: 1; duration: Theme.slow }
            }

            Column {
                id: info
                x: artBox.x + artBox.width + 46 * ex.u
                y: artBox.y + 10 * ex.u
                width: ex.width - x - tile.pad
                spacing: 10 * ex.u
                Text { width: parent.width; text: tile.session ? (tile.m.title || "") : "Spotify not running"; textFormat: Text.PlainText; wrapMode: Text.Wrap
                       color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 40 * ex.u }
                Text { text: tile.session ? (tile.m.artist || "") + "  ·  " + (tile.m.album || "") : ""; textFormat: Text.PlainText
                       color: Theme.dimOnTile; font.family: Theme.display; font.pixelSize: 20 * ex.u }
                Item { width: 1; height: 20 * ex.u }
                // seek bar
                Item {
                    id: seek
                    width: parent.width; height: 26 * ex.u
                    property real dragFrac: -1
                    readonly property real frac: dragFrac >= 0 ? dragFrac : Math.min(1, tile.pos / tile.duration)
                    Rectangle { y: parent.height / 2 - 1; width: parent.width; height: 2 * ex.u; color: "#2E2E2C" }
                    Rectangle { y: parent.height / 2 - 1; width: parent.width * seek.frac; height: 2 * ex.u; color: Theme.fgTile }
                    Rectangle { x: parent.width * seek.frac - width / 2; anchors.verticalCenter: parent.verticalCenter; width: 14 * ex.u; height: width; radius: width / 2; color: Theme.fgTile
                                scale: seekMa.pressed || seekMa.containsMouse ? 1.2 : 1; Behavior on scale { NumberAnimation { duration: Theme.fast } } }
                    MouseArea {
                        id: seekMa
                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        enabled: tile.session
                        onPressed: (e) => seek.dragFrac = Math.max(0, Math.min(1, e.x / width))
                        onPositionChanged: (e) => { if (pressed) seek.dragFrac = Math.max(0, Math.min(1, e.x / width)) }
                        onReleased: { Core.action("media.seek", { "position": seek.dragFrac * tile.duration }); seek.dragFrac = -1 }
                    }
                }
                Item {
                    width: parent.width; height: 20 * ex.u
                    Text { text: Fmt.mmss(seek.frac * tile.duration); color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                    Text { anchors.right: parent.right; text: Fmt.mmss(tile.duration); color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                }
                Item { width: 1; height: 16 * ex.u }
                Row {
                    spacing: 26 * ex.u
                    TransportButton { kind: "prev"; size: 1.6; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("media.prev", {}) }
                    TransportButton { kind: tile.playing ? "pause" : "play"; ring: true; size: 1.9; anchors.verticalCenter: parent.verticalCenter
                                      onClicked: tile.session ? Core.action("media.play_pause", {}) : Core.action("media.launch", {}) }
                    TransportButton { kind: "next"; size: 1.6; anchors.verticalCenter: parent.verticalCenter; onClicked: Core.action("media.next", {}) }
                }
                Item { width: 1; height: 22 * ex.u }
                Row {
                    spacing: 14 * ex.u
                    Text { text: "vol"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u; anchors.verticalCenter: parent.verticalCenter }
                    Item {
                        id: vol
                        width: 220 * ex.u; height: 22 * ex.u
                        anchors.verticalCenter: parent.verticalCenter
                        property real v: tile.m.volume === undefined ? 0.5 : tile.m.volume
                        property real dragV: -1
                        readonly property real shown: dragV >= 0 ? dragV : v
                        Rectangle { y: parent.height / 2 - 1; width: parent.width; height: 2 * ex.u; color: "#2E2E2C" }
                        Rectangle { y: parent.height / 2 - 1; width: parent.width * vol.shown; height: 2 * ex.u; color: Theme.fgTile }
                        Rectangle { x: parent.width * vol.shown - width / 2; anchors.verticalCenter: parent.verticalCenter; width: 12 * ex.u; height: width; radius: width / 2; color: Theme.fgTile }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    onPressed: (e) => vol.dragV = Math.max(0, Math.min(1, e.x / width))
                                    onPositionChanged: (e) => { if (pressed) vol.dragV = Math.max(0, Math.min(1, e.x / width)) }
                                    onReleased: { Core.action("media.volume", { "volume": vol.dragV }); vol.dragV = -1 } }
                    }
                    Text { text: Math.round(vol.shown * 100); color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u; anchors.verticalCenter: parent.verticalCenter }
                    Item { width: 16 * ex.u; height: 1 }
                    Chip { text: "shuffle"; filled: !!tile.m.shuffle; fontPx: 12; implicitHeight: 26 * ex.u; anchors.verticalCenter: parent.verticalCenter
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Core.action("media.shuffle", {}) } }
                    Chip { text: "repeat " + (tile.m.repeat || "off"); filled: (tile.m.repeat || "off") !== "off"; fontPx: 12; implicitHeight: 26 * ex.u; anchors.verticalCenter: parent.verticalCenter
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Core.action("media.repeat", {}) } }
                }
                Item { width: 1; height: 24 * ex.u }
                TextButton { visible: !tile.session; text: "Open Spotify"; fontPx: 16; onClicked: Core.action("media.launch", {}) }
                Text { width: parent.width; wrapMode: Text.Wrap; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 12 * ex.u
                       text: "Primary backend: Windows media session (GlobalSystemMediaTransportControls). Seek, volume and shuffle need the optional Spotify Web API (Premium)." }
            }
        }
    }
}
