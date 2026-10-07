// Copyright 2026 Alpha (code8286)
// SPDX-License-Identifier: Apache-2.0
// Formatting helpers (fixed English names, independent of the OS locale).
.pragma library

var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
var LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

function pad2(n) { n = Math.floor(n); return (n < 10 ? "0" : "") + n; }

function hhmm(ts) { var d = new Date(ts * 1000); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); }
function hm(h, m) { return pad2(h) + ":" + pad2(m); }

function footerDate(ts) {
    var d = new Date(ts * 1000);
    return hhmm(ts) + " · " + DAYS[d.getDay()] + " " + pad2(d.getDate()) + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
}

function dayLabel(ts, now) {
    var d = new Date(ts * 1000), n = new Date(now * 1000);
    var t0 = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    var days = Math.floor((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - t0) / 86400000);
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days === -1) return "yesterday";
    return DAYS[d.getDay()] + " " + pad2(d.getDate()) + " " + MONTHS[d.getMonth()];
}

// "in 18 min", "in 8 h 12 m", "in 3 d"
function relIn(sec) {
    if (sec <= 0) return "now";
    var m = Math.round(sec / 60);
    if (sec < 60) return "in " + Math.ceil(sec) + " s";
    if (m < 60) return "in " + m + " min";
    var h = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60);
    if (h < 48) return "in " + h + " h " + mm + " m";
    return "in " + Math.round(sec / 86400) + " d";
}

function ago(sec) {
    if (sec < 45) return "just now";
    if (sec < 3600) return Math.round(sec / 60) + " min ago";
    if (sec < 86400) return Math.round(sec / 3600) + " h ago";
    return Math.round(sec / 86400) + " d ago";
}

function countdown(sec) {
    sec = Math.max(0, Math.floor(sec));
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return pad2(Math.min(99, h)) + ":" + pad2(m) + ":" + pad2(s);
}

function mmss(sec) { sec = Math.max(0, Math.floor(sec)); return Math.floor(sec / 60) + ":" + pad2(sec % 60); }

// weekday pattern "M T W T F · ·" (0 = Monday)
function pattern(days) {
    var out = [];
    for (var i = 0; i < 7; i++) {
        var on = !days || days.length === 0 || days.indexOf(i) >= 0;
        out.push(on ? LETTERS[i] : "·");
    }
    return out.join(" ");
}

function repeatText(days) {
    if (!days || days.length === 0) return "once";
    if (days.length === 7) return "every day";
    var s = days.slice().sort().join(",");
    if (s === "0,1,2,3,4") return "weekdays";
    if (s === "5,6") return "weekends";
    var names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    return days.map(function (d) { return names[d]; }).join(" ");
}
