// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Page rules, vertical divider and footer (brief 1, 1.1).
import QtQuick
import Friday
import "fmt.js" as Fmt

Item {
    id: frame
    property real rulesP: 1
    property real dividerP: 1
    property string version: "0.4.0"
    readonly property real u: Theme.u
    readonly property real m: width * 0.021
    readonly property real topY: height * 0.028
    readonly property real botY: height * 0.9406
    readonly property real divX: width * 0.3485

    // rules draw outward from the horizontal centre
    Rectangle { x: frame.m + (frame.width - 2 * frame.m) * (1 - frame.rulesP) / 2; y: frame.topY
                width: (frame.width - 2 * frame.m) * frame.rulesP; height: 1; color: Theme.ink
                opacity: Theme.reducedMotion ? frame.rulesP : 1 }
    Rectangle { x: frame.m + (frame.width - 2 * frame.m) * (1 - frame.rulesP) / 2; y: frame.botY
                width: (frame.width - 2 * frame.m) * frame.rulesP; height: 1; color: Theme.ink
                opacity: Theme.reducedMotion ? frame.rulesP : 1 }
    // divider grows down from the top rule
    Rectangle { x: frame.divX; y: frame.topY; width: 1; height: (frame.botY - frame.topY) * frame.dividerP; color: Theme.ink }

    // footer
    Row {
        x: frame.m + 4 * frame.u
        y: frame.botY + 38 * frame.u - height / 2
        spacing: 0
        opacity: frame.rulesP
        Text { text: "F.R.I.D.A.Y."; color: Theme.ink; font.family: Theme.display; font.pixelSize: 19 * frame.u; font.weight: Font.Medium }
        Text { text: " · v" + frame.version + " · core "; color: Theme.pageDim; font.family: Theme.display; font.pixelSize: 19 * frame.u }
        Text { id: dotText; text: "●"; color: Core.connected ? Theme.ink : Theme.accent; font.pixelSize: 15 * frame.u; anchors.verticalCenter: parent.verticalCenter
               SequentialAnimation on opacity { running: !Core.connected && !Theme.reducedMotion; loops: Animation.Infinite; onRunningChanged: if (!running) dotText.opacity = 1
                   NumberAnimation { to: 0.25; duration: 500 } NumberAnimation { to: 1; duration: 500 } } }
        Text { text: Core.connected ? " connected" : " offline · retrying"; color: Theme.pageDim; font.family: Theme.display; font.pixelSize: 19 * frame.u }
    }
    Text {
        anchors.right: parent.right
        anchors.rightMargin: frame.m + 4 * frame.u
        y: frame.botY + 38 * frame.u - height / 2
        opacity: frame.rulesP
        text: Fmt.footerDate(Core.now)
        color: Theme.pageDim
        font.family: Theme.mono
        font.pixelSize: 16 * frame.u
    }
}
