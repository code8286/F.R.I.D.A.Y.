// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Small notice above the footer (action refused, confirmation needed, ...).
import QtQuick
import Friday

Rectangle {
    id: t
    property real u: Theme.u
    function show(msg, bad) { label.text = msg; t.bad = bad; anim.restart() }
    property bool bad: false
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.horizontalCenterOffset: parent.width * 0.17
    y: parent.height * 0.9406 - height - 14 * u
    width: label.implicitWidth + 28 * u
    height: 32 * u
    radius: height / 2
    color: Theme.ink
    opacity: 0
    visible: opacity > 0.01
    Text { id: label; anchors.centerIn: parent; color: t.bad ? Theme.accent : Theme.page; font.family: Theme.mono; font.pixelSize: 13 * t.u; textFormat: Text.PlainText }
    SequentialAnimation {
        id: anim
        NumberAnimation { target: t; property: "opacity"; to: 1; duration: Theme.d(Theme.fast) }
        PauseAnimation { duration: 2600 }
        NumberAnimation { target: t; property: "opacity"; to: 0; duration: Theme.d(Theme.base) }
    }
}
