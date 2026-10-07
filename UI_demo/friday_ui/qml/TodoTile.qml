// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile D: your to-do list (brief 5D). Distinct from the AI task queue in G.
import QtQuick
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "To-do\nList"
    property bool live: true
    readonly property var st: Core.stats

    IconTodo {
        anchors.right: parent.right; anchors.rightMargin: 43 * tile.u
        y: 59 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        hovered: tile.hovered; live: tile.live && !tile.isOpen
    }
    Item {
        visible: tile.st.todoFirst !== ""
        x: tile.pad; y: tile.height - 192 * tile.u - height / 2
        width: tile.width - 2 * tile.pad; height: firstText.implicitHeight
        Rectangle { width: 9 * tile.u; height: width; radius: width / 2; color: "transparent"; border.color: tile.fg; border.width: 1.2
                    x: 0; anchors.verticalCenter: parent.verticalCenter }
        Odometer { id: firstText; x: 20 * tile.u; width: parent.width - x; text: tile.st.todoFirst || ""; color: tile.fg; elide: Text.ElideRight
                   font.family: Theme.mono; font.pixelSize: 17 * tile.u }
    }
    Odometer {
        x: tile.pad; y: tile.height - 159 * tile.u - height / 2
        width: tile.width - 2 * tile.pad
        text: tile.st.todoOpen === undefined ? "" : (tile.st.todoOpen + " open · " + tile.st.todoDueToday + " due today")
        color: tile.dim
        font.family: Theme.mono; font.pixelSize: 19 * tile.u
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            property int addPrio: 2
            property bool addDue: false
            property string undoId: ""
            property string undoText: ""

            Text { x: tile.pad; y: 66 * ex.u; text: "To-do list"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text { x: tile.pad; y: 128 * ex.u; text: tile.st.todoOpen + " open · " + tile.st.todoDueToday + " due today · drag ⋮⋮ to reorder · swipe left to delete"
                   color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u }

            // add row
            Item {
                id: addRow
                x: tile.pad; y: 172 * ex.u
                width: ex.width - 2 * tile.pad; height: 44 * ex.u
                Text { text: "+"; color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 20 * ex.u; anchors.verticalCenter: input.verticalCenter }
                Field {
                    id: input
                    x: 28 * ex.u; width: parent.width * 0.58
                    anchors.verticalCenter: parent.verticalCenter
                    placeholderText: "Add a to-do and press Enter"
                    monoFont: false; px: 19
                    onAccepted: {
                        if (text.trim() === "") return
                        Core.action("todo.add", { "text": text.trim(), "priority": ex.addPrio, "due": ex.addDue ? Core.todayAt(18, 0) : 0 })
                        text = ""
                    }
                }
                Row {
                    anchors.left: input.right; anchors.leftMargin: 24 * ex.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12 * ex.u
                    PriorityTicks { prio: ex.addPrio; onCycled: ex.addPrio = ex.addPrio % 3 + 1; anchors.verticalCenter: parent.verticalCenter }
                    Chip { text: ex.addDue ? "due today 18:00" : "no due date"; fg: ex.addDue ? Theme.fgTile : Theme.dimOnTile
                           anchors.verticalCenter: parent.verticalCenter
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: ex.addDue = !ex.addDue } }
                    TextButton { text: "Add"; fontPx: 15; implicitHeight: 28 * ex.u; anchors.verticalCenter: parent.verticalCenter
                                 onClicked: input.accepted() }
                }
            }

            Flickable {
                id: flick
                x: tile.pad; y: 236 * ex.u
                width: ex.width - 2 * tile.pad
                height: ex.height - y - 30 * ex.u
                contentHeight: body.height + 60 * ex.u
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: body
                    width: flick.width
                    spacing: 0
                    SectionLabel { text: "OPEN · " + Core.todoOpen.count; bottomPadding: 8 * ex.u }
                    Hairline { width: parent.width }
                    ListView {
                        id: openList
                        width: parent.width
                        height: contentHeight
                        interactive: false
                        model: Core.todoOpen
                        property real rowH: 56 * ex.u
                        add: Transition { ParallelAnimation {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                            NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } } }
                        remove: Transition { ParallelAnimation {
                            NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) }
                            NumberAnimation { property: "scale"; to: 0.97; duration: Theme.d(Theme.base) } } }
                        displaced: Transition { NumberAnimation { properties: "x,y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                        move: Transition { NumberAnimation { properties: "x,y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                        delegate: TodoRow {
                            width: openList.width; height: openList.rowH
                            list: openList
                            onDeleted: (id, text) => { ex.undoId = id; ex.undoText = text; undoTimer.restart() }
                        }
                    }
                    Item { width: 1; height: 26 * ex.u }
                    SectionLabel { text: "DONE · " + Core.todoDone.count; bottomPadding: 8 * ex.u }
                    Hairline { width: parent.width }
                    ListView {
                        id: doneList
                        width: parent.width
                        height: contentHeight
                        interactive: false
                        model: Core.todoDone
                        add: Transition { ParallelAnimation {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.d(Theme.base) }
                            NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: Theme.d(Theme.base) } } }
                        remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.d(Theme.base) } }
                        displaced: Transition { NumberAnimation { properties: "x,y"; duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                        delegate: TodoRow { width: doneList.width; height: 50 * ex.u; list: doneList
                                            onDeleted: (id, text) => { ex.undoId = id; ex.undoText = text; undoTimer.restart() } }
                    }
                }
            }

            // undo toast (5 s)
            Timer { id: undoTimer; interval: 5000; onTriggered: ex.undoId = "" }
            Rectangle {
                visible: opacity > 0.01
                opacity: ex.undoId !== "" ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.d(Theme.fast) } }
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom; anchors.bottomMargin: 26 * ex.u
                width: undoRow.implicitWidth + 32 * ex.u; height: 42 * ex.u; radius: height / 2
                color: "#1A1A1A"; border.color: Theme.hairline
                Row {
                    id: undoRow
                    anchors.centerIn: parent
                    spacing: 16 * ex.u
                    Text { text: "Deleted “" + ex.undoText + "”"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 16 * ex.u; textFormat: Text.PlainText
                           anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; width: Math.min(implicitWidth, 420 * ex.u) }
                    TextButton { text: "Undo"; fontPx: 14; implicitHeight: 26 * ex.u; anchors.verticalCenter: parent.verticalCenter
                                 onClicked: { Core.action("todo.undo_delete", { "id": ex.undoId }); ex.undoId = "" } }
                }
            }
        }
    }
}
