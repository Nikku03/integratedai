/*!
 * Two Squares — contact.html: the enquiry form.
 * Prefill from the URL (venue, service, stage, from, item, message), inline
 * validation on blur + submit with an error summary, Netlify Forms submission
 * (urlencoded fetch), sending / success / network-error states.
 * Plain DOM code: it works with reduced motion and even if GSAP never loads.
 */
(function (w, d) {
  "use strict";
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const form = $("#enquiry");
  if (!form) return;

  /* ---------------------------------------------------------------- copy (verbatim from the deck) */
  const MSG = {
    name: { required: "We’ll need a name to reply to." },
    email: { required: "We’ll need an email to reply to.", invalid: "That email doesn’t look quite right. Check for a missing @ or a typo." },
    phone: { invalid: "That number doesn’t look right. Add the country code if you’re outside India." },
    city: { required: "Tell us roughly where the site is, even if it’s just the city." },
    message: { tooLong: "That’s a lot of detail, and we like it. Trim it to 2,000 characters, or attach it as a file." },
  };
  const SUMMARY = { one: "One thing needs a look before this can go.", many: "{n} things need a look before this can go." };
  const BANNER = {
    "menu-card": "From the corner table: {item}. Change anything below.",
    services: "From the menu: {item}. Change anything below.",
    // case studies send venue + item too: those prefill the chips and travel in the hidden
    // "item" field, but the deck only gives a banner for the two menus
  };
  const SEND = "Send it over", SENDING = "Sending…";
  const NETWORK = "That didn’t send, and it’s our end, not yours. Your details are still here. Try again, or email hello@twosquares.studio.";
  const BUDGET = {
    INR: [["not-sure", "Not sure yet"], ["under-25l", "Under ₹25 lakh"], ["25-60l", "₹25–60 lakh"], ["60l-1.5cr", "₹60 lakh – ₹1.5 crore"], ["over-1.5cr", "Over ₹1.5 crore"]],
    USD: [["not-sure", "Not sure yet"], ["under-50k", "Under US$50k"], ["50-150k", "US$50k–150k"], ["150-400k", "US$150k–400k"], ["over-400k", "Over US$400k"]],
  };

  /* ---------------------------------------------------------------- what the other pages send */
  // café menu card (home): contact.html?venue=cafe&service=whole-venue&from=menu-card&item=whole-cafe
  const MENU = {
    "whole-cafe": { name: "The whole café", prefill: { venue: "cafe", service: "whole-venue", message: "We’d like the whole café designed and built." } },
    "just-the-counter": { name: "Just the counter", prefill: { venue: "cafe", service: "counter", message: "We’d like to rework the counter and workstation." } },
    "a-refresh": { name: "A refresh", prefill: { venue: "cafe", service: "refresh", stage: "trading", message: "We’re open and trading, and the room needs a refresh." } },
    "something-else": { name: "Something else", prefill: { service: "not-sure", message: "" } },
  };
  // services page: contact.html?service=…&stage=…&from=services&item=<id>
  const SERVICES = {
    "site-visit": { name: "Site visit & feasibility", prefill: { service: "feasibility", stage: "looking" } },
    "test-fit": { name: "The test-fit", prefill: { service: "feasibility", stage: "looking" } },
    "whole-venue": { name: "The whole venue, designed & built", prefill: { service: "whole-venue" } },
    "design-only": { name: "Design only", prefill: { service: "design-only" } },
    "build-only": { name: "Build only", prefill: { service: "build-only", stage: "drawings" } },
    counter: { name: "The counter or workstation", prefill: { service: "counter" } },
    refresh: { name: "A refresh", prefill: { service: "refresh", stage: "trading" } },
    lighting: { name: "Lighting only", prefill: { service: "lighting" } },
    signage: { name: "Signage & brand touchpoints", prefill: { service: "signage" } },
    rollout: { name: "Roll-out for multi-site operators", prefill: { service: "rollout", stage: "multi" } },
    aftercare: { name: "Aftercare", prefill: { service: "aftercare", stage: "trading" } },
  };
  // case studies: contact.html?venue=…&from=case-study&item=<slug>
  const CASES = {
    "common-hours": { name: "Common Hours", prefill: { venue: "cafe" } },
    ember: { name: "Ember", prefill: { venue: "restaurant" } },
    stillroom: { name: "Stillroom", prefill: { venue: "bar" } },
    dhaaga: { name: "Dhaaga", prefill: { venue: "shop" } },
    otla: { name: "Otla", prefill: { venue: "restaurant" } },
    tilt: { name: "Tilt", prefill: { venue: "cafe" } },
  };
  const SOURCES = { "menu-card": MENU, services: SERVICES, "case-study": CASES };
  // tolerate the sector words other pages use (work filters, plurals, accents)
  const VENUE_ALIASES = {
    cafe: "cafe", "café": "cafe", cafes: "cafe", "cafés": "cafe", coffee: "cafe",
    restaurant: "restaurant", restaurants: "restaurant",
    bar: "bar", bars: "bar",
    shop: "shop", shops: "shop", retail: "shop", store: "shop",
    bakery: "bakery", bakeries: "bakery",
    hotel: "hotel", "hotel-fb": "hotel", hotels: "hotel",
    other: "other", "something-else": "other",
  };

  /* ---------------------------------------------------------------- elements */
  const summary = $("#form-errors"), summaryTitle = $("#form-errors-title"), summaryList = $("#form-errors-list");
  const banner = $("#prefill"), bannerText = $("#prefill-text"), clearBtn = $("#prefill-clear");
  const done = $("#enquiry-done"), netErr = $("#enquiry-neterr"), status = $("#enquiry-status");
  const submit = $(".enquiry__submit", form), submitLabel = $(".enquiry__submit-label", form);
  const reqNote = $(".enquiry__req", form);
  const state = { from: "", item: null, itemId: "", sending: false };
  const reduce = () => w.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scrollToEl = (el) => {
    const L = w.Motion && w.Motion.lenis;
    // showing the summary / success grows or shrinks the page above the viewport; the
    // browser's scroll anchoring moves the page before Lenis hears of it, so sync first
    if (L && Math.abs(L.animatedScroll - w.scrollY) > 1) L.scrollTo(w.scrollY, { immediate: true, force: true });
    if (w.Motion && w.Motion.scrollTo) w.Motion.scrollTo(el, { duration: 0.9 });
    else el.scrollIntoView({ block: "start", behavior: reduce() ? "auto" : "smooth" });
  };
  const fmt = (n) => n.toLocaleString("en-IN");

  /* ---------------------------------------------------------------- controls */
  const setRadio = (name, value) => {
    const r = value && form.querySelector(`input[type="radio"][name="${name}"][value="${CSS.escape(value)}"]`);
    if (r) r.checked = true;
    return !!r;
  };
  const setSelect = (id, value) => {
    const s = form.querySelector("#f-" + id);
    if (!s || !value) return false;
    const opt = Array.from(s.options).find((o) => o.value === value);
    if (opt) s.value = value;
    return !!opt;
  };

  // budget currency toggle: same five bands, so the chosen position carries across
  const budget = $("#f-budget"), currencyInput = $("#f-currency");
  function setCurrency(cur) {
    if (!budget || !BUDGET[cur]) return;
    const idx = budget.selectedIndex;
    const first = budget.options[0];
    budget.replaceChildren(first, ...BUDGET[cur].map(([v, l]) => new Option(l, v)));
    budget.selectedIndex = idx;
    if (currencyInput) currencyInput.value = cur;
    $$(".currency__opt", form).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.currency === cur)));
  }
  $$(".currency__opt", form).forEach((b) => b.addEventListener("click", () => setCurrency(b.dataset.currency)));

  // message counter
  const message = $("#f-message"), countNow = $("[data-count-now]", form), countEl = $(".field__count", form);
  const MAX = 2000;
  function updateCount() {
    if (!message || !countNow) return;
    const n = message.value.length;
    countNow.textContent = fmt(n);
    countEl.classList.toggle("is-over", n > MAX);
  }
  message && message.addEventListener("input", updateCount);

  /* ---------------------------------------------------------------- prefill from the URL */
  function prefill() {
    const q = new URLSearchParams(location.search);
    const from = (q.get("from") || "").trim().toLowerCase();
    const itemId = (q.get("item") || "").trim().toLowerCase();
    const source = SOURCES[from];
    const item = source && itemId ? source[itemId] : null;
    const defaults = (item && item.prefill) || {};
    const pick = (k) => (q.has(k) ? (q.get(k) || "").trim() : defaults[k] || "");

    const venueRaw = pick("venue").toLowerCase();
    setRadio("venue", VENUE_ALIASES[venueRaw] || venueRaw);
    setSelect("service", pick("service").toLowerCase());
    setSelect("stage", pick("stage").toLowerCase());
    const msg = pick("message");
    if (msg && message && !message.value) { message.value = msg.slice(0, MAX * 2); updateCount(); }

    state.from = from; state.itemId = itemId; state.item = item;
    $("#f-from").value = from || "";
    $("#f-item").value = item ? item.name : itemId;

    if (item && BANNER[from]) {
      const [pre, post] = BANNER[from].split("{item}");
      const em = d.createElement("em"); em.textContent = item.name;
      bannerText.replaceChildren(pre, em, post);
      banner.hidden = false;
    }
  }

  clearBtn && clearBtn.addEventListener("click", () => {
    form.reset();
    $("#f-from").value = ""; $("#f-item").value = "";   // hidden inputs keep programmatic values through reset()
    setCurrency("INR");
    updateCount();
    $$("[data-field]", form).forEach((f) => { setError(f, ""); delete f.dataset.dirty; });
    hideSummary();
    state.from = ""; state.item = null; state.itemId = "";
    banner.hidden = true;
    try { history.replaceState(history.state, "", location.pathname); } catch (_) {}
    const name = $("#f-name");
    name && name.focus();
  });

  /* ---------------------------------------------------------------- validation */
  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const phoneOk = (v) => /^[+()\-.\s\d]+$/.test(v) && (v.match(/\d/g) || []).length >= 8 && (v.match(/\d/g) || []).length <= 15;

  function check(field) {
    const id = field.dataset.field;
    const rules = (field.dataset.rules || "").split(",").filter(Boolean);
    const ctl = $(".field__control", field);
    if (!rules.length || !ctl) return "";
    const v = ctl.value.trim(), m = MSG[id] || {};
    if (rules.includes("required") && !v) return m.required;
    if (rules.includes("email") && v && !EMAIL.test(v)) return m.invalid;
    if (rules.includes("phone") && v && !phoneOk(v)) return m.invalid;
    const max = rules.find((r) => r.startsWith("max:"));
    if (max && ctl.value.length > +max.slice(4)) return m.tooLong;
    return "";
  }

  function setError(field, msg) {
    const ctl = $(".field__control", field), err = $(".field__error", field);
    if (!ctl || !err) return;
    const ids = (ctl.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== err.id);
    field.classList.toggle("is-invalid", !!msg);
    if (msg) {
      err.textContent = msg; err.hidden = false;
      ctl.setAttribute("aria-invalid", "true");
      ids.unshift(err.id);
    } else {
      err.textContent = ""; err.hidden = true;
      ctl.removeAttribute("aria-invalid");
    }
    if (ids.length) ctl.setAttribute("aria-describedby", ids.join(" "));
    else ctl.removeAttribute("aria-describedby");
  }

  const validated = () => $$("[data-field][data-rules]", form).filter((f) => f.dataset.rules);

  function renderSummary(errors) {
    summaryTitle.textContent = errors.length === 1 ? SUMMARY.one : SUMMARY.many.replace("{n}", errors.length);
    summaryList.replaceChildren(...errors.map(({ field, msg }) => {
      const ctl = $(".field__control", field);
      const li = d.createElement("li"), a = d.createElement("a");
      a.href = "#" + ctl.id; a.textContent = msg; a.dataset.for = ctl.id;
      li.appendChild(a); return li;
    }));
    summary.hidden = false;
  }
  function hideSummary() { summary.hidden = true; summaryList.replaceChildren(); }
  // keep an open summary honest as fields are fixed
  function refreshSummary() {
    if (summary.hidden) return;
    const errors = validated().map((field) => ({ field, msg: check(field) })).filter((e) => e.msg);
    if (!errors.length) hideSummary(); else renderSummary(errors);
  }

  // blur: validate anything the visitor has touched (don't shout at a field just tabbed past)
  form.addEventListener("focusout", (e) => {
    const field = e.target.closest && e.target.closest("[data-field]");
    if (!field || !field.dataset.rules) return;
    if (field.dataset.dirty || field.classList.contains("is-invalid")) { setError(field, check(field)); refreshSummary(); }
  });
  // typing: once a field is marked wrong, clear it the moment it's right
  form.addEventListener("input", (e) => {
    const field = e.target.closest && e.target.closest("[data-field]");
    if (!field) return;
    if (e.target.value && e.target.value.trim()) field.dataset.dirty = "1";
    if (field.classList.contains("is-invalid") || (field.dataset.field === "message" && check(field))) {
      setError(field, check(field)); refreshSummary();
    }
  });

  // summary links: focus the control itself (not a scroll-to-anchor, which would break the tab order)
  summary.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-for]");
    if (!a) return;
    e.preventDefault();
    const ctl = d.getElementById(a.dataset.for);
    if (!ctl) return;
    scrollToEl(ctl.closest("[data-field]") || ctl);
    ctl.focus({ preventScroll: true });
  });

  /* ---------------------------------------------------------------- submit */
  function setSending(on) {
    state.sending = on;
    form.classList.toggle("is-sending", on);
    form.setAttribute("aria-busy", String(on));
    submitLabel.textContent = on ? SENDING : SEND;
    if (on) submit.setAttribute("aria-disabled", "true"); else submit.removeAttribute("aria-disabled");
    if (status) status.textContent = on ? SENDING : "";
  }

  function showSuccess(preview) {
    const nameVal = ($("#f-name") && $("#f-name").value.trim()) || "";
    const first = nameVal.split(/\s+/)[0] || "there";
    const fromMenu = !!state.item && (state.from === "menu-card" || state.from === "services");
    const title = $("#done-title"), body = $("#done-body");
    if (fromMenu) {
      title.innerHTML = "Order’s <em>in</em>.";
      body.textContent = `Thanks, ${first}. ${state.item.name}, noted. We’ll reply within two working days with a few questions and a time to talk.`;
      $("#done-secondary").hidden = true;
      $("#done-button-label").textContent = "Back to the street";
      $("#done-button").setAttribute("href", "index.html");
    } else {
      body.textContent = `Thanks, ${first}. We read every enquiry ourselves, and you’ll hear from one of the team within two working days — sooner if you mentioned a lease deadline.`;
    }
    $("#done-preview").hidden = !preview;
    form.hidden = true; banner.hidden = true;
    done.hidden = false;
    setSending(false);
    if (status) status.textContent = "";
    const wrapTop = done.closest(".contact-body__form") || done;
    if (wrapTop.getBoundingClientRect().top < 0 || wrapTop.getBoundingClientRect().top > innerHeight * 0.6) scrollToEl(wrapTop);
    title.focus({ preventScroll: true });
    if (w.ScrollTrigger) requestAnimationFrame(() => w.ScrollTrigger.refresh());
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.sending) return;
    netErr.textContent = "";

    const errors = [];
    validated().forEach((field) => {
      const msg = check(field);
      setError(field, msg);
      if (msg) errors.push({ field, msg });
    });
    if (errors.length) {
      renderSummary(errors);
      scrollToEl(summary);
      summary.focus({ preventScroll: true });
      return;
    }
    hideSummary();

    // the honeypot caught something: look sent, send nothing
    const hp = form.querySelector('input[name="bot-field"]');
    if (hp && hp.value) { showSuccess(false); return; }

    setSending(true);
    const body = new URLSearchParams(new FormData(form)).toString();
    const local = location.protocol === "file:";
    try {
      let ok = false;
      if (!local) {
        const ctrl = "AbortController" in w ? new AbortController() : null;
        const timer = ctrl && setTimeout(() => ctrl.abort(), 15000);
        // Netlify Forms: an urlencoded POST (with form-name) to the site root, as its docs do for AJAX
        const res = await fetch("/", {
          method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
          signal: ctrl ? ctrl.signal : undefined,
        });
        clearTimeout(timer);
        ok = res.ok;
      }
      // not ok = no Netlify behind this preview (e.g. a local server): still show the success state
      showSuccess(!ok);
    } catch (err) {
      setSending(false);
      netErr.textContent = NETWORK;
    }
  });

  /* ---------------------------------------------------------------- boot */
  prefill();
  updateCount();
  // arrived back from a no-JS Netlify post (action="contact.html?sent=1")
  if (new URLSearchParams(location.search).get("sent") === "1") showSuccess(false);
})(window, document);
