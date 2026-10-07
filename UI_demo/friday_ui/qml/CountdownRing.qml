// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Small ring that empties toward the next fire time (brief 5H). kind: timer | event | paused
import QtQuick
import Friday

Canvas {
    id: ring
    property real fraction: 1.0          // remaining share of the period, 1 = just fired
    property string kind: "timer"
    property bool flash: false
    property color fg: Theme.fgTile
    property real u: Theme.u
    implicitWidth: 20 * u
    implicitHeight: 20 * u
    onFractionChanged: requestPaint()
    onKindChanged: requestPaint()
    onFlashChanged: requestPaint()
    onWidthChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var c = width / 2, r = width / 2 - 2 * u, lw = Math.max(1.4, 2 * u)
        ctx.lineCap = "round"
        if (kind === "event") {
            ctx.strokeStyle = fg
            ctx.lineWidth = Math.max(1, 1.2 * u)
            ctx.setLineDash([1.2, 2.6])
            ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke()
            ctx.setLineDash([])
            ctx.fillStyle = fg
            ctx.beginPath(); ctx.arc(c, c, 3 * u, 0, Math.PI * 2); ctx.fill()
            return
        }
        ctx.lineWidth = lw
        ctx.strokeStyle = kind === "paused" ? "#2C2C2B" : "#3A3A38"
        ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke()
        if (kind === "paused") return
        var f = flash ? 1 : Math.max(0, Math.min(1, fraction))
        if (f <= 0.001) return
        ctx.strokeStyle = fg
        ctx.beginPath()
        ctx.arc(c, c, r, -Math.PI / 2 - f * Math.PI * 2, -Math.PI / 2, false)
        ctx.stroke()
    }
}
