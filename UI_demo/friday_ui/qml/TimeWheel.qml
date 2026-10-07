// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// A vertical scroll wheel with inertial snapping (alarm time picker, brief 5E).
import QtQuick
import QtQuick.Controls.Basic
import Friday

Tumbler {
    id: tw
    property int itemCount: 24
    property int current: 0
    property real u: Theme.u
    model: itemCount
    visibleItemCount: 3
    wrap: true
    width: 92 * u
    height: 190 * u
    Component.onCompleted: currentIndex = current
    onCurrentIndexChanged: current = currentIndex
    delegate: Text {
        required property int index
        required property var modelData
        text: (modelData < 10 ? "0" : "") + modelData
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: Theme.fgTile
        opacity: 1.0 - Math.abs(Tumbler.displacement) / (tw.visibleItemCount / 2) * 0.8
        font.family: Theme.mono
        font.pixelSize: (Math.abs(Tumbler.displacement) < 0.5 ? 46 : 34) * tw.u
    }
    background: Item {
        Rectangle { width: parent.width; height: 1; y: parent.height / 3; color: Theme.hairline }
        Rectangle { width: parent.width; height: 1; y: parent.height * 2 / 3; color: Theme.hairline }
    }
}
