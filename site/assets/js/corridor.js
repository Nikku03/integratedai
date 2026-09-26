/*!
 * Two Squares — the corridor (home, Version A). Needs motion.js and scrub.js (Motion.ScrubVideo).
 *
 * A film you scroll through: outside the arcade → through the doors → down the corridor, turning
 * into four rooms one by one (08:00 café, 11:00 shop, 14:00 restaurant, 23:00 bar) → out.
 *
 * One tall .corridor__track (height in CSS: --corridor-len) holds a position:sticky 100svh stage.
 * A ScrollTrigger scrubs ONE number (S.t, in "screens" of scroll) across the track; render() turns
 * it into transform / opacity writes (cached, so an unchanged frame writes nothing). No pin.
 *
 * Footage: every shot is one line in CORRIDOR.shots below. Two stacked video layers: shot k plays
 * on layer k % 2, so every cut is a two-layer transition (a whip — slide + smear + streaks — for
 * the turns, a push through the doors). Only one layer seeks at a time; the other holds its
 * boundary frame (prepared while the first is idle). Files are fetched whole as Blobs, shared by
 * both layers, prefetched two shots ahead and released when far. Portrait screens use the 4:5 -sm files.
 *
 * Reduced motion / no JS: CSS lays the same DOM out as a sequence of stills (corridor.css).
 */
(function (w, d) {
  "use strict";

  /* ================================================================ CONFIG — fit the footage here
   * clips   name → file base in assets/video/: <base>.webm|.mp4, <base>-sm.webm|.mp4 (phones, 4:5),
   *         posters/<base>-poster.jpg and <base>-sm-poster.jpg (shown until the clip is ready).
   * shots   in the order you walk them. Shot k plays clip `clip` from `in` to `out` (seconds)
   *         over `len` screens of scroll, then holds on `out` for `hold` screens (end title).
   *   enter   the cut INTO this shot: "push" (forward, through doors), "whip-left" / "whip-right"
   *           (a turn: the picture slides the other way), "fade". Length: CORRIDOR[type] or enterLen.
   *   stop    the room this shot is (cafe | shop | restaurant | bar): shows its caption, end title
   *           and CTA, and lights its directory entry.
   *   sign    { stop, side: "left" | "right", at: [t0, t1] } the room's blade sign eases in from its side
   *           between clip seconds t0 and t1 of this stretch (where the door passes in the footage),
   *           drifts out a little as you approach, and leaves with the turn. (`from: 0..1` also works.)
   *   tod     time of day, 0 = 08:00 · 1 = 11:00 · 2 = 14:00 · 3 = 23:00; [a, b] ramps across the shot.
   *   place   HUD label; poster (optional) a still for this shot's first frame (file in assets/video/posters/).
   *   endStill  a still of the shot's last frame (path without extension: <p>.webp, <p>-sm.webp), shown after a jump
   *           to the hold until the clip is ready. The reduced-motion stills use the same files.
   *   still   the same, for the whole shot (a short shot that starts mid-clip).
   *   origin  (push only) where the push-in aims on the outgoing frame, e.g. "40% 56%" (the doors).
   *   focus   object-position of this shot on phones (the 4:5 file is cropped again to the screen), e.g. "22% 50%".
   * outro   screens of scroll for the end line after the last shot.
   * The CSS track length --corridor-len should be about (total + 1) × 100svh; total is logged as
   * root.__corridor.total. Only the proportions matter to the engine.
   */
  const CORRIDOR = {
    clips: {
      enter: "complex-enter",        // outside a red-brick building → up the steps → hard cut (9.3 s) → through the door into its arcaded court
      arcade: "complex-atrium",      // inside: look up at the glass roof, tilt down, walk on down the arcade
      c1: "corridor-1",              // the corridor, one continuous take cut into four stretches (the last frame of one is the
      c2: "corridor-2",              //   first frame of the next); each ends as a room's door comes level with the camera
      c3: "corridor-3",
      c4: "corridor-4",              // … through the portal into the end vestibule: bar door right, glass doors (the way out) left
      cafe: "cafe-walk",             // the owner's own café walk-in: through the green doors to the counter
      shop: "retail-walk",           // a low glide into a white furniture showroom
      restaurant: "restaurant-walk",
      bar: "bar-walk",
    },
    push: 0.26, whip: 0.3, fade: 0.32,   // default length of each kind of cut (screens)
    scrub: 0.7,                          // seconds the picture takes to catch up with the scroll
    shots: [
      { id: "outside",    clip: "enter",      in: 0.0, out: 9.2,  len: 1.25,            tod: 0,      place: "Outside", focus: "22% 50%" },
      { id: "doors",      clip: "enter",      in: 9.4, out: 11.6, len: 0.36,            tod: 0,      place: "Through the doors", enter: "push", origin: "40% 56%", focus: "30% 50%" },
      { id: "arcade",     clip: "arcade",     in: 1.2, out: 6.3,  len: 0.7,             tod: 0,      place: "The arcade", enter: "fade" },
      { id: "corridor-1", clip: "c1",         in: 0.0, out: 5.2,  len: 0.8,             tod: 0,      place: "The corridor", enter: "push",       sign: { stop: "cafe", side: "right", at: [2.6, 3.9] } },
      { id: "cafe",       clip: "cafe",       in: 0.0, out: 9.4,  len: 1.25, hold: 0.7, tod: 0,      stop: "cafe",          enter: "whip-right", endStill: "assets/img/corridor/cafe" },
      { id: "corridor-2", clip: "c2",         in: 0.0, out: 4.55, len: 0.7,             tod: [0, 1], place: "The corridor", enter: "whip-left",  sign: { stop: "shop", side: "left", at: [1.9, 3.0] } },
      { id: "shop",       clip: "shop",       in: 2.4, out: 13.2, len: 1.35, hold: 0.6, tod: 1,      stop: "shop",          enter: "whip-left",  endStill: "assets/img/corridor/shop" },
      { id: "corridor-3", clip: "c3",         in: 0.0, out: 4.4,  len: 0.68,            tod: [1, 2], place: "The corridor", enter: "whip-right", sign: { stop: "restaurant", side: "right", at: [2.1, 3.2] } },
      { id: "restaurant", clip: "restaurant", in: 0.4, out: 13.4, len: 1.6,  hold: 0.6, tod: 2,      stop: "restaurant",    enter: "whip-right", endStill: "assets/img/corridor/restaurant" },
      { id: "corridor-4", clip: "c4",         in: 0.0, out: 8.6,  len: 1.25,            tod: [2, 3], place: "The corridor", enter: "whip-left",  sign: { stop: "bar", side: "right", at: [5.9, 7.0] } },
      { id: "bar",        clip: "bar",        in: 0.6, out: 8.2,  len: 1.05, hold: 0.6, tod: 3,      stop: "bar",           enter: "whip-right", endStill: "assets/img/corridor/bar" },
      { id: "way-out",    clip: "c4",         in: 7.7, out: 8.6,  len: 0.4,             tod: 3,      place: "The corridor", enter: "whip-left",  still: "assets/img/corridor/vestibule" },
    ],
    outro: 0.8,
  };

  /* ================================================================ helpers */
  const M = w.Motion;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a)); return t * t * (3 - 2 * t); };
  const inOut = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);   // cubic in-out
  // the 4:5 (-sm) files for portrait screens (phones, portrait tablets): a 16:9 file on a 3:4 screen would show only
  // the middle 42% of the frame, and decode twice the pixels. Landscape screens get the 16:9 files.
  const mqSmall = w.matchMedia("(max-aspect-ratio: 1/1)");
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
  const TS = () => w.TS || {};

  // style writes with a per-element cache, so an unchanged frame writes nothing
  const touched = new Set();
  function css(el, prop, val) {
    if (!el) return;
    const c = el.__cc || (el.__cc = {});
    if (c[prop] === val) return;
    if (!touched.has(el)) { touched.add(el); el.__corig = el.getAttribute("style"); }
    c[prop] = val;
    el.style[prop] = val;
  }
  function cls(el, name, on) {
    const c = el.__cc || (el.__cc = {});
    const k = "." + name;
    if (c[k] === on) return;
    c[k] = on;
    if (!touched.has(el)) { touched.add(el); el.__corig = el.getAttribute("style"); }
    el.classList.toggle(name, on);
  }
  function resetTouched() {
    touched.forEach((el) => {
      if (el.__corig == null) el.removeAttribute("style"); else el.setAttribute("style", el.__corig);
      el.__cc = null;
    });
    touched.clear();
  }
  const f3 = (n) => Math.round(n * 1000) / 1000;

  /* ================================================================ the corridor */
  function initCorridor(root, env) {
    const gsap = w.gsap, ST = w.ScrollTrigger, Scrub = M.ScrubVideo;
    const C = CORRIDOR;
    const base = root.dataset.root || "";
    const stage = $(".corridor__stage", root), track = $(".corridor__track", root);
    const place = $(".corridor__place", stage), hint = $(".corridor__hint", stage), skip = $(".corridor__skip", stage);
    const dirFill = $(".corridor__dir-fill", stage);
    const dirItems = $$(".corridor__dir-item", stage);
    const tints = { am: $(".corridor__tint--am", stage), pm: $(".corridor__tint--pm", stage), night: $(".corridor__tint--night", stage) };
    const whipEl = $(".corridor__whip", stage), dipEl = $(".corridor__dip", stage), shadeEl = $(".corridor__shade", stage);
    const card = $(".corridor__card", stage);
    const outro = $(".corridor__outro", stage), outroLink = $(".corridor__outro-link", stage);
    const stops = {};
    $$(".corridor__stop", stage).forEach((el) => {
      stops[el.dataset.stop] = { el, cap: $(".corridor__cap", el), end: $(".corridor__end", el), title: $(".corridor__title", el),
        cta: $(".corridor__cta:not(.cafe-seq-fallback)", el) };
    });
    const signs = {};
    $$(".corridor__sign", stage).forEach((el) => { signs[el.dataset.sign] = { el }; });
    const offs = [];

    /* ---- the shot list, laid out in screens of scroll */
    const shots = C.shots.map((s, k) => Object.assign({}, s, { k, L: k % 2 }));
    const trans = [];
    let u = 0;
    shots.forEach((s, k) => {
      if (k > 0) {
        const type = s.enter || "fade";
        const len = s.enterLen != null ? s.enterLen : (type.indexOf("whip") === 0 ? C.whip : C[type] || C.fade);
        trans[k] = { k, type, dir: type === "whip-left" ? 1 : type === "whip-right" ? -1 : 0, a: u, b: u + len };
        u += len;
      }
      s.s = u; s.e1 = u + s.len; s.e = s.e1 + (s.hold || 0); u = s.e;
      s.tod0 = Array.isArray(s.tod) ? s.tod[0] : s.tod || 0;
      s.tod1 = Array.isArray(s.tod) ? s.tod[1] : s.tod0;
      const sg = s.stop && signs[s.stop];
      s.placeText = s.stop && sg ? $("b", sg.el).textContent.trim() + " · " + $(".corridor__sign-plate > span", sg.el).textContent.trim() : s.place || "";
      if (s.sign && signs[s.sign.stop]) {
        signs[s.sign.stop].el.dataset.side = s.sign.side || "left";
        const span = Math.max(1e-6, s.out - s.in);
        if (s.sign.at) { s.sign.from = clamp((s.sign.at[0] - s.in) / span); s.sign.to = clamp((s.sign.at[1] - s.in) / span); }
      }
    });
    const outroA = u;
    const TOTAL = u + C.outro;
    // where each room is: the hold's centre (for jumps), and its span from the turn in to the turn out
    const stopAt = {};
    shots.forEach((s, k) => {
      if (!s.stop) return;
      stopAt[s.stop] = { k, hold: (s.e1 + s.e) / 2, a: trans[k] ? trans[k].a : s.s, b: trans[k + 1] ? trans[k + 1].b : s.e };
    });
    // the directory: the fill reaches each entry's centre as you stand in that room
    const dirAnchors = [[0, 0]];
    dirItems.forEach((li, i) => { const at = stopAt[li.dataset.stop]; if (at) dirAnchors.push([at.hold, (i + 0.5) / dirItems.length]); });
    dirAnchors.push([TOTAL, 1]);
    const dirAt = (t) => {
      for (let i = 1; i < dirAnchors.length; i++) {
        const [t1, v1] = dirAnchors[i], [t0, v0] = dirAnchors[i - 1];
        if (t <= t1) return lerp(v0, v1, clamp((t - t0) / Math.max(1e-6, t1 - t0)));
      }
      return 1;
    };

    function where(t) {
      if (t >= outroA) return { k: shots.length - 1, tr: null, q: clamp((t - outroA) / C.outro) };
      for (let k = 0; k < shots.length; k++) {
        const tr = trans[k];
        if (tr && t < tr.b) return { k, tr, p: clamp((t - tr.a) / (tr.b - tr.a)) };
        if (t < shots[k].e) return { k, tr: null, q: -1 };
      }
      return { k: shots.length - 1, tr: null, q: 0 };
    }

    /* ---- files: one Blob per file, shared by both layers */
    const pickExt = (() => { const v = d.createElement("video"); return !isSafari && v.canPlayType('video/webm; codecs="vp9"') === "probably" ? "webm" : "mp4"; })();
    let small = mqSmall.matches;
    const fileBase = (clip) => C.clips[clip] || clip;
    const fileFor = (clip) => base + "assets/video/" + fileBase(clip) + (small ? "-sm" : "") + "." + pickExt;
    const posterFor = (s) => base + "assets/video/posters/" + (s.poster ? s.poster : fileBase(s.clip) + (small ? "-sm" : "") + "-poster.jpg");
    // what a layer shows until its video has a frame: the clip's first frame, or (at the end of a shot) the hold still
    function setPoster(L, end) {
      const s = shots[L.shot];
      if (!s || L.shown) return;
      const still = (end && s.endStill) || s.still;
      const src = still ? base + still + (small ? "-sm" : "") + ".webp" : posterFor(s);
      if (L.pend !== src) { L.pend = src; L.poster.setAttribute("src", src); }
    }
    const lib = new Map();
    function fetchClip(src) {
      let e = lib.get(src);
      if (e) return e.p;
      const ac = new AbortController();
      e = { ac, url: null };
      e.p = fetch(src, { signal: ac.signal })
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.blob(); })
        .then((b) => { if (ac.signal.aborted) throw new Error("aborted"); e.url = URL.createObjectURL(b); return e.url; })
        .catch((err) => { if (ac.signal.aborted) throw err; e.url = src; return src; });   // no Blob: stream the file
      e.p.catch(() => {});
      lib.set(src, e);
      return e.p;
    }
    function release(src) {
      const e = lib.get(src);
      if (!e) return;
      e.ac.abort();
      if (e.url && e.url.indexOf("blob:") === 0) URL.revokeObjectURL(e.url);
      lib.delete(src);
    }

    /* ---- the two layers: ScrubVideo (gated seeks, iOS unlock) fed from the shared files */
    class Layer extends Scrub {
      constructor(el, i) {
        super($("video", el));
        this.el = el; this.i = i;
        this.poster = $(".corridor__poster", el);
        this.smear = $(".corridor__smear", el);
        this.edge = $(".corridor__edge", el);
        this.sctx = this.smear.getContext("2d");
        if (this.sctx) this.sctx.imageSmoothingQuality = "high";
        this.src = null; this.shot = -1; this.shown = false; this.smearKey = ""; this.token = 0;
        // a finished seek means the picture is from this file: show it, even mid-scrub (not yet on target)
        this.v.addEventListener("seeked", () => { if (this.ready) this.fresh = true; if (live) render(); });
      }
      async attach(src) {
        if (this.src === src) return;
        this.src = src; this.ready = false; this.shown = false; this.fresh = false;
        const token = ++this.token;
        let url;
        try { url = await fetchClip(src); } catch (_) { return; }
        if (token !== this.token) return;
        const v = this.v;
        v.preload = "auto";
        v.src = url;
        if (v.readyState < 2) await new Promise((res) => v.addEventListener("loadeddata", res, { once: true }));
        if (token !== this.token) return;
        this.duration = v.duration;
        this.unlock();
        this.ready = true;
        render(true);
      }
      detach() {
        this.token++; this.src = null; this.ready = false; this.shown = false; this.shot = -1; this.smearKey = "";
        try { this.v.pause(); } catch (_) {}
        if (this.v.hasAttribute("src")) { this.v.removeAttribute("src"); this.v.load(); }
      }
      seekTo(time) { if (this.ready) this.target = clamp(time, 0, this.duration - 0.5 / this.fps); }
      get settled() { return this.ready && !this.v.seeking && Math.abs(this.v.currentTime - this.target) < 0.5 / this.fps + 0.001; }
      // a smeared copy of the frame on screen (a 24 × 54 canvas stretched to the stage: a horizontal motion blur, no CSS filter)
      capture(key) {
        if (this.smearKey === key || !this.sctx || !this.settled) return;
        const v = this.v, vw = v.videoWidth, vh = v.videoHeight;
        if (!vw || !vh) return;
        const ar = geo.W / geo.H;
        let sw = vw, sh = vh;
        if (vw / vh > ar) sw = vh * ar; else sh = vw / ar;
        try { this.sctx.drawImage(v, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, this.smear.width, this.smear.height); this.smearKey = key; } catch (_) {}
      }
    }
    const layers = $$(".corridor__layer", stage).map((el, i) => new Layer(el, i));
    const geo = { W: 1, H: 1 };
    let near = false, live = false, active = null, passive = null, lastK = -1;

    function assign(L, k) {
      if (L.shot === k) return;
      L.shot = k; L.smearKey = "";
      const s = shots[k];
      L.pend = null;
      const fp = small && s.focus ? s.focus : "";
      css(L.v, "objectPosition", fp); css(L.poster, "objectPosition", fp);
      L.attach(fileFor(s.clip));   // same file: keeps the frame on screen, just seeks
    }
    // keep the files for the shot you're in, one behind and two ahead; let go of the rest
    function updateLib(k) {
      const keep = new Set();
      for (let j = k - 1; j <= k + 2; j++) if (shots[j]) keep.add(fileFor(shots[j].clip));
      layers.forEach((L) => { if (L.src) keep.add(L.src); });
      keep.forEach((src) => fetchClip(src));
      Array.from(lib.keys()).forEach((src) => { if (!keep.has(src)) release(src); });
    }
    function releaseAll() {
      layers.forEach((L) => L.detach());
      Array.from(lib.keys()).forEach(release);
      lastK = -1;
    }

    function measure() {
      geo.W = stage.clientWidth || w.innerWidth;
      geo.H = stage.clientHeight || w.innerHeight;
    }

    /* ---- render: S.t → styles (writes only) */
    const S = { t: 0 };
    let lastPlace = null, lastLoading = null;
    function layerStyle(L, x, sc, o, z, sm, key, edge) {
      css(L.el, "transform", `translate3d(${f3(x)}%,0,0) scale(${f3(sc)})`);
      css(L.edge, "opacity", String(f3(edge || 0)));
      css(L.el, "opacity", String(f3(o)));
      css(L.el, "zIndex", String(z));
      css(L.v, "opacity", L.shown ? "1" : "0");
      css(L.smear, "opacity", String(L.smearKey === key ? f3(sm) : 0));
    }
    function render(force) {
      const t = S.t;
      const R = where(t);
      const k = R.k, s = shots[k];
      const A = layers[s.L], B = layers[1 - s.L];

      /* which shot each layer holds, and the frame it should show */
      if (near) {
        if (R.tr) { assign(A, k); assign(B, k - 1); }
        else {
          assign(A, k);
          const f = (t - s.s) / Math.max(1e-6, s.e - s.s);
          const holds = B.shot === k - 1 || B.shot === k + 1 ? B.shot : k + 1;
          // the other layer gets ready for the next cut in the direction you're going: past the middle of
          // a shot that's the next one, before it the one behind (a band in between stops it flip-flopping)
          const want = R.q >= 0 ? k - 1 : f > 0.55 ? k + 1 : f < 0.4 ? k - 1 : holds;
          if (shots[want]) assign(B, want);
        }
        if (k !== lastK) { lastK = k; updateLib(k); }
      }
      const f1 = s.len ? clamp((t - s.s) / s.len) : 1;
      if (R.tr) {
        A.seekTo(s.in); B.seekTo(shots[k - 1].out);
        active = R.p < 0.5 ? B : A; passive = active === A ? B : A;
      } else {
        A.seekTo(lerp(s.in, s.out, f1));
        if (B.shot >= 0 && shots[B.shot]) B.seekTo(B.shot > k ? shots[B.shot].in : shots[B.shot].out);
        active = A; passive = B;
      }
      layers.forEach((L) => { if (!L.shown && L.ready && (L.fresh || L.settled)) L.shown = true; });
      if (near) { setPoster(A, !R.tr && f1 > 0.5); setPoster(B, B.shot < k); }

      /* the cut: two layers */
      let whipO = 0, whipX = 0, dip = 0;
      if (R.tr) {
        const p = R.p, e = inOut(p), tr = R.tr;
        const kIn = "in" + k, kOut = "out" + (k - 1);
        A.capture(kIn); B.capture(kOut);
        if (tr.dir) {
          // a turn: the room slides away the way you turn, the next one comes in from the other side, smeared
          const D = tr.dir * 46;
          const edge = Math.sin(Math.PI * p);
          layerStyle(B, e * D, 1 + 0.05 * e, 1 - smooth(0.38, 0.72, p), 1, smooth(0.02, 0.3, p), kOut, edge);
          layerStyle(A, -(1 - e) * D, 1.05 - 0.05 * e, smooth(0.28, 0.62, p), 2, 1 - smooth(0.58, 0.96, p), kIn, edge);
          whipO = Math.sin(Math.PI * p);
          whipX = (p - 0.5) * tr.dir * 36;
          dip = 0.34 * Math.sin(Math.PI * p);
        } else if (tr.type === "push") {
          // forward through the doors: push in on the last frame, the next picks up slightly large and settles
          css(B.el, "transformOrigin", s.origin || "");
          layerStyle(B, 0, 1 + 0.05 * e, 1 - smooth(0.3, 0.8, p), 1, 0, kOut);
          layerStyle(A, 0, 1.04 - 0.04 * e, smooth(0.25, 0.75, p), 2, 0, kIn);
          dip = 0.5 * Math.sin(Math.PI * p);
        } else {
          // a dip: out through black and up into the next scene (no muddy double exposure)
          layerStyle(B, 0, 1, 1 - smooth(0.12, 0.55, p), 1, 0, kOut);
          layerStyle(A, 0, 1.02 - 0.02 * e, smooth(0.45, 0.9, p), 2, 0, kIn);
          dip = 0.55 * Math.sin(Math.PI * p);
        }
      } else {
        css(B.el, "transformOrigin", "");
        if (f1 >= 1 && s.stop) A.capture("out" + k);     // ready for the turn back out
        if (B.shot === k + 1 && B.shown) B.capture("in" + (k + 1));
        layerStyle(A, 0, 1, 1, 2, 0, "");
        layerStyle(B, 0, 1, 0, 1, 0, "");
      }
      css(whipEl, "opacity", String(f3(whipO * 0.85)));
      css(whipEl, "transform", `translate3d(${f3(whipX)}%,0,0)`);

      /* light across the day */
      let tod;
      if (t >= outroA) tod = shots[shots.length - 1].tod1;
      else if (R.tr) tod = lerp(shots[k - 1].tod1, s.tod0, R.p);
      else tod = lerp(s.tod0, s.tod1, clamp((t - s.s) / Math.max(1e-6, s.e - s.s)));
      css(tints.am, "opacity", String(f3(clamp(1 - tod))));
      css(tints.pm, "opacity", String(f3(clamp(tod - 1) * (1 - clamp(tod - 2)))));
      css(tints.night, "opacity", String(f3(clamp(tod - 2))));

      /* the title card, over the walk up to the doors */
      const fc = t / Math.max(1e-6, shots[0].len);
      const cardO = 1 - smooth(0.32, 0.62, fc);
      css(card, "opacity", String(f3(cardO)));
      css(card, "transform", `translate3d(0,${f3(-28 * smooth(0.2, 0.62, fc))}px,0)`);

      /* blade signs: in from their side as the room comes up, away with the turn */
      Object.keys(signs).forEach((id) => { signs[id].o = 0; });
      if (!R.tr && s.sign && signs[s.sign.stop]) {
        const sg = signs[s.sign.stop], side = s.sign.side === "right" ? 1 : -1;
        const f = clamp((t - s.s) / Math.max(1e-6, s.len)), from = s.sign.from || 0, to = s.sign.to || Math.min(1, from + 0.22);
        sg.o = smooth(from, to, f);
        // in from its side, then it drifts out with the door as you walk up to it (screen space, never on the footage)
        sg.x = side * (72 * (1 - sg.o) + geo.W * 0.03 * smooth(from, 1, f));
        sg.sc = 0.93 + 0.07 * smooth(from, 1, f);
      } else if (R.tr && shots[k - 1].sign && signs[shots[k - 1].sign.stop]) {
        const prev = shots[k - 1], sg = signs[prev.sign.stop];
        const e = inOut(R.p);
        sg.o = 1 - smooth(0, 0.4, R.p);
        sg.x = (prev.sign.side === "right" ? 1 : -1) * geo.W * 0.03 + (R.tr.dir ? e * R.tr.dir * 46 : 0) * geo.W / 100;
        sg.sc = 1 + (R.tr.dir ? 0.05 * e : 0.08 * e);
      }
      Object.keys(signs).forEach((id) => {
        const sg = signs[id];
        css(sg.el, "opacity", String(f3(sg.o)));
        if (sg.o > 0) css(sg.el, "transform", `translate3d(${f3(sg.x)}px,0,0) scale(${f3(sg.sc)})`);
      });

      /* the rooms: caption while you walk in, end title + action on the hold */
      let shade = 0;
      Object.keys(stops).forEach((id) => {
        const st = stops[id];
        let capO = 0, endO = 0;
        const at = stopAt[id];
        if (at) {
          const sk = shots[at.k];
          if (k === at.k && !R.tr) {
            const f = clamp((t - sk.s) / Math.max(1e-6, sk.len));
            capO = smooth(0.06, 0.18, f) * (1 - smooth(0.5, 0.62, f));
            endO = smooth(0.8, 0.97, f);
          } else if (R.tr && k === at.k + 1) {
            endO = 1 - smooth(0, 0.32, R.p);
          }
        }
        css(st.cap, "opacity", String(f3(capO)));
        css(st.cap, "transform", `translate3d(0,${f3(16 * (1 - smooth(0, 1, capO)))}px,0)`);
        css(st.end, "opacity", String(f3(endO)));
        css(st.end, "transform", `translate3d(0,${f3(22 * (1 - endO))}px,0)`);
        cls(st.el, "is-cta", endO > 0.6);
        shade = Math.max(shade, endO * 0.92, capO * 0.6);
      });

      /* the end of the corridor */
      const q = t >= outroA ? clamp((t - outroA) / C.outro) : 0;
      const outO = smooth(0.25, 0.7, q);
      css(outro, "opacity", String(f3(outO)));
      css(outro, "transform", `translate3d(0,${f3(20 * (1 - outO))}px,0)`);
      cls(outro, "is-cta", outO > 0.6);
      shade = Math.max(shade, smooth(0, 0.6, q) * 0.95);
      css(shadeEl, "opacity", String(f3(shade)));
      css(dipEl, "opacity", String(f3(Math.max(dip, smooth(0.1, 1, q) * 0.45))));

      /* HUD: where you are, the directory, the hint */
      const txt = R.tr ? (R.p < 0.5 ? shots[k - 1].placeText : s.placeText) : (t >= outroA && q > 0.5 ? "The way out" : s.placeText);
      if (txt !== lastPlace) { lastPlace = txt; place.textContent = txt; }
      css(dirFill, "transform", `scaleX(${f3(dirAt(t))})`);
      dirItems.forEach((li) => {
        const at = stopAt[li.dataset.stop];
        cls(li, "is-here", !!at && t >= at.a && t <= at.b);
        cls(li, "is-past", !!at && t > at.b);
      });
      css(hint, "opacity", String(f3(1 - smooth(0.05, 0.35, t))));
      const loading = live && near && !!active && !active.ready;
      if (loading !== lastLoading) { lastLoading = loading; stage.classList.toggle("is-loading", loading); }
    }

    /* ---- scroll → S.t */
    // the header steps out of the way while the film is on screen (onToggle can fire inside ST.create)
    let headerHidden = false;
    function setLive(on) {
      if (on === live) return;
      live = on;
      stage.classList.toggle("is-live", on);
      if (on !== headerHidden && TS().hideHeader) { headerHidden = on; TS().hideHeader(on); }
      if (on) render(true);
    }
    measure();
    const tween = gsap.to(S, { t: TOTAL, ease: "none", paused: true, onUpdate: render });
    const st = ST.create({
      trigger: track, start: "top top", end: "bottom bottom",
      animation: tween, scrub: C.scrub,
      onRefresh: () => { measure(); render(true); },
    });
    // "live" (the header steps aside, the picture seeks) is a couple of pixels wider than the scrub, so a stage
    // resting exactly on its first or last frame (the hero's "Walk in" cue, the outro, a restored scroll) still counts
    const liveST = ST.create({ trigger: track, start: "top top+=2", end: "bottom bottom-=2", onToggle: (self) => setLive(self.isActive) });

    // fetch the first files as the corridor comes near; let go of everything far away
    const io = new IntersectionObserver((es) => {
      const e = es[es.length - 1];
      near = e.isIntersecting;
      if (near) render(true); else releaseAll();
    }, { rootMargin: "100% 0px 100% 0px" });
    io.observe(track);

    // one layer scrubs: the one on screen. The other only prepares its boundary frame: while the first is
    // idle, or at once (a single seek) when it has just been given a new file and has nothing to show yet
    const tick = () => {
      if (!near || !active) return;
      const busy = active.ready && !active.settled;
      if (busy && live) active.tick();
      if (passive && passive.ready && !passive.settled && (!busy || !passive.shown)) passive.tick();
    };
    gsap.ticker.add(tick);

    /* ---- controls */
    const timeToY = (time) => st.start + (st.end - st.start) * (time / TOTAL);
    // a keyboard jump is a cut: the scrub's catch-up is finished at once, so the control that takes
    // focus is on screen and opaque when its ring is drawn
    const jumpTo = (time) => {
      M.scrollTo(Math.round(timeToY(time)), { immediate: true });
      ST.update();
      const tw = st.getTween && st.getTween();
      if (tw) tw.progress(1); else tween.progress(time / TOTAL);
      render(true);
    };
    Object.keys(stops).forEach((id) => {
      const sp = stops[id], at = stopAt[id];
      if (!sp.cta || !at) return;
      const onFocus = () => { if (!sp.el.classList.contains("is-cta")) jumpTo(at.hold); };
      const onTitle = () => { if (sp.el.classList.contains("is-cta")) sp.cta.click(); };
      sp.cta.addEventListener("focus", onFocus);
      sp.title.addEventListener("click", onTitle);
      if (sp.cta.dataset.cursor) sp.title.dataset.cursor = sp.cta.dataset.cursor;
      offs.push(() => { sp.cta.removeEventListener("focus", onFocus); sp.title.removeEventListener("click", onTitle); delete sp.title.dataset.cursor; });
    });
    // the directory walks you straight to a room
    dirItems.forEach((li) => {
      const a = $("a", li), at = stopAt[li.dataset.stop], sp = stops[li.dataset.stop];
      if (!a || !at) return;
      const onClick = (e) => {
        e.preventDefault();
        jumpTo(at.hold);
        if (sp && sp.cta) sp.cta.focus({ preventScroll: true });
      };
      a.addEventListener("click", onClick);
      offs.push(() => a.removeEventListener("click", onClick));
    });
    const onOutroFocus = () => { if (!outro.classList.contains("is-cta")) jumpTo(TOTAL); };
    outroLink.addEventListener("focus", onOutroFocus);
    offs.push(() => outroLink.removeEventListener("focus", onOutroFocus));
    // skip the walk: land on the next section's own top edge (the header hides on the way down)
    const onSkip = (e) => {
      const target = d.getElementById("after-walk") || root.nextElementSibling;
      if (!target) return;
      e.preventDefault();
      releaseAll();
      const y = Math.max(st.end + 1, Math.round(target.getBoundingClientRect().top + w.scrollY));
      M.scrollTo(y, { immediate: true });
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    };
    skip.addEventListener("click", onSkip);
    offs.push(() => skip.removeEventListener("click", onSkip));

    // phone ↔ desktop files
    const onMQ = () => { releaseAll(); small = mqSmall.matches; ST.refresh(); render(true); };
    mqSmall.addEventListener("change", onMQ);
    offs.push(() => mqSmall.removeEventListener("change", onMQ));

    render(true);

    // debug / QA handle
    root.__corridor = { S, st, tween, shots, trans, stopAt, total: TOTAL, outroA, layers, lib, where, jumpTo, get active() { return active; }, config: C };

    return () => {
      offs.forEach((f) => f());
      gsap.ticker.remove(tick);
      io.disconnect();
      st.kill(); liveST.kill(); tween.kill();
      setLive(false);
      releaseAll();
      layers.forEach((L) => { L.poster.removeAttribute("src"); L.destroy(); });
      Object.keys(stops).forEach((id) => stops[id].el.classList.remove("is-cta"));
      outro.classList.remove("is-cta");
      stage.classList.remove("is-loading", "is-live");
      place.textContent = "Outside";
      resetTouched();
      delete root.__corridor;
    };
  }

  /* ================================================================ boot */
  function boot(env) {
    const root = d.querySelector("[data-corridor]");
    if (!root) return null;
    const ok = env.motion && w.gsap && w.ScrollTrigger && M && M.ScrubVideo && w.IntersectionObserver && w.fetch;
    // film only with motion and a working engine; otherwise CSS keeps the stills
    root.classList.toggle("corridor--stills", !ok);
    if (!ok) return () => root.classList.remove("corridor--stills");
    const off = initCorridor(root, env);
    return () => { off(); root.classList.remove("corridor--stills"); };
  }

  if (M && M.global && w.gsap) M.global((env) => boot(env));
})(window, document);
