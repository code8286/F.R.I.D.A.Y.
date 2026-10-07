// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Single line that scrolls when it does not fit, pausing 1.5 s at each end (brief 5F).
import QtQuick
import Friday

Item {
    id: mq
    property string text: ""
    property alias font: label.font
    property alias color: label.color
    property bool live: true
    clip: true
    implicitHeight: label.implicitHeight
    readonly property real overflow: Math.max(0, label.implicitWidth - width)
    Text { id: label; text: mq.text; textFormat: Text.PlainText; x: 0 }
    onTextChanged: { label.x = 0; if (scroll.running) scroll.restart() }
    onOverflowChanged: if (scroll.running) scroll.restart()
    SequentialAnimation {
        id: scroll
        running: mq.overflow > 2 && mq.live && !Theme.reducedMotion
        loops: Animation.Infinite
        PauseAnimation { duration: 1500 }
        NumberAnimation { target: label; property: "x"; to: -mq.overflow; duration: Math.max(800, mq.overflow * 28); easing.type: Easing.InOutSine }
        PauseAnimation { duration: 1500 }
        NumberAnimation { target: label; property: "x"; to: 0; duration: Math.max(800, mq.overflow * 28); easing.type: Easing.InOutSine }
    }
}
