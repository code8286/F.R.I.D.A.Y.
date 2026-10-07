// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// H, expanded: standing commands with countdowns, run now / pause / edit / delete, and the "+ New" editor
// (typewriter preview + parsed schedule). Saving goes to the core, which returns a confirmation card.
import QtQuick
import Friday
import "fmt.js" as Fmt

Item {
    id: ex
    property bool live: true
    property bool startEditing: false
    readonly property real u: Theme.u
    readonly property real pad: 33 * u
    readonly property var st: Core.stats
    property bool editing: startEditing
    readonly property var parsed: Core.parseTrigger(trigIn.text)
    onEditingChanged: if (editing) cmdIn.forceActiveFocus()
    Component.onCompleted: if (editing) cmdIn.forceActiveFocus()

    TextButton { anchors.right: parent.right; anchors.rightMargin: 30 * ex.u; y: 35 * ex.u; text: ex.editing ? "Cancel" : "+ New"; fontPx: 18; implicitHeight: 33 * ex.u
                 onClicked: ex.editing = !ex.editing }
    Text { x: ex.pad; y: 66 * ex.u; text: "Commands"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
    Text { x: ex.pad; y: 128 * ex.u; text: ex.st.cmdStanding + " standing · " + ex.st.cmdPaused + " paused · standing instructions to FRIDAY itself"
           color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }

    Rectangle {
        id: editor
        x: ex.pad; y: 172 * ex.u
        width: ex.width - 2 * ex.pad
        height: ex.editing ? 200 * ex.u : 0
        clip: true
        radius: 14 * ex.u
        color: "#0E0E0E"; border.color: ex.editing ? Theme.hairline : "transparent"
        Behavior on height { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
        Row {
            x: 22 * ex.u; y: 18 * ex.u
            spacing: 18 * ex.u
            Field { id: cmdIn; width: editor.width * 0.52; placeholderText: "what should FRIDAY do? e.g. summarise new GitHub issues"; px: 16
                    onAccepted: trigIn.forceActiveFocus() }
            Field { id: trigIn; width: editor.width * 0.3; placeholderText: "when? daily 08:00 · every 2h · on wake"; px: 16
                    onAccepted: save.clicked() }
        }
        // typewriter mirror of what is being typed
        Row {
            x: 22 * ex.u; y: 82 * ex.u
            spacing: 6 * ex.u
            Text { text: "›"; color: "#7A7A77"; font.family: Theme.mono; font.pixelSize: 18 * ex.u }
            Text { text: cmdIn.text; textFormat: Text.PlainText; color: Theme.fgTile; font.family: Theme.mono; font.pixelSize: 18 * ex.u }
            Rectangle { width: 9 * ex.u; height: 20 * ex.u; color: Theme.fgTile; anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity { running: ex.editing && !Theme.reducedMotion; loops: Animation.Infinite
                            PropertyAction { value: 1 } PauseAnimation { duration: 530 } PropertyAction { value: 0 } PauseAnimation { duration: 530 } } }
        }
        Text { x: 40 * ex.u; y: 116 * ex.u; text: trigIn.text === "" ? "→ add a trigger" : ex.parsed.human
               color: ex.parsed.ok ? Theme.dimOnTile : (trigIn.text === "" ? "#5E5E5B" : Theme.accent); font.family: Theme.mono; font.pixelSize: 14 * ex.u }
        Row {
            x: 22 * ex.u; y: 150 * ex.u
            spacing: 12 * ex.u
            TextButton { id: save; text: "Save"; filled: true; fontPx: 15; implicitHeight: 30 * ex.u; enabledLook: cmdIn.text.trim() !== "" && ex.parsed.ok
                onClicked: { Core.action("command.create", { "text": cmdIn.text.trim(), "trigger": trigIn.text.trim() }); cmdIn.text = ""; trigIn.text = ""; ex.editing = false } }
            Text { anchors.verticalCenter: parent.verticalCenter; text: "Standing commands can trigger tools, so the core asks you to approve them in A."
                   color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 12 * ex.u }
        }
    }

    ListView {
        id: list
        x: ex.pad - 12 * ex.u; y: editor.y + editor.height + 18 * ex.u
        width: ex.width - 2 * ex.pad + 24 * ex.u
        height: ex.height - y - 26 * ex.u
        clip: true
        model: Core.commands
        boundsBehavior: Flickable.StopAtBounds
        add: Transition { ParallelAnimation { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                                              NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base) } } }
        remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
        displaced: Transition { NumberAnimation { properties: "y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
        delegate: Item {
            id: row
            required property var model
            width: list.width; height: 74 * ex.u
            property bool edit: false
            readonly property bool paused: !!model.paused
            readonly property real frac: (model.period > 0 && model.next > 0) ? Math.max(0, Math.min(1, (model.next - Core.now) / model.period)) : 1
            property real flash: 0
            Rectangle { anchors.fill: parent; radius: 10 * ex.u; color: Theme.flash; opacity: row.flash }
            Rectangle { anchors.fill: parent; radius: 10 * ex.u; color: "#0B0B0B"; visible: hov.hovered && row.flash < 0.01 }
            HoverHandler { id: hov }
            CountdownRing { x: 24 * ex.u; anchors.verticalCenter: parent.verticalCenter; width: 24 * ex.u; height: width
                            kind: row.paused ? "paused" : (row.model.kind === "event" ? "event" : "timer"); fraction: row.frac; flash: row.flash > 0.05 }
            Text { x: 64 * ex.u; y: 14 * ex.u; text: "›"; color: "#7A7A77"; font.family: Theme.mono; font.pixelSize: 18 * ex.u }
            Text { visible: !row.edit; x: 84 * ex.u; y: 12 * ex.u; width: actions.x - x - 20 * ex.u; text: row.model.text; textFormat: Text.PlainText; elide: Text.ElideRight
                   color: row.paused ? "#5E5E5B" : Theme.fgTile; font.family: Theme.mono; font.pixelSize: 18 * ex.u }
            Field { id: editIn; visible: row.edit; x: 84 * ex.u; y: 6 * ex.u; width: actions.x - x - 20 * ex.u; px: 17; text: row.model.text
                    onAccepted: { Core.action("command.update", { "id": row.model.id, "text": text }); row.edit = false }
                    Keys.onEscapePressed: row.edit = false }
            Text { x: 84 * ex.u; y: 42 * ex.u; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u
                   text: (row.paused ? "paused" : (row.model.kind === "event" ? "runs " + row.model.chip : (row.model.next ? "next " + Fmt.relIn(row.model.next - Core.now) : "done"))) + "  ·  last: " + (row.model.last || "never") }
            Row {
                id: actions
                anchors.right: parent.right; anchors.rightMargin: 14 * ex.u; anchors.verticalCenter: parent.verticalCenter
                spacing: 6 * ex.u
                Row {
                    visible: hov.hovered
                    spacing: 2 * ex.u
                    anchors.verticalCenter: parent.verticalCenter
                    GlyphButton { glyph: "▶"; px: 12; onClicked: Core.action("command.run_now", { "id": row.model.id }) }
                    GlyphButton { glyph: row.paused ? "↺" : "‖"; onClicked: Core.action(row.paused ? "command.resume" : "command.pause", { "id": row.model.id }) }
                    GlyphButton { glyph: "✎"; px: 14; onClicked: { editIn.text = row.model.text; row.edit = true; editIn.forceActiveFocus() } }
                    GlyphButton { glyph: "×"; onClicked: Core.action("command.delete", { "id": row.model.id }) }
                }
                Chip { anchors.verticalCenter: parent.verticalCenter; text: row.paused ? "paused" : row.model.chip; fontPx: 13; implicitHeight: 24 * ex.u
                       fg: row.paused ? "#5E5E5B" : Theme.fgTile; line: row.paused ? "#2A2A28" : "#4A4A48" }
            }
            Item {
                x: 20 * ex.u; width: parent.width - 40 * ex.u; anchors.bottom: parent.bottom; height: 1.5 * ex.u; clip: true
                Rectangle { width: parent.width; height: 1; color: Theme.hairline }
                Rectangle { id: pulse; visible: false; width: parent.width * 0.3; height: 1.5 * ex.u
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.8; color: Theme.fgTile } GradientStop { position: 1; color: "transparent" } } }
            }
            SequentialAnimation {
                id: fire
                PropertyAction { target: pulse; property: "visible"; value: true }
                NumberAnimation { target: row; property: "flash"; to: 1; duration: 90 }
                ParallelAnimation {
                    NumberAnimation { target: pulse; property: "x"; from: -pulse.width; to: row.width; duration: 700; easing.type: Easing.InOutCubic }
                    NumberAnimation { target: row; property: "flash"; to: 0; duration: 700 }
                }
                PropertyAction { target: pulse; property: "visible"; value: false }
            }
            Connections { target: Core; function onCoreEvent(name, p) { if (name === "command.fired" && p.id === row.model.id && !Theme.reducedMotion) fire.restart() } }
        }
    }
}
