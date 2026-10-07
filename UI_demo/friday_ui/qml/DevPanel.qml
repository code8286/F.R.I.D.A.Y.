// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Demo controls (F1). Not part of the product: they poke the mock core so every state can be seen on demand.
import QtQuick
import Friday

Rectangle {
    id: dp
    property bool shown: false
    property real u: Theme.u
    width: 330 * u
    height: col.implicitHeight + 28 * u
    radius: 16 * u
    color: Theme.tile
    border.color: Theme.hairline
    opacity: shown ? 1 : 0
    visible: opacity > 0.01
    scale: shown ? 1 : 0.97
    Behavior on opacity { NumberAnimation { duration: Theme.d(Theme.fast) } }
    Behavior on scale { NumberAnimation { duration: Theme.d(Theme.fast) } }

    readonly property var items: [
        { k: Qt.Key_S, key: "Ctrl+S", label: "next HUD state", run: function () { Core.dev("next_state", {}) } },
        { k: Qt.Key_M, key: "Ctrl+M", label: "auto-cycle states (4 s)", run: function () { Core.dev("cycle", {}) }, on: function () { return Core.cycling } },
        { k: Qt.Key_K, key: "Ctrl+K", label: "clap", run: function () { Core.dev("clap", {}) } },
        { k: Qt.Key_N, key: "Ctrl+N", label: "Telegram message (untrusted)", run: function () { Core.dev("notify", {}) } },
        { k: Qt.Key_P, key: "Ctrl+P", label: "confirmation request (T3)", run: function () { Core.dev("confirm", {}) } },
        { k: Qt.Key_E, key: "Ctrl+E", label: "reminder due in 2 s", run: function () { Core.dev("fire_reminder", {}) } },
        { k: Qt.Key_R, key: "Ctrl+R", label: "ring an alarm", run: function () { Core.dev("ring_alarm", {}) } },
        { k: Qt.Key_F, key: "Ctrl+F", label: "core refuses next action", run: function () { Core.dev("fail_next", {}) } },
        { k: Qt.Key_O, key: "Ctrl+O", label: "core offline / online", run: function () { Core.dev("offline", {}) }, on: function () { return !Core.connected } },
        { k: Qt.Key_D, key: "Ctrl+D", label: "dark mode", run: function () { Theme.themeOverride = Theme.dark ? 1 : 2 }, on: function () { return Theme.dark } },
        { k: Qt.Key_T, key: "Ctrl+T", label: "reduced motion", run: function () { Theme.reducedMotion = !Theme.reducedMotion }, on: function () { return Theme.reducedMotion } }
    ]
    function handle(key) {
        for (var i = 0; i < items.length; i++) if (items[i].k === key) { items[i].run(); return true }
        return false
    }

    Column {
        id: col
        x: 16 * dp.u; y: 14 * dp.u
        width: dp.width - 32 * dp.u
        spacing: 2 * dp.u
        Text { text: "DEMO CONTROLS · mock core"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 11 * dp.u; font.letterSpacing: 1.5 * dp.u; bottomPadding: 6 * dp.u }
        Repeater {
            model: dp.items.length
            delegate: Item {
                required property int index
                readonly property var it: dp.items[index]
                width: col.width; height: 26 * dp.u
                Rectangle { anchors.fill: parent; radius: 6 * dp.u; color: rowMa.containsMouse ? "#1C1C1C" : "transparent" }
                Text { x: 6 * dp.u; anchors.verticalCenter: parent.verticalCenter; text: parent.it.key; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 12 * dp.u }
                Text { x: 74 * dp.u; anchors.verticalCenter: parent.verticalCenter; text: parent.it.label; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 14 * dp.u }
                Rectangle { visible: parent.it.on !== undefined; anchors.right: parent.right; anchors.rightMargin: 6 * dp.u; anchors.verticalCenter: parent.verticalCenter
                            width: 8 * dp.u; height: width; radius: width / 2
                            color: (parent.it.on !== undefined && dp.shown && parent.it.on()) ? Theme.accent : "#333" }
                MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.it.run() }
            }
        }
        Text { text: "1–8 open tiles · arrows/Tab focus · Enter open · Esc back\nhold Space: push-to-talk · F1 hide"; color: Theme.dimOnTile
               font.family: Theme.mono; font.pixelSize: 11 * dp.u; topPadding: 8 * dp.u; lineHeight: 1.3 }
    }
}
