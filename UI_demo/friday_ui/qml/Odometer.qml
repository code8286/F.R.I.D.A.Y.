// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// A glance value that rolls vertically when it changes (brief 3.3). Always plain text.
import QtQuick
import Friday

Item {
    id: od
    property string text: ""
    property alias font: cur.font
    property alias color: cur.color
    property alias horizontalAlignment: cur.horizontalAlignment
    property alias elide: cur.elide
    property string _last: ""
    implicitWidth: cur.implicitWidth
    implicitHeight: cur.implicitHeight
    clip: roll.running

    Text { id: prev; width: od.width; opacity: 0; font: cur.font; color: cur.color; textFormat: Text.PlainText
           horizontalAlignment: cur.horizontalAlignment; elide: cur.elide }
    Text { id: cur; width: od.width; text: od.text; textFormat: Text.PlainText }

    Component.onCompleted: _last = text
    onTextChanged: {
        if (Theme.reducedMotion || !od.visible || _last === "") { _last = text; return }
        prev.text = _last
        _last = text
        roll.restart()
    }
    ParallelAnimation {
        id: roll
        NumberAnimation { target: prev; property: "y"; from: 0; to: -od.height * 0.9; duration: Theme.base; easing.type: Easing.InOutCubic }
        NumberAnimation { target: prev; property: "opacity"; from: 1; to: 0; duration: Theme.base; easing.type: Easing.InCubic }
        NumberAnimation { target: cur; property: "y"; from: od.height * 0.9; to: 0; duration: Theme.base; easing.type: Easing.OutCubic }
        NumberAnimation { target: cur; property: "opacity"; from: 0; to: 1; duration: Theme.base; easing.type: Easing.OutCubic }
    }
}
