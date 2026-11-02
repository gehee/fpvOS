/* fpvOS VRX simulator.
   The goggle's own screens (kestrel-gnd: idle, canopy HUD, menu, gallery, stats,
   channel page, bind) redrawn in a canvas from the app's source, over a simulated
   flight whose telemetry matches the picture. Geometry, strings and timings follow
   kestrel-gnd; the radio, the air unit and the recordings are simulated. */
(function () {
  'use strict';
  var root = document.getElementById('sim');
  if (!root) return;
  var cv = root.querySelector('canvas');
  var hintEl = root.querySelector('[data-sim-hint]');
  var W = 1920, H = 1080, FH = 1.32474, FW = FH * W / H, D = 3.2, FU = H / (2 * FH);
  var FONT = '"Chakra Petch", "Rajdhani", system-ui, sans-serif';
  var F = 64; // reference font px for perspective text

  // ---------------------------------------------------------------- themes
  var THEMES = {
    KESTREL: { text: [1, 1, 1], data: [0, 0.9, 1], accent: [0.7, 1, 0], ground: [0.024, 0.125, 0.2], quiet: [0.55, 0.62, 0.7] },
    EMBER: { text: [1, 0.96, 0.9], data: [1, 0.69, 0.13], accent: [1, 0.42, 0.1], ground: [0.102, 0.055, 0.024], quiet: [0.7, 0.63, 0.56] },
    ICE: { text: [1, 1, 1], data: [0.56, 0.83, 1], accent: [0, 0.9, 1], ground: [0.024, 0.094, 0.169], quiet: [0.58, 0.66, 0.74] },
    MONO: { text: [1, 1, 1], data: [0.81, 0.85, 0.87], accent: [1, 1, 1], ground: [0.063, 0.075, 0.078], quiet: [0.5, 0.54, 0.56] },
    VIOLET: { text: [1, 1, 1], data: [0.49, 0.77, 1], accent: [0.83, 0.42, 1], ground: [0.09, 0.031, 0.169], quiet: [0.62, 0.58, 0.72] }
  };
  var REST = [0.663, 0.706, 0.741], AMBER = [1, 0.72, 0.15], RED = [1, 0.3, 0.25], MAMBER = [0.95, 0.79, 0.3];
  var DANGER = [0.93, 0.33, 0.28], GREY = [0.45, 0.45, 0.45], WHITE = [1, 1, 1], BLACK = [0, 0, 0];
  var STAGE = { exp: [0.6, 0.68, 0.82], enc: [1, 0.42, 0.42], rf: [0.1, 0.83, 0.64], dec: [0.95, 0.79, 0.3], disp: [1, 0.54, 0.3] };
  var T = THEMES.KESTREL;
  function rgb(c, m) { m = m == null ? 1 : m; return 'rgb(' + Math.round(Math.min(1, c[0] * m) * 255) + ',' + Math.round(Math.min(1, c[1] * m) * 255) + ',' + Math.round(Math.min(1, c[2] * m) * 255) + ')'; }
  function pale(c) { return [0.5 + 0.5 * c[0], 0.5 + 0.5 * c[1], 0.5 + 0.5 * c[2]]; }
  function mul(c, m) { return [Math.min(1, c[0] * m), Math.min(1, c[1] * m), Math.min(1, c[2] * m)]; }

  // ---------------------------------------------------------------- helpers
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function ease(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function easeOut(t) { t = clamp(t, 0, 1); return 1 - Math.pow(1 - t, 3); }
  function follow(v, target, tau, dt) { var n = v + (target - v) * (1 - Math.exp(-dt / tau)); return Math.abs(target - n) < 0.002 ? target : n; }
  function noise(n) { var x = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function mss(s) { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + pad2(s % 60); }

  // ---------------------------------------------------------------- media
  function mkVideo(src, loop) {
    var v = document.createElement('video');
    v.muted = true; v.playsInline = true; v.loop = !!loop; v.preload = 'auto';
    v.setAttribute('muted', ''); v.setAttribute('playsinline', '');
    v.src = src; return v;
  }
  var vFlight = mkVideo('media/flight.mp4', true);
  var vIdle = mkVideo('media/idle.mp4', true);
  var vPlay = mkVideo('media/flight.mp4', false);
  var imgIdle = new Image(); imgIdle.src = 'media/idle.jpg';
  var TEL = null;
  function telXhr() { try { var x = new XMLHttpRequest(); x.open('GET', 'media/flight.json'); x.onload = function () { try { TEL = JSON.parse(x.responseText); } catch (e) {} }; x.send(); } catch (e) {} }
  if (window.fetch) fetch('media/flight.json').then(function (r) { return r.json(); }).then(function (j) { TEL = j; }).catch(telXhr); else telXhr();
  function ready(v) { return v.readyState >= 2 && v.videoWidth > 0; }
  function tel(t) {
    if (!TEL) return null;
    var rows = TEL.rows, i = clamp(Math.floor(t * TEL.rate), 0, rows.length - 1), r = rows[i];
    return { armed: !!r[1], v: r[2], a: r[3], speed: r[4], dist: r[5], gr: r[6], gp: r[7], gy: r[8], lq: r[9], mcs: r[10], snr: r[11], flight: r[12], mah: r[13], cells: TEL.cells };
  }

  // ---------------------------------------------------------------- canvas
  var ctx = cv.getContext('2d');
  var osd = document.createElement('canvas'), oc = osd.getContext('2d');
  var snap = document.createElement('canvas'), sc = snap.getContext('2d');
  var K = 1;
  function resize() {
    var r = cv.getBoundingClientRect();
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = Math.max(320, Math.min(1920, Math.round(r.width * dpr)));
    var h = Math.round(w * 9 / 16);
    if (cv.width !== w) { cv.width = w; cv.height = h; osd.width = w; osd.height = h; snap.width = w; snap.height = h; }
    K = w / W;
  }
  var widthCache = {};
  function tw(s) {
    var k = s; var v = widthCache[k];
    if (v == null) { oc.save(); oc.setTransform(1, 0, 0, 1, 0, 0); oc.font = '600 ' + F + 'px ' + FONT; v = oc.measureText(s).width; oc.restore(); widthCache[k] = v; }
    return v;
  }
  function numAdv(s) { return tw(String(s).replace(/[0-9]/g, '0')); }
  // flat screen-pixel text: em in 1080p px
  function stext(c, s, x, base, em, align, col, a) {
    if (a <= 0.003 || !s) return 0;
    var w = tw(s) * em / F;
    var x0 = align === 1 ? x - w / 2 : align === 2 ? x - w : x;
    c.setTransform(K * em / F, 0, 0, K * em / F, K * x0, K * base);
    c.globalAlpha = a; c.fillStyle = rgb(col); c.font = '600 ' + F + 'px ' + FONT; c.fillText(s, 0, 0);
    c.setTransform(K, 0, 0, K, 0, 0); c.globalAlpha = 1;
    return w;
  }
  function stw(s, em) { return tw(s) * em / F; }
  function fill(c, x, y, w, h, col, a) { if (a <= 0.003) return; c.globalAlpha = a; c.fillStyle = rgb(col); c.fillRect(x, y, w, h); c.globalAlpha = 1; }
  function ring(c, x, y, w, h, t, col, a) { fill(c, x - t, y - t, w + 2 * t, t, col, a); fill(c, x - t, y + h, w + 2 * t, t, col, a); fill(c, x - t, y, t, h, col, a); fill(c, x + w, y, t, h, col, a); }

  // ---------------------------------------------------------------- settings
  var S = {
    hudStyle: 'CANOPY', bfOsd: 'ON', canopyVolt: 'PER CELL', clock: 'IDLE ONLY 24H', dyn: 'MEDIUM', debug: 'OFF',
    theme: 'KESTREL', bgVideo: 'ON', picSize: 'FULL', uiScale: '1.0x', bright: '50', frameMode: 'FULL FRAME', refreshSync: 'OFF', syncMargin: '0 MS',
    dvrSource: 'SCREEN', screenMode: 'Auto', wifi: 'OFF', licence: 'NO', area: 'NOT SET', country: '--', tz: '--',
    videoMode: '1080p100', maxBitrate: 'AUTO', rotate: '0', scene: 'Race', ev: '0 EV', wb: 'Auto', sat: 'Auto', con: 'Auto', sharp: 'Auto', dnr: 'Off', focus: 'Off',
    txPower: '25mW', maxMcs: 'AUTO', maxBw: '40 MHz', vrxFw: 'OPEN8030', autoStandby: 'ON'
  };
  var AREAS = {
    Europe: { France: ['Paris'], Germany: ['Berlin'], 'United Kingdom': ['London'], Spain: ['Madrid', 'Canary'], Italy: ['Rome'] },
    America: { 'United States': ['New York', 'Chicago', 'Denver', 'Los Angeles'], Canada: ['Toronto', 'Vancouver'] },
    Australia: { Australia: ['Sydney', 'Perth'] }
  };
  var ISO = { France: 'FR', Germany: 'DE', 'United Kingdom': 'GB', Spain: 'ES', Italy: 'IT', 'United States': 'US', Canada: 'CA', Australia: 'AU' };
  function range(a, b, step, fmt) { var o = []; for (var v = a; v <= b + 1e-9; v += step) o.push(fmt(v)); return o; }

  // ---------------------------------------------------------------- simulated link
  var now = 0;
  var L = {
    power: false, autoOnAt: 2.5, radioOkAt: Infinity, bound: true, fpvAir: true, pairing: false,
    radio: false, linkAt: 0, frames: false, firstFrameAt: -1, lastFrameAt: -1,
    conn: false, connAt: -1, dropStart: -1, lostAt: -1, everConn: false, reconnect: false,
    vs: 'BACKGROUND', warpAt: -1, frozenT: 0, fwRestartUntil: -1, intervals: []
  };
  function setPower(on) {
    L.power = on;
    if (on) { L.radioOkAt = now + 1.0; }
    syncControls();
  }
  var arm = { state: -1, wipeAt: -100, from: REST, to: REST, armedAt: -100 };

  // ---------------------------------------------------------------- dynamic HUD spring
  var dyn = { x: 0, y: 0, b: 0, vx: 0, vy: 0, vb: 0 };
  function dynStep(dt, t) {
    var k = { OFF: 0, SMALL: 0.5, MEDIUM: 1, EXTREME: 3 }[S.dyn];
    var tx = 0, ty = 0, tb = 0;
    if (t && L.conn && L.frames && k > 0) {
      var mo = 0.12 * k, mb = 3.5 * Math.PI / 180 * k;
      var sl = function (r, m) { return Math.abs(r) < 3 ? 0 : clamp(-r / 360 * m, -m, m); };
      ty = sl(t.gp, mo); tx = sl(t.gy, mo); tb = sl(t.gr, mb);
    }
    var n = Math.max(1, Math.ceil(dt / 0.01)), h = dt / n;
    for (var i = 0; i < n; i++) {
      dyn.vx += (220 * (tx - dyn.x) - 16 * dyn.vx) * h; dyn.x += dyn.vx * h;
      dyn.vy += (220 * (ty - dyn.y) - 16 * dyn.vy) * h; dyn.y += dyn.vy * h;
      dyn.vb += (220 * (tb - dyn.b) - 16 * dyn.vb) * h; dyn.b += dyn.vb * h;
    }
  }

  // ---------------------------------------------------------------- projection
  var P = { scale: 1, ui: 1 };
  function proj(x, y, z) {
    var s = D / (D - z);
    var sx = W / 2 + (x * s) / FW * W / 2, sy = H / 2 - (y * s) / FH * H / 2;
    return [W / 2 + (sx - W / 2) * P.scale, H / 2 + (sy - H / 2) * P.scale];
  }
  var cos26 = Math.cos(0.26), sin26 = Math.sin(0.26);
  var EX = (FW - 0.02) * D / (cos26 * D + (FW - 0.02) * sin26), MAG = D / (D - sin26 * EX);
  function UX() { return (2 * FW / 1200) * P.ui / MAG; }
  function UY() { return (2 * FH / 620) * P.ui / MAG; }
  function MY(y) { return (-FH + 0.02) / MAG + (608 - y) * UY(); }
  function XO(side, x) { return side ? EX - x * UX() : -EX + x * UX(); }
  var lift = [0, 0];
  function panelM(side) {
    var sl = side ? -0.05934 : 0.05934, cs = Math.cos(sl), sn = Math.sin(sl);
    var px = XO(side, 56), py = MY(502), b = dyn.b, cb = Math.cos(b), sb = Math.sin(b);
    var dx = dyn.x, dy = dyn.y + lift[side];
    return function (x, y) {
      var ax = x - px, ay = y - py;
      var x1 = px + ax * cs - ay * sn, y1 = py + ax * sn + ay * cs;
      var x2 = x1 * cos26, z2 = side ? x1 * sin26 : -x1 * sin26;
      var x3 = x2 * cb - y1 * sb, y3 = x2 * sb + y1 * cb;
      return proj(x3 + dx, y3 + dy, z2);
    };
  }
  // text in a perspective space: x, base in model units, em in model units
  function ptext(c, M, s, x, base, em, align, col, a) {
    if (!s) return 0;
    var w = tw(s) * em / F;
    if (a <= 0.003) return w;
    var x0 = align === 1 ? x - w / 2 : align === 2 ? x - w : x;
    var p0 = M(x0, base), p1 = M(x0 + em, base), p2 = M(x0, base + em);
    c.setTransform(K * (p1[0] - p0[0]) / F, K * (p1[1] - p0[1]) / F, -K * (p2[0] - p0[0]) / F, -K * (p2[1] - p0[1]) / F, K * p0[0], K * p0[1]);
    c.globalAlpha = a; c.fillStyle = rgb(col); c.font = '600 ' + F + 'px ' + FONT; c.fillText(s, 0, 0);
    c.setTransform(K, 0, 0, K, 0, 0); c.globalAlpha = 1;
    return w;
  }
  function pquad(c, M, pts, col, a) {
    if (a <= 0.003) return;
    c.beginPath();
    for (var i = 0; i < pts.length; i++) { var p = M(pts[i][0], pts[i][1]); if (i) c.lineTo(p[0], p[1]); else c.moveTo(p[0], p[1]); }
    c.closePath(); c.globalAlpha = a; c.fillStyle = rgb(col); c.fill(); c.globalAlpha = 1;
  }
  // vector icons, 32-unit space (vec_icons.cpp)
  var ICONS = {
    drone: { w: 27.8, h: 27.8, draw: function (c) {
      c.lineWidth = 2.6; c.beginPath(); c.moveTo(10.5, 10.5); c.lineTo(21.5, 21.5); c.moveTo(21.5, 10.5); c.lineTo(10.5, 21.5); c.stroke();
      c.lineWidth = 2.4; [[7.5, 7.5], [24.5, 7.5], [7.5, 24.5], [24.5, 24.5]].forEach(function (p) { c.beginPath(); c.arc(p[0], p[1], 4.2, 0, 7); c.stroke(); });
    } },
    goggles: { w: 29.6, h: 13.6, draw: function (c) {
      c.lineWidth = 2.4; rr(c, 2.4, 10.4, 12.2, 11.2, 4); c.stroke(); rr(c, 17.4, 10.4, 12.2, 11.2, 4); c.stroke();
      c.beginPath(); c.moveTo(14.6, 16); c.lineTo(17.4, 16); c.stroke();
    } },
    dist: { w: 27.2, h: 14.4, draw: function (c) {
      c.lineWidth = 2.4; c.beginPath(); c.moveTo(3.6, 10); c.lineTo(3.6, 22); c.moveTo(28.4, 10); c.lineTo(28.4, 22); c.stroke();
      c.lineWidth = 2.2; c.beginPath(); c.moveTo(3.6, 16); c.lineTo(28.4, 16); c.stroke();
      c.beginPath(); c.moveTo(10.6, 11.6); c.lineTo(6.4, 16); c.lineTo(10.6, 20.4); c.moveTo(21.4, 11.6); c.lineTo(25.6, 16); c.lineTo(21.4, 20.4); c.stroke();
    } }
  };
  function rr(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }
  // icon centred at model (cx, cy), fitted in (sw x sh) model units
  function picon(c, M, name, cx, cy, sw, sh, col, a) {
    if (a <= 0.003) return;
    var ic = ICONS[name], s = Math.min(sh / ic.h, sw / ic.w);
    var p0 = M(cx, cy), p1 = M(cx + s, cy), p2 = M(cx, cy + s);
    var a1 = p1[0] - p0[0], b1 = p1[1] - p0[1], c1 = -(p2[0] - p0[0]), d1 = -(p2[1] - p0[1]);
    c.save();
    c.setTransform(K * a1, K * b1, K * c1, K * d1, K * (p0[0] - 16 * a1 - 16 * c1), K * (p0[1] - 16 * b1 - 16 * d1));
    c.globalAlpha = a; c.strokeStyle = rgb(col); c.lineCap = 'round'; c.lineJoin = 'round';
    ic.draw(c);
    c.restore();
  }
  function sicon(c, name, cx, cy, h, col, a) {
    var ic = ICONS[name], s = h / ic.h;
    c.save(); c.setTransform(K * s, 0, 0, K * s, K * (cx - 16 * s), K * (cy - 16 * s));
    c.globalAlpha = a; c.strokeStyle = rgb(col); c.lineCap = 'round'; c.lineJoin = 'round'; ic.draw(c); c.restore();
  }

  // ---------------------------------------------------------------- picture rect
  function picRect() {
    var p = S.picSize === 'FULL' ? 1 : parseInt(S.picSize, 10) / 100;
    var w = W * p, h = H * p;
    return { x: (W - w) / 2, y: (H - h) / 2, w: w, h: h, p: p };
  }

  // ---------------------------------------------------------------- live values
  function cellOf(t) { return t ? t.v / t.cells : 0; }
  var peakCell = 0;
  var MCS_CAP = [3.3, 6.6, 9.9, 13.2, 19.8, 26.4, 29.7, 33, 39.6, 44, 52.8, 58.6, 66, 70];
  // link width: 40 MHz is the default ceiling; the link widens on a strong signal (Max Bandwidth caps it)
  var LINK = { bw: 20, hist: [[0, 20]] };
  function maxBwMhz() { return S.maxBw === 'AUTO' ? 40 : parseInt(S.maxBw, 10); }
  function linkStep(t) {
    var cap = maxBwMhz(), bw = LINK.bw;
    if (!t || !L.frames) bw = Math.min(20, cap);
    else if (t.snr >= 21 && cap >= 40) bw = 40;
    else if (t.snr < 17 || cap < 40) bw = Math.min(20, cap);
    if (bw !== LINK.bw) { LINK.bw = bw; LINK.hist.push([now, bw]); if (LINK.hist.length > 400) LINK.hist.shift(); }
  }
  function bwAt(tc) { var b = LINK.hist[0][1]; for (var i = 0; i < LINK.hist.length && LINK.hist[i][0] <= tc; i++) b = LINK.hist[i][1]; return b; }
  function rfFrameMs(bw) { return bw >= 40 ? 3.25 : 4.65; }
  // air TX power: fixed levels, or AUTO following the signal up to its cap (dBm on the air unit's scale)
  var PWR_DBM = { 25: 13, 100: 19, 200: 22, 500: 26 };
  function airDbm(t) {
    var mw = parseInt(S.txPower, 10);
    if (S.txPower.indexOf('AUTO') < 0) return PWR_DBM[mw] || 13;
    var cap = mw >= 500 ? 26 : 19;
    return clamp(Math.round(13 + (26 - (t ? t.snr : 26)) * 0.7), 13, cap);
  }
  function mwFromDbm(d) { var tb = { 13: 25, 19: 100, 21: 150, 22: 200, 26: 500 }; return tb[d] || Math.round(Math.pow(10, (d + 1) / 10)); }
  function mwText(mw) { return mw >= 1000 ? (mw / 1000).toFixed(1) + 'W' : mw + 'mW'; }
  function linkCap(t, bw) { var m = t ? t.mcs : 8; return MCS_CAP[clamp(m, 0, 13)] * 0.68 * ((bw || LINK.bw) / 20); }
  function videoRate(t) {
    var cap = linkCap(t), auto = Math.min(cap * 0.42, 18);
    var lim = S.maxBitrate === 'AUTO' || !L.fpvAir ? 99 : parseInt(S.maxBitrate, 10);
    return Math.min(auto, lim) * (0.93 + 0.07 * noise(Math.floor(now * 4)));
  }
  // VIDEO track: the range left, in dB over MCS, width and AUTO power headroom (12 blocks)
  var RANGE_ROWS = [[-1, -0.9], [0, 2.6], [3, 5.2], [5, 8.3], [6, 11.2], [8, 14.2], [10, 16.1]];
  function rangeLeft(t) {
    if (!t || !L.conn || !L.frames) return { norm: 0, blocks: -1 };
    var m = t.mcs - 2, mcsDb = -1;
    RANGE_ROWS.forEach(function (r) { if (m >= r[0]) mcsDb = r[1] - RANGE_ROWS[0][1]; });
    if (mcsDb < 0) return { norm: 0, blocks: -1 };
    var step = { 5: 2, 10: 3, 20: 4, 40: 5 }[LINK.bw] || 4, widthDb = step > 2 && step < 6 ? 3 * (step - 2) : 0;
    var powerDb = 0, fullPow = 0;
    if (S.txPower.indexOf('AUTO') >= 0) { var cap = parseInt(S.txPower, 10) >= 500 ? 26 : 19; powerDb = Math.max(0, cap - airDbm(t)); fullPow = cap > 22 ? cap - 22 : 0; }
    var full = 15.1 + 9 + fullPow, norm = clamp((mcsDb + widthDb + powerDb) / full, 0, 1);
    return { norm: norm, blocks: Math.round(norm * 12) };
  }
  function linkWarn(t) {
    if (L.everConn && L.vs === 'LIVE' && L.lastFrameAt > 0 && now - L.lastFrameAt > 0.4 && L.conn) return 2;
    var r = rangeLeft(t); if (r.blocks < 0) return 0;
    return r.blocks <= 4 ? 2 : r.blocks <= 7 ? 1 : 0;
  }
  var glowA = { 1: 0, 2: 0 };
  function standby(t) { return L.frames && t && !t.armed && S.autoStandby === 'ON'; }
  function txText(t) {
    if (S.txPower.indexOf('AUTO') < 0) return S.txPower;
    return mwText(mwFromDbm(airDbm(t))) + ' (A)';
  }
  var DIST = { zeroed: false };
  function modeStr() { return S.videoMode.replace(/p(\d+)/, 'p$1'); }
  var FREQ = 5840;

  // ---------------------------------------------------------------- canopy HUD
  var T_BIG = 0.185, T_STATE = 0.125, T_UNIT = 0.082, T_ROW = 0.058, T_SMALL = 0.055, T_LABEL = 0.04;
  var arrive = { at: -1 }, idleFx = { at: -1 }, standbyFx = { on: false, at: -100 };
  function railAlpha(x) { return x <= 126 ? 0.8 : 0.8 * (1 - Math.pow((x - 126) / 126, 2)); }
  function drawRail(c, M, side, y, gap, reach, colAt, dimm) {
    var X = function (v) { return XO(side, v); };
    var th = 2.2 / 2, x0 = -60, x1 = Math.min(252, -60 + 312 * reach);
    var cuts = [x0, x1];
    if (gap) { cuts = [x0, Math.min(x1, gap[0])]; if (gap[1] < x1) cuts.push(gap[1], x1); }
    for (var k = 0; k + 1 < cuts.length; k += 2) {
      var a = cuts[k], b = cuts[k + 1];
      var n = Math.max(1, Math.ceil((b - a) / 14));
      for (var i = 0; i < n; i++) {
        var u = a + (b - a) * i / n, v = a + (b - a) * (i + 1) / n + 0.6, m = (u + v) / 2;
        pquad(c, M, [[X(u), MY(y - th)], [X(Math.min(v, b)), MY(y - th)], [X(Math.min(v, b)), MY(y + th)], [X(u), MY(y + th)]], colAt(m), railAlpha(m) * dimm);
      }
    }
  }
  function segTrack(c, M, side, x0, x1, y0, y1, segs, fillv, col, aHi, aLo, reveal, dimm) {
    var X = function (v) { return XO(side, v); };
    var w = x1 - x0, p = w / (segs * 0.84), pos = x0, lit = Math.round(clamp(fillv, 0, 1) * segs), cy = (y0 + y1) / 2;
    var shown = Math.round(reveal * segs);
    for (var i = 0; i < segs; i++) {
      var t = segs > 1 ? i / (segs - 1) : 0, s = 1 - 0.32 * t, bw = p * 10 / 13 * s, gp = p * 3 / 13 * s, h = (y1 - y0) * s;
      if (i < shown) {
        var a = i < lit ? (aHi - (aHi - aLo) * t) * dimm : 0.13;
        pquad(c, M, [[X(pos), MY(cy - h / 2)], [X(pos + bw), MY(cy - h / 2)], [X(pos + bw), MY(cy + h / 2)], [X(pos), MY(cy + h / 2)]], col, a);
      }
      pos += bw + gp;
    }
  }
  function canopy(c, t) {
    var s = P.ui, since = now - arrive.at;
    var fRule = clamp(since / 0.12, 0, 1), fShade = clamp((since - 0.12) / 0.14, 0, 1), fBlock = clamp((since - 0.26) / 0.16, 0, 1);
    var idleDim = 1, railDim = 1, mark = 0;
    if (!L.conn && L.lostAt > 0) {
      var e = now - L.lostAt;
      idleDim = 1 - 0.5 * clamp(e / 0.24, 0, 1);
      railDim = e < 0.24 ? idleDim : e < 0.6 ? 0.5 + 0.5 * Math.sin(Math.PI * (e - 0.24) / 0.36) : 0.5;
      mark = clamp((e - 0.44) / 0.24, 0, 1);
    }
    var fresh = t && L.frames;
    var dim = (fresh ? 1 : 0.75) * fBlock * idleDim, ldim = fBlock * idleDim;
    var armed = t ? t.armed : false;
    // arm wipe
    var wipeT = clamp((now - arm.wipeAt) / 0.9, 0, 1), arming = arm.to !== REST;
    var front = arming ? -60 + 312 * wipeT : 252 - 312 * wipeT;
    var colAt = function (x) { if (wipeT >= 1) return arm.to; return arming ? (x < front ? arm.to : arm.from) : (x > front ? arm.to : arm.from); };
    var ux = UX(), uy = UY();
    var iw = 1.35 * 14, igap = 8;
    for (var side = 0; side < 2; side++) {
      var M = panelM(side), X = (function (sd) { return function (v) { return XO(sd, v); }; })(side);
      // wedge
      var xs = [-60, 156, 252, 300], tp = [462, 462, 462, 526], bt = [590, 590, 590, 526], al = [0.66, 0.34, 0.11, 0];
      for (var i = 0; i < 3; i++) {
        var pa = M(X(xs[i]), MY(526)), pb = M(X(xs[i + 1]), MY(526));
        var g = c.createLinearGradient(pa[0], pa[1], pb[0], pb[1]);
        var gr = T.ground; g.addColorStop(0, 'rgba(' + gr.map(function (v) { return Math.round(v * 255); }).join(',') + ',' + (al[i] * fShade * idleDim) + ')');
        g.addColorStop(1, 'rgba(' + gr.map(function (v) { return Math.round(v * 255); }).join(',') + ',' + (al[i + 1] * fShade * idleDim) + ')');
        c.beginPath();
        [[xs[i], tp[i]], [xs[i + 1], tp[i + 1]], [xs[i + 1], bt[i + 1]], [xs[i], bt[i]]].forEach(function (q, k) { var p = M(X(q[0]), MY(q[1])); if (k) c.lineTo(p[0], p[1]); else c.moveTo(p[0], p[1]); });
        c.closePath(); c.fillStyle = g; c.fill();
      }
      var baseBig = MY(512) + 0.25 * T_BIG * s;
      var em = function (Tq) { return 0.625 * Tq * s; };
      var gapTop = null, stateWord = null;
      if (side === 0) {
        // headline
        var cell = cellOf(t), vtxt, vcol = mul(T.text, dim);
        if (t) vtxt = (S.canopyVolt === 'PACK' ? t.v : cell).toFixed(2); else { vtxt = '--'; vcol = GREY; }
        var x = X(14);
        ptext(c, M, vtxt, x, baseBig, em(T_BIG), 0, vcol, 1); x += numAdv(vtxt) * em(T_BIG) / F;
        x += ptext(c, M, 'V', x, baseBig, em(T_UNIT), 0, mul(T.text, dim * 0.72), 1);
        x += 10 * uy;
        var stateX = X(60);
        if (t) {
          x += ptext(c, M, '•', x, baseBig, em(T_UNIT), 0, mul(WHITE, 0.42 * dim), 1);
          x += 10 * uy; stateX = x;
          var at = t.a.toFixed(1);
          ptext(c, M, at, x, baseBig, em(T_UNIT), 0, mul(WHITE, 0.82 * dim), 1); x += numAdv(at) * em(T_UNIT) / F;
          ptext(c, M, 'A', x, baseBig, em(T_SMALL), 0, mul(T.text, dim * 0.72), 1);
        }
        // state word in the top rail
        if (t) {
          var word, wcol;
          if (!armed) { word = 'DISARMED'; wcol = REST; }
          else if (now - arm.armedAt < 1.8) { word = 'ARMED'; wcol = T.accent; }
          else { var fs = Math.floor(t.flight); word = Math.floor(fs / 60) + "'" + pad2(fs % 60) + '"'; wcol = T.accent; }
          var ww = tw(word) * em(T_STATE) / F, lxd = (stateX - X(0)) / ux;
          gapTop = [lxd - 8, lxd + ww / ux + 10];
          var past = wipeT >= 1 || (arming ? front > gapTop[1] : front < gapTop[0]);
          if (!past) wcol = arm.from === REST ? REST : T.accent;
          stateWord = [word, stateX, wcol];
        }
        drawRail(c, M, 0, 456, gapTop, fRule, colAt, railDim * idleDim);
        drawRail(c, M, 0, 596, null, fRule, colAt, railDim * idleDim);
        if (stateWord) ptext(c, M, stateWord[0], stateWord[1], MY(456) - 0.25 * T_STATE * s, em(T_STATE), 0, mul(stateWord[2], idleDim * fBlock), 1);
        // REC marker
        if (REC.on) {
          pquad(c, M, [[X(14), MY(431)], [X(14 + 9 * uy / ux), MY(431)], [X(14 + 9 * uy / ux), MY(440)], [X(14), MY(440)]], [0.95, 0.15, 0.15], fBlock);
          ptext(c, M, 'REC ' + mss(now - REC.at), X(14) + 17 * uy, MY(442) + 0.25 * T_ROW * s, em(T_ROW), 0, [1, 0.35, 0.35], fBlock);
        }
        // tracks
        var lw = Math.max(tw('CELL'), tw('SAG')) * em(T_LABEL) / F / ux, tx0 = 14 + lw + 12;
        ptext(c, M, 'CELL', X(14), MY(527) + 0.25 * T_LABEL * s, em(T_LABEL), 0, mul(T.text, dim), 1);
        ptext(c, M, 'SAG', X(14), MY(537) + 0.25 * T_LABEL * s, em(T_LABEL), 0, mul(T.accent, dim), 1);
        segTrack(c, M, 0, tx0, 271, 516, 525, 20, t ? (cell - 3.3) / 0.9 : 0, T.data, 1, 0.7, fBlock, dim);
        segTrack(c, M, 0, tx0, 271, 530, 534, 20, t ? (peakCell - cell) / 0.5 : 0, T.accent, 1, 0.6, fBlock, dim);
        // drone row
        var rb = MY(560) + 0.25 * T_ROW * s, icy = rb + 0.25 * T_ROW * s, ih = 14 * uy, x2 = X(14);
        picon(c, M, 'drone', x2 + iw * ux / 2, icy, iw * ux, ih, mul(T.text, dim), 1); x2 += iw * ux + igap * ux;
        x2 += ptext(c, M, 'ACRO', x2, rb, em(T_ROW), 0, mul(T.text, dim), 1) + igap * ux;
        if (t) {
          x2 += ptext(c, M, '•', x2, rb, em(T_ROW), 0, mul(T.text, dim * 0.68), 1) + igap * ux;
          picon(c, M, 'dist', x2 + iw * ux / 2, icy, iw * ux, ih, mul(T.text, dim), 1); x2 += iw * ux + igap * ux;
          var dist = Math.max(0, Math.round(t.dist));
          ptext(c, M, !DIST.zeroed ? '--' : dist >= 1000 ? (dist / 1000).toFixed(2) + 'km' : dist + 'm', x2, rb, em(T_ROW), 0, mul(T.text, dim), 1);
        }
        // goggle row
        var gb = MY(584) + 0.25 * T_ROW * s, gcy = gb + 0.25 * T_ROW * s, x3 = X(14);
        picon(c, M, 'goggles', x3 + iw * ux / 2, gcy, iw * ux, ih, mul(T.text, dim), 1); x3 += iw * ux + igap * ux;
        x3 += ptext(c, M, 'VRX ' + Math.round(VRX_TEMP()) + 'C', x3, gb, em(T_ROW), 0, mul(T.text, dim), 1);
        if (L.radio && S.vrxFw === 'OPEN8030') x3 += ptext(c, M, ' • ' + mwText(mwFromDbm(airDbm(t))), x3, gb, em(T_ROW), 0, mul(T.text, dim), 1);
        x3 += 1.6 * igap * ux;
        x3 += ptext(c, M, '12.0V', x3, gb, em(T_ROW), 0, mul(T.text, dim), 1);
        if (S.wifi === 'ON') ptext(c, M, 'WIFI', x3 + 1.6 * igap * ux, gb, em(T_ROW), 0, mul(T.accent, dim), 1);
      } else {
        // right headline: from the edge inward
        var xr = X(14), spd = t && L.frames ? Math.round(t.speed * 3.6) + '' : null;
        xr -= ptext(c, M, 'km/h', xr, baseBig, em(T_SMALL), 2, mul(T.text, ldim * 0.72), 1);
        if (spd) { ptext(c, M, spd, xr, baseBig, em(T_BIG), 2, mul(T.text, ldim), 1); xr -= numAdv(spd) * em(T_BIG) / F; }
        else xr -= ptext(c, M, '--', xr, baseBig, em(T_BIG), 2, GREY, 1);
        xr -= 10 * uy;
        if (t) {
          xr -= ptext(c, M, '•', xr, baseBig, em(T_UNIT), 2, mul(WHITE, 0.42 * ldim), 1); xr -= 10 * uy;
          xr -= ptext(c, M, 'm', xr, baseBig, em(T_SMALL), 2, mul(T.text, ldim * 0.72), 1);
          var ds = DIST.zeroed ? Math.round(t.dist) + '' : '--';
          xr -= ptext(c, M, ds, xr, baseBig, em(T_UNIT), 2, mul(WHITE, 0.82 * ldim), 1);
          if (L.radio) {
            xr -= 10 * uy;
            xr -= ptext(c, M, '•', xr, baseBig, em(T_UNIT), 2, mul(WHITE, 0.42 * ldim), 1); xr -= 10 * uy;
            xr -= ptext(c, M, 'dB', xr, baseBig, em(T_SMALL), 2, mul(T.text, ldim * 0.72), 1);
            ptext(c, M, Math.max(0, Math.round(t.snr)) + '', xr, baseBig, em(T_UNIT), 2, mul(WHITE, 0.82 * ldim), 1);
          }
        }
        // IDLE / STANDBY
        var rgap = null, rword = null;
        if (mark > 0) {
          var iwd = tw('IDLE') * em(T_STATE) / F / ux, mid = 150 + iwd / 2, half = (iwd / 2 + 9) * mark;
          rgap = [mid - half, mid + half]; rword = ['IDLE', X(150), mul(T.quiet, mark), 1];
        } else {
          var sb = standby(t);
          if (sb !== standbyFx.on) { standbyFx.on = sb; standbyFx.at = now; }
          var sw = clamp((now - standbyFx.at) / 0.9, 0, 1), vis = standbyFx.on ? sw : 1 - sw;
          if (vis > 0.01 && arrive.at > 0) {
            var dw = tw('DISARMED') * em(T_STATE) / F / ux, swd = tw('STANDBY') * em(T_STATE) / F / ux, lx = 60 + dw - swd;
            rgap = [lx - 8, lx - 8 + (swd + 18) * vis]; rword = ['STANDBY', X(lx), mul(REST, idleDim * fBlock), vis];
          }
        }
        drawRail(c, M, 1, 456, rgap, fRule, colAt, railDim * idleDim);
        drawRail(c, M, 1, 596, null, fRule, colAt, railDim * idleDim);
        if (rword) {
          if (rword[3] < 1) {
            // crop wipe, left to right in reading order
            var pL = M(rword[1], MY(456) + 0.3), pR = M(rword[1] - tw('STANDBY') * em(T_STATE) / F * rword[3], MY(456));
            c.save(); c.beginPath(); c.rect(Math.min(pL[0], pR[0]) * K, 0, Math.abs(pR[0] - pL[0]) * K, H * K); c.clip();
            ptext(c, M, rword[0], rword[1], MY(456) - 0.25 * T_STATE * s, em(T_STATE), 2, rword[2], 1); c.restore();
          } else ptext(c, M, rword[0], rword[1], MY(456) - 0.25 * T_STATE * s, em(T_STATE), 2, rword[2], 1);
        }
        // tracks
        var rlw = Math.max(tw('RC'), tw('VIDEO')) * em(T_LABEL) / F / ux, rx0 = 14 + rlw + 12;
        var warn = linkWarn(t), vcolr = warn === 2 ? RED : warn === 1 ? AMBER : T.accent;
        ptext(c, M, 'RC', X(14), MY(527) + 0.25 * T_LABEL * s, em(T_LABEL), 2, mul(T.text, ldim), 1);
        ptext(c, M, 'VIDEO', X(14), MY(537) + 0.25 * T_LABEL * s, em(T_LABEL), 2, mul(vcolr, ldim), 1);
        segTrack(c, M, 1, rx0, 271, 516, 525, 20, t && L.frames ? t.lq / 100 : 0, T.data, 1, 0.7, fBlock, ldim);
        segTrack(c, M, 1, rx0, 271, 530, 534, 12, rangeLeft(t).norm, vcolr, 0.85, 0.55, fBlock, ldim);
        // drone row
        var rb2 = MY(560) + 0.25 * T_ROW * s, icy2 = rb2 + 0.25 * T_ROW * s, ih2 = 14 * uy, xq = X(14);
        picon(c, M, 'drone', xq - iw * ux / 2, icy2, iw * ux, ih2, mul(T.text, ldim), 1); xq -= iw * ux + igap * ux;
        var vtx = 'VTX ' + FREQ + '@' + LINK.bw + 'MHz • ' + txText(t) + ' • ' + Math.round(VTX_TEMP()) + 'C';
        ptext(c, M, vtx, xq, rb2, em(T_ROW), 2, mul(T.text, ldim), 1);
        // goggle row
        var gb2 = MY(584) + 0.25 * T_ROW * s, gcy2 = gb2 + 0.25 * T_ROW * s, xg = X(14);
        picon(c, M, 'goggles', xg - iw * ux / 2, gcy2, iw * ux, ih2, mul(T.text, ldim), 1); xg -= iw * ux + igap * ux;
        var rate = L.frames ? videoRate(t).toFixed(1) + '/' + linkCap(t).toFixed(1) + 'Mbps' : '--';
        var lat = L.frames ? Math.round(LAT.p50 - 0.6) + '|' + Math.round(LAT.p50 + 3.4) + 'ms' : '--';
        var md = L.frames ? modeStr() : '--';
        ptext(c, M, rate + ' • ' + lat + ' • ' + md, xg, gb2, em(T_ROW), 2, mul(T.text, ldim), 1);
        if (S.debug === 'ON') ptext(c, M, L.frames ? 'FRAME ' + rfFrameMs(LINK.bw).toFixed(2) + 'ms SHORT' : 'FRAME --', X(14 + iw + igap), MY(612) + 0.25 * T_LABEL * s, em(T_LABEL), 2, mul(T.text, ldim), 1);
      }
    }
  }
  function VRX_TEMP() { return 44 + 3 * Math.sin(now / 40); }
  function VTX_TEMP() { return L.frames ? 41 + 6 * Math.sin(now / 55) : 0; }

  // ---------------------------------------------------------------- edge glow
  var glowCache = {};
  function glowCanvas(col) {
    var k = col.join(',');
    if (glowCache[k]) return glowCache[k];
    var g = document.createElement('canvas'); g.width = 384; g.height = 216; var c = g.getContext('2d');
    var depth = 0.15 * 216;
    [[0, 1], [216, -1]].forEach(function (e) {
      var gr = c.createLinearGradient(0, e[0], 0, e[0] + e[1] * depth);
      [[0, 1], [0.04, 1], [0.12, 0.55], [0.45, 0.18], [1, 0]].forEach(function (st) { gr.addColorStop(st[0], 'rgba(' + col.map(function (v) { return Math.round(v * 255); }).join(',') + ',' + st[1] + ')'); });
      c.fillStyle = gr; c.fillRect(0, e[1] > 0 ? 0 : 216 - depth, 384, depth);
    });
    c.globalCompositeOperation = 'destination-in';
    var hz = c.createLinearGradient(0, 0, 384, 0);
    var a = (1 - 0.88) / 2, b = (1 - 0.6336) / 2;
    hz.addColorStop(0, 'rgba(0,0,0,0)'); hz.addColorStop(a, 'rgba(0,0,0,0)'); hz.addColorStop(b, 'rgba(0,0,0,1)'); hz.addColorStop(1 - b, 'rgba(0,0,0,1)'); hz.addColorStop(1 - a, 'rgba(0,0,0,0)'); hz.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = hz; c.fillRect(0, 0, 384, 216);
    glowCache[k] = g; return g;
  }
  function edgeGlow(c, t, dt, pr) {
    var w = linkWarn(t);
    [1, 2].forEach(function (l) {
      var on = w === l;
      glowA[l] = on ? Math.min(1, glowA[l] + dt / 0.15) : Math.max(0, glowA[l] - dt / 0.6);
      if (glowA[l] > 0.003) {
        var a = 0.75 * glowA[l];
        if (l === 2) a *= 0.65 + 0.35 * (0.5 + 0.5 * Math.sin(7.54 * now));
        c.globalAlpha = a; c.drawImage(glowCanvas(l === 2 ? RED : AMBER), pr.x, pr.y, pr.w, pr.h); c.globalAlpha = 1;
      }
    });
  }

  // ---------------------------------------------------------------- idle screen
  var wordFit = null;
  function wordmark(c, cx, cyFromTop, inkH, alpha, stretch) {
    if (!wordFit) {
      oc.save(); oc.setTransform(1, 0, 0, 1, 0, 0); oc.font = '700 100px ' + FONT;
      var m = oc.measureText('fpvOS'); wordFit = { asc: m.actualBoundingBoxAscent || 75, desc: m.actualBoundingBoxDescent || 22 }; oc.restore();
    }
    var size = 100 * inkH / (wordFit.asc + wordFit.desc);
    var base = cyFromTop + (wordFit.asc - wordFit.desc) / 2 * size / 100;
    c.save(); c.font = '700 ' + size + 'px ' + FONT; c.textBaseline = 'alphabetic';
    var w1 = c.measureText('fpv').width, w2 = c.measureText('OS').width, x0 = cx - (w1 + w2) / 2;
    c.translate(cx, 0); c.scale(stretch || 1, 1); c.translate(-cx, 0);
    var sh = 0.018 * 0.3315 * H;
    c.globalAlpha = alpha;
    [[2 * sh, [0, 0, 0.05]], [sh, [0, 0, 0.03]]].forEach(function (p) { c.fillStyle = rgb(p[1]); c.fillText('fpv', x0 + p[0], base + p[0]); c.fillText('OS', x0 + w1 + p[0], base + p[0]); });
    c.fillStyle = rgb(T.text); c.fillText('fpv', x0, base); c.fillStyle = rgb(T.accent); c.fillText('OS', x0 + w1, base);
    c.restore(); c.globalAlpha = 1;
  }
  function idleScreen(c, pr) {
    var openMax = Math.max(MENU.openF[0], MENU.openF[1]);
    var dx = (ease(MENU.openF[0]) - ease(MENU.openF[1])) * 0.34 * W / 2 * pr.p;
    var shrink = 1 + (0.708 - 1) * openMax;
    var warp = L.vs === 'TRANSITION' ? clamp((now - L.warpAt) / 0.45, 0, 1) : 0, t2 = warp * warp;
    var a = Math.max(0, 1 - 1.35 * t2);
    c.save(); c.setTransform(K, 0, 0, K, 0, 0);
    var cx = W / 2 + dx;
    var inkH = 0.172 * H * pr.p * shrink * (1 + 2 * t2);
    wordmark(c, cx, H / 2 - 0.04 * H * pr.p, inkH, a, 1 + 6 * t2);
    var bandF = MENU.band;
    var ra = (1 - ease(bandF)) * a;
    if (ra > 0.01 && L.vs === 'BACKGROUND') {
      var em = 45.8 * P.ui * pr.p, by = H / 2 + (0.867 - 0.5) * H * pr.p;
      var rs = 0.035 * 0.18 * FU;
      stext(c, 'Ready', cx + 2 * rs, by + 2 * rs, em, 1, [0, 0, 0.05], 0.35 * ra);
      stext(c, 'Ready', cx + rs, by + rs, em, 1, [0, 0, 0.03], 0.6 * ra);
      stext(c, 'Ready', cx, by, em, 1, T.accent, ra);
    }
    c.restore();
  }
  function clockStrip(c, pr) {
    var show = S.clock.indexOf('ON') === 0 || (S.clock.indexOf('IDLE') === 0 && !L.conn);
    var recOnStrip = REC.on && !(S.hudStyle === 'CANOPY' && arrive.at > 0);
    if (!show && !recOnStrip) return;
    var d = new Date(), h = d.getHours(), m = d.getMinutes(), txt;
    if (S.clock.indexOf('12H') > 0) txt = ((h + 11) % 12 + 1) + ':' + pad2(m) + (h < 12 ? ' AM' : ' PM'); else txt = pad2(h) + ':' + pad2(m);
    var q = 0.075 * P.ui * FU * pr.p, em = 0.625 * q, top = pr.y + 0.02 * FU * pr.p, base = top + 0.75 * q;
    var parts = [];
    if (show) parts.push({ icon: 1, w: q * 0.8 }, { gap: 0.35 * q }, { s: txt, col: WHITE });
    if (recOnStrip) { if (show) parts.push({ gap: 0.55 * q }, { s: '•', col: [0.45, 0.5, 0.55] }, { gap: 0.55 * q }); parts.push({ dot: 1, w: 0.45 * q }, { gap: 0.3 * q }, { s: 'REC ' + mss(now - REC.at), col: [1, 0.35, 0.35] }); }
    var tot = 0; parts.forEach(function (p) { p.ww = p.s ? stw(p.s, em) : p.w || p.gap; tot += p.ww; });
    var x = W / 2 - tot / 2 + dyn.x * FU;
    parts.forEach(function (p) {
      if (p.icon) { c.save(); c.globalAlpha = 0.95; c.strokeStyle = '#fff'; c.lineWidth = q * 0.07; c.beginPath(); c.arc(x + p.w / 2, base - em * 0.36, p.w * 0.42, 0, 7); c.moveTo(x + p.w / 2, base - em * 0.36); c.lineTo(x + p.w / 2, base - em * 0.36 - p.w * 0.26); c.moveTo(x + p.w / 2, base - em * 0.36); c.lineTo(x + p.w / 2 + p.w * 0.2, base - em * 0.36); c.stroke(); c.restore(); }
      else if (p.dot) fill(c, x, base - em * 0.6, p.w, p.w, [1, 0.25, 0.25], 1);
      else if (p.s) stext(c, p.s, x, base, em, 0, p.col, 1);
      x += p.ww;
    });
  }

  // ---------------------------------------------------------------- lock figure (acquiring + bind)
  var lockPh0 = 0, sweepAng = 0;
  function lockFigure(c, o) {
    // o: scale, cyFrac, textScale, ph, lp, fade, title, stage, ground
    var U = FH * o.scale * FU, cx = W / 2 + (o.dyn ? dyn.x * FU : 0), cy = H / 2 - FH * o.cyFrac * FU;
    var lpE = ease(o.lp), locked = o.lp > 0.75, fade = o.fade, rG = 0.085 * U, px = FU;
    c.save(); c.setTransform(K, 0, 0, K, 0, 0); c.lineCap = 'butt';
    if (o.ground) fill(c, 0, 0, W, H, BLACK, 1);
    c.globalCompositeOperation = 'lighter';
    for (var i = 0; i < 4; i++) {
      var p = (o.ph / 2.6 + i / 4) % 1, r = 0.47 * U - easeOut(p) * (0.47 * U - rG);
      c.globalAlpha = Math.min(1, 5 * p) * (1 - p) * 0.65 * fade; c.strokeStyle = rgb(T.data); c.lineWidth = 0.0035 * px;
      c.beginPath(); c.arc(cx, cy, r, 0, 7); c.stroke();
    }
    var sa = 0.9 * (1 - clamp((o.lp - 0.75) / 0.25, 0, 1)) * fade;
    if (sa > 0) { var span = 0.55 + 0.5 * (1 - lpE); c.globalAlpha = sa; c.strokeStyle = rgb(T.accent); c.lineWidth = 0.005 * px; c.beginPath(); c.arc(cx, cy, 0.37 * U, -o.sweep, -o.sweep + span); c.stroke(); }
    c.globalAlpha = 0.28 * fade; c.strokeStyle = rgb(T.quiet); c.lineWidth = 0.004 * px; c.beginPath(); c.arc(cx, cy, 0.163 * U, 0, 7); c.stroke();
    if (o.lp <= 0) { c.globalAlpha = 0.9 * fade; c.strokeStyle = rgb(T.data); c.lineWidth = 0.005 * px; c.beginPath(); c.arc(cx, cy, 0.163 * U, -1.6 * o.ph, -1.6 * o.ph + 1.15); c.stroke(); }
    else { c.globalAlpha = 0.95 * fade; c.strokeStyle = rgb(locked ? T.accent : T.data); c.lineWidth = 0.005 * px; c.beginPath(); c.arc(cx, cy, 0.163 * U, -Math.PI / 2, -Math.PI / 2 - lpE * 2 * Math.PI, true); c.stroke(); }
    var far = 0.33 * U, near = 0.112 * U, mid = (far + near) / 2, amp = (far - near) / 2;
    var d = mid + amp * Math.cos(2 * Math.PI * o.ph / 3.4); d = d + (near - d) * lpE;
    var arm = 0.3 * d, st = Math.max(0.006 * U, 0.003 * px) * P.ui;
    c.globalAlpha = 0.95 * fade; c.fillStyle = rgb(locked ? T.accent : T.text);
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(function (q) {
      var x = cx + q[0] * d, y = cy + q[1] * d;
      c.fillRect(Math.min(x, x - q[0] * arm), y - st / 2, arm, st);
      c.fillRect(x - st / 2, Math.min(y, y - q[1] * arm), st, arm);
    });
    c.globalCompositeOperation = 'source-over';
    sicon(c, 'drone', cx, cy, 2 * rG, mul(WHITE, (0.55 + 0.45 * lpE) * fade), 1);
    if (o.lp > 0.75) { var fp = (o.lp - 0.75) / 0.25; c.globalAlpha = (1 - fp) * 0.8; c.strokeStyle = '#fff'; c.lineWidth = 0.008 * px; c.beginPath(); c.arc(cx, cy, rG + fp * 0.19 * U, 0, 7); c.stroke(); c.globalAlpha = 1; }
    var s = o.scale, ts = o.textScale, ty = cy + Math.max(0.4 * U, 0.34 * s * ts * px);
    var q1 = 0.088 * P.ui * ts * px, q2 = 0.05 * s * ts * px * (o.scale < 1 ? 2.2 : 1);
    stext(c, o.title, cx, ty - 0.25 * q1, 0.625 * q1, 1, mul(T.text, fade), 1);
    stext(c, o.stage, cx, ty + Math.max(0.075 * U, 0.105 * s * ts * px) - 0.25 * q2 + q2 * 0.2, 0.625 * q2, 1, mul(o.subAccent || locked ? T.accent : T.text, fade), 1);
    c.restore();
  }

  // ---------------------------------------------------------------- Betaflight OSD (a few elements of the FC's own canvas)
  function bfOsd(c, t, pr) {
    if (!t || !L.frames) return;
    var cw = pr.w / 53, ch = pr.h / 20, em = 0.6 * ch;
    function at(col, row, s, align) { stext(c, s, pr.x + col * cw + dyn.x * FU, pr.y + row * ch + 0.78 * ch + dyn.y * -FU, em, align || 0, T.text, 0.92); }
    at(2, 0.6, t.mah + 'mAh'); if (S.hudStyle !== 'CANOPY') at(26.5, 0.6, 'LQ ' + t.lq, 1); at(51, 0.6, -40 - Math.round((100 - t.lq) / 2) + 'dBm', 2);
  }

  // ---------------------------------------------------------------- arena (legacy HUD), briefly
  function arena(c, t, full) {
    for (var side = 0; side < 2; side++) {
      var M = panelM(side), X = function (v) { return XO(side, v); };
      pquad(c, M, [[X(-60), MY(470)], [X(330), MY(470)], [X(330), MY(600)], [X(-60), MY(600)]], T.ground, 0.55);
      var lines = side === 0 ? ['LATENCY (gnd): ' + LAT.p50.toFixed(1) + 'ms | MAX: ' + (LAT.p99 + 4).toFixed(1) + 'ms', S.videoMode.indexOf('1080') === 0 ? '1920x1080 | 100 FPS | ' + videoRate(t).toFixed(1) + ' Mbps' : '1280x720 | 100 FPS | ' + videoRate(t).toFixed(1) + ' Mbps']
        : ['LINK ' + (t ? t.lq : 0) + '%  +' + (t ? t.snr : 0).toFixed(1) + ' dB  ' + txText(t), 'RX MCS' + (t ? t.mcs : 0) + '  ' + linkCap(t).toFixed(2) + ' Mbps'];
      if (full) lines.push(side === 0 ? '[air:9.8, dec:1.0, disp:6.7]' : FREQ + ' MHz  BW: 20 MHz');
      lines.forEach(function (l, i) { ptext(c, M, l, side ? X(20) : X(20), MY(500 + i * 26), 0.625 * 0.07, side ? 2 : 0, T.text, 1); });
    }
  }

  // ---------------------------------------------------------------- latency model (simulated)
  var LAT = { p50: 23.4, p99: 26.8 };
  function sample(tc, seed) {
    var tl = tel(tc % 82.9), m = tl ? tl.mcs : 10;
    var n1 = noise(Math.floor(tc * 37) + seed), n2 = noise(Math.floor(tc * 53) + 7 + seed), n3 = noise(Math.floor(tc * 11) + 3);
    var rf = 8.4 + 1.2 * n1 + (m < 7 ? (7 - m) * 1.1 : 0), disp = 5.8 + 1.6 * n2;
    var st = { exp: 0, read: 4.1 + 0.2 * n3, enc: 1.0 + 0.1 * n1, rf: rf, dec: 1.0 + 0.05 * n2, disp: disp };
    var sp = noise(Math.floor(tc * 23) + 911);
    if (sp > 0.965) st.rf += 3 + 9 * noise(Math.floor(tc * 29) + 5);
    st.total = st.read + st.enc + st.rf + st.dec + st.disp;
    return st;
  }

  // ---------------------------------------------------------------- the menu
  var MENU = { open: false, stage: 0, side: 1, tab: [0, 1], sel: 0, edit: false, pend: {}, editFrom: null,
    wake: 0, liftF: [0, 0], openF: [0, 0], band: 0, trial: null, firstOpen: true, status: null };
  var TABS = [['HUD', 'DISPLAY', 'DVR', 'SYSTEM'], ['VIDEO', 'RADIO', 'SERIAL', 'INFO']];
  function opt(id, label, vals, o) { o = o || {}; o.id = id; o.label = label; o.vals = vals; o.type = 'S'; return o; }
  var FRAME_HELP = {
    'SPLIT': 'Lowest latency: the top of the picture goes up before the bottom.\nMay tear in the middle on fast motion. No gain on a screen that buffers frames.',
    'FULL DECODE': 'Highest latency, the most conservative: the decoder only gets\nwhole pictures.',
    'FULL FRAME': 'Low latency, whole pictures: slices are decoded as they land, and\nonly whole pictures go up. No tearing. The default.'
  };
  var CAPS = 'Air Timing, Radio Clock, Frame Clock, Sensor Timing, Intra Refresh, Camera IMU, Bandwidth Cap, 864p120';
  function radioLinked() { return L.radio; }
  function rows(side, tab) {
    var r = [];
    var name = TABS[side][tab];
    if (side === 0 && name === 'HUD') {
      r.push(opt('hudStyle', 'HUD Style', ['OFF', 'CANOPY', 'ARENA', 'ARENA FULL'], { live: 1, help: function () { return S.hudStyle === 'CANOPY' ? "Battery, flight mode and GPS come from the flight controller (polled over MSP) and the HUD's movement from the camera's IMU.\nLink quality is still read off Betaflight's OSD: enable that element there." : 'Which overlay is drawn over the video.'; } }));
      r.push(opt('bfOsd', 'Betaflight OSD', ['OFF', 'ON'], { live: 1, help: "Draw Betaflight's own OSD across the screen." }));
      if (S.hudStyle === 'CANOPY') r.push(opt('canopyVolt', 'Canopy Voltage', ['PER CELL', 'PACK'], { live: 1, help: "The canopy's headline voltage: per cell reads the same on any pack size." }));
      r.push(opt('clock', 'Clock', ['OFF', 'IDLE ONLY 12H', 'IDLE ONLY 24H', 'ON 12H', 'ON 24H'], { live: 1, help: 'When the time is shown at the top of the screen, and how it is written.' }));
      r.push(opt('dyn', 'Dynamic HUD', ['OFF', 'SMALL', 'MEDIUM', 'EXTREME'], { live: 1, help: 'Let the panels move with the aircraft.' }));
      r.push(opt('debug', 'Debug Info', ['OFF', 'ON'], { live: 1, help: "A line of radio details under the right panel, for field tests: the radio's frame, and the mode it means." }));
    } else if (side === 0 && name === 'DISPLAY') {
      r.push(opt('theme', 'Theme', ['KESTREL', 'EMBER', 'ICE', 'MONO', 'VIOLET'], { live: 1, help: 'Which hues carry which meaning.' }));
      r.push(opt('bgVideo', 'Background Video', ['OFF', 'ON'], { help: 'Play the idle scene when nothing is linked.' }));
      r.push(opt('picSize', 'Picture Size', range(60, 95, 5, function (v) { return v + '%'; }).concat(['FULL']), { live: 1, help: 'Shrink the whole picture if your optics clip the edges.' }));
      r.push(opt('uiScale', 'UI Scaling', range(0.5, 2.0, 0.1, function (v) { return v.toFixed(1) + 'x'; }), { live: 1, help: "Size of the HUD's type. The panels stay put." }));
      r.push(opt('bright', 'Brightness', range(0, 100, 5, function (v) { return '' + v; }), { live: 1, help: 'Panel backlight. Lifts video and HUD together.' }));
      r.push({ type: 'H', label: 'ADVANCED' });
      r.push(opt('frameMode', 'Frame Mode', ['SPLIT', 'FULL FRAME', 'FULL DECODE'], { live: 1, help: function () { return FRAME_HELP[S.frameMode]; } }));
      r.push(opt('refreshSync', 'Refresh Sync', ['OFF', 'ON', 'FREE'], { live: 1, trial: 1, help: function () {
        if (S.refreshSync === 'ON') return "Holds this screen's 200.00 Hz just after each picture, 2 refreshes a\ncamera frame (100.00 fps). Off if the screen blanks. Holding now.";
        if (S.refreshSync === 'FREE') return 'Slows this screen from 240.00 Hz to 200.00 Hz in this video mode, 2 refreshes a camera frame.\nOnly for screens that take any frame length.';
        return 'The screen refreshes on its own timing: 240.00 Hz, the camera 100.00 fps.\nON or FREE hold it in step with the pictures.';
      } }));
      if (S.refreshSync !== 'OFF') r.push(opt('syncMargin', 'Sync Margin', ['0 MS', '1 MS', '2 MS', '3 MS', '4 MS'], { live: 1, help: "Refresh Sync's refresh this much later. Fewer pictures miss their refresh (a hitch each), for that much latency: 2 MS, about a third fewer." }));
    } else if (side === 0 && name === 'DVR') {
      r.push(opt('dvrSource', 'Source', ['FPV', 'SCREEN'], { help: function () { return (pendVal('dvrSource') || S.dvrSource) === 'SCREEN' ? "Records the screen - video and HUD, as you see them - 60 times a second.\nAdds about 1 ms to the FPV feed's latency while recording." : "Records the FPV stream as the air unit sends it: full quality, no HUD.\nNo impact on the FPV feed's latency."; } }));
      r.push({ type: 'R', label: 'Folder', value: function () { return '/media/dvr'; }, help: 'Where recordings are written.' });
      r.push({ type: 'R', label: 'Space Left', value: function () { return '28 GB'; }, help: 'Room remaining on the recordings partition.' });
    } else if (side === 0 && name === 'SYSTEM') {
      r.push({ type: 'R', label: 'Build', value: function () { return '2026-10-20 18:02'; } });
      r.push({ type: 'R', label: 'Version', value: function () { return 'v2026.10.beta4'; } });
      r.push({ type: 'R', label: 'Decoder', value: function () { return 'rkmpp'; } });
      r.push(opt('screenMode', 'Screen Mode', ['Auto', '1920x1080 @ 240 Hz', '1920x1080 @ 144 Hz', '1920x1080 @ 120 Hz', '1920x1080 @ 60 Hz', '1280x720 @ 60 Hz'], { trial: 1, help: "Showing 1920x1080 @ 200 Hz. Auto refreshes in step with the camera's frame rate\nwhere the screen can, else at the highest refresh it offers.", warnPending: 'Enter tries it: the app restarts, then asks whether to keep it.' }));
      r.push(opt('wifi', 'WiFi AP', ['OFF', 'ON'], { help: function () { return S.wifi === 'ON' ? 'Network fpvOS-3F2A   Password 12345678   (running). Watch the video at http://192.168.4.1' : 'Wifi access point for spectators'; }, warn: 'Warning: Before enabling, plug an external antenna to the wifi uFL connector.' }));
      r.push({ type: 'H', label: 'WHERE YOU FLY' });
      r.push(opt('licence', 'Amateur Licence', ['NO', 'YES'], { live: 1, help: "Whether you hold an amateur radio licence. With it, the amateur band of your country's ITU region reads OK on the channel page; your licence sets the power." }));
      r.push(opt('area', 'Area', ['NOT SET'].concat(Object.keys(AREAS)), { live: 1, help: "Where you fly, starting with the part of the world. Sets the clock and which channels the channel page allows. Or set it from a phone, on the VRX's web page." }));
      r.push(opt('country', 'Country', S.area === 'NOT SET' ? ['--'] : Object.keys(AREAS[S.area]), { live: 1, help: 'The country you fly in: its rules for the radio\'s channels.' }));
      if (S.area !== 'NOT SET' && AREAS[S.area][S.country] && AREAS[S.area][S.country].length > 1)
        r.push(opt('tz', 'Timezone', AREAS[S.area][S.country], { live: 1, help: function () { return S.tz + '. Only the clock follows this; the channel rules are ' + S.country + "'s either way."; } }));
    } else if (side === 1 && name === 'VIDEO') {
      r.push(opt('videoMode', 'Video Mode', ['720p60', '720p100', '864p120', '1080p60', '1080p100'].filter(function (v) { return L.fpvAir || v.indexOf('864') < 0; })));
      if (L.fpvAir) r.push(opt('maxBitrate', 'Max Bitrate', ['AUTO', '6 Mbps', '8 Mbps', '10 Mbps', '12 Mbps', '15 Mbps', '18 Mbps', '20 Mbps', '22 Mbps', '25 Mbps', '30 Mbps', '35 Mbps', '40 Mbps'], { help: 'Cap on the video bitrate. AUTO follows the link. A cap below it gives a steadier picture and less time on the air per frame. fpvOS air units only.' }));
      else r.push({ type: 'R', off: 1, label: 'Max Bitrate', value: function () { return 'FPVOS AIR ONLY'; }, help: 'Needs an fpvOS air unit: this one runs the stock air app, which ignores the cap.' });
      r.push(opt('rotate', 'Rotate', ['0', '180']));
      r.push(opt('scene', 'Scene', ['Race', 'Standard']));
      r.push(opt('ev', 'EV', ['-1.0 EV', '-0.7 EV', '-0.3 EV', '0 EV', '+0.3 EV', '+0.7 EV', '+1.0 EV']));
      r.push(opt('wb', 'White Balance', ['Auto'].concat(range(4000, 7000, 100, function (v) { return v + 'K'; }))));
      var tenth = ['Auto'].concat(range(1, 10, 1, function (v) { return '' + v; }));
      r.push(opt('sat', 'Saturation', tenth)); r.push(opt('con', 'Contrast', tenth)); r.push(opt('sharp', 'Sharpness', tenth));
      r.push(opt('dnr', '3D DNR', ['Off', 'Low', 'Mid', 'High', 'Auto']));
      r.push(opt('focus', 'Focus Mode', ['Off', 'On']));
    } else if (side === 1 && name === 'RADIO') {
      var fwHelp = "This VRX's own radio firmware: STOCK, or OPEN8030 (open source) when it is installed. The air unit's is not changed. Enter applies it: the radio restarts, the picture is back in ~10 s.";
      if (!radioLinked()) {
        r.push({ id: 'bind', type: 'A', label: 'Bind', hint: BIND.state === 'running' ? 'ENTER: CANCEL' : BIND.state === 'failed' ? 'ENTER: RETRY' : 'ENTER: BIND', help: 'Pairs this VRX with an air unit. Put the air unit in its pairing mode first: hold its bind button until the LED turns red.', act: function () { if (BIND.state === 'running') BIND.state = 'none'; else bindStart(); } });
        r.push(opt('vrxFw', 'VRX Radio Firmware', ['STOCK', 'OPEN8030'], { help: fwHelp }));
      } else {
        r.push({ id: 'channel', type: 'A', label: 'Channel', hint: 'ENTER: OPEN', value: function () { return FREQ + ' MHz  ' + chanModeName(); }, help: 'Where the link sits, what is on every channel and what your country allows. With SYSTEM > Time Zone set: AUTO takes the quietest allowed channel when the link connects, AUTO HOP lets the air unit hop by itself.', act: chanOpen });
        r.push(opt('txPower', 'TX Power', ['25mW', '100mW', '100mW AUTO'], { help: 'Radio output. More reaches further and runs hotter.' }));
        if (S.vrxFw === 'OPEN8030') r.push(opt('maxMcs', 'Max MCS', ['AUTO'].concat(range(0, 11, 1, function (v) { return 'MCS ' + v; }))));
        r.push(opt('maxBw', 'Max Bandwidth', S.vrxFw === 'OPEN8030' ? ['AUTO', '5 MHz', '10 MHz', '20 MHz', '40 MHz'] : ['20 MHz', '40 MHz'], { help: function () { return S.vrxFw === 'OPEN8030' ? 'How wide the video link may go; below it the link picks its width from the signal. 40 on a strong link: more bitrate, a shorter radio frame, less range. Narrower reaches further. Enter applies it, no restart.' : 'How wide the video link may go. 40 widens it on a strong link: more bitrate, a shorter radio frame, less range. 20 reaches further. Enter applies it: the radio restarts, the picture is back in ~10 s.'; } }));
        r.push(opt('vrxFw', 'VRX Radio Firmware', ['STOCK', 'OPEN8030'], { help: fwHelp }));
        r.push(opt('autoStandby', 'Auto Standby', ['OFF', 'ON'], { help: "Force the air unit's low-power standby on or off for now." }));
      }
    } else if (side === 1 && name === 'SERIAL') {
      r.push({ type: 'H', label: 'FLIGHT CONTROLLER' });
      r.push({ type: 'R', label: 'Receiving', value: function () { return L.frames ? 'MSP' : L.radio ? 'NOTHING' : '--'; }, help: 'Whether MSP frames from the flight controller are coming in now.' });
      r.push({ type: 'R', label: 'Frames', value: function () { return L.frames ? Math.floor((now - L.linkAt) * 48) + '  (48/s)' : '--'; }, help: 'MSP frames received and understood, with the rate.' });
      r.push({ type: 'R', label: 'Data', value: function () { return L.frames ? (2.1 + 0.2 * noise(Math.floor(now * 4))).toFixed(1) + ' KB/s' : '--'; }, help: 'Flight controller frames arriving, in bytes a second. Measured while this tab is open.' });
    } else if (side === 1 && name === 'INFO') {
      var lk = radioLinked();
      r.push({ type: 'H', label: 'AIR UNIT' });
      r.push({ type: 'R', label: 'Model', value: function () { return lk ? 'Ascent Lite' : '--'; }, help: 'The air unit on the other end of the link, as it reports itself.' });
      r.push({ type: 'R', label: 'HW Version', value: function () { return lk ? '1.0-1.0' : '-.-'; }, help: "As stock shows it: the board's version, then the RF board's." });
      r.push({ type: 'R', label: 'SN', value: function () { return lk ? 'H_Sky_000000' : '--------'; }, help: "As stock shows it: the model, then the radio chip's ID. Caddx's air app always reports 0 there, so an Ascent reads H_Sky_000000." });
      r.push({ type: 'R', label: 'SW Version', value: function () { return lk ? '18.21.10' : '-.-.-'; }, help: 'The Caddx firmware on the air unit, as stock shows it. With fpvOS it is the stock firmware fpvOS runs on.' });
      if (lk && L.fpvAir) {
        r.push({ type: 'H', label: 'FPVOS' });
        r.push({ type: 'R', label: 'fpvOS', value: function () { return '2026.10.beta4'; }, help: 'The fpvOS air image the unit was flashed with.' });
        r.push({ type: 'R', label: 'kestrel-air', value: function () { return 'beta4 (protocol 9)'; }, help: "fpvOS's air app: it runs the camera and the radio in place of Caddx's." });
        r.push({ type: 'R', label: 'Radio Driver', value: function () { return 'ar_libre beta4'; }, help: 'What drives the AR8030 radio on the air unit.' });
        r.push({ type: 'R', label: 'Radio Firmware', value: function () { return 'Open8030'; }, help: "What runs on the air unit's AR8030 radio chip: the stock firmware, or Open8030, the open one (Lite and Lite+)." });
        r.push({ type: 'R', label: 'Kernel', value: function () { return '5.10.221'; }, help: "The air unit's Linux kernel (the stock one)." });
        r.push({ type: 'R', label: 'Camera', value: function () { return 'CV2004'; }, help: "The camera's image sensor." });
        r.push({ type: 'H', label: 'CAPABILITIES' });
        r.push({ type: 'L', label: CAPS, help: "What this air unit's kestrel-air has on. Air Timing: its times in each slice. Radio Clock: pictures stamped on the radio's clock. Frame Clock: its radio's frame, for exact latency. Sensor Timing: readout and exposure, for STATS. Intra Refresh: no keyframe spikes. Camera IMU: the camera's gyro with the video. FC IMU: the flight controller's gyro instead. Bandwidth Cap: takes the VRX's limit. 864p120, 864p144: Video Mode offers a 1536x864 window at 120 or 144 fps." });
      }
    }
    return r;
  }
  function tabsOf(side) { return TABS[side].map(function (n, i) { return i; }).filter(function (i) { return !(side === 1 && TABS[1][i] === 'VIDEO' && !radioLinked()); }); }
  function selectable(rw) { return rw.type !== 'H'; }
  function firstSel(list) { for (var i = 0; i < list.length; i++) if (selectable(list[i])) return i; return 0; }
  function pendVal(id) { return MENU.pend[id] ? MENU.pend[id].to : null; }
  function shownVal(rw) {
    if (rw.type === 'S') return MENU.pend[rw.id] ? MENU.pend[rw.id].to : S[rw.id];
    if (rw.value) return rw.value();
    return '';
  }
  function applySetting(id, v) {
    S[id] = v;
    if (id === 'theme') setTheme(v, true);
    if (id === 'area') { S.country = v === 'NOT SET' ? '--' : Object.keys(AREAS[v])[0]; S.tz = v === 'NOT SET' ? '--' : AREAS[v][S.country][0]; }
    if (id === 'country' && S.area !== 'NOT SET') S.tz = AREAS[S.area][v][0];
    if (id === 'vrxFw' || (id === 'maxBw' && S.vrxFw === 'STOCK')) { L.radioOkAt = now + 3.5; L.fwRestart = true; }
    if (id === 'refreshSync' && v !== 'OFF') MENU.trial = { id: id, back: 'OFF', until: now + 10, msg: function (s) { return 'Keep it? Enter keeps it - back to OFF in ' + s + ' s.'; } };
    if (id === 'refreshSync' && v === 'OFF') MENU.trial = null;
    if (id === 'screenMode') MENU.trial = { id: id, back: MENU.trialPrev || 'Auto', until: now + 15, msg: function (s) { return 'Keep this mode? Enter keeps it - going back in ' + s + ' s.'; } };
    if (id === 'bright') cv.style.filter = 'brightness(' + (0.55 + 0.9 * parseInt(v, 10) / 100) + ')';
  }
  function curRows() { return rows(MENU.side, MENU.tab[MENU.side]); }
  function menuOpen() {
    MENU.open = true; MENU.stage = 0; MENU.edit = false; MENU.pend = {};
    if (MENU.firstOpen) { MENU.firstOpen = false; MENU.side = 1; }
    CH.open = false;
  }
  function menuKey(k) {
    if (CH.open) return chanKey(k);
    var list, rw, i;
    if (MENU.stage === 0) {
      if (k === 'left') MENU.side = 0; else if (k === 'right') MENU.side = 1;
      else if (k === 'ok') {
        var tabs = tabsOf(MENU.side); if (tabs.indexOf(MENU.tab[MENU.side]) < 0) MENU.tab[MENU.side] = tabs[0];
        MENU.stage = 1; MENU.sel = firstSel(curRows());
      } else if (k === 'back') { MENU.open = false; }
      return;
    }
    list = curRows(); if (MENU.sel >= list.length) MENU.sel = firstSel(list); rw = list[MENU.sel];
    if (MENU.trial && k === 'ok') { MENU.trial = null; return; }
    if (!MENU.edit) {
      if (k === 'up' || k === 'down') {
        var d = k === 'down' ? 1 : -1; i = MENU.sel;
        for (var n = 0; n < list.length; n++) { i = (i + d + list.length) % list.length; if (selectable(list[i])) break; }
        MENU.sel = i;
      } else if (k === 'left' || k === 'right') {
        var tabs2 = tabsOf(MENU.side), ti = tabs2.indexOf(MENU.tab[MENU.side]);
        ti = clamp(ti + (k === 'right' ? 1 : -1), 0, tabs2.length - 1);
        if (tabs2[ti] !== MENU.tab[MENU.side]) { MENU.tab[MENU.side] = tabs2[ti]; MENU.sel = firstSel(curRows()); }
      } else if (k === 'ok') {
        if (rw.type === 'S') {
          if (rw.vals.length > 1) { MENU.edit = true; if (rw.trial && !MENU.pend[rw.id]) MENU.trialPrev = S[rw.id]; }
        } else if (rw.type === 'A') rw.act();
      } else if (k === 'back') { MENU.stage = 0; }
      return;
    }
    // EDIT
    if (k === 'up' || k === 'down') {
      var cur = shownVal(rw), ix = rw.vals.indexOf(cur); if (ix < 0) ix = 0;
      ix = (ix + (k === 'down' ? 1 : -1) + rw.vals.length) % rw.vals.length;
      var v = rw.vals[ix];
      if (rw.live) applySetting(rw.id, v);
      else {
        if (!MENU.pend[rw.id]) MENU.pend[rw.id] = { from: S[rw.id], to: v };
        else MENU.pend[rw.id].to = v;
        if (MENU.pend[rw.id].to === MENU.pend[rw.id].from) delete MENU.pend[rw.id];
      }
    } else if (k === 'ok') {
      if (MENU.pend[rw.id]) { var to = MENU.pend[rw.id].to; delete MENU.pend[rw.id]; applySetting(rw.id, to); }
      MENU.edit = false;
    } else if (k === 'left' || k === 'back') MENU.edit = false;
  }
  function wrapText(s, em, maxW) {
    var out = [];
    String(s).split('\n').forEach(function (para) {
      var words = para.split(' '), line = '';
      words.forEach(function (w) {
        var t = line ? line + ' ' + w : w;
        if (stw(t, em) > maxW && line) { out.push(line); line = w; } else line = t;
      });
      out.push(line);
    });
    return out;
  }
  function drawMenu(c, pr, dt) {
    var u0 = pr.h / 1080, u = u0 * P.ui;
    var pick = MENU.wake * (1 - Math.max(MENU.openF[0], MENU.openF[1])) * (1 - MENU.band);
    // dim
    fill(c, pr.x, pr.y, pr.w, pr.h, T.ground, 0.1 * MENU.wake + 0.06 * Math.max(MENU.openF[0], MENU.openF[1]));
    // pick labels over the blades
    if (pick > 0.01 && (arrive.at > 0 || !L.everConn || true)) {
      for (var side = 0; side < 2; side++) {
        var M = panelM(side), picked = MENU.stage === 0 && MENU.side === side, X = XO(side, 14);
        ptext(c, M, side ? 'AIR UNIT  >' : '<  GROUND UNIT', X, MY(407) + 0.0, 0.625 * T_STATE * P.ui, side ? 2 : 0, picked ? T.accent : T.quiet, pick);
        ptext(c, M, side ? 'VIDEO   RADIO   SERIAL   INFO' : 'HUD   DISPLAY   DVR   SYSTEM', X, MY(427), 0.625 * T_UNIT * P.ui, side ? 2 : 0, picked ? T.text : T.quiet, (picked ? 0.85 : 0.6) * pick);
      }
    }
    for (var sd = 0; sd < 2; sd++) {
      var t = MENU.openF[sd]; if (t <= 0.003) continue;
      var e = ease(t);
      var railY = M0railY();
      var fw = 0.31 * pr.w, ow = 0.34 * pr.w;
      var from = { x: sd ? pr.x + pr.w - fw : pr.x, y: railY, w: fw, h: pr.y + pr.h - railY };
      var to = { x: sd ? pr.x + pr.w - ow : pr.x, y: pr.y + 0.06 * pr.h, w: ow, h: 0.92 * pr.h };
      var R = { x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, w: from.w + (to.w - from.w) * e, h: from.h + (to.h - from.h) * e };
      if (MENU.band > 0.003 && sd === 1) {
        var eb = ease(MENU.band), B = { x: pr.x, y: pr.y + 0.59 * pr.h, w: pr.w, h: 0.41 * pr.h };
        R = { x: R.x + (B.x - R.x) * eb, y: R.y + (B.y - R.y) * eb, w: R.w + (B.w - R.w) * eb, h: R.h + (B.h - R.h) * eb };
      }
      fill(c, R.x, R.y, R.w, R.h, T.ground, 0.94 * Math.min(1, 1.6 * t));
      fill(c, R.x, R.y, R.w, 3 * u0, T.accent, t);
      if (t > 0.5 && MENU.side === sd && MENU.stage === 1) blade(c, R, u, (t - 0.5) * 2);
    }
    if (MENU.band > 0.003) {
      var tb = MENU.band, eb2 = ease(tb);
      var from2 = { x: pr.x + pr.w - 0.34 * pr.w, y: pr.y + 0.06 * pr.h, w: 0.34 * pr.w, h: 0.92 * pr.h }, to2 = { x: pr.x, y: pr.y + 0.59 * pr.h, w: pr.w, h: 0.41 * pr.h };
      var Rb = { x: from2.x + (to2.x - from2.x) * eb2, y: from2.y + (to2.y - from2.y) * eb2, w: from2.w + (to2.w - from2.w) * eb2, h: from2.h + (to2.h - from2.h) * eb2 };
      fill(c, Rb.x, Rb.y, Rb.w, Rb.h * 0.14, T.ground, 0.45 * tb);
      fill(c, Rb.x, Rb.y + Rb.h * 0.14, Rb.w, Rb.h * 0.86, T.ground, 0.9 * tb);
      if (tb > 0.5) chanBand(c, Rb, (tb - 0.5) * 2, dt);
    }
  }
  function M0railY() { var p = panelM(0)(XO(0, 0), MY(456)); return p[1]; }
  function blade(c, R, u, a) {
    var pad = 22 * u, side = MENU.side, list = curRows();
    if (MENU.sel >= list.length || !selectable(list[MENU.sel])) MENU.sel = firstSel(list);
    stext(c, side ? 'AIR UNIT' : 'GROUND UNIT', R.x + pad, R.y + pad + 14 * u, 15 * u, 0, T.accent, a);
    var tx = R.x + pad, tb = R.y + pad + 52 * u, tabs = tabsOf(side);
    tabs.forEach(function (ti) {
      var name = TABS[side][ti], act = ti === MENU.tab[side], w = stw(name, 21 * u);
      stext(c, name, tx, tb, 21 * u, 0, act ? T.text : T.quiet, act ? a : 0.8 * a);
      if (act) fill(c, tx, tb + 9 * u, w, 3 * u, T.accent, a);
      tx += w + 26 * u;
    });
    var listTop = tb + 26 * u;
    fill(c, R.x + pad, listTop - 6 * u, R.w - 2 * pad, 1.2 * u, T.quiet, 0.3 * a);
    // help area
    var rw = list[MENU.sel] || {}, lines = [], em = 18 * u, maxW = R.w - 2 * pad;
    if (MENU.pend[rw.id]) lines = lines.concat(wrapText('Pending: ' + MENU.pend[rw.id].from + ' -> ' + MENU.pend[rw.id].to + '. OK sends it.', em, maxW).map(function (l) { return [l, T.accent, 1]; }));
    if (rw.id === 'bind' && BIND.state !== 'none') {
      var bs = BIND.state === 'running' ? 'BINDING  ' + Math.max(0, Math.ceil(120 - (now - BIND.at))) + 's' : BIND.state === 'ok' ? 'BOUND  3F:2A:91:C4' : BIND.state === 'failed' ? 'NO AIR UNIT FOUND' : '';
      if (bs) lines.push([bs, T.accent, 1]);
    }
    var help = typeof rw.help === 'function' ? rw.help() : rw.help;
    if (help && !(rw.id === 'wifi' && MENU.pend.wifi)) lines = lines.concat(wrapText(help, em, maxW).map(function (l) { return [l, mul(T.text, 0.7), 1]; }));
    var warn = rw.warn || (MENU.pend[rw.id] && rw.warnPending) || null;
    if (rw.warnPending && !MENU.pend[rw.id]) warn = null;
    if (MENU.trial) { warn = MENU.trial.msg(Math.max(0, Math.ceil(MENU.trial.until - now))); }
    if (warn) lines = lines.concat(wrapText(warn, em, maxW).map(function (l) { return [l, MAMBER, 1]; }));
    lines = lines.slice(0, 10);
    var lh = em * 1.4, helpTop = R.y + R.h - pad - lines.length * lh;
    if (lines.length) fill(c, R.x + pad, helpTop - 10 * u, R.w - 2 * pad, 1.2 * u, T.quiet, 0.35 * a);
    lines.forEach(function (l, i) { stext(c, l[0], R.x + pad, helpTop + (i + 0.78) * lh, em, 0, l[1], a * l[2]); });
    var listBottom = helpTop - 20 * u, rowH = 50 * u;
    // rows
    var heights = list.map(function (r2, i) {
      if (r2.type === 'L') return Math.max(rowH, wrapText(r2.label.replace(/, /g, ',\n').replace(/,\n/g, ', \n'), 23 * u, R.w - 2 * pad).length * 1.4 * 23 * u + 14 * u);
      return i === MENU.sel && MENU.edit ? rowH + 1.6 * rowH : rowH;
    });
    var avail = listBottom - listTop, start = 0, end = list.length, used = 0;
    // window keeps the selection centred (pinned at the ends)
    var visN = clamp(Math.floor((avail - (MENU.edit ? 80 * u : 0)) / rowH), 3, 16);
    if (list.length > visN) { start = clamp(MENU.sel - Math.floor(visN / 2), 0, list.length - visN); end = start + visN; }
    var ry = listTop;
    for (var i = start; i < end; i++) {
      var r = list[i], h = heights[i];
      if (ry + h > listBottom + 1) break;
      var sel = i === MENU.sel;
      if (r.type === 'H') {
        stext(c, r.label, R.x + pad, ry + 36 * u, 15 * u, 0, T.quiet, 0.9 * a);
        fill(c, R.x + pad, ry + 43 * u, R.w - 2 * pad, 1.2 * u, T.quiet, 0.3 * a);
      } else if (r.type === 'L') {
        var ls = wrapText(r.label, 23 * u, R.w - 2 * pad);
        if (sel) { fill(c, R.x + pad / 2, ry + 2 * u, R.w - pad, h - 4 * u, mul(T.ground, 1.6), 0.95 * a); ring(c, R.x + pad / 2 + 3 * u, ry + 2 * u + 3 * u, R.w - pad - 6 * u, h - 10 * u, 3 * u, T.accent, a); }
        ls.forEach(function (l, j) { stext(c, l, R.x + pad, ry + 30 * u + j * 1.4 * 23 * u, 23 * u, 0, T.quiet, a); });
      } else {
        if (sel) { fill(c, R.x + pad / 2, ry + 2 * u, R.w - pad, h - 4 * u, mul(T.ground, 1.6), 0.95 * a); ring(c, R.x + pad / 2 + 3 * u, ry + 5 * u, R.w - pad - 6 * u, h - 10 * u, 3 * u, T.accent, a); }
        var lab = r.off ? T.quiet : sel ? T.text : mul(T.text, 0.82);
        var lb = ry + 25 * u + 0.36 * 23 * u;
        var lw = stext(c, r.label, R.x + pad, lb, 23 * u, 0, lab, a);
        if (sel && MENU.edit && r.type === 'S') {
          var cur = shownVal(r), ix = r.vals.indexOf(cur), cy = ry + 65 * u;
          stext(c, cur + (MENU.pend[r.id] ? ' *' : ''), R.x + R.w - pad, cy + 0.36 * 30 * u, 30 * u, 2, T.accent, a);
          if (ix > 0) stext(c, r.vals[ix - 1], R.x + R.w - pad, cy - 34 * u + 0.36 * 18 * u, 18 * u, 2, T.quiet, 0.8 * a);
          if (ix >= 0 && ix < r.vals.length - 1) stext(c, r.vals[ix + 1], R.x + R.w - pad, cy + 34 * u + 0.36 * 18 * u, 18 * u, 2, T.quiet, 0.8 * a);
        } else {
          var val = r.type === 'A' && sel ? r.hint : shownVal(r);
          if (r.type === 'S' && MENU.pend[r.id]) val += ' *';
          var vc = r.off ? T.quiet : sel ? T.accent : r.type === 'R' ? T.quiet : T.text;
          var vem = 20 * u, room = R.w - 2 * pad - lw - 16 * u;
          while (vem > 12 * u && stw(val, vem) > room) vem -= u;
          stext(c, val, R.x + R.w - pad, lb, vem, 2, vc, sel ? a : 0.85 * a);
        }
      }
      ry += h;
    }
    if (start > 0) tri(c, R.x + R.w / 2, listTop + 2 * u, 6 * u, -1, T.quiet, 0.8 * a);
    if (end < list.length) tri(c, R.x + R.w / 2, listBottom + 6 * u, 6 * u, 1, T.quiet, 0.8 * a);
    // WiFi QR codes (placeholders drawn as the real layout: two codes with labels)
    if (rw.id === 'wifi' && S.wifi === 'ON' && !MENU.edit && !MENU.pend.wifi) {
      var qs = Math.min((R.w - 2 * pad - 24 * u) / 2, 150 * u), qy = helpTop - 40 * u - qs - 30 * u;
      [['1  JOIN THE WIFI', 0], ['2  WATCH', 1]].forEach(function (q, j) {
        var qx = R.x + pad + j * (qs + 24 * u);
        fakeQR(c, qx, qy, qs, j + 1, a);
        stext(c, q[0], qx, qy + qs + 24 * u, 17 * u, 0, T.text, a);
      });
    }
  }
  function tri(c, x, y, s, dir, col, a) { c.globalAlpha = a; c.fillStyle = rgb(col); c.beginPath(); c.moveTo(x - s, y); c.lineTo(x + s, y); c.lineTo(x, y + dir * s); c.closePath(); c.fill(); c.globalAlpha = 1; }
  function fakeQR(c, x, y, s, seed, a) {
    var n = 25, m = s / (n + 6);
    fill(c, x, y, s, s, WHITE, a);
    for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
      var finder = function (fx, fy) { var dx = i - fx, dy = j - fy; return dx >= 0 && dx < 7 && dy >= 0 && dy < 7 && (dx === 0 || dx === 6 || dy === 0 || dy === 6 || (dx > 1 && dx < 5 && dy > 1 && dy < 5)); };
      var inF = (i < 8 && j < 8) || (i > n - 9 && j < 8) || (i < 8 && j > n - 9);
      var on = inF ? (finder(0, 0) || finder(n - 7, 0) || finder(0, n - 7)) : noise(i * 31 + j * 7 + seed * 101) > 0.5;
      if (on) fill(c, x + (i + 3) * m, y + (j + 3) * m, m + 0.3, m + 0.3, BLACK, a);
    }
  }

  // ---------------------------------------------------------------- channel page
  // cursor: 0 = AUTO, 1 = AUTO HOP, r + 2 = the r-th channel by frequency
  var CH = { open: false, sel: 0, cx: -1, lx: -1, mode: 0, work: -1, lvl: [], pk: [], pkAt: [], list: [], refusedAt: -100 };
  var CH_PRE = 2;
  (function () {
    for (var f = 5150; f <= 5250; f += 10) CH.list.push(f);
    for (var g = 5660; g <= 5960; g += 10) CH.list.push(g);
    CH.work = CH.list.indexOf(FREQ);
    CH.list.forEach(function (f, i) { CH.lvl[i] = -95; CH.pk[i] = -95; CH.pkAt[i] = 0; });
  })();
  function usable(f) { var v = verdict(f); return v.state === 'allowed'; }
  function autoN() { if (!rulesKnown()) return 0; var n = 0; CH.list.forEach(function (f) { if (usable(f)) n++; }); return n; }
  function chanMode() { return CH.mode >= 0 && autoN() > 0 ? CH.mode : -1; }
  function chanModeName() { var m = chanMode(); return m === 0 ? 'AUTO' : m === 1 ? 'AUTO HOP' : 'FIXED'; }
  function chanOpen() { CH.open = true; CH.sel = CH.work >= 0 ? CH.work + CH_PRE : 0; CH.cx = -1; CH.lx = -1; }
  function quietest() {
    var best = -1, bv = 1e9;
    CH.list.forEach(function (f, i) { var ok = !rulesKnown() || usable(f); if (ok && CH.pk[i] < bv) { bv = CH.pk[i]; best = i; } });
    return best;
  }
  function chanKey(k) {
    var n = CH.list.length;
    if (k === 'back') { CH.open = false; return; }
    if (k === 'left') CH.sel = Math.max(0, CH.sel - 1);
    if (k === 'right') CH.sel = Math.min(n + 1, CH.sel + 1);
    if (k === 'up') { var q = quietest(); if (q >= 0) CH.sel = q + CH_PRE; }
    if (k === 'down' && CH.work >= 0) CH.sel = CH.work + CH_PRE;
    if (k === 'ok') {
      if (CH.sel < CH_PRE) {
        if (autoN() === 0) { CH.refusedAt = now; return; }
        CH.mode = CH.sel;
        if (CH.sel === 0) { var q2 = quietest(); if (q2 >= 0) { CH.work = q2; FREQ = CH.list[q2]; } }
      } else { CH.mode = -1; CH.work = CH.sel - CH_PRE; FREQ = CH.list[CH.work]; }
    }
  }
  var EU = ['France', 'Germany', 'Spain', 'Italy'];
  function rulesKnown() { return S.area !== 'NOT SET' && S.country !== '--'; }
  function itu() { return S.area === 'America' ? 2 : S.area === 'Australia' ? 3 : 1; }
  // judged at the link's own width
  function verdict(f) {
    var c = S.country, half = LINK.bw / 2, lo = f - half, hi = f + half, ex = [];
    if (EU.indexOf(c) >= 0) ex = [[5725, 5875, 25, 0, 'EU SRD Decision 2006/771/EC as amended by (EU) 2022/180, band 61: 25 mW e.i.r.p., certified equipment']];
    if (c === 'United Kingdom') ex = [[5725, 5875, 25, 0, 'Ofcom IR 2030: 25 mW e.i.r.p., certified equipment']];
    if (c === 'United States') ex = [[5725, 5850, 1000, 0, 'FCC 47 CFR 15.247: 1 W conducted, digital modulation, certified equipment']];
    if (c === 'Canada') ex = [[5725, 5850, 1000, 0, 'ISED RSS-247 Issue 4: 1 W conducted, certified equipment'], [5150, 5250, 200, 1, 'ISED RSS-247 Issue 4: indoors only, 200 mW e.i.r.p., certified equipment']];
    if (c === 'Australia') ex = [[5725, 5850, 4000, 0, 'ACMA LIPD Class Licence 2015: 4 W e.i.r.p., digital modulation, certified equipment']];
    for (var i = 0; i < ex.length; i++) if (lo >= ex[i][0] && hi <= ex[i][1]) return { state: ex[i][3] ? 'indoor' : 'allowed', cap: ex[i][2], note: ex[i][4] };
    var am = itu() === 2 ? [5650, 5925] : [5650, 5850];
    var cov = function (a, b) { if (a >= am[0] && b <= am[1]) return true; for (var j = 0; j < ex.length; j++) { if (a >= ex[j][0] && a < ex[j][1] && b > am[1] && b <= ex[j][1]) return true; } return false; };
    if (cov(lo, hi)) return { state: S.licence === 'YES' ? 'allowed' : 'licence', amateur: true, note: 'Amateur band, ITU Region ' + itu() + ' (Radio Regulations art. 5): with an amateur licence; national rules may narrow it' };
    return { state: 'no' };
  }
  function chanScanStep(dt) {
    CH.list.forEach(function (f, i) {
      var base = -96 + 5 * noise(i * 3.1), busy = (f === 5745 || f === 5765 || f === 5220) ? 14 : (f === 5800 ? 9 : 0);
      var target = base + busy + 3 * noise(Math.floor(now * 14) + i * 17);
      CH.lvl[i] = follow(CH.lvl[i], target, 0.07, dt);
      if (target >= CH.pk[i] || now - CH.pkAt[i] > 30) { CH.pk[i] = target; CH.pkAt[i] = now; }
    });
  }
  function chanBand(c, R, a, dt) {
    var cu = R.w / 100, n = CH.list.length, bandH = R.h / cu;
    var X = function (v) { return R.x + v * cu; }, Y = function (v) { return R.y + v * cu; };
    var txt = function (s, x, top, size, col, align, al) { return stext(c, s, X(x), Y(top + 0.87 * size), size * cu, align || 0, col, (al == null ? 1 : al) * a) / cu; };
    var bf = function (x, y, w, h, col, al) { fill(c, X(x), Y(y), w * cu, h * cu, col, al * a); };
    var hatch = function (x, y, w, h, col, al, pitch, stripe) {
      c.save(); c.beginPath(); c.rect(X(x), Y(y), w * cu, h * cu); c.clip(); c.globalAlpha = al * a; c.strokeStyle = rgb(col); c.lineWidth = stripe * cu;
      c.beginPath(); for (var s = -h; s < w + h; s += pitch) { c.moveTo(X(x + s), Y(y + h)); c.lineTo(X(x + s + h), Y(y)); } c.stroke(); c.restore(); c.globalAlpha = 1;
    };
    var bands = [], b = 0; CH.list.forEach(function (f, i) { if (i && f - CH.list[i - 1] > 100) b++; bands[i] = b; });
    var nb = b + 1, units = CH_PRE + 1.0 + n + 1.4 * nb, sw = 95.6 / units, bwid = 0.62 * sw, x0 = 2.2;
    var slotX = function (s) {
      if (s < CH_PRE) return x0 + (s * 2 + 0.5) * sw;
      var r = s - CH_PRE; return x0 + (CH_PRE + 1.0 + 1.4 * (bands[r] + 1) + r + 0.5) * sw;
    };
    var slotXF = function (f) { var a0 = Math.floor(f), t0 = f - a0; return a0 >= n + 1 ? slotX(n + 1) : slotX(a0) + (slotX(a0 + 1) - slotX(a0)) * t0; };
    var yT = 8.6, yB = bandH - 4.6, Yd = function (d) { return yB - clamp((d + 100) / 40, 0, 1) * (yB - yT); };
    if (CH.cx < 0) { CH.cx = CH.sel; CH.lx = CH.work + CH_PRE; }
    CH.cx = follow(CH.cx, CH.sel, 0.055, dt); CH.lx = follow(CH.lx, CH.work + CH_PRE, 0.12, dt);
    bf(2, 4.2, 96, 0.12, T.text, 0.85);
    var busyCol = function (d) { return d <= -88 ? T.data : d <= -80 ? MAMBER : DANGER; }, busyWord = function (d) { return d <= -88 ? 'QUIET' : d <= -80 ? 'SOME TRAFFIC' : 'BUSY'; };
    var known = rulesKnown(), N = autoN(), mode = chanMode();
    if (CH.sel < CH_PRE) {
      var nm = CH.sel === 0 ? 'AUTO' : 'AUTO HOP', head, hc = T.text;
      if (!known) { head = nm + '   -   not available: set SYSTEM > Time Zone first'; hc = T.quiet; }
      else if (N === 0) { head = nm + '   -   not available: no channel allowed in ' + S.country; hc = T.quiet; }
      else if (CH.sel === 0) head = 'AUTO   -   ' + (mode === 0 ? '' : 'OK: ') + 'the quietest of ' + N + ' allowed in ' + S.country + ' at link-up';
      else head = 'AUTO HOP   -   ' + (mode === 1 ? '' : 'OK: ') + 'the air unit hops by itself on ' + N + ' allowed in ' + S.country;
      if (now - CH.refusedAt < 3) hc = DANGER;
      txt(head, 2.2, 1.3, 1.5, hc);
    } else {
      var r = CH.sel - CH_PRE, f = CH.list[r], xx = 2.2;
      xx += txt(f + ' MHz', xx, 1.3, 1.5, T.text) + 1.4;
      var lv = Math.round(CH.lvl[r]), pk = Math.round(CH.pk[r]);
      xx += txt(busyWord(pk) + '   ' + lv + ' dBm, 30 s peak ' + pk, xx, 1.55, 1.15, busyCol(pk)) + 1.4;
      var vd = verdict(f), ls, lc;
      if (!known) { ls = 'time zone not set'; lc = T.quiet; }
      else if (vd.state === 'no') { ls = 'not allowed in ' + S.country; lc = DANGER; }
      else if (vd.state === 'licence') { ls = 'needs an amateur licence in ' + S.country; lc = T.data; }
      else if (vd.state === 'indoor') { ls = 'indoor only in ' + S.country; lc = MAMBER; }
      else if (vd.amateur) { ls = 'allowed with your amateur licence'; lc = T.text; }
      else { var cap = vd.cap >= 1000 ? vd.cap / 1000 + ' W' : vd.cap + ' mW', tx = parseInt(S.txPower, 10); ls = 'allowed, ' + cap + ' max' + (tx > vd.cap ? ' (TX Power is ' + tx + ' mW)' : ''); lc = T.text; }
      txt(ls, xx, 1.55, 1.15, lc);
    }
    txt('LINK ' + FREQ + ' MHz  ' + chanModeName() + '   ' + (ISO[S.country] || ''), 97.8, 1.55, 1.1, T.quiet, 2);
    // rule rail
    var xa = slotX(CH_PRE) - sw / 2, xb = slotX(n + 1) + sw / 2;
    if (!known) {
      c.globalAlpha = 0.6 * a; c.strokeStyle = rgb(T.quiet); c.lineWidth = 0.1 * cu; c.strokeRect(X(xa), Y(6), (xb - xa) * cu, 1.7 * cu); c.globalAlpha = 1;
      txt('TIME ZONE NOT SET  -  SYSTEM > TIME ZONE', (xa + xb) / 2, 6.4, 0.85, MAMBER, 1);
    } else {
      var runs = [], cur = null;
      CH.list.forEach(function (f, i) { var v = verdict(f), key = v.state + '|' + (v.cap || 0) + '|' + (v.amateur ? 1 : 0) + '|' + bands[i]; if (!cur || cur.key !== key) { cur = { key: key, a: i, b: i, v: v }; runs.push(cur); } else cur.b = i; });
      runs.forEach(function (rn) {
        var xa2 = slotX(rn.a + CH_PRE) - sw / 2 + 0.08, xb2 = slotX(rn.b + CH_PRE) + sw / 2 - 0.08, v = rn.v;
        var col = v.state === 'no' ? DANGER : v.state === 'indoor' ? MAMBER : v.state === 'licence' ? T.data : T.quiet;
        if (v.state === 'allowed') bf(xa2, 6, xb2 - xa2, 0.14, v.amateur ? T.data : T.text, 0.45);
        else hatch(xa2, 6, xb2 - xa2, 1.7, col, 0.42, 0.55, 0.2);
        if (xb2 - xa2 >= 9) {
          var lab = v.state === 'no' ? 'NOT ALLOWED' : v.state === 'indoor' ? 'INDOOR ONLY' : v.state === 'licence' ? 'LICENCE NEEDED' : v.amateur ? 'OK  -  AMATEUR' : 'OK  -  ' + (v.cap >= 1000 ? v.cap / 1000 + ' W' : v.cap + ' mW') + ' MAX';
          var tw2 = stw(lab, 0.8 * cu) / cu, mid = (xa2 + xb2) / 2;
          bf(mid - tw2 / 2 - 0.35, 6.2, tw2 + 0.7, 1.3, T.ground, 1);
          txt(lab, mid, 6.4, 0.8, v.amateur && v.state === 'allowed' ? T.data : col, 1);
        }
      });
    }
    // the two automatic slots
    [['AUTO', 0], ['HOP', 1]].forEach(function (sl) {
      var on = mode === sl[1];
      hatch(slotX(sl[1]) - bwid / 2, yT, bwid, yB - yT, on ? T.text : T.quiet, N === 0 ? 0.08 : on ? 0.45 : 0.2, 0.6, 0.25);
      txt(sl[0], slotX(sl[1]), yB + 0.7, 0.85, on ? T.text : T.quiet, 1, N === 0 ? 0.5 : 1);
    });
    // bars
    CH.list.forEach(function (f, i) {
      var x = slotX(i + CH_PRE), banned = known && verdict(f).state === 'no', lv = CH.lvl[i], pk = CH.pk[i];
      if (banned) hatch(x - sw / 2, yT, sw, yB - yT, DANGER, 0.16, 0.55, 0.2);
      bf(x - bwid / 2, Yd(lv), bwid, Math.max(0.25, yB - Yd(lv)), banned ? T.quiet : busyCol(lv), banned ? 0.4 : 0.92);
      if (pk > lv + 1) bf(x - bwid / 2 - 0.08, Yd(pk) - 0.12, bwid + 0.16, 0.24, T.text, banned ? 0.4 : 0.75);
    });
    if (CH.work >= 0) {
      var lx = slotXF(CH.lx), lvw = CH.lvl[CH.work], pkw = CH.pk[CH.work];
      bf(lx - bwid / 2 - 0.1, Yd(lvw) - 0.42, bwid + 0.2, 0.42, T.accent, 1);
      var lw = stw('LINK', 0.8 * cu) / cu + 0.8, top = Math.min(Yd(lvw), Yd(pkw)) - 2.1;
      bf(lx - lw / 2, top, lw, 1.36, T.accent, 1);
      txt('LINK', lx - lw / 2 + 0.4, top + 0.288, 0.8, T.ground);
    }
    // band labels
    for (var bi = 0; bi < nb; bi++) {
      var idx = []; CH.list.forEach(function (f, i) { if (bands[i] === bi) idx.push(i); });
      [idx[0], idx[idx.length - 1]].forEach(function (i) { if (Math.abs(i + CH_PRE - CH.cx) > 2.5) txt('' + CH.list[i], slotX(i + CH_PRE), yB + 0.7, 0.8, T.quiet, 1); });
      var mf = (CH.list[idx[0]] + CH.list[idx[idx.length - 1]]) / 2;
      txt((mf / 1000).toFixed(1) + ' GHz', (slotX(idx[0] + CH_PRE) + slotX(idx[idx.length - 1] + CH_PRE)) / 2, yB + 2.4, 0.9, T.quiet, 1);
    }
    // cursor
    var cx = slotXF(CH.cx);
    bf(cx - 0.62 * sw, yT - 0.5, 1.24 * sw, yB - yT + 2.5, T.accent, 0.07);
    c.globalAlpha = a; c.strokeStyle = rgb(T.accent); c.lineWidth = 0.16 * cu; c.strokeRect(X(cx - 0.62 * sw), Y(yT - 0.5), 1.24 * sw * cu, (yB - yT + 2.5) * cu); c.globalAlpha = 1;
    if (CH.sel >= CH_PRE) {
      var fs = '' + CH.list[CH.sel - CH_PRE], tws = stw(fs, 0.95 * cu) / cu;
      bf(cx - tws / 2 - 0.3, yB + 0.5, tws + 0.6, 1.3, T.ground, 1);
      txt(fs, cx, yB + 0.65, 0.95, T.text, 1);
      var vd2 = verdict(CH.list[CH.sel - CH_PRE]);
      if (known && vd2.note) txt('Source: ' + vd2.note, 97.8, yB + 2.45, 0.75, T.quiet, 2);
    }
  }

  // ---------------------------------------------------------------- bind
  var BIND = { state: 'none', at: 0, okAt: 0 };
  function bindStart() {
    if (L.radio) { BIND.state = 'already'; BIND.at = now; return; }
    BIND.state = 'running'; BIND.at = now; syncControls();
  }
  function bindOverlay(c) {
    if (BIND.state === 'none') return;
    var e = now - BIND.at, head, sub, lp = 0, fade = 1;
    if (BIND.state === 'running') { head = 'BINDING   ' + Math.max(0, Math.ceil(120 - e)) + 's'; sub = 'Push the bind button on the air unit'; if (e > 120) { BIND.state = 'failed'; BIND.at = now; } }
    else if (BIND.state === 'ok') { head = 'BOUND'; sub = '3F:2A:91:C4   saved'; lp = clamp(e / 0.9, 0, 1); if (e > 3) { BIND.state = 'none'; syncControls(); } }
    else if (BIND.state === 'already') { head = 'ALREADY LINKED'; sub = 'an air unit is already connected'; if (e > 2.5) BIND.state = 'none'; }
    else { head = 'NO AIR UNIT FOUND'; sub = 'Push the bind button on the air unit'; if (e > 3) BIND.state = 'none'; }
    if (BIND.state === 'none') return;
    lockFigure(c, { scale: 0.34, cyFrac: -0.5, textScale: 1.3, ph: now, lp: lp, fade: fade, title: head, stage: sub, sweep: now * 2.3, dyn: 1, subAccent: BIND.state === 'ok' && lp > 0.75 });
  }

  // ---------------------------------------------------------------- recording
  var REC = { on: false, at: 0, vt: 0 };
  function recToggle() {
    if (!REC.on) { REC.on = true; REC.at = now; REC.vt = vFlight.currentTime || 0; }
    else {
      REC.on = false;
      var dur = now - REC.at;
      if (dur > 1) {
        var th = document.createElement('canvas'); th.width = 384; th.height = 216; th.getContext('2d').drawImage(cv, 0, 0, 384, 216);
        var d = new Date(Date.now() - dur * 1000);
        var name = d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + '  ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
        GAL.recs.push({ name: name, dur: Math.min(dur, 70), start: REC.vt, mb: Math.round(dur * 1.9), thumb: th });
      }
    }
  }

  // ---------------------------------------------------------------- gallery
  var GAL = { mode: 'off', sel: 0, scroll: 0, k: 0, play: 0, dlg: 0, lit: 0, gap: 0, gapFrom: 0, win: 2, recs: [], paused: false, ended: false, pos: 0, item: null };
  var WINS = [2, 5, 10, 60, 180], WINL = ['-2 s', '-5 s', '-10 s', '-1 min', '-3 min'];
  (function seedRecs() {
    [['2026-10-18  13:55:24', 44, 6, 61], ['2026-10-18  14:01:15', 31, 40, 43], ['2026-10-20  12:09:33', 26, 55, 36]].forEach(function (r) { GAL.recs.push({ name: r[0], dur: r[1], start: r[2], mb: r[3], thumb: null, want: r[2] + 2 }); });
  })();
  function galItems() { return GAL.recs.map(function (r) { return { kind: 'rec', r: r }; }).concat([{ kind: 'live' }, { kind: 'stats' }]); }
  function galOpen() {
    sc.setTransform(1, 0, 0, 1, 0, 0); sc.clearRect(0, 0, snap.width, snap.height); sc.drawImage(osd, 0, 0);
    GAL.mode = 'strip'; GAL.sel = GAL.recs.length; GAL.scroll = GAL.sel; GAL.k = 0; GAL.play = 0; GAL.dlg = 0;
  }
  function galKey(k) {
    GAL.uiKeyAt = now;
    var items = galItems(), it = items[GAL.sel], liveI = GAL.recs.length;
    if (GAL.mode === 'closing') return;
    if (GAL.mode === 'confirm') {
      if (k === 'left') GAL.lit = 0; else if (k === 'right') GAL.lit = 1;
      else if (k === 'ok') { if (GAL.lit === 1) { GAL.recs.splice(GAL.sel, 1); GAL.gap = 1; GAL.gapFrom = GAL.sel; } GAL.mode = 'strip'; }
      else GAL.mode = 'strip';
      return;
    }
    if (GAL.mode === 'playing') {
      var r = GAL.item;
      if (k === 'left') { GAL.pos = Math.max(0, GAL.pos - 5); if (GAL.ended) { GAL.ended = false; GAL.paused = false; } seekPlay(); }
      else if (k === 'right' && !GAL.ended) { GAL.pos = Math.min(r.dur - 0.5, GAL.pos + 5); seekPlay(); }
      else if (k === 'ok') { if (GAL.ended) { GAL.pos = 0; GAL.ended = false; GAL.paused = false; seekPlay(); } else GAL.paused = !GAL.paused; }
      else if (k === 'back') { GAL.mode = 'strip'; vPlay.pause(); }
      return;
    }
    if (GAL.mode === 'stats') {
      if (k === 'up') GAL.win = Math.max(0, GAL.win - 1); else if (k === 'down') GAL.win = Math.min(4, GAL.win + 1);
      else if (k === 'back') GAL.mode = 'strip';
      return;
    }
    if (k === 'left') GAL.sel = Math.max(0, GAL.sel - 1);
    else if (k === 'right') GAL.sel = Math.min(items.length - 1, GAL.sel + 1);
    else if (k === 'back' || (k === 'ok' && it.kind === 'live')) { GAL.sel = liveI; GAL.mode = 'closing'; }
    else if (k === 'ok' && it.kind === 'stats') GAL.mode = 'stats';
    else if (k === 'ok' && it.kind === 'rec') { GAL.mode = 'playing'; GAL.item = it.r; GAL.pos = 0; GAL.paused = false; GAL.ended = false; seekPlay(); }
    else if (k === 'down' && it.kind === 'rec') { GAL.mode = 'confirm'; GAL.lit = 0; }
  }
  function seekPlay() { try { vPlay.currentTime = GAL.item.start + GAL.pos; } catch (e) {} if (!GAL.paused) vPlay.play().catch(function () {}); }
  var thumbBusy = false;
  function thumbs() {
    if (thumbBusy || !ready(vPlay) || GAL.mode === 'playing') return;
    var r = GAL.recs.filter(function (x) { return !x.thumb && x.want != null; })[0];
    if (!r) return;
    thumbBusy = true;
    var done = function () {
      vPlay.removeEventListener('seeked', done);
      var th = document.createElement('canvas'); th.width = 384; th.height = 216; th.getContext('2d').drawImage(vPlay, 0, 0, 384, 216); r.thumb = th; thumbBusy = false;
    };
    vPlay.addEventListener('seeked', done); vPlay.currentTime = r.want;
  }
  function drawVideo(c, v, x, y, w, h, live) {
    if (!ready(v)) { fill(c, x, y, w, h, mul(T.ground, 0.55), 1); return; }
    c.save();
    if (live) {
      var f = [];
      var ev = parseFloat(S.ev); if (ev) f.push('brightness(' + (1 + ev * 0.35) + ')');
      if (S.sat !== 'Auto') f.push('saturate(' + (0.4 + parseInt(S.sat, 10) * 0.12) + ')');
      if (S.con !== 'Auto') f.push('contrast(' + (0.7 + parseInt(S.con, 10) * 0.06) + ')');
      if (S.scene === 'Standard') f.push('saturate(0.92)');
      if (f.length) c.filter = f.join(' ');
      if (S.rotate === '180') { c.translate(x + w / 2, y + h / 2); c.rotate(Math.PI); c.translate(-(x + w / 2), -(y + h / 2)); }
    }
    c.drawImage(v, x, y, w, h); c.restore();
  }
  function galleryDraw(c, dt, pr) {
    var items = galItems(), n = items.length, liveI = GAL.recs.length;
    GAL.k = follow(GAL.k, GAL.mode === 'closing' ? 0 : 1, 0.09, dt);
    GAL.scroll = follow(GAL.scroll, GAL.sel, 0.07, dt);
    GAL.play = follow(GAL.play, (GAL.mode === 'playing' || GAL.mode === 'stats') ? 1 : 0, 0.1, dt);
    GAL.dlg = follow(GAL.dlg, GAL.mode === 'confirm' ? 1 : 0, 0.05, dt);
    GAL.gap = follow(GAL.gap, 0, 0.07, dt);
    if (GAL.mode === 'closing' && GAL.k === 0) { GAL.mode = 'off'; return false; }
    var k = GAL.k, pt = GAL.play, u = H / 1080;
    var stripA = k * (1 - pt), statsZoom = items[GAL.sel] && items[GAL.sel].kind === 'stats' && pt > 0.003;
    var wordsA = clamp((k - 0.5) * 2, 0, 1) * (1 - pt) * (statsZoom ? 0 : 1);
    fill(c, 0, 0, W, H, T.ground, Math.min(1, 1.4 * k));
    var tw0 = 0.6 * W, th0 = 0.6 * H, pitch = 0.66 * W, cyT = 0.42 * H;
    var rectOf = function (i) { var sh = i >= GAL.gapFrom ? GAL.gap : 0; return { x: W / 2 + (i - GAL.scroll + sh) * pitch - tw0 / 2, y: cyT - th0 / 2, w: tw0, h: th0 }; };
    var lerpR = function (a, b, t) { return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, w: a.w + (b.w - a.w) * t, h: a.h + (b.h - a.h) * t }; };
    var full = { x: 0, y: 0, w: W, h: H };
    var order = []; for (var i = 0; i < n; i++) if (i !== GAL.sel) order.push(i); order.push(GAL.sel);
    order.forEach(function (i) {
      var it = items[i], r = rectOf(i);
      if (r.x > W || r.x + r.w < 0) { if (!(i === GAL.sel && pt > 0)) return; }
      var dist = Math.min(1, Math.abs(i - GAL.scroll)), a = stripA * (1 - 0.45 * dist), zooming = i === GAL.sel && pt > 0.003;
      if (it.kind === 'live') {
        var lr = lerpR(pr, r, k);
        c.save(); c.beginPath(); c.rect(lr.x, lr.y, lr.w, lr.h); c.clip();
        if (L.vs !== 'BACKGROUND' && L.everConn) drawVideo(c, vFlight, lr.x, lr.y, lr.w, lr.h, true); else fill(c, lr.x, lr.y, lr.w, lr.h, mul(T.ground, 0.55), 1);
        c.setTransform(K, 0, 0, K, 0, 0);
        var sx = lr.w / pr.w;
        c.drawImage(snap, 0, 0, snap.width, snap.height, lr.x - pr.x * sx, lr.y - pr.y * sx, W * sx, H * sx);
        c.restore();
        if (L.everConn && stripA > 0.003) pill(c, L.frames ? 'LIVE' : 'LAST FRAME', lr.x + 8 * u, lr.y + 8 * u, 22 * u, L.frames ? T.accent : T.quiet, 0.95, T.ground, stripA);
        if (i === GAL.sel && pt <= 0.003) ring(c, lr.x, lr.y, lr.w, lr.h, 4 * u, T.accent, k);
      } else if (it.kind === 'rec') {
        var rr2 = zooming ? lerpR(r, full, pt) : r, aa = zooming ? 1 : a;
        fill(c, rr2.x, rr2.y, rr2.w, rr2.h, zooming ? BLACK : mul(T.ground, 0.55), aa);
        c.globalAlpha = aa;
        if (zooming && GAL.mode === 'playing' && ready(vPlay)) drawVideo(c, vPlay, rr2.x, rr2.y, rr2.w, rr2.h);
        else if (it.r.thumb) c.drawImage(it.r.thumb, rr2.x, rr2.y, rr2.w, rr2.h);
        else stext(c, 'NO PREVIEW YET', rr2.x + rr2.w / 2, rr2.y + rr2.h / 2 + 5 * u, 30.8 * u * rr2.w / tw0, 1, T.quiet, aa);
        c.globalAlpha = 1;
        if (!zooming) {
          var dl = mss(it.r.dur), fs = 22 * u, pw = stw(dl, fs) + fs, ph = 1.7 * fs;
          fill(c, r.x + r.w - 8 * u - pw, r.y + r.h - 8 * u - ph, pw, ph, T.ground, 0.8 * a);
          stext(c, dl, r.x + r.w - 8 * u - pw / 2, r.y + r.h - 8 * u - 0.55 * fs, fs, 1, T.text, a);
          if (i === GAL.sel) ring(c, r.x, r.y, r.w, r.h, 4 * u, T.accent, a);
        }
      } else {
        var sr = zooming ? lerpR(r, full, pt) : r;
        statsDraw(c, sr, zooming ? 1 : a, !zooming || pt < 0.999);
        if (i === GAL.sel && !zooming) ring(c, r.x, r.y, r.w, r.h, 4 * u, T.accent, a);
      }
    });
    // words
    if (wordsA > 0.003) {
      stext(c, 'GALLERY', 48 * u, 70 * u, 34 * u, 0, T.text, wordsA);
      var it2 = items[GAL.sel], l1, l2;
      if (it2.kind === 'live') { l1 = 'LIVE'; l2 = L.frames ? 'Receiving video' : L.everConn ? 'Video stopped' : 'No video yet'; }
      else if (it2.kind === 'stats') { l1 = 'STATS'; l2 = 'Latency, frame pacing and link, live'; }
      else { l1 = it2.r.name; l2 = mss(it2.r.dur) + '  -  ' + it2.r.mb + ' MB'; }
      stext(c, l1, W / 2, 0.82 * H, 40 * u, 1, T.text, wordsA);
      stext(c, l2, W / 2, 0.82 * H + 40 * u, 28 * u, 1, T.quiet, wordsA);
      if (GAL.sel > 0) stext(c, '<', 0.025 * W, cyT + 14 * u, 52 * u, 0, T.text, wordsA);
      if (GAL.sel < n - 1) stext(c, '>', 0.975 * W, cyT + 14 * u, 52 * u, 2, T.text, wordsA);
    }
    // delete dialog
    if (GAL.dlg > 0.003 && items[GAL.sel].kind === 'rec') {
      var dA = GAL.dlg, bw = 0.15 * W, bh = 66 * u, gx = 0.02 * W, pd = 0.03 * W, pw2 = 2 * bw + gx + 2 * pd, ph2 = bh + 1.6 * pd;
      fill(c, 0, 0, W, H, BLACK, 0.6 * dA);
      var px = (W - pw2) / 2, py = (H - ph2) / 2;
      fill(c, px, py, pw2, ph2, mul(T.ground, 0.45), 0.98 * dA); ring(c, px, py, pw2, ph2, 2 * u, T.quiet, dA);
      var by = py + (ph2 - bh) / 2;
      [['CANCEL', W / 2 - gx / 2 - bw, 0], ['DELETE', W / 2 + gx / 2, 1]].forEach(function (b) {
        var lit = GAL.lit === b[2], col = lit ? (b[2] ? DANGER : T.accent) : mul(T.ground, 0.45), rc = lit ? col : T.quiet;
        fill(c, b[1], by, bw, bh, col, dA); ring(c, b[1], by, bw, bh, 2 * u, rc, dA);
        stext(c, b[0], b[1] + bw / 2, by + bh / 2 + 11 * u, 30 * u, 1, lit ? T.ground : T.text, dA);
      });
    }
    // playback overlay
    if (GAL.mode === 'playing' || (pt > 0.5 && items[GAL.sel].kind === 'rec')) {
      var hideUi = GAL.mode === 'playing' && !GAL.paused && !GAL.ended ? clamp(1 - (now - (GAL.uiKeyAt || 0) - 3) / 0.3, 0, 1) : 1;
      var oa = Math.max(0, (pt - 0.5) * 2) * hideUi, r3 = GAL.item || items[GAL.sel].r;
      if (r3 && GAL.mode === 'playing') {
        if (!GAL.paused && !GAL.ended) { GAL.pos += dt; if (GAL.pos >= r3.dur) { GAL.pos = r3.dur; GAL.ended = true; GAL.paused = true; } }
        if (GAL.paused) vPlay.pause(); else if (vPlay.paused) vPlay.play().catch(function () {});
      }
      if (r3 && oa > 0.003) {
        pill(c, r3.name, 48 * u, 36 * u, 26 * u, T.ground, 0.7, T.text, oa);
        fill(c, 36 * u, H - 130 * u, W - 72 * u, 80 * u, T.ground, 0.7 * oa);
        var byy = H - 90 * u, bx = 138 * u, bww = W - 276 * u;
        fill(c, bx, byy - 3 * u, bww, 6 * u, T.quiet, 0.5 * oa);
        fill(c, bx, byy - 3 * u, bww * clamp(GAL.pos / r3.dur, 0, 1), 6 * u, T.accent, oa);
        stext(c, mss(GAL.pos), bx - 14 * u, byy + 9 * u, 26 * u, 2, T.text, oa);
        stext(c, mss(r3.dur), bx + bww + 14 * u, byy + 9 * u, 26 * u, 0, T.quiet, oa);
        stext(c, 'LEFT / RIGHT  SEEK 5 S        ENTER  PAUSE        BACK  GALLERY', W / 2, byy - 56 * u, 24 * u, 1, T.quiet, oa);
        if (GAL.ended) stext(c, 'ENDED - ENTER TO REPLAY', W / 2, H / 2, 40 * u, 1, T.text, oa);
        else if (GAL.paused) stext(c, 'PAUSED', W / 2, H / 2, 40 * u, 1, T.text, oa);
      }
    }
    return true;
  }
  function pill(c, s, x, y, font, bg, bgA, fg, a) {
    var pd = 0.5 * font, w = stw(s, font) + 2 * pd, h = 1.7 * font;
    fill(c, x, y, w, h, bg, bgA * a); stext(c, s, x + pd, y + h / 2 + 0.36 * font, font, 0, fg, a);
  }

  // ---------------------------------------------------------------- stats screen
  var VIOLET = [0.78, 0.58, 1], MAGENTA = [1, 0.42, 0.86], SLIME = [0.7, 1, 0], SAMBER = [0.95, 0.79, 0.3], SRED = [1, 0.3, 0.3];
  function shade(base, v, lo, hi) {
    var g = (base[0] + base[1] + base[2]) / 3, t = -(2 * clamp((v - lo) / (hi - lo), 0, 1) - 1);
    return base.map(function (b) { var x = clamp(g + (b - g) * 1.25, 0, 1); return t >= 0 ? x + (1 - x) * 0.32 * t : x * (1 + 0.42 * t); });
  }
  function screenHz() {
    var m = /(\d+)x(\d+) @ (\d+)/.exec(S.screenMode);
    return m ? { h: +m[2], hz: +m[3] } : { h: 1080, hz: 200 };
  }
  function statsDraw(c, R, A, cheap) {
    var m = R.w / 680, fs = m * 0.8;
    var Bx = function (x) { return R.x + x * m; }, By = function (y) { return R.y + y * m; };
    var t = function (s, x, y, size, col, align, al) { return stext(c, s, Bx(x), By(y), size * fs, align || 0, col, (al == null ? 1 : al) * A) / m; };
    var tw0 = function (s, size) { return stw(s, size * fs) / m; };
    var bf = function (x, y, w, h, col, al) { fill(c, Bx(x), By(y), w * m, h * m, col, al * A); };
    var dash = function (x0, y0, x1, y1, col, al, lw, d) { c.save(); c.setLineDash(d ? [d[0] * m, d[1] * m] : []); c.globalAlpha = al * A; c.strokeStyle = rgb(col); c.lineWidth = lw * m * 0.6; c.beginPath(); c.moveTo(Bx(x0), By(y0)); c.lineTo(Bx(x1), By(y1)); c.stroke(); c.restore(); };
    c.save(); c.beginPath(); c.rect(R.x, R.y, R.w, R.h); c.clip();
    bf(0, 0, 680, 383, mul(T.ground, 0.45), 1);
    var win = WINS[GAL.win], cols = 240, col = win / cols, tEnd = now, live = L.frames, vt = vFlight.currentTime || 0;
    var tl = tel(vt), have = function (tc) { return L.firstFrameAt > 0 && tc > L.firstFrameAt && inFrames(tc); };
    var telAt = function (back) { return tel(((vt - back) % 82.9 + 82.9) % 82.9); };
    var totals = [], stages = [], tels = [], ok = [];
    for (var i = 0; i < cols; i++) {
      var back = (cols - 1 - i) * col, tc = tEnd - back, h = have(tc);
      ok.push(h); tels.push(h ? telAt(back) : null);
      if (h) { var sm = sample(tc, 0); totals.push(sm.total); stages.push(sm); } else { totals.push(0); stages.push(null); }
    }
    var valid = totals.filter(function (v) { return v > 0; }).slice().sort(function (a, b) { return a - b; });
    var p50 = valid.length ? valid[Math.floor(valid.length * 0.5)] : 0, p99 = valid.length ? valid[Math.min(valid.length - 1, Math.floor(valid.length * 0.99))] : 0;
    if (valid.length) { LAT.p50 = p50; LAT.p99 = p99; }
    // header
    [[42, 'SHOWN/DECODED'], [130, 'BITRATE'], [190, 'SMOOTH'], [262, 'MCS / SNR'], [338, 'CHANNEL']].forEach(function (h) { t(h[1], h[0], 16, 11, T.quiet); });
    var rate = live ? videoRate(tl) : 0;
    var x1 = t(live ? '100/100' : '0/0', 42, 40, 16, T.text); t('fps', 42 + x1 + 3, 40, 10, T.quiet);
    var x2 = t(rate.toFixed(1), 130, 40, 16, T.text); t('Mbps', 130 + x2 + 3, 40, 10, T.quiet);
    bf(190, 28, 9, 9, live ? SLIME : T.quiet, 1); t(live ? '99.4%' : '--', 204, 40, 16, T.text);
    t(live && tl ? (tl.mcs - 2) + ' / ' + tl.snr : '--', 262, 40, 16, T.text);
    var x5 = t(live ? '' + FREQ : '--', 338, 40, 16, T.text);
    if (live) {
      var cx = 338 + x5 + 4; cx += t(LINK.bw + ' MHz', cx, 40, 11, T.quiet);
      t('RF FRAME', cx + 8, 16, 11, T.quiet); t(rfFrameMs(LINK.bw).toFixed(2) + ' ms', cx + 8, 40, 11, T.text);
    }
    var lu = live ? Math.round(rate / linkCap(tl) * 100) : 0;
    var x6 = t('LINK USE', 42, 62, 10, T.quiet); t(lu + '%', 42 + x6 + 3, 62, 10, T.text);
    var lostV = '0', x7 = t('LOST', 104, 62, 10, T.quiet); var x7v = t(lostV, 104 + x7 + 3, 62, 10, T.text);
    var rx = 104 + x7 + 3 + x7v + 16, resent = live ? '' + Math.round(4 + 6 * noise(Math.floor(now / 2))) : '--';
    var x8 = t('RESENT', rx, 62, 10, T.quiet); t(resent, rx + x8 + 3, 62, 10, T.text);
    var vrx = Math.round(VRX_TEMP()) + ' C', vtx = live ? Math.round(VTX_TEMP()) + ' C' : '--';
    var wv = tw0(vrx, 10), wl = tw0('VRX TEMP', 10), xs = 418 - wv - 3 - wl;
    t('VRX TEMP', xs, 62, 10, T.quiet); t(vrx, xs + wl + 3, 62, 10, T.text);
    var wv2 = tw0(vtx, 10), wl2 = tw0('VTX TEMP', 10), xs2 = xs - 16 - wv2 - 3 - wl2;
    t('VTX TEMP', xs2, 62, 10, T.quiet); t(vtx, xs2 + wl2 + 3, 62, 10, T.text);
    // frame spacing, one line over the chart
    var fx = 42;
    fx += t('frame spacing', fx, 78, 9, T.quiet) + 7;
    if (live) {
      fx += t('on target 99.4%', fx, 78, 9, T.text) + 7;
      t('early 0.1%   late 0.4%   a frame late 0.1%   later 0.0%   at 100 fps', fx, 78, 9, T.quiet);
    } else t('n/a (needs vsync)', fx, 78, 9, T.quiet);
    // latency chart
    var top = 84, hgt = 128, base = 212, ymax = Math.max(40, Math.min(100, Math.ceil(p99 * 1.3 / 10) * 10));
    var Yv = function (v) { return base - clamp(v / ymax, 0, 1) * hgt; };
    for (var g = 5; g <= ymax; g += 5) dash(42, Yv(g), 418, Yv(g), T.data, g % 10 ? 0.12 : 0.25, g % 10 ? 0.8 : 1, [3, 5]);
    for (var g2 = 0; g2 <= ymax; g2 += 5) t('' + g2, 37, Yv(g2) + 3.2, 8.5, T.quiet, 2);
    t('ms', 37, 78, 11, T.quiet, 2); t('I', 37, 225, 11, T.quiet, 2);
    var kw = tw0('keyframe', 11);
    t('keyframe', 418, 98, 11, T.quiet, 2); bf(418 - kw - 8.5, 91, 1, 7, SAMBER, 0.7); bf(418 - kw - 11, 87.5, 6, 4, SAMBER, 1);
    var sx = 418 - kw - 20, skw = tw0('skipped', 11);
    t('skipped', sx, 98, 11, T.quiet, 2); bf(sx - skw - 6, 90, 1.6, 8, SRED, 1);
    var rsx = sx - skw - 20, rsw = tw0('resent', 11);
    t('resent', rsx, 98, 11, T.quiet, 2); bf(rsx - rsw - 6, 90, 1.6, 8, MAGENTA, 1);
    var cw = 376 / 240, cxOf = function (i) { return 42 + (i + 0.5) * cw; };
    var acc = stages.map(function () { return 0; });
    [['read', pale(STAGE.enc)], ['enc', STAGE.enc], ['rf', STAGE.rf], ['dec', STAGE.dec], ['disp', STAGE.disp]].forEach(function (pp) {
      c.beginPath();
      var pts = [];
      for (var i2 = 0; i2 < cols; i2++) { var s2 = stages[i2]; var lo = acc[i2], hi = lo + (s2 ? s2[pp[0]] : 0); pts.push([cxOf(i2), lo, hi]); acc[i2] = hi; }
      pts.forEach(function (p, j) { var X = Bx(p[0]), Yh = By(Yv(p[2])); if (j) c.lineTo(X, Yh); else c.moveTo(X, Yh); });
      for (var j2 = pts.length - 1; j2 >= 0; j2--) c.lineTo(Bx(pts[j2][0]), By(Yv(pts[j2][1])));
      c.closePath(); c.globalAlpha = 0.8 * A; c.fillStyle = rgb(pp[1]); c.fill(); c.globalAlpha = 1;
    });
    c.beginPath(); totals.forEach(function (v, j) { var X = Bx(cxOf(j)), Yh = By(Yv(v)); if (j) c.lineTo(X, Yh); else c.moveTo(X, Yh); });
    c.globalAlpha = 0.9 * A; c.strokeStyle = '#fff'; c.lineWidth = 1.2 * m * 0.6; c.stroke(); c.globalAlpha = 1;
    // resends: magenta ticks up from the chart foot
    for (var i4 = 0; i4 < cols; i4++) if (ok[i4] && noise(Math.floor((tEnd - (cols - 1 - i4) * col) * 9) + 77) > 0.93) bf(cxOf(i4) - 0.8, base - 6, 1.6, 6, MAGENTA, 0.9);
    [[p50, T.data, 'p50'], [p99, SAMBER, 'p99']].forEach(function (pl) {
      dash(42, Yv(pl[0]), 418, Yv(pl[0]), pl[1], 1, 1.2, [7, 4]);
      t(pl[2], 422, Yv(pl[0]) + 4, 11, pl[1]);
    });
    // link lane
    var lb = 300, lh = 46, vrs = [], lcs = [], dss = [];
    for (var i3 = 0; i3 < cols; i3++) {
      var tt = tels[i3], bwc = bwAt(tEnd - (cols - 1 - i3) * col);
      vrs.push(tt ? videoRate(tt) : 0); lcs.push(tt ? linkCap(tt, bwc) : 0); dss.push(tt && DIST.zeroed ? tt.dist : null);
    }
    var lmax = Math.ceil(Math.max(40, Math.max.apply(null, lcs), Math.max.apply(null, vrs), LINK.bw) / 20) * 20;
    var step = lmax <= 40.5 ? 10 : lmax <= 80.5 ? 20 : 40, Yl = function (v) { return lb - Math.min(v, lmax) / lmax * lh; };
    for (var g3 = step; g3 <= lmax; g3 += step) dash(42, Yl(g3), 418, Yl(g3), T.quiet, g3 % 20 ? 0.2 : 0.4, g3 % 20 ? 0.8 : 1, [3, 5]);
    for (var g4 = 0; g4 <= lmax; g4 += 2 * step) t('' + g4, 37, Yl(g4) + 3.2, 9, T.quiet, 2);
    t('Mbps', 37, 247, 11, T.quiet, 2);
    var kx = 42;
    bf(kx, 239, 10, 8, T.data, 0.55); kx += 14 + t('video rate', kx + 14, 247, 11, T.text) + 4 + 14;
    bf(kx, 242.5, 10, 1.6, WHITE, 1); kx += 14 + t('link capacity', kx + 14, 247, 11, T.text) + 4 + 14;
    bf(kx + 4, 238, 2.4, 9, SRED, 1); kx += 14 + t('lost pictures', kx + 14, 247, 11, T.text) + 4 + 14;
    bf(kx, 242.5, 10, 1.6, VIOLET, 1); t('distance', kx + 14, 247, 11, T.text);
    c.beginPath(); c.moveTo(Bx(42), By(lb)); vrs.forEach(function (v, j) { c.lineTo(Bx(cxOf(j)), By(Yl(v))); }); c.lineTo(Bx(418), By(lb)); c.closePath();
    c.globalAlpha = 0.5 * A; c.fillStyle = rgb(T.data); c.fill();
    c.beginPath(); lcs.forEach(function (v, j) { var X = Bx(cxOf(j)), Yh = By(Yl(v)); if (j) c.lineTo(X, Yh); else c.moveTo(X, Yh); }); c.globalAlpha = 0.7 * A; c.strokeStyle = '#fff'; c.lineWidth = m * 0.6; c.stroke(); c.globalAlpha = 1;
    var dmaxRaw = Math.max.apply(null, dss.map(function (d) { return d || 0; })), dmax = 10;
    [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000].some(function (d) { dmax = d; return d >= dmaxRaw; });
    var Yd2 = function (d) { return lb - clamp(d / dmax, 0, 1) * lh; };
    c.beginPath(); var pen = false;
    dss.forEach(function (d, j) { if (d == null) { pen = false; return; } var X = Bx(cxOf(j)), Yh = By(Yd2(d)); if (pen) c.lineTo(X, Yh); else c.moveTo(X, Yh); pen = true; });
    c.globalAlpha = 0.95 * A; c.strokeStyle = rgb(VIOLET); c.lineWidth = 1.2 * m * 0.6; c.stroke(); c.globalAlpha = 1;
    t(dmax + ' m', 416, 263, 9, VIOLET, 2, 0.85); t('' + dmax / 2, 416, 280.2, 9, VIOLET, 2, 0.85);
    if (live) {
      var ends = [[lcs[cols - 1].toFixed(1) + ' Mb', Yl(lcs[cols - 1]) + 4, WHITE], [vrs[cols - 1].toFixed(1) + ' Mb', Yl(vrs[cols - 1]) + 4, T.data]];
      if (dss[cols - 1] != null) ends.push([Math.round(dss[cols - 1]) + ' m', Yd2(dss[cols - 1]) + 4, VIOLET]);
      ends.sort(function (a, b) { return a[1] - b[1]; });
      for (var e = 1; e < ends.length; e++) if (ends[e][1] - ends[e - 1][1] < 12) ends[e][1] = ends[e - 1][1] + 12;
      var over = ends[ends.length - 1][1] - 304; if (over > 0) ends.forEach(function (en) { en[1] -= over; });
      ends.forEach(function (en) { t(en[0], 422, en[1], 11, en[2]); });
    }
    // link settings rows: MCS, channel, bandwidth, air power
    var rowsDef = [
      { y: 306, base: STAGE.rf, val: function (j) { return tels[j] ? tels[j].mcs : null; }, lo: 0, hi: 13, lab: function (v) { return 'MCS ' + (v - 2); }, num: function (v) { return '' + (v - 2); } },
      { y: 319, base: STAGE.enc, val: function (j) { return ok[j] ? FREQ : null; }, lo: 5650, hi: 5900, lab: function (v) { return '' + v; }, num: function (v) { return '' + v; } },
      { y: 332, base: STAGE.dec, val: function (j) { return ok[j] ? bwAt(tEnd - (cols - 1 - j) * col) : null; }, lo: Math.log(5), hi: Math.log(40), map: Math.log, lab: function (v) { return v + ' MHz'; }, num: function (v) { return '' + v; } },
      { y: 345, base: STAGE.disp, val: function (j) { return tels[j] ? airDbm(tels[j]) : null; }, lo: 13, hi: 26, lab: function (v) { return mwFromDbm(v) + ' mW'; }, num: function (v) { return '' + mwFromDbm(v); } }
    ];
    rowsDef.forEach(function (rd) {
      var runs = [], cur = null;
      for (var j = 0; j < cols; j++) { var v = rd.val(j); if (v == null) { cur = null; continue; } if (!cur || cur.v !== v) { cur = { v: v, a: j, b: j }; runs.push(cur); } else cur.b = j; }
      runs.forEach(function (rn, k) {
        var xa = 42 + rn.a * cw, xb = 42 + (rn.b + 1) * cw - 0.8, w = xb - xa;
        var col2 = shade(rd.base, rd.map ? rd.map(rn.v) : rn.v, rd.lo, rd.hi);
        bf(xa, rd.y, w, 11, col2, 1); bf(xa, rd.y, w, 1.4, col2.map(function (q) { return 0.45 + 0.55 * q; }), 0.75);
        var luma = 0.3 * col2[0] + 0.59 * col2[1] + 0.11 * col2[2], ink = luma > 0.55 ? [0.06, 0.07, 0.1] : WHITE;
        var full = rd.lab(rn.v), short = rd.num(rn.v);
        if (tw0(full, 9) + 4 <= w) t(full, xa + 2, rd.y + 8.5, 9, ink);
        else if (tw0(short, 9) + 3 <= w) t(short, xa + 1.5, rd.y + 8.5, 9, ink);
        else if (k === runs.length - 1) t(full, 422, rd.y + 8.5, 9, T.text);
      });
    });
    t(WINL[GAL.win], 42, 370, 11, T.quiet); t('now', 418, 370, 11, T.quiet, 2);
    // PiP
    var pipX = Bx(464), pipY = By(10), pipW = 208 * m, pipH = 117 * m;
    if (L.everConn) drawVideo(c, vFlight, pipX, pipY, pipW, pipH, true); else fill(c, pipX, pipY, pipW, pipH, mul(T.ground, 0.55), 1);
    if (A < 1) fill(c, pipX, pipY, pipW, pipH, mul(T.ground, 0.45), 1 - A);
    ring(c, pipX, pipY, pipW, pipH, 3 * m, T.accent, A);
    if (L.everConn) {
      pill(c, L.frames ? 'LIVE' : 'LAST FRAME', pipX + 4 * m, pipY + 4 * m, 8 * m, L.frames ? T.accent : T.quiet, 0.95, T.ground, A);
      var mtxt = S.videoMode.indexOf('1080') === 0 ? '1080p' : S.videoMode.indexOf('864') === 0 ? '864p' : '720p', mw = stw(mtxt, 8 * m) + 8 * m;
      pill(c, mtxt, pipX + pipW - 4 * m - mw, pipY + 4 * m, 8 * m, T.quiet, 0.95, T.ground, A);
    }
    // the screen: its mode and the refresh it really runs at
    var scr = screenHz(), sxp = 464;
    sxp += t('SCREEN MODE', sxp, 140.5, 10, T.quiet) + 3;
    sxp += t(scr.h + 'p@' + scr.hz, sxp, 140.5, 10, T.text) + 10;
    sxp += t('CURRENT', sxp, 140.5, 10, T.quiet) + 3;
    t((scr.hz - 0.1 + 0.15 * noise(Math.floor(now * 2))).toFixed(1) + ' Hz', sxp, 140.5, 10, T.text);
    // latency distribution
    t('latency distribution', 464, 152, 11, T.quiet);
    var bins = []; for (var bb = 0; bb < 30; bb++) bins.push(0);
    valid.forEach(function (v) { bins[Math.min(29, Math.floor(v / 2))]++; });
    var bmax = Math.max.apply(null, bins) || 1;
    bins.forEach(function (v, j) { if (v) bf(464 + j * 6.93, 212 - 56 * v / bmax, 5.93, 56 * v / bmax, j * 2 <= p99 ? T.data : SAMBER, 0.65); });
    bf(464, 212, 208, 0.8, T.quiet, 0.6);
    for (var lt = 0; lt <= 60; lt += 5) { bf(464 + lt / 60 * 208, 212, 1, lt % 20 ? 3 : 5, T.quiet, 0.6); t('' + lt, 464 + lt / 60 * 208, 225, 9.5, T.quiet, lt === 0 ? 0 : lt === 60 ? 2 : 1); }
    [[p50, T.data], [p99, SAMBER]].forEach(function (pl) { if (pl[0]) { var X = 464 + Math.min(60, pl[0]) / 60 * 208; dash(X, 156, X, 212, pl[1], 1, 1.2, [4, 3]); } });
    // slice timelines
    t('slices timelines', 464, 240, 11, T.quiet); t('| vblank  : mid-screen', 674, 240, 8, T.quiet, 2);
    if (live) {
      var scale = 200 / 30;
      [0, 1].forEach(function (r) {
        var y = 244 + r * 18, bh = 14, x = 474 + r * 4.3 * scale, st = sample(now - 0.5, r * 5);
        t('' + (r + 1), 464, y + bh / 2 + 3, 8, T.quiet);
        [['read', pale(STAGE.enc)], ['enc', STAGE.enc], ['rf', STAGE.rf], ['dec', STAGE.dec], ['disp', STAGE.disp]].forEach(function (pp) {
          var w = st[pp[0]] * scale; bf(x, y, w, bh, pp[1], 1);
          var s3 = st[pp[0]].toFixed(1); if (tw0(s3, 8) + 1 <= w) t(s3, x + w / 2, y + bh / 2 + 3, 8, mul(T.ground, 0.45), 1);
          x += w; bf(x - 0.3, y, 0.6, bh, mul(T.ground, 0.45), 1);
        });
      });
      bf(474, 282, 200, 0.5, T.quiet, 0.6);
      for (var tk = 0; tk <= 30; tk += 5) { bf(474 + tk * scale, 282, 0.6, tk % 10 ? 2 : 3, T.quiet, 0.8); if (tk % 10 === 0) t('' + tk, 474 + tk * scale, 290, 7.5, T.quiet, tk ? 1 : 0); }
      t('ms', 674, 290, 7.5, T.quiet, 2);
      t('slice 1', 572, 306, 7.5, T.text, 2); t('slice 2', 652, 306, 7.5, T.text, 2);
      var s1 = sample(now - 0.5, 0), s2b = sample(now - 0.5, 5);
      [['Exp', 'exp', STAGE.exp], ['Read', 'read', pale(STAGE.enc)], ['Enc', 'enc', STAGE.enc], ['RF', 'rf', STAGE.rf], ['Dec', 'dec', STAGE.dec], ['Disp', 'disp', STAGE.disp]].forEach(function (rw2, j) {
        var yb = 314 + j * 7;
        bf(464, yb - 5, 5, 5, rw2[2], 1); t(rw2[0], 472, yb, 7.5, T.text);
        t(rw2[1] === 'exp' ? '--' : s1[rw2[1]].toFixed(1), 572, yb, 7.5, T.text, 2); t(rw2[1] === 'exp' ? '--' : s2b[rw2[1]].toFixed(1), 652, yb, 7.5, T.text, 2);
      });
      bf(464, 353, 210, 0.5, T.quiet, 0.6);
      t('p50', 472, 360, 7.5, T.text); t(p50.toFixed(1), 572, 360, 7.5, T.text, 2); t((p50 + 3.6).toFixed(1), 652, 360, 7.5, T.text, 2);
      t('p99', 472, 367, 7.5, T.text); t(p99.toFixed(1), 572, 367, 7.5, T.text, 2); t((p99 + 3.4).toFixed(1), 652, 367, 7.5, T.text, 2);
    }
    c.restore();
  }
  function inFrames(tc) {
    for (var i = L.intervals.length - 1; i >= 0; i--) { var iv = L.intervals[i]; if (tc >= iv[0] && tc <= (iv[1] < 0 ? now : iv[1])) return true; }
    return false;
  }

  // ---------------------------------------------------------------- keys
  function key(k) {
    if (!started) start();
    if (k === 'rec') { recToggle(); return; }
    if (k === 'bind') {
      if (BIND.state === 'running') { BIND.state = 'none'; syncControls(); } else bindStart();
      return;
    }
    if (GAL.mode !== 'off') { galKey(k); return; }
    if (MENU.open) { menuKey(k); return; }
    if (k === 'ok') menuOpen();
    else if (k === 'back') galOpen();
  }

  // ---------------------------------------------------------------- per-frame state
  function update(dt) {
    var wasRadio = L.radio;
    if (L.power && now >= L.radioOkAt && L.bound) {
      if (!L.radio) { L.radio = true; L.linkAt = now; }
    } else if (L.radio) { L.radio = false; L.frames = false; }
    if (L.fwRestart && now < L.radioOkAt && L.radio) { L.radio = false; L.frames = false; }
    if (L.fwRestart && now >= L.radioOkAt) L.fwRestart = false;
    var fr = L.radio && now - L.linkAt > 1.0;
    if (fr && !L.frames) { L.intervals.push([now, -1]); if (L.firstFrameAt < 0) L.firstFrameAt = now; }
    if (!fr && L.frames && L.intervals.length) L.intervals[L.intervals.length - 1][1] = now;
    L.frames = fr;
    if (L.frames) L.lastFrameAt = now;
    if (L.radio) {
      L.dropStart = -1;
      if (!L.conn) { L.conn = true; L.connAt = now; L.reconnect = L.everConn; L.everConn = true; arrive.at = now; L.lostAt = -1; }
    } else if (L.conn) {
      if (L.dropStart < 0) L.dropStart = now;
      if (now - L.dropStart > 1.5) { L.conn = false; L.lostAt = now; }
    }
    // video
    if (L.frames) { if (vFlight.paused) vFlight.play().catch(function () {}); } else if (!vFlight.paused) vFlight.pause();
    var wantIdle = L.vs !== 'LIVE' && S.bgVideo === 'ON';
    if (wantIdle && vIdle.paused) vIdle.play().catch(function () {}); else if (!wantIdle && !vIdle.paused) vIdle.pause();
    if (L.vs === 'BACKGROUND' && L.frames && now - L.firstFrameAt > 0.8) { L.vs = 'TRANSITION'; L.warpAt = now; }
    if (L.vs === 'TRANSITION' && now - L.warpAt > 0.45) L.vs = 'LIVE';
    // telemetry
    var t = L.everConn && ready(vFlight) ? tel(vFlight.currentTime || 0) : null;
    if (t) {
      var st = t.armed ? 1 : 0;
      if (arm.state < 0) { arm.state = st; arm.to = st ? T.accent : REST; arm.from = arm.to; arm.wipeAt = -100; }
      else if (st !== arm.state) { arm.from = arm.state ? T.accent : REST; arm.to = st ? T.accent : REST; arm.state = st; arm.wipeAt = now; if (st) { arm.armedAt = now; DIST.zeroed = true; } }
      if (arm.to !== REST) arm.to = T.accent;
      var cell = cellOf(t);
      if (!t.armed && t.flight < 1) peakCell = cell; else peakCell = Math.max(peakCell, cell);
    }
    // menu motion
    MENU.wake = follow(MENU.wake, MENU.open ? 1 : 0, 0.09, dt);
    for (var s = 0; s < 2; s++) {
      MENU.liftF[s] = follow(MENU.liftF[s], MENU.open && MENU.stage === 0 ? (MENU.side === s ? 1 : -0.6) : 0, 0.08, dt);
      MENU.openF[s] = follow(MENU.openF[s], MENU.open && MENU.stage === 1 && MENU.side === s && !CH.open ? 1 : 0, 0.09, dt);
      lift[s] = MENU.liftF[s] * 0.06 * FH - Math.max(MENU.openF[s], s === 1 ? MENU.band : MENU.band) * 0.9 * FH;
    }
    MENU.band = follow(MENU.band, MENU.open && CH.open ? 1 : 0, 0.09, dt);
    if (MENU.trial && now > MENU.trial.until) { var tr = MENU.trial; MENU.trial = null; applySetting(tr.id, tr.back); MENU.trial = null; }
    if (MENU.open && CH.open && !L.radio) CH.open = false;
    // a VIDEO tab disappears when the link drops
    if (MENU.open && MENU.side === 1 && TABS[1][MENU.tab[1]] === 'VIDEO' && !L.radio) { MENU.tab[1] = 1; MENU.sel = firstSel(curRows()); MENU.edit = false; }
    // bind
    if (BIND.state === 'running' && L.pairing && L.power) { BIND.state = 'ok'; BIND.at = now; L.bound = true; L.pairing = false; L.radioOkAt = now + 0.8; syncControls(); }
    // auto power on
    if (!L.power && L.autoOnAt > 0 && now >= L.autoOnAt) { L.autoOnAt = -1; setPower(true); }
    if (CH.open) chanScanStep(dt);
    linkStep(t);
    dynStep(dt, t);
    thumbs();
    return t;
  }

  // ---------------------------------------------------------------- frame
  var last = 0, started = false, visible = true, t0 = 0;
  function frame(ts) {
    requestAnimationFrame(frame);
    if (!visible || !started) return;
    var tnow = ts / 1000; var dt = clamp(tnow - last, 0, 1 / 30); last = tnow; now = tnow - t0;
    resize();
    P.scale = picRect().p; P.ui = parseFloat(S.uiScale);
    var t = update(dt), pr = picRect();
    // video layer
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.setTransform(K, 0, 0, K, 0, 0);
    var galOn = GAL.mode !== 'off';
    if (!galOn) {
      if (L.vs !== 'BACKGROUND') drawVideo(ctx, vFlight, pr.x, pr.y, pr.w, pr.h, true);
      if (L.vs !== 'LIVE') {
        var warp = L.vs === 'TRANSITION' ? clamp((now - L.warpAt) / 0.45, 0, 1) : 0, t2 = warp * warp, z = 1 + 8 * t2, a = Math.max(0, 1 - 1.35 * t2);
        ctx.save(); ctx.globalAlpha = a; ctx.beginPath(); ctx.rect(pr.x, pr.y, pr.w, pr.h); ctx.clip();
        var src = S.bgVideo === 'ON' && ready(vIdle) ? vIdle : imgIdle;
        var zx = 1 + 8 * t2 * 1.35, zy = 1 + 8 * t2;
        try { ctx.drawImage(src, pr.x + pr.w / 2 - pr.w * zx / 2, pr.y + pr.h / 2 - pr.h * zy / 2, pr.w * zx, pr.h * zy); } catch (e) {}
        if (t2 > 0) { ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = a * 0.25 * t2; try { ctx.drawImage(src, pr.x + pr.w / 2 - pr.w * zx * 1.02 / 2, pr.y + pr.h / 2 - pr.h * zy / 2, pr.w * zx * 1.02, pr.h * zy); } catch (e2) {} }
        ctx.restore();
      }
    }
    // OSD layer
    oc.setTransform(1, 0, 0, 1, 0, 0); oc.clearRect(0, 0, osd.width, osd.height); oc.setTransform(K, 0, 0, K, 0, 0);
    oc.save(); oc.beginPath(); oc.rect(pr.x, pr.y, pr.w, pr.h); oc.clip();
    if (L.vs !== 'LIVE') idleScreen(oc, pr);
    var hudOn = L.everConn && arrive.at > 0 && !(MENU.wake > 0 && false);
    if (S.bfOsd === 'ON' && L.vs === 'LIVE' && !MENU.open) bfOsd(oc, t, pr);
    if (hudOn) {
      if (S.hudStyle === 'CANOPY') canopy(oc, t);
      else if (S.hudStyle.indexOf('ARENA') === 0) arena(oc, t, S.hudStyle === 'ARENA FULL');
    }
    if (L.vs === 'LIVE') edgeGlow(oc, t, dt, pr);
    clockStrip(oc, pr);
    // acquiring on a reconnect
    if (L.vs === 'LIVE' && L.conn && L.reconnect && !MENU.open) {
      var e = now - L.connAt, hold = 1.9;
      if (e < hold) {
        var lockAt = 1.0, lp = e > lockAt ? clamp((e - lockAt) / 0.9, 0, 1) : 0;
        var stage = !L.radio ? 'SEARCHING' : e < 0.35 ? 'LINK ' + FREQ + ' MHz' : e < 0.7 ? 'HANDSHAKE' : 'WAITING FOR KEYFRAME';
        sweepAng += dt * 2.3 * (1 - 0.75 * ease(lp));
        lockFigure(oc, { scale: 1, cyFrac: 0.09, textScale: 1, ph: e, lp: lp, fade: e > hold - 0.4 ? (hold - e) / 0.4 : 1, title: 'ACQUIRING VIDEO', stage: stage, sweep: sweepAng, ground: e < lockAt });
      }
    }
    if (MENU.open || MENU.wake > 0.003 || MENU.band > 0.003) drawMenu(oc, pr, dt);
    bindOverlay(oc);
    oc.restore();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (galOn) {
      ctx.setTransform(K, 0, 0, K, 0, 0);
      if (!galleryDraw(ctx, dt, pr)) { ctx.setTransform(1, 0, 0, 1, 0, 0); if (L.vs !== 'BACKGROUND') { ctx.setTransform(K, 0, 0, K, 0, 0); drawVideo(ctx, vFlight, pr.x, pr.y, pr.w, pr.h, true); ctx.setTransform(1, 0, 0, 1, 0, 0); } ctx.drawImage(osd, 0, 0); }
    } else ctx.drawImage(osd, 0, 0);
    hint();
  }

  // ---------------------------------------------------------------- page glue
  var lastHint = '';
  function hint() {
    var h;
    if (GAL.mode === 'playing') h = 'Left / Right seek 5 s · OK pauses · ESC back to the gallery';
    else if (GAL.mode === 'stats') h = 'Up / Down change the time window · ESC back to the gallery';
    else if (GAL.mode === 'confirm') h = 'Right picks DELETE · OK confirms · ESC keeps it';
    else if (GAL.mode !== 'off') h = 'Left / Right browse · OK plays · Down deletes · ESC back to live';
    else if (CH.open) h = 'Left / Right walk AUTO, AUTO HOP and the channels · Up: quietest · Down: the link\'s · OK picks · ESC closes';
    else if (MENU.open && MENU.stage === 0) h = 'Left / Right pick a side · OK unfolds it · ESC closes the menu';
    else if (MENU.open && MENU.edit) h = 'Up / Down change the value · OK applies it · Left leaves it pending';
    else if (MENU.open) h = 'Up / Down pick a row · Left / Right change tab · OK edits · ESC folds the blade';
    else if (BIND.state === 'running') h = 'Binding: waits 120 s for an air unit in pairing mode · BIND again cancels';
    else if (!L.everConn) h = L.power ? 'The air unit is powering up…' : 'Power the air unit to link up';
    else h = 'OK opens the menu · ESC opens the gallery · REC records';
    if (h !== lastHint && hintEl) { hintEl.textContent = h; lastHint = h; }
  }
  var setPageTheme = window.fpvosSetTheme || function () {};
  function setTheme(name, fromSim) { if (!THEMES[name]) return; S.theme = name; T = THEMES[name]; if (fromSim) setPageTheme(name, true); }
  window.fpvosSimTheme = function (name) { setTheme(name, false); };
  function syncControls() {
    root.querySelectorAll('[data-sim-power]').forEach(function (b) { b.setAttribute('aria-pressed', String(L.power)); b.querySelector('span').textContent = L.power ? 'Air unit on' : 'Air unit off'; });
  }
  root.querySelectorAll('[data-key]').forEach(function (b) {
    b.addEventListener('click', function (ev) { ev.preventDefault(); key(b.getAttribute('data-key')); cv.focus({ preventScroll: true }); });
  });
  root.querySelectorAll('[data-sim-power]').forEach(function (b) { b.addEventListener('click', function () { if (!started) start(); L.autoOnAt = -1; setPower(!L.power); }); });
  var fsBtn = root.querySelector('[data-sim-fullscreen]');
  if (fsBtn) fsBtn.addEventListener('click', function () {
    var el = root.querySelector('.sim-stage');
    try { if (document.fullscreenElement) document.exitFullscreen(); else (el.requestFullscreen || el.webkitRequestFullscreen).call(el); } catch (e) {}
  });
  var KEYMAP = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'ok', Escape: 'back', Backspace: 'back', r: 'rec', R: 'rec' };
  cv.setAttribute('tabindex', '0');
  cv.addEventListener('keydown', function (e) { var k = KEYMAP[e.key]; if (k) { e.preventDefault(); key(k); } });
  cv.addEventListener('click', function () { cv.focus({ preventScroll: true }); if (!started) start(); });
  function start() {
    if (started) return; started = true; t0 = performance.now() / 1000; last = t0;
    vIdle.play().catch(function () {});
    syncControls();
  }
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (es) {
    es.forEach(function (e) { visible = e.isIntersecting; if (visible && !started) start(); if (!visible) { vFlight.pause(); vIdle.pause(); vPlay.pause(); } });
  }, { threshold: 0.15 }) : null;
  if (io) io.observe(root); else start();
  document.addEventListener('visibilitychange', function () { if (document.hidden) { visible = false; vFlight.pause(); vIdle.pause(); } else visible = true; });
  // first paint: draw the poster until fonts and media are in
  (document.fonts && document.fonts.load ? document.fonts.load('600 64px "Chakra Petch"') : Promise.resolve()).then(function () { widthCache = {}; wordFit = null; }, function () {});
  setTheme(window.fpvosTheme || S.theme, false);
  syncControls();
  requestAnimationFrame(frame);
  // debug/test hook: window.fpvSim.key('ok')
  window.fpvSim = { key: key, state: function () { return { L: L, S: S, MENU: MENU, GAL: GAL, now: now }; }, power: setPower };
})();
