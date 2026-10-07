// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Tile B: calendar (brief 5B). Month / week / day views; every change goes through the core's calendar tool.
import QtQuick
import Friday
import "fmt.js" as Fmt

Tile {
    id: tile
    title: "Calendar"
    property bool live: true
    readonly property var st: Core.stats

    IconCalendar {
        anchors.right: parent.right; anchors.rightMargin: 38 * tile.u
        y: 40 * tile.u
        scale: tile.u; transformOrigin: Item.TopRight
        hovered: tile.hovered; live: tile.live && !tile.isOpen
    }
    // week strip
    Repeater {
        model: 7
        delegate: Item {
            required property int index
            readonly property bool today: index === tile.st.weekday
            x: tile.pad + (8 + index * 31) * tile.u - width / 2
            y: tile.height - 160 * tile.u - letter.height / 2
            width: 20 * tile.u; height: 40 * tile.u
            Text { id: letter; anchors.horizontalCenter: parent.horizontalCenter; text: Fmt.LETTERS[parent.index]
                   color: parent.today ? tile.fg : "#8C8C88"; font.family: Theme.mono; font.pixelSize: 15 * tile.u }
            Rectangle { visible: parent.today; anchors.horizontalCenter: parent.horizontalCenter; y: letter.height - 1 * tile.u
                        width: 11 * tile.u; height: 1.5 * tile.u; color: tile.fg }
            Rectangle { visible: tile.st.week ? !!tile.st.week[parent.index] : false
                        anchors.horizontalCenter: parent.horizontalCenter; y: 18 * tile.u + letter.height / 2
                        width: 3.6 * tile.u; height: width; radius: width / 2; color: tile.fg }
        }
    }
    Odometer {
        x: tile.pad; y: tile.height - 106 * tile.u - height / 2
        width: tile.width - 2 * tile.pad
        text: tile.st.eventNextTitle ? tile.st.eventNextTitle + " · " + (tile.st.eventNextAt <= Core.now ? "now" : Fmt.relIn(tile.st.eventNextAt - Core.now)) : "Nothing scheduled"
        color: tile.fg; elide: Text.ElideRight
        font.family: Theme.mono; font.pixelSize: 19 * tile.u
    }

    expanded: Component {
        Item {
            id: ex
            readonly property real u: Theme.u
            property string viewMode: "month"
            property int vy: new Date(Core.now * 1000).getFullYear()
            property int vm: new Date(Core.now * 1000).getMonth()
            property int sy: 0
            property int sm: 0
            property int sd: 1
            Component.onCompleted: { var t = new Date(Core.now * 1000); sy = t.getFullYear(); sm = t.getMonth(); sd = t.getDate() }
            property int gen: 0
            property int dir: 0
            property int rev: 0
            Connections { target: Core.events
                function onCountChanged() { ex.rev++ }
                function onDataChanged() { ex.rev++ } }
            readonly property var todayD: new Date(Core.now * 1000)
            function isToday(y, m, d) { return y === todayD.getFullYear() && m === todayD.getMonth() && d === todayD.getDate() }
            function shiftMonth(k) {
                dir = k
                var d = new Date(vy, vm + k, 1)
                vy = d.getFullYear(); vm = d.getMonth()
                gen++
            }
            function goToday() { var t = todayD; dir = 0; vy = t.getFullYear(); vm = t.getMonth(); sy = vy; sm = vm; sd = t.getDate(); gen++ }
            function select(y, m, d) { sy = y; sm = m; sd = d; if (m !== vm || y !== vy) { dir = (y * 12 + m) > (vy * 12 + vm) ? 1 : -1; vy = y; vm = m; gen++ } }
            function shiftDays(k) { var d = new Date(sy, sm, sd + k); select(d.getFullYear(), d.getMonth(), d.getDate()) }
            readonly property var cells: {
                var first = new Date(vy, vm, 1)
                var lead = (first.getDay() + 6) % 7
                var out = []
                for (var i = 0; i < 42; i++) {
                    var d = new Date(vy, vm, 1 - lead + i)
                    out.push({ y: d.getFullYear(), m: d.getMonth(), d: d.getDate(), inMonth: d.getMonth() === vm })
                }
                return out
            }
            readonly property var monthDays: { rev; return Core.eventDays(vy, vm + 1) }
            readonly property var selEvents: { rev; return Core.eventsOn(sy, sm + 1, sd) }
            readonly property var weekStart: { var d = new Date(sy, sm, sd); return new Date(sy, sm, sd - (d.getDay() + 6) % 7) }

            Text { x: tile.pad; y: 66 * ex.u; text: "Calendar"; color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 46 * ex.u }
            Text {
                x: tile.pad; y: 128 * ex.u
                text: ex.viewMode === "month" ? (Fmt.MONTHS_LONG[ex.vm] + " " + ex.vy + " · " + ex.monthDays.length + " days with events")
                      : ex.viewMode === "week" ? ("Week of " + Fmt.DAYS[ex.weekStart.getDay()] + " " + ex.weekStart.getDate() + " " + Fmt.MONTHS[ex.weekStart.getMonth()])
                      : (Fmt.DAYS[new Date(ex.sy, ex.sm, ex.sd).getDay()] + " " + ex.sd + " " + Fmt.MONTHS_LONG[ex.sm] + " " + ex.sy)
                color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 14 * ex.u
            }
            Row {
                anchors.right: parent.right; anchors.rightMargin: tile.pad
                y: 72 * ex.u
                spacing: 8 * ex.u
                GlyphButton { glyph: "‹"; px: 20; anchors.verticalCenter: parent.verticalCenter
                              onClicked: ex.viewMode === "month" ? ex.shiftMonth(-1) : ex.shiftDays(ex.viewMode === "week" ? -7 : -1) }
                TextButton { text: "Today"; fontPx: 14; implicitHeight: 28 * ex.u; anchors.verticalCenter: parent.verticalCenter; onClicked: ex.goToday() }
                GlyphButton { glyph: "›"; px: 20; anchors.verticalCenter: parent.verticalCenter
                              onClicked: ex.viewMode === "month" ? ex.shiftMonth(1) : ex.shiftDays(ex.viewMode === "week" ? 7 : 1) }
                Item { width: 16 * ex.u; height: 1 }
                Repeater {
                    model: ["month", "week", "day"]
                    Chip { required property string modelData; text: modelData; filled: ex.viewMode === modelData; fontPx: 13; implicitHeight: 28 * ex.u
                           anchors.verticalCenter: parent.verticalCenter
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { ex.viewMode = parent.modelData; ex.gen++ } } }
                }
            }

            // ------------------------------------------------ body
            Item {
                id: body
                x: tile.pad; y: 176 * ex.u
                width: ex.width - 2 * tile.pad
                height: ex.height - y - 30 * ex.u
                readonly property real agendaW: ex.viewMode === "day" ? 0 : Math.min(380 * ex.u, width * 0.32)
                readonly property real mainW: width - agendaW - (agendaW > 0 ? 28 * ex.u : 0)

                // month grid
                Item {
                    id: month
                    visible: ex.viewMode === "month"
                    width: body.mainW; height: body.height
                    property real slide: 0
                    x: slide
                    opacity: 1 - Math.abs(slide) / (60 * ex.u)
                    Connections { target: ex; function onGenChanged() { if (!Theme.reducedMotion && ex.dir !== 0) { month.slide = ex.dir * 40 * ex.u; slideBack.restart() } } }
                    NumberAnimation { id: slideBack; target: month; property: "slide"; to: 0; duration: Theme.base; easing.type: Easing.OutCubic }
                    readonly property real cw: width / 7
                    readonly property real chh: (height - 34 * ex.u) / 6
                    Repeater {
                        model: 7
                        Text { required property int index; x: index * month.cw + 10 * ex.u; text: Fmt.LETTERS[index]; color: "#6E6E6B"; font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                    }
                    Repeater {
                        model: 42
                        delegate: Item {
                            id: cell
                            required property int index
                            readonly property var c: ex.cells[index]
                            readonly property int row: Math.floor(index / 7)
                            readonly property int col: index % 7
                            readonly property bool today: ex.isToday(c.y, c.m, c.d)
                            readonly property bool selected: c.y === ex.sy && c.m === ex.sm && c.d === ex.sd
                            readonly property int nEvents: { ex.rev; return c.inMonth && ex.monthDays.indexOf(c.d) >= 0 ? Math.min(3, Core.eventsOn(c.y, c.m + 1, c.d).length) : 0 }
                            x: col * month.cw; y: 34 * ex.u + row * month.chh + shift
                            width: month.cw - 6 * ex.u; height: month.chh - 6 * ex.u
                            property real shift: 0
                            property real dotsPop: 1
                            Rectangle { anchors.fill: parent; radius: 10 * ex.u; color: cell.selected ? "#141414" : (cma.containsMouse ? "#0D0D0D" : "transparent")
                                        border.color: cell.selected ? "#3A3A38" : "transparent" }
                            Text { id: num; x: 12 * ex.u; y: 10 * ex.u; text: cell.c.d; color: cell.today ? "#000000" : (cell.c.inMonth ? Theme.fgTile : "#3E3E3C")
                                   font.family: Theme.mono; font.pixelSize: 16 * ex.u; z: 2 }
                            Rectangle { visible: cell.today; anchors.centerIn: num; width: 30 * ex.u; height: width; radius: width / 2; color: Theme.fgTile; z: 1
                                        opacity: todayRing.progress }
                            Canvas {
                                id: todayRing
                                visible: cell.today
                                anchors.centerIn: num
                                width: 38 * ex.u; height: width; z: 1
                                property real progress: 0
                                onProgressChanged: requestPaint()
                                onPaint: { var ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = "#F5F5F2"; ctx.lineWidth = 1.5 * ex.u
                                           ctx.beginPath(); ctx.arc(width / 2, height / 2, width / 2 - 1.5 * ex.u, -Math.PI / 2, -Math.PI / 2 + progress * Math.PI * 2); ctx.stroke() }
                                NumberAnimation on progress { running: cell.today; from: 0; to: 1; duration: Theme.d(Theme.slow); easing.type: Easing.OutCubic }
                            }
                            Row {
                                x: 12 * ex.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 12 * ex.u
                                spacing: 5 * ex.u
                                Repeater { model: cell.nEvents
                                    Rectangle { width: 6 * ex.u; height: width; radius: width / 2; color: Theme.fgTile; scale: cell.dotsPop } }
                            }
                            MouseArea { id: cma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: ex.select(cell.c.y, cell.c.m, cell.c.d)
                                        onDoubleClicked: { ex.select(cell.c.y, cell.c.m, cell.c.d); ex.viewMode = "day"; ex.gen++ } }
                            // diagonal cascade: delay = (row + col) x 15 ms, then the event dots pop
                            SequentialAnimation {
                                id: cascade
                                PropertyAction { target: cell; property: "opacity"; value: 0 }
                                PropertyAction { target: cell; property: "shift"; value: 8 * ex.u }
                                PropertyAction { target: cell; property: "dotsPop"; value: 0 }
                                PauseAnimation { duration: (cell.row + cell.col) * 15 }
                                ParallelAnimation {
                                    NumberAnimation { target: cell; property: "opacity"; to: 1; duration: Theme.base; easing.type: Easing.OutCubic }
                                    NumberAnimation { target: cell; property: "shift"; to: 0; duration: Theme.base; easing.type: Easing.OutCubic }
                                }
                                NumberAnimation { target: cell; property: "dotsPop"; to: 1; duration: Theme.base; easing.type: Easing.OutBack; easing.overshoot: 2.2 }
                            }
                            function run() { if (Theme.reducedMotion) { opacity = 1; shift = 0; dotsPop = 1 } else cascade.restart() }
                            Component.onCompleted: run()
                            Connections { target: ex; function onGenChanged() { cell.run() } }
                        }
                    }
                }

                // week / day timeline
                Item {
                    id: timeline
                    visible: ex.viewMode !== "month"
                    width: body.mainW; height: body.height
                    opacity: visible ? 1 : 0
                    readonly property int h0: 7
                    readonly property int h1: 23
                    readonly property real axisW: 56 * ex.u
                    readonly property int ndays: ex.viewMode === "week" ? 7 : 1
                    readonly property real colW: (width - axisW) / ndays
                    readonly property real topY: 40 * ex.u
                    readonly property real hourH: (height - topY) / (h1 - h0)
                    function yOf(ts) { var d = new Date(ts * 1000); return topY + (d.getHours() + d.getMinutes() / 60 - h0) * hourH }
                    property string openEvent: ""
                    Repeater {
                        model: timeline.h1 - timeline.h0 + 1
                        Item {
                            required property int index
                            y: timeline.topY + index * timeline.hourH
                            width: timeline.width
                            Text { text: Fmt.pad2(timeline.h0 + parent.index) + ":00"; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 11 * ex.u; y: -height / 2 }
                            Rectangle { x: timeline.axisW; width: timeline.width - timeline.axisW; height: 1; color: "#1C1C1C" }
                        }
                    }
                    Repeater {
                        model: timeline.ndays
                        delegate: Item {
                            id: dcol
                            required property int index
                            readonly property var day: ex.viewMode === "week" ? new Date(ex.weekStart.getFullYear(), ex.weekStart.getMonth(), ex.weekStart.getDate() + index) : new Date(ex.sy, ex.sm, ex.sd)
                            readonly property bool today: ex.isToday(day.getFullYear(), day.getMonth(), day.getDate())
                            readonly property var evs: { ex.rev; return Core.eventsOn(day.getFullYear(), day.getMonth() + 1, day.getDate()) }
                            x: timeline.axisW + index * timeline.colW
                            width: timeline.colW; height: timeline.height
                            Text { x: 8 * ex.u; text: Fmt.DAYS[dcol.day.getDay()] + " " + dcol.day.getDate(); color: dcol.today ? Theme.fgTile : Theme.dimOnTile
                                   font.family: Theme.mono; font.pixelSize: 13 * ex.u; font.underline: dcol.today
                                   MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                               onClicked: { ex.select(dcol.day.getFullYear(), dcol.day.getMonth(), dcol.day.getDate()); ex.viewMode = "day" } } }
                            Rectangle { x: 0; y: timeline.topY; width: 1; height: parent.height - timeline.topY; color: "#1C1C1C" }
                            Repeater {
                                model: dcol.evs
                                delegate: Rectangle {
                                    id: blk
                                    required property var modelData
                                    readonly property bool opened: timeline.openEvent === modelData.id
                                    x: 6 * ex.u; width: dcol.width - 12 * ex.u
                                    y: Math.max(timeline.topY, timeline.yOf(modelData.start))
                                    height: Math.max(26 * ex.u, timeline.yOf(modelData.end) - y) + (opened ? 70 * ex.u : 0)
                                    Behavior on height { NumberAnimation { duration: Theme.d(Theme.base); easing.type: Easing.OutCubic } }
                                    radius: 8 * ex.u
                                    z: opened ? 5 : 1
                                    color: opened ? "#1E1E1E" : "#151515"
                                    border.color: opened ? Theme.fgTile : "#3A3A38"
                                    clip: true
                                    Column {
                                        x: 8 * ex.u; y: 5 * ex.u; width: parent.width - 16 * ex.u
                                        spacing: 3 * ex.u
                                        Text { width: parent.width; text: Fmt.hhmm(blk.modelData.start) + "  " + blk.modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight
                                               color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 14 * ex.u }
                                        Text { visible: blk.opened; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText
                                               text: blk.modelData.calendar + (blk.modelData.location ? " · " + blk.modelData.location : "") + (blk.modelData.notes ? "\n" + blk.modelData.notes : "")
                                               color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 12 * ex.u }
                                    }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: timeline.openEvent = blk.opened ? "" : blk.modelData.id }
                                }
                            }
                            // the "now" line
                            Rectangle {
                                visible: dcol.today
                                x: 0; width: parent.width; height: 1.5 * ex.u
                                y: timeline.yOf(Core.now)
                                color: Theme.accent
                                Behavior on y { NumberAnimation { duration: 900; easing.type: Easing.InOutCubic } }
                                Rectangle { x: -4 * ex.u; y: -3.5 * ex.u; width: 8 * ex.u; height: width; radius: width / 2; color: Theme.accent }
                            }
                        }
                    }
                }

                // agenda for the selected day
                Item {
                    id: agenda
                    visible: body.agendaW > 0
                    x: body.width - body.agendaW
                    width: body.agendaW; height: body.height
                    Rectangle { x: -14 * ex.u; width: 1; height: parent.height; color: Theme.hairline }
                    Text { id: agHead; text: Fmt.DAYS[new Date(ex.sy, ex.sm, ex.sd).getDay()] + " " + ex.sd + " " + Fmt.MONTHS[ex.sm]
                           color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 24 * ex.u }
                    Text { anchors.top: agHead.bottom; text: ex.selEvents.length + (ex.selEvents.length === 1 ? " event" : " events"); color: Theme.dimOnTile
                           font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                    ListView {
                        id: agList
                        y: 70 * ex.u
                        width: parent.width; height: parent.height - y - addBox.height - 16 * ex.u
                        clip: true
                        model: ex.selEvents
                        spacing: 4 * ex.u
                        delegate: Item {
                            id: ev
                            required property var modelData
                            width: agList.width; height: 70 * ex.u
                            Text { y: 8 * ex.u; text: Fmt.hhmm(ev.modelData.start) + "–" + Fmt.hhmm(ev.modelData.end); color: Theme.dimOnTile; font.family: Theme.mono; font.pixelSize: 13 * ex.u }
                            Text { y: 28 * ex.u; width: parent.width - 40 * ex.u; text: ev.modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight
                                   color: Theme.fgTile; font.family: Theme.display; font.pixelSize: 18 * ex.u }
                            Text { y: 50 * ex.u; width: parent.width - 40 * ex.u; text: ev.modelData.calendar + (ev.modelData.location ? " · " + ev.modelData.location : "")
                                   textFormat: Text.PlainText; elide: Text.ElideRight; color: "#6E6E6B"; font.family: Theme.mono; font.pixelSize: 12 * ex.u }
                            GlyphButton { anchors.right: parent.right; y: 22 * ex.u; glyph: "×"; onClicked: Core.action("calendar.delete", { "id": ev.modelData.id }) }
                            Hairline { anchors.bottom: parent.bottom; width: parent.width }
                        }
                        Text { visible: agList.count === 0; text: "Nothing on this day."; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 13 * ex.u; y: 8 * ex.u }
                    }
                    Column {
                        id: addBox
                        anchors.bottom: parent.bottom
                        width: parent.width
                        spacing: 10 * ex.u
                        property int dur: 60
                        SectionLabel { text: "ADD EVENT ON " + ex.sd + " " + Fmt.MONTHS[ex.sm].toUpperCase() }
                        Field { id: evTitle; width: parent.width; placeholderText: "Title"; monoFont: false; px: 17; onAccepted: addBtn.clicked() }
                        Row {
                            spacing: 8 * ex.u
                            Field { id: evTime; width: 80 * ex.u; text: "16:00"; px: 16; inputMask: "99:99"; anchors.verticalCenter: parent.verticalCenter }
                            Repeater { model: [30, 60, 120]
                                Chip { required property int modelData; text: modelData < 60 ? modelData + "m" : (modelData / 60) + "h"; filled: addBox.dur === modelData
                                       fontPx: 12; implicitHeight: 24 * ex.u; anchors.verticalCenter: parent.verticalCenter
                                       MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: addBox.dur = parent.modelData } } }
                            TextButton {
                                id: addBtn
                                text: "Add"; fontPx: 14; implicitHeight: 28 * ex.u; anchors.verticalCenter: parent.verticalCenter
                                onClicked: {
                                    if (evTitle.text.trim() === "") return
                                    var p = evTime.text.split(":"), hh = parseInt(p[0]) || 0, mm = parseInt(p[1]) || 0
                                    var start = new Date(ex.sy, ex.sm, ex.sd, Math.min(23, hh), Math.min(59, mm)).getTime() / 1000
                                    Core.action("calendar.create", { "title": evTitle.text.trim(), "start": start, "end": start + addBox.dur * 60 })
                                    evTitle.text = ""
                                }
                            }
                        }
                        Text { width: parent.width; wrapMode: Text.Wrap; text: "Deleting an event asks for approval in A (T2)."; color: "#5E5E5B"; font.family: Theme.mono; font.pixelSize: 11 * ex.u }
                    }
                }
            }
        }
    }
}
