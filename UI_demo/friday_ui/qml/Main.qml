// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// F.R.I.D.A.Y. frontpage: frame, HUD panel, tile grid, keyboard, launch sequence, demo controls.
import QtQuick
import QtQuick.Window
import Friday

Window {
    id: win
    // set from Python (app.py)
    property int startWidth: 0
    property int startHeight: 0
    property bool startFullscreen: false
    property string version: "0.4.0"
    property string themeChoice: "system"
    property bool reducedMotionFlag: false
    property bool showHint: true
    property bool showCaption: true
    property int ringRepeats: 4
    property string openAtStart: ""
    property var fontsLoaded: []
    property bool testMode: false

    width: startWidth > 0 ? startWidth : Math.min(1600, Screen.desktopAvailableWidth * 0.92)
    height: startHeight > 0 ? startHeight : Math.min(1131, Screen.desktopAvailableHeight * 0.9)
    minimumWidth: 1280
    minimumHeight: 760
    visible: true
    visibility: startFullscreen ? Window.FullScreen : Window.Windowed
    color: Theme.page
    title: "F.R.I.D.A.Y."

    readonly property real winW: width
    readonly property real winH: height
    readonly property real u: Math.min(winW / 2000, winH / 1414)
    readonly property bool live: win.visibility !== Window.Minimized && win.visibility !== Window.Hidden && win.visible

    Binding { target: Theme; property: "u"; value: win.u }
    Component.onCompleted: {
        Theme.themeOverride = themeChoice === "dark" ? 2 : (themeChoice === "light" ? 1 : 0)
        Theme.reducedMotion = reducedMotionFlag
        if (fontsLoaded.indexOf("Space Grotesk") < 0) Theme.display = fontsLoaded.indexOf("Inter") >= 0 ? "Inter" : "Segoe UI"
        if (fontsLoaded.indexOf("JetBrains Mono") < 0) Theme.mono = Qt.platform.os === "windows" ? "Consolas" : "DejaVu Sans Mono"
        if (testMode || reducedMotionFlag) launchMs = 1250; else launch.start()
        if (openAtStart !== "") grid.open(openAtStart)
        root.forceActiveFocus()
    }
    onLiveChanged: Core.setSpectrumWanted(live)

    // ---------------------------------------------------------------- launch sequence (brief 3.1)
    property real launchMs: 0
    NumberAnimation { id: launch; target: win; property: "launchMs"; from: 0; to: 1250; duration: 1250 }
    function ease(t) { t = Math.max(0, Math.min(1, t)); return 1 - Math.pow(1 - t, 3) }
    readonly property real rulesP: Theme.reducedMotion ? 1 : ease(launchMs / 300)
    readonly property real dividerP: Theme.reducedMotion ? 1 : ease((launchMs - 150) / 300)
    readonly property real ringBoot: Theme.reducedMotion ? 1 : Math.max(0, Math.min(1, (launchMs - 400) / 800))
    function tileEnter(order) { return Theme.reducedMotion ? Math.min(1, launchMs / 120) : ease((launchMs - 300 - order * 60) / Theme.base) }
    function skipLaunch() { if (launch.running) launch.complete() }

    FocusScope {
        id: root
        anchors.fill: parent
        focus: true

        Keys.onPressed: (e) => win.handleKey(e)
        Keys.onReleased: (e) => {
            if (e.key === Qt.Key_Space && !e.isAutoRepeat && win.ptt) { win.ptt = false; Core.action("activation.ptt", { "down": false }); e.accepted = true }
        }

        Frame {
            id: frame
            anchors.fill: parent
            rulesP: win.rulesP
            dividerP: win.dividerP
            version: win.version
        }

        HudPanel {
            id: hud
            x: win.winW * 0.021
            y: win.winH * 0.028
            width: win.winW * 0.3485 - x
            height: win.winH * 0.9406 - y
            boot: win.ringBoot
            live: win.live
            repeats: win.ringRepeats
            showCaption: win.showCaption
            onRingClicked: if (Core.state === "confirm" || Core.stats.confirms > 0) grid.open("A")
        }

        // ------------------------------------------------------------ right section
        Item {
            id: grid
            x: win.winW * 0.369
            y: win.winH * 0.0523
            width: win.winW * 0.978 - x
            height: win.winH * 0.9158 - y
            readonly property real gap: win.winW * 0.0065
            readonly property real cw: (width - 2 * gap) / 3
            readonly property real ch: (height - 2 * gap) / 3
            property string openKey: ""
            property string focusKey: "B"
            property bool kbd: false
            readonly property var slotOrder: ["B", "C", "D", "A", "E", "F", "G", "H"]
            readonly property rect full: Qt.rect(0, 0, width, height)
            function slot(c, r, rs) { return Qt.rect(c * (cw + gap), r * (ch + gap), cw, ch * rs + gap * (rs - 1)) }
            function open(k) { if (["A","B","C","D","E","F","G","H"].indexOf(k) >= 0) { openKey = k; focusKey = k } }
            function close() { openKey = ""; root.forceActiveFocus() }

            CalendarTile {
                letter: "B"; order: 1; slotRect: grid.slot(0, 0, 1); openRect: grid.full
                isOpen: grid.openKey === "B"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "B" && grid.openKey === ""; live: win.live
                onActivated: grid.open("B"); onCloseRequested: grid.close()
            }
            RemindersTile {
                letter: "C"; order: 2; slotRect: grid.slot(1, 0, 1); openRect: grid.full
                isOpen: grid.openKey === "C"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "C" && grid.openKey === ""; live: win.live
                onActivated: grid.open("C"); onCloseRequested: grid.close()
            }
            TodoTile {
                letter: "D"; order: 3; slotRect: grid.slot(0, 1, 1); openRect: grid.full
                isOpen: grid.openKey === "D"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "D" && grid.openKey === ""; live: win.live
                onActivated: grid.open("D"); onCloseRequested: grid.close()
            }
            UpcomingTile {
                letter: "A"; order: 0; slotRect: grid.slot(1, 1, 1); openRect: grid.full
                isOpen: grid.openKey === "A"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "A" && grid.openKey === ""; live: win.live
                onActivated: grid.open("A"); onCloseRequested: grid.close()
            }
            AlarmsTile {
                letter: "E"; order: 4; slotRect: grid.slot(0, 2, 1); openRect: grid.full
                isOpen: grid.openKey === "E"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "E" && grid.openKey === ""; live: win.live
                onActivated: grid.open("E"); onCloseRequested: grid.close()
            }
            MusicTile {
                letter: "F"; order: 5; slotRect: grid.slot(1, 2, 1); openRect: grid.full
                isOpen: grid.openKey === "F"; dimmed: grid.openKey !== "" && !isOpen; enter: win.tileEnter(order)
                focusRing: grid.kbd && grid.focusKey === "F" && grid.openKey === ""; live: win.live
                onActivated: grid.open("F"); onCloseRequested: grid.close()
            }
            QueueColumn {
                slotRect: grid.slot(2, 0, 3); openRect: grid.full
                openPane: grid.openKey === "G" || grid.openKey === "H" ? grid.openKey : ""
                dimmed: grid.openKey !== "" && openPane === ""
                enterG: win.tileEnter(6); enterH: win.tileEnter(7)
                focusPane: grid.kbd && grid.openKey === "" && (grid.focusKey === "G" || grid.focusKey === "H") ? grid.focusKey : ""
                live: win.live
                onActivated: (k) => grid.open(k)
                onCloseRequested: grid.close()
            }
        }

        // launch is skippable by any input
        MouseArea {
            anchors.fill: parent
            z: 1000
            enabled: launch.running
            onPressed: (m) => { win.skipLaunch(); m.accepted = true }
        }

        DevPanel { id: dev; z: 900; anchors.left: parent.left; anchors.bottom: parent.bottom
                   anchors.leftMargin: win.winW * 0.021 + 6 * win.u; anchors.bottomMargin: win.winH * 0.075 }

        Toast { id: toast; z: 950 }

        // one-time hint for the demo controls
        Text {
            id: hint
            visible: win.showHint && opacity > 0.01
            opacity: 0
            z: 800
            x: win.winW * 0.3485 + 18 * win.u
            y: win.winH * 0.9406 + 28 * win.u
            text: "demo · F1 controls · 1–8 open tiles · hold Space to talk · Esc back"
            color: Theme.pageDim
            font.family: Theme.mono
            font.pixelSize: 13 * win.u
            SequentialAnimation on opacity {
                running: win.showHint && !win.testMode
                PauseAnimation { duration: 1600 }
                NumberAnimation { to: 1; duration: 400 }
                PauseAnimation { duration: 7000 }
                NumberAnimation { to: 0; duration: 800 }
            }
        }
    }

    // ---------------------------------------------------------------- keyboard (brief 3.2)
    property bool ptt: false
    readonly property var navGrid: ({
        "B": { "l": "B", "r": "C", "u": "B", "d": "D" },
        "C": { "l": "B", "r": "G", "u": "C", "d": "A" },
        "D": { "l": "D", "r": "A", "u": "B", "d": "E" },
        "A": { "l": "D", "r": "G", "u": "C", "d": "F" },
        "E": { "l": "E", "r": "F", "u": "D", "d": "E" },
        "F": { "l": "E", "r": "H", "u": "A", "d": "F" },
        "G": { "l": "C", "r": "G", "u": "G", "d": "H" },
        "H": { "l": "F", "r": "H", "u": "G", "d": "H" }
    })
    function handleKey(e) {
        if (launch.running) { skipLaunch(); e.accepted = true; return }
        var ctrl = (e.modifiers & Qt.ControlModifier)
        if (ctrl) { if (dev.handle(e.key)) e.accepted = true; return }
        if (e.key === Qt.Key_F1) { dev.shown = !dev.shown; e.accepted = true; return }
        if (e.key === Qt.Key_Escape) {
            if (dev.shown) dev.shown = false
            else if (grid.openKey !== "") grid.close()
            e.accepted = true; return
        }
        if (e.key === Qt.Key_Space) {
            if (!e.isAutoRepeat && !ptt) { ptt = true; Core.action("activation.ptt", { "down": true }) }
            e.accepted = true; return
        }
        if (grid.openKey !== "" ) return
        if (e.key >= Qt.Key_1 && e.key <= Qt.Key_8) { grid.open(grid.slotOrder[e.key - Qt.Key_1]); e.accepted = true; return }
        var dir = { [Qt.Key_Left]: "l", [Qt.Key_Right]: "r", [Qt.Key_Up]: "u", [Qt.Key_Down]: "d" }[e.key]
        if (dir) { grid.kbd = true; grid.focusKey = navGrid[grid.focusKey][dir]; e.accepted = true; return }
        if (e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) {
            grid.kbd = true
            var i = grid.slotOrder.indexOf(grid.focusKey)
            i = (i + (e.key === Qt.Key_Backtab ? 7 : 1)) % 8
            grid.focusKey = grid.slotOrder[i]
            e.accepted = true; return
        }
        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && grid.kbd) { grid.open(grid.focusKey); e.accepted = true }
    }

    // transient core events -> toasts
    Connections {
        target: Core
        function onCoreEvent(name, p) {
            if (name === "action.rejected" && p.error) toast.show(p.error === "core offline" ? "Core offline · action not sent" : p.error, true)
            else if (name === "confirm.pending") toast.show("Needs your approval · see A", false)
            else if (name === "command.fired") toast.show("Standing command fired → G", false)
        }
    }
}
