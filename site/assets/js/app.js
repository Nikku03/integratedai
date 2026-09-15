/* =====================================================================
   TWO SQUARES — motion engine
   One requestAnimationFrame loop drives everything scroll-related.
   Effects are opt-in via data-attributes, so pages stay plain HTML:

     data-reveal[="left|right|scale|none"]   fade + rise when it enters view
     data-parallax="0.25"                    drift at a fraction of scroll speed
     data-float                              gentle continuous bob
     data-tilt                               follows the mouse in 3D (hero cards)
     data-speed="1.2"                        per-card multiplier inside .float-grid
     .split                                  line-by-line masked text reveal
     .wipe                                   image curtain reveal
     .chapter                                sticky pinned "story" section
     .hscroll                                drag-to-scroll horizontal rail
     data-count="120"                        number counts up when in view
     data-magnetic                           button leans toward the cursor
     data-lift[="0.5"]                       tilts toward the cursor, rises on Z and zooms (hover)
     .gates                                  the framed-door walk (entrance opens → room fills the screen → next door)

   Respects prefers-reduced-motion: all motion collapses to static.
   ===================================================================== */
(() => {
  "use strict";

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = window.matchMedia("(pointer: fine)").matches;
  const lerp = (a, b, t) => a + (b - a) * t;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // --------------------------------------------------------------- state
  const S = {
    y: window.scrollY,     // real scroll
    sy: window.scrollY,    // smoothed scroll (what parallax reads)
    vy: 0,                 // velocity
    lastY: window.scrollY,
    vh: window.innerHeight,
    vw: window.innerWidth,
    mx: window.innerWidth / 2,
    my: window.innerHeight / 2,
    smx: window.innerWidth / 2,
    smy: window.innerHeight / 2,
  };

  const onScroll = () => { S.y = window.scrollY; };
  const onResize = () => { S.vh = window.innerHeight; S.vw = window.innerWidth; measureAll(); };
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", debounce(onResize, 120));
  window.addEventListener("mousemove", (e) => { S.mx = e.clientX; S.my = e.clientY; }, { passive: true });

  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  // --------------------------------------------------------------- nav
  const nav = $(".nav");
  const progress = $(".progress");
  const burger = $(".burger");
  if (burger) {
    burger.addEventListener("click", () => {
      const open = document.body.classList.toggle("menu-open");
      burger.setAttribute("aria-expanded", String(open));
      document.documentElement.style.overflow = open ? "hidden" : "";
    });
    $$(".menu a").forEach((a) => a.addEventListener("click", () => {
      document.body.classList.remove("menu-open");
      document.documentElement.style.overflow = "";
    }));
  }
  // mark current page in nav
  {
    const here = location.pathname.split("/").pop() || "index.html";
    $$(".nav__links a, .menu a").forEach((a) => {
      const target = (a.getAttribute("href") || "").split("/").pop();
      if (target === here) a.setAttribute("aria-current", "page");
    });
  }

  function tickNav() {
    if (!nav) return;
    nav.classList.toggle("is-scrolled", S.y > 24);
    const goingDown = S.y > S.lastY + 2;
    const goingUp = S.y < S.lastY - 2;
    if (goingDown && S.y > S.vh * 0.6) nav.classList.add("is-hidden");
    else if (goingUp) nav.classList.remove("is-hidden");
    if (progress) {
      const max = document.documentElement.scrollHeight - S.vh;
      progress.style.transform = `scaleX(${max > 0 ? S.y / max : 0})`;
    }
  }

  // --------------------------------------------------------------- reveal
  // Anything that should animate when it enters the viewport.
  const revealTargets = $$("[data-reveal], .split, .wipe");
  if (reduce) {
    revealTargets.forEach((el) => el.classList.add("is-in"));
  } else {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
      }
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.05 });
    revealTargets.forEach((el) => io.observe(el));
  }

  // --------------------------------------------------------------- split text
  // Wrap words, then group them into visual lines so each line rises under a mask.
  function splitLines(el) {
    if (el.dataset.split === "done") { unsplit(el); }
    const raw = el.dataset.original ?? el.innerHTML;
    el.dataset.original = raw;
    // tokenise on whitespace but keep inline tags (em/i/br) intact
    const tmp = document.createElement("div");
    tmp.innerHTML = raw;
    const words = [];
    const walk = (node, wrap) => {
      node.childNodes.forEach((n) => {
        if (n.nodeType === 3) {
          n.textContent.split(/(\s+)/).forEach((tok) => {
            if (!tok.trim()) return;
            words.push(wrap ? `<${wrap}>${tok}</${wrap}>` : tok);
          });
        } else if (n.nodeName === "BR") {
          words.push("<br>");
        } else if (n.nodeType === 1) {
          walk(n, n.nodeName.toLowerCase());
        }
      });
    };
    walk(tmp, null);
    el.innerHTML = words.map((w) => (w === "<br>" ? w : `<span class="w">${w}</span>`)).join(" ");
    const spans = $$(".w", el);
    const lines = [];
    let top = null, cur = null;
    spans.forEach((s) => {
      const t = s.offsetTop;
      if (top === null || Math.abs(t - top) > 2) { top = t; cur = []; lines.push(cur); }
      cur.push(s);
    });
    el.innerHTML = lines.map((ws, i) =>
      `<span class="line"><span style="--i:${i}">${ws.map((w) => w.outerHTML.replace(/<span class="w">|<\/span>$/g, "")).join(" ")}</span></span>`
    ).join("");
    el.dataset.split = "done";
  }
  function unsplit(el) { el.innerHTML = el.dataset.original || el.innerHTML; }
  const splits = $$(".split");
  if (!reduce) {
    const doSplits = () => splits.forEach(splitLines);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(doSplits); else doSplits();
    window.addEventListener("resize", debounce(() => { splits.forEach((el) => { const was = el.classList.contains("is-in"); splitLines(el); if (was) el.classList.add("is-in"); }); }, 200));
  }

  // --------------------------------------------------------------- parallax
  // Elements drift relative to their natural position; speed is a fraction of scroll.
  const px = [];
  function measureAll() {
    px.length = 0;
    if (reduce) return;
    $$("[data-parallax]").forEach((el) => {
      el.style.transform = "";
      const r = el.getBoundingClientRect();
      px.push({ el, speed: parseFloat(el.dataset.parallax) || 0.2, top: r.top + S.y, h: r.height });
    });
    $$(".float-grid .proj").forEach((el) => {
      el.style.transform = "";
      const r = el.getBoundingClientRect();
      const speed = (parseFloat(el.dataset.speed) || 1) - 1; // 1 = static, 1.3 = leads, 0.7 = lags
      px.push({ el, speed: speed * 0.35, top: r.top + S.y, h: r.height });
    });
    chapters.forEach(measureChapter);
    measureWalk();
  }
  function tickParallax() {
    for (const p of px) {
      const center = p.top + p.h / 2 - S.sy;          // element centre in viewport coords
      const dist = center - S.vh / 2;                 // 0 when centred
      if (Math.abs(dist) > S.vh * 1.5) continue;      // off-screen: skip
      p.el.style.transform = `translate3d(0, ${(-dist * p.speed).toFixed(2)}px, 0)`;
    }
  }

  // --------------------------------------------------------------- hero tilt
  const tilts = $$("[data-tilt]");
  function tickTilt() {
    if (!finePointer || reduce || !tilts.length) return;
    const nx = (S.smx / S.vw - 0.5) * 2;   // -1..1
    const ny = (S.smy / S.vh - 0.5) * 2;
    tilts.forEach((el) => {
      const depth = parseFloat(el.dataset.tilt) || 1;
      const x = nx * 18 * depth, y = ny * 12 * depth;
      const ry = nx * 6 * depth, rx = -ny * 6 * depth;
      el.style.transform = `translate3d(${x}px, ${y - (S.sy * (0.15 * depth))}px, 0) rotateY(${ry}deg) rotateX(${rx}deg)`;
    });
  }

  // --------------------------------------------------------------- marquee
  // Loops forever; speeds up with scroll velocity like a ticker being flicked.
  const marquees = $$(".marquee__track").map((track) => {
    // duplicate content until it's at least 2x viewport
    const html = track.innerHTML;
    while (track.scrollWidth < S.vw * 2.2) track.insertAdjacentHTML("beforeend", html);
    return { track, x: 0, w: track.scrollWidth / 2, dir: track.dataset.dir === "rtl" ? -1 : 1 };
  });
  function tickMarquee() {
    if (reduce) return;
    const boost = clamp(Math.abs(S.vy) * 0.08, 0, 6);
    for (const m of marquees) {
      m.x -= (0.6 + boost) * m.dir;
      if (m.x < -m.w) m.x += m.w;
      if (m.x > 0) m.x -= m.w;
      m.track.style.transform = `translate3d(${m.x.toFixed(2)}px,0,0)`;
    }
  }

  // --------------------------------------------------------------- pinned chapters
  const chapters = $$(".chapter").map((el) => ({
    el,
    imgs: $$(".chapter__media img", el),
    steps: $$(".chapter__step", el),
    ticks: $$(".chapter__track i", el),
    top: 0, h: 0, active: -1,
  }));
  function measureChapter(c) {
    const r = c.el.getBoundingClientRect();
    c.top = r.top + S.y; c.h = r.height;
  }
  function tickChapters() {
    for (const c of chapters) {
      const n = c.steps.length; if (!n) continue;
      const prog = clamp((S.y - c.top + S.vh * 0.5) / (c.h - S.vh * 0.5), 0, 0.9999);
      const idx = Math.floor(prog * n);
      if (idx !== c.active) {
        c.active = idx;
        c.imgs.forEach((im, i) => im.classList.toggle("is-active", i === idx));
        c.ticks.forEach((t, i) => t.classList.toggle("is-active", i <= idx));
      }
    }
  }

  // --------------------------------------------------------------- horizontal rail
  $$(".hscroll").forEach((wrap) => {
    const rail = $(".hscroll__rail", wrap);
    const bar = $(".hscroll__bar i", wrap);
    if (!rail) return;
    let down = false, startX = 0, startL = 0, moved = 0;
    rail.addEventListener("pointerdown", (e) => { down = true; moved = 0; startX = e.clientX; startL = rail.scrollLeft; rail.setPointerCapture(e.pointerId); });
    rail.addEventListener("pointermove", (e) => {
      if (!down) return;
      const dx = e.clientX - startX; moved = Math.max(moved, Math.abs(dx));
      if (moved > 4) rail.classList.add("is-dragging");
      rail.scrollLeft = startL - dx;
    });
    const up = () => { down = false; setTimeout(() => rail.classList.remove("is-dragging"), 30); };
    rail.addEventListener("pointerup", up); rail.addEventListener("pointercancel", up);
    const updateBar = () => {
      if (!bar) return;
      const max = rail.scrollWidth - rail.clientWidth;
      const frac = max > 0 ? rail.scrollLeft / max : 0;
      const w = clamp(rail.clientWidth / rail.scrollWidth, 0.08, 1);
      bar.style.width = `${w * 100}%`;
      bar.style.transform = `translateX(${frac * (1 / w - 1) * 100}%)`;
    };
    rail.addEventListener("scroll", updateBar, { passive: true });
    updateBar();
  });

  // --------------------------------------------------------------- counters
  {
    const els = $$("[data-count]");
    const run = (el) => {
      const end = parseFloat(el.dataset.count); const dur = 1600; const t0 = performance.now();
      const suffix = el.dataset.suffix || "";
      const step = (t) => {
        const k = clamp((t - t0) / dur, 0, 1); const e = 1 - Math.pow(1 - k, 3);
        el.firstChild.nodeValue = Math.round(end * e).toLocaleString();
        if (k < 1) requestAnimationFrame(step); else el.firstChild.nodeValue = end.toLocaleString();
      };
      el.innerHTML = `0<sup>${suffix}</sup>`;
      if (reduce) { el.innerHTML = `${end.toLocaleString()}<sup>${suffix}</sup>`; return; }
      requestAnimationFrame(step);
    };
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { run(e.target); io.unobserve(e.target); } }), { threshold: 0.4 });
    els.forEach((el) => io.observe(el));
  }

  // --------------------------------------------------------------- index hover thumb
  {
    const thumb = $(".index__thumb");
    const img = thumb && $("img", thumb);
    if (thumb && img && finePointer) {
      $$(".index__row").forEach((row) => {
        row.addEventListener("mouseenter", () => { img.src = row.dataset.img || ""; thumb.classList.add("is-on"); });
        row.addEventListener("mouseleave", () => thumb.classList.remove("is-on"));
      });
      document.addEventListener("mousemove", (e) => { thumb.style.left = `${e.clientX + 40}px`; thumb.style.top = `${e.clientY}px`; }, { passive: true });
    }
  }

  // --------------------------------------------------------------- magnetic buttons
  if (finePointer && !reduce) {
    $$("[data-magnetic], .btn").forEach((b) => {
      b.addEventListener("mousemove", (e) => {
        const r = b.getBoundingClientRect();
        const x = (e.clientX - r.left - r.width / 2) * 0.28, y = (e.clientY - r.top - r.height / 2) * 0.28;
        b.style.transform = `translate(${x}px, ${y}px)`;
      });
      b.addEventListener("mouseleave", () => { b.style.transition = "transform .6s cubic-bezier(.22,1,.36,1)"; b.style.transform = ""; setTimeout(() => (b.style.transition = ""), 600); });
    });
  }

  // --------------------------------------------------------------- 3D hover lift
  // The element tilts toward the cursor (CSS vars), and CSS lifts/zooms it on :hover.
  $$("[data-lift]").forEach((el) => {
    const strength = parseFloat(el.dataset.lift) || 1;
    el.style.setProperty("--lift", strength);
    if (!finePointer || reduce) return;
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.classList.add("is-tilting");
      el.style.setProperty("--ry", `${(x * 10 * strength).toFixed(2)}deg`);
      el.style.setProperty("--rx", `${(-y * 8 * strength).toFixed(2)}deg`);
    });
    el.addEventListener("pointerleave", () => {
      el.classList.remove("is-tilting");
      el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg");
    });
  });

  // --------------------------------------------------------------- the walk (framed doors)
  // Framed entrance pictures hang in a row. Scroll progress W runs one unit per
  // gate: the door in picture k opens, the frame scales about the door until the
  // room behind fills the screen, scales back, the door shuts, and the row slides
  // so the next door is centred. W is anchored to where each text panel is centred.
  const gatesEl = $(".gates");
  const GT = gatesEl ? {
    el: gatesEl,
    track: $(".gates__track", gatesEl),
    floor: $(".gates__floor", gatesEl),
    grade: $(".gates__grade", gatesEl),
    gates: $$(".gate", gatesEl).map((g) => ({
      el: g, frame: $(".gate__frame", g),
      dx: parseFloat(g.style.getPropertyValue("--dx")) / 100, dy: parseFloat(g.style.getPropertyValue("--dy")) / 100,
      dw: parseFloat(g.style.getPropertyValue("--dw")) / 100, dh: parseFloat(g.style.getPropertyValue("--dh")) / 100,
      cx: 0, cy: 0, w: 0, h: 0, smax: 4,
    })),
    insides: $$(".gates__inside", gatesEl),
    steps: $$(".gates__step", gatesEl),
    hud: $$(".gates__hud span", gatesEl),
    anchors: [], top: 0, h: 0, room: -1, hudIdx: -1, lastW: NaN, active: -1,
  } : null;
  const CH = [-0.05, 0.41, 1.41, 2.41];                    // W when each step (arrive, café, restaurant, bar) is centred
  const ROOM_KEYS = ["cafe", "rest", "bar"];
  const smooth = (t) => t * t * (3 - 2 * t);
  const seg = (p, a, b) => clamp((p - a) / (b - a), 0, 1);

  function measureWalk() {
    if (!GT) return;
    const r = GT.el.getBoundingClientRect();
    GT.top = r.top + S.y; GT.h = r.height;
    GT.anchors = GT.steps.map((st) => { const sr = st.getBoundingClientRect(); return sr.top + S.y + sr.height / 2 - S.vh / 2; });
    // door centres in track coordinates (frames unscaled)
    GT.track.style.setProperty("--tx", "0px");
    GT.gates.forEach((g) => { g.frame.style.setProperty("--s", "1"); });
    const tr = GT.track.getBoundingClientRect();
    const sk = $(".gates__sticky", GT.el).getBoundingClientRect();
    GT.gates.forEach((g) => {
      const fr = g.el.getBoundingClientRect();
      g.w = fr.width; g.h = fr.height;
      g.cx = fr.left - tr.left + (g.dx + g.dw / 2) * fr.width;      // relative to the track's left edge
      g.cy = fr.top - sk.top + (g.dy + g.dh / 2) * fr.height;       // relative to the sticky stage (= viewport when pinned)
      const holeW = g.dw * fr.width, holeH = g.dh * fr.height;
      g.smax = Math.max(S.vw / holeW, S.vh / holeH) * 1.06;
    });
    GT.lastW = NaN;
  }
  function progressAt(scroll) {
    const A = GT.anchors, n = A.length;
    if (n < 2) return 0;
    let i = 0;
    while (i < n - 2 && scroll > A[i + 1]) i++;
    const t = (scroll - A[i]) / (A[i + 1] - A[i]);
    return clamp(lerp(CH[i], CH[i + 1], t), -0.4, 2.78);
  }
  function tickWalk() {
    if (!GT || !GT.gates.length) return;
    if (S.y + S.vh < GT.top - S.vh || S.y > GT.top + GT.h + S.vh) return;
    const W = progressAt(S.sy);
    if (Math.abs(W - GT.lastW) < 0.0002) return;
    GT.lastW = W;
    const n = GT.gates.length;
    const k = clamp(Math.floor(W), 0, n - 1);
    const p = W - k;                                        // negative before the first door
    const g = GT.gates[k];
    // phases: open .03–.13 · travel in .13–.34 · hold .34–.50 · travel out .50–.70 · close .66–.76 · walk .80–1
    const open = 106 * smooth(seg(p, 0.03, 0.13)) * (1 - smooth(seg(p, 0.66, 0.76)));
    const depth = smooth(seg(p, 0.13, 0.34)) * (1 - smooth(seg(p, 0.50, 0.70)));   // 0 outside … 1 fully inside
    const s = 1 + (g.smax - 1) * depth;
    const zoom = 1 + 0.12 * depth;
    const walk = p < 0 ? p * 2 : k + smooth(seg(p, 0.80, 1.0));
    // exterior fades once the doorway is most of the screen, so the room takes over cleanly
    const cover = (g.dw * g.w * s) / S.vw;
    const ext = 1 - smooth(seg(cover, 0.6, 1.05));
    // track: door centre of the walk position sits at the viewport centre
    let cxTrack;
    if (walk < 0) cxTrack = GT.gates[0].cx + walk * (n > 1 ? GT.gates[1].cx - GT.gates[0].cx : 400);
    else { const i = Math.min(Math.floor(walk), n - 1), j = Math.min(i + 1, n - 1); cxTrack = lerp(GT.gates[i].cx, GT.gates[j].cx, walk - i); }
    const tx = S.vw / 2 - cxTrack;
    GT.track.style.setProperty("--tx", `${tx.toFixed(1)}px`);
    GT.floor.style.setProperty("--fx", `${(tx * 0.35).toFixed(1)}px`);
    // active gate
    if (k !== GT.active) {
      GT.gates.forEach((x, i) => { x.el.classList.toggle("is-active", i === k); if (i !== k) { x.frame.style.setProperty("--s", "1"); x.el.style.setProperty("--open", "0"); x.el.style.setProperty("--ext", "1"); } });
      GT.insides.forEach((im, i) => im.classList.toggle("is-active", i === k));
      GT.el.dataset.room = ROOM_KEYS[k] || ROOM_KEYS[0];
      GT.active = k;
    }
    g.el.style.setProperty("--open", open.toFixed(2));
    g.el.style.setProperty("--ext", ext.toFixed(3));
    g.frame.style.setProperty("--s", s.toFixed(4));
    GT.el.style.setProperty("--zoom", zoom.toFixed(4));
    // the room shows only through the doorway: clip the full-bleed interior to the hole
    const hw = g.dw * g.w * s, hh = g.dh * g.h * s, cx = S.vw / 2, cy = g.cy;
    const cl = Math.max(0, cx - hw / 2), cr = Math.max(0, S.vw - (cx + hw / 2));
    const ct = Math.max(0, cy - hh / 2), cb = Math.max(0, S.vh - (cy + hh / 2));
    const clip = open > 0.5 || depth > 0 ? `inset(${ct.toFixed(1)}px ${cr.toFixed(1)}px ${cb.toFixed(1)}px ${cl.toFixed(1)}px)` : "inset(50% 50% 50% 50%)";
    const inside = GT.insides[k]; if (inside) inside.style.clipPath = clip;
    GT.grade.style.clipPath = clip;
    GT.el.classList.toggle("is-inside", depth > 0.6);
    // HUD
    const hudIdx = (k === 0 && p < 0.03) ? 0 : k + 1;
    if (hudIdx !== GT.hudIdx) { GT.hudIdx = hudIdx; GT.hud.forEach((h, i) => h.classList.toggle("is-active", i === hudIdx)); }
  }

  // --------------------------------------------------------------- cursor glow
  const glow = $(".cursor-glow");
  if (glow && finePointer && !reduce) {
    document.body.classList.add("has-pointer");
  }
  function tickGlow() {
    if (!glow || !finePointer) return;
    glow.style.transform = `translate(${S.smx - 260}px, ${S.smy - 260}px)`;
  }

  // --------------------------------------------------------------- page transitions
  {
    const veil = $(".veil");
    if (veil && !reduce) {
      document.body.classList.add("is-entering");
      requestAnimationFrame(() => requestAnimationFrame(() => {
        veil.classList.add("is-out");
        setTimeout(() => document.body.classList.remove("is-entering"), 800);
      }));
      document.addEventListener("click", (e) => {
        const a = e.target.closest("a[href]");
        if (!a) return;
        const href = a.getAttribute("href");
        if (!href || href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:") || a.target === "_blank" || /^https?:\/\//.test(href)) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        document.body.classList.remove("menu-open");
        document.documentElement.style.overflow = "";
        veil.classList.remove("is-out");
        document.body.classList.add("is-leaving");
        setTimeout(() => (location.href = href), 560);
      });
    }
  }

  // --------------------------------------------------------------- contact form (demo)
  {
    const form = $("form[data-demo]");
    if (form) form.addEventListener("submit", (e) => {
      e.preventDefault();
      const btn = $("button[type=submit]", form);
      const orig = btn.innerHTML;
      btn.innerHTML = "Thanks — we'll be in touch within two working days.";
      btn.disabled = true;
      setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; form.reset(); }, 4000);
    });
  }

  // --------------------------------------------------------------- main loop
  function frame() {
    S.vy = S.y - S.lastY;
    S.sy = reduce ? S.y : lerp(S.sy, S.y, 0.12);
    S.smx = lerp(S.smx, S.mx, 0.1); S.smy = lerp(S.smy, S.my, 0.1);
    tickNav();
    tickParallax();
    tickTilt();
    tickMarquee();
    tickChapters();
    tickWalk();
    tickGlow();
    S.lastY = S.y;
    requestAnimationFrame(frame);
  }

  // kick off after layout is stable
  const start = () => { measureAll(); requestAnimationFrame(frame); };
  if (document.readyState === "complete") start(); else window.addEventListener("load", start);
  // re-measure once fonts settle (heights change)
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(measureAll, 50));
})();
