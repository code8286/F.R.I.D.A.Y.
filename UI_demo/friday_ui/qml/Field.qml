// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Text input on a black tile: mono, hairline underline, Esc hands focus back to the page.
import QtQuick
import QtQuick.Controls.Basic
import Friday

TextField {
    id: f
    property real u: Theme.u
    property real px: 18
    property bool monoFont: true
    color: Theme.fgTile
    placeholderTextColor: "#5E5E5B"
    selectionColor: Theme.accent
    selectedTextColor: "#000000"
    font.family: monoFont ? Theme.mono : Theme.display
    font.pixelSize: px * u
    leftPadding: 0; rightPadding: 0; topPadding: 6 * u; bottomPadding: 8 * u
    background: Item {
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: f.activeFocus ? Theme.fgTile : Theme.hairline
                    Behavior on color { ColorAnimation { duration: Theme.d(Theme.fast) } } }
    }
    Keys.onEscapePressed: (e) => { if (f.text !== "") { f.text = ""; e.accepted = true } else { e.accepted = false } }
}
