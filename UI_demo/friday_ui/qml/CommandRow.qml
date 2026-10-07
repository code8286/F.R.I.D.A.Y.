// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// One standing command (compact form): countdown ring, prompt glyph, command, trigger chip, fire pulse.
import QtQuick
import Friday

Item {
    id: r
    required property var model
    property bool live: true
    readonly property real u: Theme.u
    readonly property bool paused: !!model.paused
    readonly property real frac: (model.period > 0 && model.next > 0) ? Math.max(0, Math.min(1, (model.next - Core.now) / model.period)) : 1
    readonly property color txt: paused ? "#4E4E4B" : Theme.fgTile
    property real flash: 0
    property real pulse: -1

    Rectangle { anchors.fill: parent; anchors.leftMargin: 18 * r.u; anchors.rightMargin: 18 * r.u; radius: 8 * r.u; color: Theme.flash; opacity: r.flash }
    CountdownRing { x: 31 * r.u; anchors.verticalCenter: parent.verticalCenter
                    kind: r.paused ? "paused" : (r.model.kind === "event" ? "event" : "timer"); fraction: r.frac; flash: r.flash > 0.05
                    fg: r.paused ? "#3A3A38" : Theme.fgTile }
    Text { x: 64 * r.u; anchors.verticalCenter: parent.verticalCenter; text: "›"; color: r.paused ? "#3A3A38" : "#7A7A77"; font.family: Theme.mono; font.pixelSize: 15 * r.u }
    Text {
        x: 84 * r.u; anchors.verticalCenter: parent.verticalCenter
        width: chip.x - x - 12 * r.u
        text: r.model.text || ""; textFormat: Text.PlainText; elide: Text.ElideRight
        color: r.txt; font.family: Theme.mono; font.pixelSize: 16 * r.u
    }
    Chip {
        id: chip
        anchors.right: parent.right; anchors.rightMargin: 30 * r.u; anchors.verticalCenter: parent.verticalCenter
        text: r.paused ? "paused" : (r.model.chip || "")
        fg: r.paused ? "#4E4E4B" : Theme.fgTile; line: r.paused ? "#2A2A28" : "#4A4A48"
    }
    Item {
        x: 30 * r.u; width: parent.width - 60 * r.u
        anchors.bottom: parent.bottom; height: 1.5 * r.u
        clip: true
        Rectangle { width: parent.width; height: 1; color: Theme.hairline }
        Rectangle {          // the fire pulse travels left to right
            visible: r.pulse >= 0
            width: parent.width * 0.3; height: 1.5 * r.u
            x: -width + r.pulse * (parent.width + width)
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.8; color: Theme.fgTile } GradientStop { position: 1; color: "transparent" } }
        }
    }
    function fire() {
        if (Theme.reducedMotion) { fadeOnly.restart(); return }
        fireAnim.restart()
    }
    SequentialAnimation {
        id: fireAnim
        NumberAnimation { target: r; property: "flash"; to: 1; duration: 90 }
        ParallelAnimation {
            NumberAnimation { target: r; property: "pulse"; from: 0; to: 1; duration: 700; easing.type: Easing.InOutCubic }
            NumberAnimation { target: r; property: "flash"; to: 0; duration: 700 }
        }
        PropertyAction { target: r; property: "pulse"; value: -1 }
    }
    SequentialAnimation { id: fadeOnly; NumberAnimation { target: r; property: "flash"; to: 1; duration: 60 } NumberAnimation { target: r; property: "flash"; to: 0; duration: 120 } }
    Connections { target: Core; function onCoreEvent(name, p) { if (name === "command.fired" && p.id === r.model.id) r.fire() } }
}
