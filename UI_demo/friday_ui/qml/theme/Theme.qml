// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Design tokens (brief section 2). The only place colours, fonts and motion constants live.
pragma Singleton
import QtQuick

QtObject {
    // 0 = follow the OS, 1 = light, 2 = dark
    property int themeOverride: 0
    property bool reducedMotion: false
    readonly property bool osDark: Qt.styleHints.colorScheme === 2
    readonly property bool dark: themeOverride === 2 || (themeOverride === 0 && osDark)

    // colours
    readonly property color page: dark ? "#0B0B0B" : "#F6F3EE"
    readonly property color ink: dark ? "#EDEAE4" : "#0A0A0A"
    readonly property color tile: dark ? "#161616" : "#000000"
    readonly property color fgTile: "#F5F5F2"
    readonly property color dimOnTile: "#8C8C88"
    readonly property color hairline: "#2A2A2A"
    readonly property color accent: "#F96148"
    readonly property color fgAccent: "#0A0A0A"
    readonly property color danger: accent
    // page-side greys (derived from ink, used for labels and the ring guides)
    readonly property color pageDim: dark ? "#8F8C86" : "#6E6B66"
    readonly property color pageMid: dark ? "#6A6762" : "#76736D"
    readonly property color pageFaint: dark ? "#3A3936" : "#C9C5BE"
    readonly property color flash: "#1E1E1E"

    // type
    property string display: "Space Grotesk"
    property string mono: "JetBrains Mono"

    // motion
    readonly property int fast: 140
    readonly property int base: 240
    readonly property int slow: 420
    function d(ms) { return reducedMotion ? 120 : ms }

    // layout unit: 1.0 at the 2000x1414 reference
    property real u: 1.0
    function s(px) { return px * u }
}
