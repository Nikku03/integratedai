/*!
 * Two Squares — scroll-scrubbed media (prototype v1). Needs motion.js.
 *
 *   <section class="scrub" data-scrub style="--scrub-length:400vh">
 *     <div class="scrub__stage">
 *       <video muted playsinline preload="none" poster="cafe-poster.jpg"
 *              data-src-webm="cafe.webm" data-src-mp4="cafe.mp4"></video>
 *       -- or --
 *       <canvas data-frames="frames/f_{i}.webp" data-count="60" data-pad="3"></canvas>
 *     </div>
 *   </section>
 *
 * Sticky stage + ScrollTrigger progress (no pin): no pin-spacer, no position:fixed
 * swap, no iOS jitter. Progress is smoothed through a scrubbed proxy tween so
 * native touch scrolling (no Lenis smoothing) still looks continuous.
 */
(function (w, d) {
  "use strict";
  const gsap = w.gsap, ST = w.ScrollTrigger, Motion = w.Motion;
  if (!gsap || !Motion) return;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  // ---------------------------------------------------------------- video
  class ScrubVideo {
    constructor(video, opts = {}) {
      this.v = video;
      this.mode = opts.mode || "gated";          // "gated" (recommended) | "naive"
      this.fps = opts.fps || 24;
      this.target = 0;
      this.ready = false;
      this.stats = { seeks: 0, seekMs: [] };
      video.muted = true; video.playsInline = true;
      video.setAttribute("muted", ""); video.setAttribute("playsinline", "");
      video.addEventListener("seeked", () => {
        if (this._t0 != null) { this.stats.seekMs.push(performance.now() - this._t0); this._t0 = null; }
      });
      // what is actually on screen (for lag measurement): mediaTime of the last presented frame
      this.presented = 0; this.stats.presents = 0;
      if ("requestVideoFrameCallback" in video) {
        const onFrame = (_now, meta) => { this.presented = meta.mediaTime; this.stats.presents++; video.requestVideoFrameCallback(onFrame); };
        video.requestVideoFrameCallback(onFrame);
      }
    }
    get lagFrames() { return Math.abs(this.target - this.presented) * this.fps; }
    pickSrc() {
      const v = this.v;
      const webm = v.dataset.srcWebm, mp4 = v.dataset.srcMp4;
      // Safari 17+ says "maybe"/"probably" for VP9 in WebM but decodes it in software; prefer MP4 there.
      const vp9 = v.canPlayType('video/webm; codecs="vp9"');
      const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
      return (webm && vp9 === "probably" && !isSafari) ? webm : (mp4 || webm);
    }
    // Fetch the whole file as a Blob: every frame becomes seekable immediately,
    // independent of server Range support and Safari's range quirks.
    async load() {
      const src = this.pickSrc();
      let url = src;
      try {
        const res = await fetch(src);
        if (!res.ok) throw new Error(res.status);
        url = URL.createObjectURL(await res.blob());
        this.objectURL = url;
      } catch (_) { /* fall back to streaming the URL */ }
      // setting src starts the load; an extra video.load() would restart it and abort the first read
      this.v.preload = "auto";
      this.v.src = url;
      if (this.v.readyState < 2) await new Promise((res) => this.v.addEventListener("loadeddata", res, { once: true }));
      this.duration = this.v.duration;
      this.unlock();
      this.ready = true;
    }
    // iOS Safari does not paint seeked frames until the element has played once.
    unlock() {
      const v = this.v;
      const p = v.play();
      if (p && p.then) p.then(() => v.pause()).catch(() => {
        // Low-power mode / autoplay blocked: retry on the first user gesture
        const once = () => { v.play().then(() => v.pause()).catch(() => {}); };
        w.addEventListener("pointerdown", once, { once: true, passive: true });
        w.addEventListener("touchstart", once, { once: true, passive: true });
      });
      else v.pause();
    }
    setProgress(p) {
      if (!this.ready) return;
      // stop half a frame short of the end: seeking to duration shows a black frame in some browsers
      this.target = clamp(p, 0, 1) * (this.duration - 0.5 / this.fps);
      if (this.mode === "naive") this.seek(this.target);
    }
    // called once per frame from gsap.ticker
    tick() {
      if (!this.ready || this.mode !== "gated" || this.v.seeking) return;
      if (Math.abs(this.v.currentTime - this.target) < 0.5 / this.fps) return;
      this.seek(this.target);
    }
    seek(t) {
      this._t0 = performance.now();
      this.stats.seeks++;
      this.v.currentTime = t;
    }
    destroy() { if (this.objectURL) URL.revokeObjectURL(this.objectURL); }
  }

  // ---------------------------------------------------------------- frames
  class ScrubFrames {
    constructor(canvas, opts = {}) {
      this.c = canvas;
      this.ctx = canvas.getContext("2d", { alpha: false });
      this.pattern = opts.pattern || canvas.dataset.frames;
      this.count = opts.count || parseInt(canvas.dataset.count, 10);
      this.pad = opts.pad || parseInt(canvas.dataset.pad || "3", 10);
      // bitmap (recommended): fetch → createImageBitmap decodes OFF the main thread
      // ONCE; drawImage(bitmap) is then a cheap copy. With <img> sources Chrome may
      // discard the decoded pixels and re-decode synchronously inside drawImage →
      // one long task per frame on slow CPUs (measured). Cap the decoded width to
      // bound memory: 60 × 1280×720×4 B ≈ 221 MB, 60 × 960×540×4 B ≈ 124 MB.
      this.bitmap = opts.bitmap ?? (canvas.dataset.bitmap !== "0" && "createImageBitmap" in w);
      this.maxW = opts.maxW || parseInt(canvas.dataset.maxw || "0", 10) || 0;
      this.imgs = new Array(this.count);
      this.last = -1; this.target = 0; this.ready = false;
      this.stats = { drawMs: [] };
      this.resize = this.resize.bind(this);
      this.ro = new ResizeObserver(this.resize);
      this.ro.observe(canvas);
    }
    url(i) { return this.pattern.replace("{i}", String(i + 1).padStart(this.pad, "0")); }
    loadOne(i) {
      if (this.imgs[i]) return this.imgs[i].p;
      if (this.bitmap) {
        const rec = { ok: false };
        rec.p = fetch(this.url(i)).then((r) => r.blob()).then((b) => createImageBitmap(b, this.maxW ? { resizeWidth: this.maxW, resizeQuality: "high" } : undefined))
          .then((bm) => { rec.bm = bm; rec.naturalWidth = bm.width; rec.naturalHeight = bm.height; rec.ok = true; })
          .catch(() => {});
        this.imgs[i] = rec;
        return rec.p;
      }
      const img = new Image();
      img.decoding = "async";
      img.src = this.url(i);
      img.p = img.decode().then(() => { img.ok = true; }).catch(() => {});
      this.imgs[i] = img;
      return img.p;
    }
    // coarse-to-fine: every 8th frame first so scrubbing works almost at once,
    // then fill the gaps
    async load() {
      const first = [], rest = [];
      for (let i = 0; i < this.count; i++) (i % 8 === 0 || i === this.count - 1 ? first : rest).push(i);
      await Promise.all(first.map((i) => this.loadOne(i)));
      this.ready = true; this.resize();
      for (let k = 0; k < rest.length; k += 6) await Promise.all(rest.slice(k, k + 6).map((i) => this.loadOne(i)));
    }
    resize() {
      const dpr = Math.min(w.devicePixelRatio || 1, 2);
      const r = this.c.getBoundingClientRect();
      const W = Math.round(r.width * dpr), H = Math.round(r.height * dpr);
      if (W && H && (this.c.width !== W || this.c.height !== H)) { this.c.width = W; this.c.height = H; this.last = -1; }
    }
    setProgress(p) { this.target = clamp(p, 0, 1) * (this.count - 1); }
    get lagFrames() { return this.last < 0 ? 0 : Math.abs(this.target - this.last); }
    nearestLoaded(i) {
      for (let k = 0; k < this.count; k++) {
        const a = this.imgs[i - k], b = this.imgs[i + k];
        if (a && a.ok) return i - k;
        if (b && b.ok) return i + k;
      }
      return -1;
    }
    tick() {
      if (!this.ready) return;
      const i = this.nearestLoaded(Math.round(this.target));
      if (i < 0 || i === this.last) return;
      const img = this.imgs[i], cw = this.c.width, ch = this.c.height;
      const s = Math.max(cw / img.naturalWidth, ch / img.naturalHeight);    // object-fit: cover
      const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
      const t0 = performance.now();
      this.ctx.drawImage(img.bm || img, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
      this.stats.drawMs.push(performance.now() - t0);
      this.last = i;
    }
    destroy() { this.ro.disconnect(); this.imgs.forEach((r) => r && r.bm && r.bm.close()); this.imgs = []; }
  }

  Motion.ScrubVideo = ScrubVideo;
  Motion.ScrubFrames = ScrubFrames;

  // ---------------------------------------------------------------- effect
  // data-scrub on the tall section. Loads media only when the section is within
  // 1.5 screens (IntersectionObserver), ticks only while it is on screen.
  Motion.effect("scrub", (section, env) => {
    const stage = section.querySelector(".scrub__stage");
    const video = stage.querySelector("video"), canvas = stage.querySelector("canvas");
    const player = video ? new ScrubVideo(video, { mode: section.dataset.scrubMode })
                         : new ScrubFrames(canvas);
    section._scrub = player;
    const state = { p: 0 };
    // Default: CSS sticky stage inside a tall section (no pin-spacer).
    // data-scrub-pin: classic ScrollTrigger pin of a 100vh section instead.
    const pin = section.hasAttribute("data-scrub-pin");
    if (pin) section.classList.add("scrub--pin");
    const length = () => stage.offsetHeight * (parseFloat(getComputedStyle(section).getPropertyValue("--scrub-length")) / 100 - 1 || 3);
    // proxy tween: scrub:0.4 smooths native (touch) scroll; with Lenis it adds a little extra glide
    gsap.to(state, {
      p: 1, ease: "none",
      scrollTrigger: pin
        ? { trigger: section, start: "top top", end: () => "+=" + length(), pin: true, anticipatePin: 1,
            scrub: parseFloat(section.dataset.scrubSmooth ?? "0.4"), invalidateOnRefresh: true }
        : { trigger: section, start: "top top", end: "bottom bottom",
            scrub: parseFloat(section.dataset.scrubSmooth ?? "0.4") },
      onUpdate: () => player.setProgress(state.p),
    });
    let active = false, loaded = false;
    // PITFALL (hit): one callback can carry several entries for the same target
    // (e.g. after ScrollTrigger reparents it into a pin-spacer) — read the LAST one.
    const io = new IntersectionObserver((entries) => {
      const e = entries[entries.length - 1];
      if (e.isIntersecting && !loaded) { loaded = true; player.load(); }
      active = e.isIntersecting;
    }, { rootMargin: "150% 0px 150% 0px" });
    io.observe(section);
    const tick = () => { if (active) player.tick(); };
    gsap.ticker.add(tick);
    return () => { gsap.ticker.remove(tick); io.disconnect(); player.destroy(); };
  });
})(window, document);
