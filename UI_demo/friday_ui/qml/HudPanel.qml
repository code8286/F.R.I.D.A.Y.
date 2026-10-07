// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Left panel: the HUD ring and its instrument labels (brief 4).
import QtQuick
import Friday

Item {
    id: panel
    property real boot: 1
    property bool live: true
    property int repeats: 4
    property bool showCaption: true
    signal ringClicked()
    readonly property real u: Theme.u
    readonly property real ringR: 0.40 * Math.min(width, height * 0.55)
    readonly property real cx: width / 2
    readonly property real cy: height * 0.459
    readonly property bool alarm: !!Core.stats.alarmRinging
    readonly property string mode: !Core.connected ? "offline" : (alarm ? "confirm" : Core.state)
    readonly property var captions: ({ "idle": "IDLE", "listening": "LISTENING", "thinking": "THINKING", "speaking": "SPEAKING",
                                       "confirm": "AWAITING CONFIRMATION", "offline": "CORE OFFLINE · retrying" })

    Text {
        x: 4 * panel.u; y: 37 * panel.u - height / 2
        text: "MIC · AudioHub 16 kHz"
        color: Theme.pageDim; font.family: Theme.mono; font.pixelSize: 13 * panel.u
        opacity: panel.boot > 0 ? 1 : 0
    }
    Text {
        anchors.right: parent.right; anchors.rightMargin: 5 * panel.u
        y: 37 * panel.u - height / 2
        text: !Core.connected ? "RMS —" : ("RMS " + (Core.rmsDb > -89 ? "−" + Math.abs(Math.round(Core.rmsDb)) : "−∞") + " dBFS")
        color: Theme.pageDim; font.family: Theme.mono; font.pixelSize: 13 * panel.u
        opacity: panel.boot > 0 ? 1 : 0
    }

    HudRing {
        id: ring
        width: panel.ringR * 2.5
        height: width
        x: panel.cx - width / 2
        y: panel.cy - height / 2
        feed: Core
        mode: panel.mode
        ink: Theme.ink
        faint: Theme.pageFaint
        mid: Theme.pageMid
        accent: Theme.accent
        boot: panel.boot
        reducedMotion: Theme.reducedMotion
        running: panel.live
        repeats: panel.repeats
        MouseArea {
            anchors.centerIn: parent
            width: panel.ringR * 2.3; height: width
            cursorShape: (Core.state === "confirm" || Core.stats.confirms > 0) ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: panel.ringClicked()
        }
    }

    Text { text: "000"; color: Theme.ink; font.family: Theme.mono; font.pixelSize: 14 * panel.u
           x: panel.cx - width / 2; y: panel.cy - 1.294 * panel.ringR - height / 2; opacity: Math.min(1, panel.boot * 2) }
    Text { text: "180"; color: Theme.ink; font.family: Theme.mono; font.pixelSize: 14 * panel.u
           x: panel.cx - width / 2; y: panel.cy + 1.298 * panel.ringR - height / 2; opacity: Math.min(1, panel.boot * 2) }

    Odometer {
        visible: panel.showCaption
        width: panel.width
        y: panel.cy + 1.425 * panel.ringR - height / 2
        horizontalAlignment: Text.AlignHCenter
        text: panel.alarm && Core.connected ? "ALARM · " + (Core.stats.alarmRingingLabel || "").toUpperCase() : (panel.captions[panel.mode] || panel.mode.toUpperCase())
        color: panel.mode === "confirm" ? Theme.accent : Theme.ink
        font.family: Theme.mono
        font.pixelSize: 20 * panel.u
        font.letterSpacing: 7 * panel.u
        opacity: Math.min(1, panel.boot * 2)
    }
    Text {
        visible: panel.showCaption
        width: panel.width
        y: panel.cy + 1.555 * panel.ringR - height / 2
        horizontalAlignment: Text.AlignHCenter
        text: "32 bands · 60 Hz — 7.6 kHz · ×" + panel.repeats + " mirrored"
        color: Theme.pageDim; font.family: Theme.mono; font.pixelSize: 14 * panel.u
        opacity: Math.min(1, panel.boot * 2)
    }
}
