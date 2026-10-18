/* FitChat front end. Plain JS, no build step: the FastAPI server serves this folder. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, cls, html) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtNum = (n, d = 0) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: d });
  const titleCase = (s) => String(s).replace(/_/g, ' ');

  const state = { summary: null, injuries: [], unavailable: [], foods: null, ingredients: null, sending: false, sheet: null, page: null };

  /* ---------- API ---------- */
  async function api(path, { method = 'GET', body, timeout = 20000 } = {}) {
    const auth = window.FCAuth;
    for (let attempt = 0; attempt < 2; attempt++) {
      const extra = auth ? await auth.headers() : {};  // waits here until signed in (hosted); nothing to wait for on a laptop
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), timeout);
      try {
        const res = await fetch(path, {
          method,
          headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...extra },
          body: body ? JSON.stringify(body) : undefined,
          signal: ctl.signal,
        });
        if (res.status === 401 && auth && attempt === 0) { if (await auth.expired()) continue; }
        if (!res.ok) {
          let msg = res.statusText;
          try {
            const j = await res.json();
            msg = typeof j.detail === 'string' ? j.detail
              : Array.isArray(j.detail) ? j.detail.map((d) => `${(d.loc || []).slice(1).join(' ')}: ${d.msg}`).join('; ')
              : JSON.stringify(j.detail);
          } catch (_) { /* keep statusText */ }
          if (res.status === 503 && /paused/i.test(msg) && auth) auth.showPaused();
          const err = new Error(msg);
          err.status = res.status;
          throw err;
        }
        return res.status === 204 ? null : res.json();
      } finally {
        clearTimeout(timer);
      }
    }
  }

  /* ---------- small helpers ---------- */
  let toastTimer;
  function toast(text) {
    const t = $('#toast');
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  // Minimal, safe formatting: escape first, then allow bold, italics, bullet and numbered lists.
  function inline(s) {
    return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, '$1<em>$2</em>');
  }
  function format(text) {
    const lines = esc(text).split('\n');
    let html = '';
    let list = null; // 'ul' | 'ol'
    const close = () => { if (list) { html += `</${list}>`; list = null; } };
    for (const raw of lines) {
      const line = raw.trimEnd();
      let m;
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
        if (list !== 'ul') { close(); html += '<ul>'; list = 'ul'; }
        html += `<li>${inline(m[1])}</li>`;
      } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        if (list !== 'ol') { close(); html += '<ol>'; list = 'ol'; }
        html += `<li>${inline(m[1])}</li>`;
      } else if (!line.trim()) {
        close();
      } else {
        close();
        html += `<p>${inline(line)}</p>`;
      }
    }
    close();
    return html;
  }

  /* ---------- chat rendering ---------- */
  const chat = $('#chat');
  const scroller = $('#scroller');
  const empty = $('#empty');

  function scrollDown() { scroller.scrollTop = scroller.scrollHeight; }
  function syncEmpty() { empty.hidden = chat.children.length > 0; }

  function addMessage(role, text, opts = {}) {
    const wrap = el('div', `msg ${role}${opts.error ? ' error' : ''}${opts.degraded ? ' degraded' : ''}`);
    const body = el('div', 'msg-body');
    body.innerHTML = role === 'user' ? esc(text).replace(/\n/g, '<br>') : format(text);
    wrap.append(body);
    chat.append(wrap);
    syncEmpty();
    return wrap;
  }

  function exerciseCard(c) {
    const card = el('article', 'xcard');
    card.append(el('h3', null, esc(c.name)));
    const tags = [c.equipment, c.level, ...(c.primary_muscles || [])].filter(Boolean);
    if (tags.length) card.append(el('div', 'tags', tags.map((t) => `<span>${esc(t)}</span>`).join('')));

    const imgs = (c.images || []).slice(0, 2);
    if (imgs.length) {
      const shots = el('div', 'shots');
      imgs.forEach((url, i) => {
        const label = imgs.length > 1 ? (i === 0 ? 'Start' : 'Finish') : 'Form';
        const fig = el('figure');
        const btn = el('button', 'shot');
        btn.type = 'button';
        btn.setAttribute('aria-label', `Enlarge ${label.toLowerCase()} picture of ${c.name}`);
        const img = new Image();
        img.loading = 'lazy';
        img.alt = `${c.name}, ${label.toLowerCase()} position`;
        img.src = url;
        img.addEventListener('error', () => { btn.replaceWith(el('p', 'shot-broken', 'Picture did not load. Check your internet connection.')); });
        btn.append(img);
        btn.addEventListener('click', () => openLightbox(url, img.alt));
        fig.append(btn, el('figcaption', null, label));
        shots.append(fig);
      });
      card.append(shots);
    }
    const log = el('button', 'btn small log-sets', 'Log sets');
    log.type = 'button';
    log.setAttribute('aria-label', `Log sets for ${c.name}`);
    log.addEventListener('click', () => openWorkout({ id: c.id, name: c.name }));
    card.append(log);
    if ((c.secondary_muscles || []).length) card.append(el('p', 'also', `Also works: ${esc(c.secondary_muscles.join(', '))}`));
    if ((c.steps || []).length) {
      const d = el('details');
      d.append(el('summary', null, `Step-by-step (${c.steps.length})`));
      d.append(el('ol', null, c.steps.map((s) => `<li>${esc(s)}</li>`).join('')));
      card.append(d);
    }
    return card;
  }

  function addCards(cards) {
    for (const c of cards || []) if (c.type === 'exercise') chat.append(exerciseCard(c));
  }

  function openLightbox(url, alt) {
    $('#lbImg').src = url;
    $('#lbImg').alt = alt;
    $('#lightbox').showModal();
  }
  $('#lbClose').addEventListener('click', () => $('#lightbox').close());
  $('#lightbox').addEventListener('click', (e) => { if (e.target.id === 'lightbox') e.target.close(); });

  /* ---------- sending ---------- */
  const input = $('#input');
  const sendBtn = $('#send');

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  }
  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', (e) => {
    // On a keyboard, Enter sends and Shift+Enter adds a line. On phones Enter stays a new line.
    if (e.key === 'Enter' && !e.shiftKey && matchMedia('(pointer: fine)').matches) {
      e.preventDefault();
      $('#composer').requestSubmit();
    }
  });

  async function send(text) {
    if (state.sending || !text.trim()) return;
    state.sending = true;
    sendBtn.disabled = true;
    addMessage('user', text);
    const typing = el('div', 'typing', '<i></i><i></i><i></i><span>Working it out</span>');
    chat.append(typing);
    scrollDown();
    try {
      const r = await api('/api/chat', { method: 'POST', body: { message: text }, timeout: 120000 });
      typing.remove();
      addMessage('assistant', r.reply, { degraded: r.degraded });
      addCards(r.cards);
      refreshSummary();
      refreshStatus();
    } catch (err) {
      typing.remove();
      addMessage('assistant', err.status ? err.message : "Can't reach the server. Check that it's running and that your phone is on the same Wi-Fi as the laptop, then send it again.", { error: true });
      input.value = text;
      autoGrow();
    } finally {
      state.sending = false;
      sendBtn.disabled = false;
      scrollDown();
    }
  }

  $('#composer').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    autoGrow();
    send(text);
  });
  $$('.example').forEach((b) => b.addEventListener('click', () => send(b.textContent)));

  /* ---------- header macros ---------- */
  function setBar(id, eaten, target) {
    const bar = $(id);
    const pct = target > 0 ? Math.min(100, (eaten / target) * 100) : 0;
    $('i', bar).style.width = `${pct}%`;
    bar.classList.toggle('over', target > 0 && eaten > target);
    bar.setAttribute('aria-label', `${fmtNum(eaten)} of ${fmtNum(target)}`);
  }

  function renderMacros(s) {
    const r = s.remaining;
    const calLeft = r.calories_remaining;
    $('#calBig').textContent = fmtNum(Math.abs(calLeft));
    $('#calUnit').textContent = calLeft >= 0 ? 'kcal left' : 'kcal over';
    $('#calSub').textContent = `${fmtNum(r.calories_eaten)} of ${fmtNum(r.calorie_target)}`;
    setBar('#calBar', r.calories_eaten, r.calorie_target);

    const proLeft = r.protein_remaining_g;
    $('#proBig').textContent = fmtNum(Math.abs(proLeft));
    $('#proUnit').textContent = proLeft >= 0 ? 'g protein left' : 'g protein over';
    $('#proSub').textContent = `${fmtNum(r.protein_eaten_g)} of ${fmtNum(r.protein_target_g)} g`;
    setBar('#proBar', r.protein_eaten_g, r.protein_target_g);

    const note = $('#trainNote');
    note.hidden = !(r.training_day_bonus > 0);
    note.textContent = r.training_day_bonus > 0 ? `+${fmtNum(r.training_day_bonus)} kcal for training` : '';
    $('#macros').classList.remove('stale');
    const gl = $('#gutLine');
    if (gl && s.gut) {
      const g = s.gut;
      gl.textContent = `Water ${fmtNum(g.water_ml / 1000, 1)} of ${fmtNum(g.water_target_ml / 1000, 1)} L \u00b7 Fibre ${fmtNum(g.fibre_g)} of ${fmtNum(g.fibre_target_g)} g${g.alert === 'see_doctor' ? ' \u00b7 see a doctor' : ''}`;
      gl.classList.toggle('alert', g.alert === 'see_doctor');
    }
  }

  function setBadge(id, n, warn) {
    const b = $(id);
    if (!b) return;
    b.hidden = !n;
    b.textContent = n || '';
    b.classList.toggle('warn', !!warn);
  }

  async function refreshSummary() {
    try {
      state.summary = await api('/api/summary/today');
      renderMacros(state.summary);
      const rd = state.summary.readiness;
      setBadge('#badgeState', rd.reported_today ? '\u2713' : '', false);
      if (state.sheet) state.sheet.render();
      document.dispatchEvent(new Event('fc:summary'));
    } catch (_) {
      $('#macros').classList.add('stale');
    }
  }

  async function refreshStatus() {
    try {
      const [inj, gear, wk] = await Promise.all([api('/api/injuries'), api('/api/equipment/unavailable'), api('/api/workout/today')]);
      setBadge('#badgeWorkout', wk.total_sets || '', false);
      state.injuries = inj;
      state.unavailable = gear;
      setBadge('#badgeInjury', inj.length, true);
      setBadge('#badgeGear', gear.length, false);
      if (state.sheet) state.sheet.render();
    } catch (_) { /* header badges are optional */ }
  }

  /* ---------- bottom sheets ---------- */
  const sheet = $('#sheet');
  const sheetBody = $('#sheetBody');

  /* One render at a time per container. Screens load data with await, so two renders could overlap and an older one
     could finish last and paint stale rows over a newer view. Calls that arrive mid-render collapse into one re-run. */
  const runners = new WeakMap();
  function runRender(host, render) {
    let r = runners.get(host);
    if (!r) { r = { busy: false, again: false, fn: null }; runners.set(host, r); }
    r.fn = render;
    if (r.busy) { r.again = true; return Promise.resolve(); }
    r.busy = true;
    return (async () => {
      try {
        do {
          r.again = false;
          try { await r.fn(host); } catch (err) { console.error(err); }
        } while (r.again);
      } finally { r.busy = false; }
    })();
  }

  function openSheet(title, render) {
    $('#sheetTitle').textContent = title;
    state.sheet = { render: () => runRender(sheetBody, render) };
    state.sheet.render();
    if (!sheet.open) sheet.showModal();
  }
  function closeSheet() { if (sheet.open) sheet.close(); }
  // The close event arrives a moment after close(); if the sheet was already reopened by then, leave the new one alone.
  sheet.addEventListener('close', () => {
    if (sheet.open) return;
    state.sheet = state.page; foodFilter.day = null; foodFilter.dayData = null;
    if (state.page) state.page.render();
  });
  const pageBody = $('#pageBody');
  function openPage(title, render) {
    $('#pageTitle').textContent = title;
    state.page = { render: () => runRender(pageBody, render) };
    if (!sheet.open) state.sheet = state.page;
    state.page.render();
    pageBody.scrollTop = 0;
  }
  function leavePage() { state.page = null; if (!sheet.open) state.sheet = null; }
  sheet.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); });
  $('#sheetClose').addEventListener('click', closeSheet);

  async function guarded(fn, failText) {
    try { return await fn(); } catch (err) { toast(`${failText}: ${err.message}`); return undefined; }
  }

  /* Add food */
  const blankDraft = (basis = '100g') => ({ basis, name: '', aliases: '', calories: '', protein_g: '', carbs_g: '', fat_g: '', fibre_g: '', serving_g: '', serving_label: '', dish_serving: '' });
  const foodFilter = { q: '', qty: {}, grams: {}, mode: 'dishes', view: 'list', day: null, dayData: null, draft: blankDraft(), editing: null, online: { q: '', results: null, busy: false, error: '' } };
  const reloadFoods = () => { state.foods = null; state.ingredients = null; foodFilter.grams = {}; foodFilter.qty = {}; }; // ids can be reused after a delete, so drop typed amounts

  const foodDayBody = () => (foodFilter.day ? { day: foodFilter.day } : {});
  const foodChanged = () => { foodFilter.dayData = null; planUI.data = null; if (typeof dayUI !== 'undefined') dayUI.data = null; refreshSummary(); };
  const planUI = { data: null, exclude: [], busy: false };

  async function renderFood(root) {
    if (!state.foods) {
      root.innerHTML = '<p class="hint">Loading foods</p>';
      state.foods = await guarded(() => api('/api/foods'), 'Could not load foods');
      if (!state.foods) { root.innerHTML = '<p class="hint">Could not load the food list. Check the server and try again.</p>'; return; }
    }
    if (!state.ingredients) state.ingredients = (await guarded(() => api('/api/ingredients'), 'Could not load ingredients')) || null;
    if (foodFilter.day && !foodFilter.dayData) {
      foodFilter.dayData = await guarded(() => api(`/api/day/${foodFilter.day}`), 'Could not load that day');
      if (!foodFilter.dayData) { root.innerHTML = '<p class="hint">Could not load that day. Close this and try again.</p>'; return; }
    }
    if (foodFilter.view === 'form') { renderFoodForm(root); return; }
    if (foodFilter.view === 'online') { renderOnline(root); return; }
    if (foodFilter.view === 'recipe') { renderRecipeForm(root); return; }
    const keepFocus = document.activeElement && document.activeElement.id === 'foodSearch';
    root.innerHTML = '';

    const pastDay = foodFilter.day;
    const items = pastDay ? foodFilter.dayData.meals.flatMap((m) => m.items) : ((state.summary && state.summary.totals.items) || []);
    if (pastDay) {
      const bar = el('div', 'daybanner');
      bar.append(el('span', null, `Adding to <b>${esc(fmtDayLong(pastDay))}</b>`));
      const back = el('button', 'btn small', 'Back to daily log');
      back.type = 'button';
      back.dataset.action = 'back-to-day';
      back.addEventListener('click', () => { foodFilter.day = null; foodFilter.dayData = null; dayUI.data = null; openDay(pastDay); });
      bar.append(back);
      root.append(bar);
    }
    const today = el('section');
    today.append(el('h3', null, pastDay ? `Eaten on ${fmtDayLong(pastDay)}` : 'Eaten today'));
    if (!items.length) {
      today.append(el('p', 'hint', pastDay ? 'Nothing logged for this day yet.' : 'Nothing logged yet. Add something below, or just tell the coach what you ate.'));
    } else {
      const list = el('div', 'list');
      items.forEach((it) => {
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${it.qty === 1 ? '' : `${esc(it.qty)} &times; `}${esc(it.food)}${it.estimated ? ' (estimated)' : ''}</div><div class="meta">${fmtNum(it.kcal)} kcal, ${fmtNum(it.protein_g, 1)} g protein</div></div>`;
        const del = el('button', 'btn small', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove ${it.food}`);
        del.addEventListener('click', async () => {
          await guarded(() => api(`/api/meals/${it.id}`, { method: 'DELETE' }), 'Could not remove');
          toast('Removed');
          foodChanged();
        });
        row.append(del);
        list.append(row);
      });
      today.append(list);
    }
    root.append(today);

    const add = el('section');
    add.append(el('h3', null, 'Add something'));
    const modes = el('div', 'seg words');
    modes.style.marginBottom = '8px';
    [['dishes', 'Dishes'], ['weight', 'By weight'], ['recipes', 'Recipes'], ...(pastDay ? [] : [['plan', 'Plan']])].forEach(([key, label]) => {
      const b = el('button', null, label);
      b.type = 'button';
      b.dataset.mode = key;
      b.setAttribute('aria-pressed', String(foodFilter.mode === key));
      b.addEventListener('click', () => { foodFilter.mode = key; if (state.sheet) state.sheet.render(); });
      modes.append(b);
    });
    add.append(modes);
    if (foodFilter.mode === 'plan' && !pastDay) { renderPlan(add); root.append(add); return; }
    if (foodFilter.mode === 'plan') foodFilter.mode = 'dishes';
    const search = el('input', 'field');
    search.id = 'foodSearch';
    search.type = 'search';
    search.placeholder = foodFilter.mode === 'weight' ? 'Search rajma, rice, egg, paneer' : foodFilter.mode === 'recipes' ? 'Search your recipes' : 'Search roti, paneer, whey';
    search.setAttribute('aria-label', 'Search foods');
    search.value = foodFilter.q;
    add.append(search);
    const actions = el('div', 'actions');
    const mine = el('button', 'btn small', '+ My own food');
    mine.type = 'button';
    mine.dataset.action = 'new';
    mine.addEventListener('click', () => {
      if (foodFilter.mode === 'recipes') { startRecipe(null); return; }
      foodFilter.draft = blankDraft(foodFilter.mode === 'weight' ? '100g' : 'dish');
      foodFilter.draft.name = foodFilter.q.trim();
      foodFilter.editing = null;
      foodFilter.view = 'form';
      state.sheet.render();
    });
    if (foodFilter.mode === 'recipes') { mine.textContent = '+ New recipe'; mine.dataset.action = 'new-recipe'; }
    actions.append(mine);
    if (foodFilter.mode === 'weight') {
      const online = el('button', 'btn small', 'Search online');
      online.type = 'button';
      online.dataset.action = 'online';
      online.addEventListener('click', () => {
        foodFilter.online.q = foodFilter.q.trim();
        foodFilter.online.results = null;
        foodFilter.online.error = '';
        foodFilter.view = 'online';
        state.sheet.render();
      });
      actions.append(online);
    }
    add.append(actions);
    const list = el('div', 'list');
    list.style.marginTop = '8px';
    add.append(list);
    add.append(el('p', 'hint', foodFilter.mode === 'weight'
      ? 'Values are per 100 g of the food as eaten (cooked unless it says dry). Home-made curry or mixed dish? Tell the coach what went in.'
      : 'Not listed? Use By weight, or tell the coach in the chat and it will log an estimate, clearly marked as one.'));
    root.append(add);

    const paintDishes = () => {
      const q = foodFilter.q.trim().toLowerCase();
      const recipesOnly = foodFilter.mode === 'recipes';
      const shown = state.foods.filter((f) => (!recipesOnly || f.source === 'recipe') && (!q || f.name.toLowerCase().includes(q)));
      if (!shown.length) list.append(el('p', 'hint', recipesOnly ? 'No saved recipes yet. Tap + New recipe, or tell the coach how you cook a dish.' : 'No match. Try By weight, or the chat.'));
      shown.forEach((f) => {
        const qty = foodFilter.qty[f.id] || 1;
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${esc(f.name)}</div><div class="meta">${esc(f.serving)}: ${fmtNum(f.calories)} kcal, ${fmtNum(f.protein_g, 1)} g protein${f.fibre_g ? `, ${fmtNum(f.fibre_g, 1)} g fibre` : ''}</div></div>`;
        if (f.source === 'recipe') {
          row.querySelector('.name').insertAdjacentHTML('beforeend', ' <span class="tag">recipe</span>');
          row.querySelector('.meta').append(editLink(`Edit recipe ${f.name}`, async () => {
            const all = await guarded(() => api('/api/recipes'), 'Could not load the recipe');
            const rec = all && all.find((r) => r.food_id === f.id);
            if (rec) startRecipe(rec);
          }));
        } else row.querySelector('.meta').append(editLink(`Edit ${f.name}`, () => startEdit('dish', f)));
        const step = el('div', 'stepper');
        const minus = el('button', null, '&minus;');
        minus.type = 'button';
        minus.setAttribute('aria-label', `Fewer servings of ${f.name}`);
        const out = el('output', null, fmtNum(qty, 1));
        const plus = el('button', null, '+');
        plus.type = 'button';
        plus.setAttribute('aria-label', `More servings of ${f.name}`);
        const setQty = (v) => { foodFilter.qty[f.id] = Math.max(0.5, Math.min(20, v)); out.textContent = fmtNum(foodFilter.qty[f.id], 1); };
        minus.addEventListener('click', () => setQty((foodFilter.qty[f.id] || 1) - 0.5));
        plus.addEventListener('click', () => setQty((foodFilter.qty[f.id] || 1) + 0.5));
        step.append(minus, out, plus);
        const go = el('button', 'btn primary small', 'Add');
        go.type = 'button';
        go.addEventListener('click', async () => {
          const n = foodFilter.qty[f.id] || 1;
          go.disabled = true;
          const r = await guarded(() => api('/api/meals', { method: 'POST', body: { name: f.name, quantity: n, ...foodDayBody() } }), 'Could not add');
          go.disabled = false;
          if (r) { toast(`Added ${fmtNum(n, 1)} × ${f.name}`); foodFilter.qty[f.id] = 1; foodChanged(); }
        });
        row.append(step, go);
        list.append(row);
      });
    };

    const paintWeighed = () => {
      if (!state.ingredients) { list.append(el('p', 'hint', 'Could not load the ingredient table. Check the server and reopen this screen.')); return; }
      const q = foodFilter.q.trim().toLowerCase();
      const shown = state.ingredients.filter((i) => !q || i.name.toLowerCase().includes(q) || (i.aliases || []).some((a) => a.includes(q)));
      if (!shown.length) { list.append(el('p', 'hint', 'Not in the table. Tell the coach in the chat what it was and roughly how much.')); return; }
      shown.forEach((i) => {
        const row = el('div', 'row weigh');
        const piece = i.serving_g ? `; ${esc(i.serving_label)} = ${fmtNum(i.serving_g, 1)} g` : '';
        row.innerHTML = `<div class="grow"><div class="name">${esc(i.name)}${i.source !== 'seed_approx' ? ' <span class="tag">yours</span>' : ''}</div><div class="meta">per 100 g: ${fmtNum(i.calories_100g)} kcal, ${fmtNum(i.protein_100g, 1)} g protein${piece}</div></div>`;
        row.querySelector('.meta').append(editLink(`Edit ${i.name}`, () => startEdit('ingredient', i)));
        const ctl = el('div', 'weigh-ctl');
        const input = el('input', 'field grams');
        input.type = 'number';
        input.inputMode = 'decimal';
        input.min = '1';
        input.max = '5000';
        input.step = 'any';
        input.value = foodFilter.grams[i.id] != null ? foodFilter.grams[i.id] : (i.serving_g || 100);
        input.setAttribute('aria-label', `Grams of ${i.name}`);
        const unit = el('span', 'unit', 'g');
        const live = el('output', 'live');
        const go = el('button', 'btn primary small', 'Add');
        go.type = 'button';
        const grams = () => { const g = parseFloat(input.value); return Number.isFinite(g) && g > 0 && g <= 5000 ? g : null; };
        const update = () => {
          const g = grams();
          foodFilter.grams[i.id] = input.value;
          live.textContent = g ? `${fmtNum(Math.round(i.calories_100g * g) / 100)} kcal · ${fmtNum(Math.round(i.protein_100g * g) / 100, 1)} g protein` : 'Enter grams';
          go.disabled = !g;
        };
        const submit = async () => {
          const g = grams();
          if (!g) return;
          go.disabled = true;
          const r = await guarded(() => api('/api/meals/weighed', { method: 'POST', body: { ingredient_id: i.id, grams: g, ...foodDayBody() } }), 'Could not add');
          if (r) { toast(`Added ${fmtNum(g, 1)} g ${i.name}`); delete foodFilter.grams[i.id]; foodChanged(); } else update();
        };
        input.addEventListener('input', update);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
        go.addEventListener('click', submit);
        ctl.append(input, unit, live, go);
        row.append(ctl);
        update();
        list.append(row);
      });
    };

    const paint = () => { list.innerHTML = ''; (foodFilter.mode === 'weight' ? paintWeighed : paintDishes)(); };
    search.addEventListener('input', () => { foodFilter.q = search.value; paint(); });
    paint();
    if (keepFocus) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
  }

  /* My foods: add / edit form and online search */
  /* Rest-of-day meal plan */
  async function loadPlan(more) {
    if (more && planUI.data) planUI.exclude = [...new Set([...planUI.exclude, ...planUI.data.slots.flatMap((sl) => sl.items.map((i) => i.food))])];
    if (!more) planUI.exclude = [];
    const q = planUI.exclude.map((n) => `exclude=${encodeURIComponent(n)}`).join('&');
    planUI.busy = true;
    planUI.data = await guarded(() => api(`/api/plan${q ? `?${q}` : ''}`), 'Could not build a plan');
    planUI.busy = false;
  }

  async function logPlanItems(items, mealType) {
    for (const i of items) {
      const r = await guarded(() => api('/api/meals', { method: 'POST', body: { name: i.food, quantity: i.servings, meal_type: mealType } }), `Could not log ${i.food}`);
      if (!r) { foodChanged(); return false; }
    }
    foodChanged();
    return true;
  }

  async function renderPlan(root) {
    if (!planUI.data && !planUI.busy) {
      root.append(el('p', 'hint', 'Planning'));
      await loadPlan(false);
      if (!state.sheet || foodFilter.mode !== 'plan') return;
      state.sheet.render();
      return;
    }
    const d = planUI.data;
    if (!d && planUI.busy) { root.append(el('p', 'hint', 'Planning')); return; }
    if (!d) { root.append(el('p', 'hint', 'Could not build a plan. Check the server and try again.')); return; }
    const r = d.remaining;
    root.append(el('p', 'hint', `Left today: ${fmtNum(r.calories)} kcal, ${fmtNum(r.protein_g)} g protein, ${fmtNum(r.fibre_g)} g fibre.`));
    if (d.status !== 'plan') {
      root.append(el('p', 'planmsg', esc(d.summary)));
    } else {
      d.slots.forEach((sl) => {
        const card = el('div', 'plancard');
        card.dataset.slot = sl.slot;
        card.append(el('h4', null, `${esc(sl.label)} <span class="hint">${fmtNum(sl.totals.calories)} kcal, ${fmtNum(sl.totals.protein_g, 0)} g protein</span>`));
        sl.items.forEach((i) => {
          const row = el('div', 'planrow');
          row.append(el('span', 'grow', `${fmtNum(i.servings, 1)} &times; ${esc(i.food)} <span class="hint">${esc(i.serving)}, ${fmtNum(i.kcal)} kcal</span>`));
          const one = el('button', 'btn small', 'Log');
          one.type = 'button';
          one.setAttribute('aria-label', `Log ${i.food}`);
          one.addEventListener('click', async () => { one.disabled = true; if (await logPlanItems([i], sl.slot)) toast(`Logged ${i.food}`); });
          row.append(one);
          card.append(row);
        });
        const all = el('button', 'btn primary small', `Log whole ${sl.label.toLowerCase()}`);
        all.type = 'button';
        all.dataset.action = 'log-meal';
        all.addEventListener('click', async () => { all.disabled = true; if (await logPlanItems(sl.items, sl.slot)) toast(`${sl.label} logged`); });
        card.append(all);
        root.append(card);
      });
      const pd = d.projected_day;
      root.append(el('p', 'hint', `If you follow this the day ends near ${fmtNum(pd.calories)} of ${fmtNum(pd.calorie_target)} kcal and ${fmtNum(pd.protein_g, 0)} of ${fmtNum(pd.protein_target_g)} g protein.`));
    }
    (d.notes || []).forEach((n) => root.append(el('p', 'note', esc(n))));
    const wk = el('button', 'btn small', 'Plan the whole week and shopping list');
    wk.type = 'button';
    wk.dataset.action = 'week-from-food';
    wk.addEventListener('click', () => window.FC.openWeekPlan());
    root.append(wk);
    if (d.status === 'plan') {
      const more = el('button', 'btn', 'Another option');
      more.type = 'button';
      more.dataset.action = 'plan-more';
      more.addEventListener('click', async () => { more.disabled = true; await loadPlan(true); if (state.sheet) state.sheet.render(); });
      root.append(more);
    }
  }

  function editLink(label, onClick) {
    const b = el('button', 'linklike', 'Edit');
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.addEventListener('click', onClick);
    return b;
  }

  function startEdit(kind, row) {
    const d = blankDraft(kind === 'dish' ? 'dish' : '100g');
    d.name = row.name;
    d.aliases = (row.aliases || []).join(', ');
    if (kind === 'dish') {
      Object.assign(d, { dish_serving: row.serving, calories: row.calories, protein_g: row.protein_g, carbs_g: row.carbs_g, fat_g: row.fat_g, fibre_g: row.fibre_g || '' });
    } else {
      Object.assign(d, { calories: row.calories_100g, protein_g: row.protein_100g, carbs_g: row.carbs_100g, fat_g: row.fat_100g, fibre_g: row.fibre_100g || '',
        serving_g: row.serving_g || '', serving_label: row.serving_label || '' });
    }
    foodFilter.draft = d;
    foodFilter.editing = { kind, id: row.id, source: row.source };
    foodFilter.view = 'form';
    state.sheet.render();
  }

  const backToList = () => { foodFilter.view = 'list'; foodFilter.editing = null; state.sheet.render(); };
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

  function renderFoodForm(root) {
    const d = foodFilter.draft, ed = foodFilter.editing;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', backToList);
    root.append(back);

    const sec = el('section');
    sec.append(el('h3', null, ed ? 'Edit food' : 'Add your own food'));
    if (ed && ed.source === 'seed_approx') sec.append(el('p', 'hint', 'This is a built-in food. Saving makes it yours, and your numbers are kept from now on.'));
    if (!ed) {
      const seg = el('div', 'seg words');
      [['100g', 'Per 100 g'], ['serving', 'Per serving + grams'], ['dish', 'Dish (servings)']].forEach(([key, label]) => {
        const b = el('button', null, label);
        b.type = 'button';
        b.dataset.basis = key;
        b.setAttribute('aria-pressed', String(d.basis === key));
        b.addEventListener('click', () => { d.basis = key; state.sheet.render(); });
        seg.append(b);
      });
      sec.append(seg);
      sec.append(el('p', 'hint', {
        '100g': 'Numbers per 100 g, from the pack or a table. Best for ingredients and packaged foods.',
        serving: 'Numbers for one serving plus how many grams it weighs. They are converted to per 100 g, so you can log any weight later.',
        dish: 'For a plate or bowl you cannot weigh. Numbers for one serving; you log it in servings like your other dishes.',
      }[d.basis]));
    }

    const field = (label, key, attrs = {}) => {
      const wrap = el('label', 'flabel');
      wrap.append(el('span', null, label));
      const input = el('input', 'field');
      input.type = attrs.type || 'text';
      if (attrs.type === 'number') { input.inputMode = 'decimal'; input.step = 'any'; input.min = '0'; }
      if (attrs.placeholder) input.placeholder = attrs.placeholder;
      input.name = key;
      input.value = d[key];
      input.addEventListener('input', () => { d[key] = input.value; });
      wrap.append(input);
      return wrap;
    };

    const form = el('div', 'fform');
    form.append(field('Name', 'name', { placeholder: 'e.g. Protein bhel' }));
    form.append(field('Also called (optional, comma separated)', 'aliases', { placeholder: 'e.g. bhel, protein chaat' }));
    if (d.basis === 'serving') {
      const g = el('div', 'fgrid');
      g.append(field('One serving weighs (g)', 'serving_g', { type: 'number', placeholder: 'e.g. 60' }), field('Serving name', 'serving_label', { placeholder: 'e.g. 1 bar' }));
      form.append(g);
    }
    if (d.basis === 'dish') form.append(field('Serving', 'dish_serving', { placeholder: 'e.g. 1 katori, 1 plate' }));
    const per = d.basis === 'dish' ? 'per serving' : d.basis === 'serving' ? 'per serving' : 'per 100 g';
    const grid = el('div', 'fgrid');
    grid.append(field(`Calories ${per}`, 'calories', { type: 'number' }), field(`Protein (g) ${per}`, 'protein_g', { type: 'number' }),
      field('Carbs (g)', 'carbs_g', { type: 'number' }), field('Fat (g)', 'fat_g', { type: 'number' }), field('Fibre (g, optional)', 'fibre_g', { type: 'number' }));
    form.append(grid);
    if (d.basis === '100g') {
      const det = el('details', 'piece');
      det.open = Boolean(d.serving_g);
      det.append(el('summary', null, 'Countable item? (optional)'));
      const g = el('div', 'fgrid');
      g.append(field('One piece weighs (g)', 'serving_g', { type: 'number', placeholder: 'e.g. 50' }), field('Piece name', 'serving_label', { placeholder: 'e.g. 1 egg' }));
      det.append(g);
      form.append(det);
    }
    sec.append(form);

    const err = el('p', 'err');
    err.setAttribute('role', 'alert');
    err.hidden = true;
    const showErr = (m) => { err.textContent = m; err.hidden = !m; };
    form.addEventListener('input', () => showErr(''));
    const save = el('button', 'btn primary', ed ? 'Save changes' : 'Save food');
    save.type = 'button';
    save.dataset.action = 'save';
    save.addEventListener('click', async () => {
      showErr('');
      if (!d.name.trim()) { showErr('Give the food a name.'); return; }
      if (num(d.calories) == null || num(d.protein_g) == null) { showErr('Enter calories and protein.'); return; }
      if (d.basis === 'dish' && !d.dish_serving.trim()) { showErr('Say what one serving is, for example 1 katori.'); return; }
      if (d.basis === 'serving' && !(num(d.serving_g) > 0)) { showErr('Enter how many grams one serving weighs.'); return; }
      const aliases = d.aliases.split(',').map((a) => a.trim()).filter(Boolean);
      const vals = { calories: num(d.calories), protein_g: num(d.protein_g), carbs_g: num(d.carbs_g) || 0, fat_g: num(d.fat_g) || 0, fibre_g: num(d.fibre_g) || 0 };
      let path, body;
      if (d.basis === 'dish') { path = '/api/foods'; body = { name: d.name.trim(), aliases, serving: d.dish_serving.trim(), ...vals }; }
      else {
        path = '/api/ingredients';
        body = { name: d.name.trim(), aliases, basis: d.basis, ...vals };
        if (num(d.serving_g) > 0) body.serving_g = num(d.serving_g);
        if (d.serving_label.trim()) body.serving_label = d.serving_label.trim();
      }
      save.disabled = true;
      try {
        const saved = await api(ed ? `${path}/${ed.id}` : path, { method: ed ? 'PUT' : 'POST', body });
        reloadFoods();
        foodFilter.mode = d.basis === 'dish' ? 'dishes' : 'weight';
        foodFilter.q = saved.name;
        foodFilter.view = 'list';
        foodFilter.editing = null;
        toast(saved.warnings && saved.warnings.length ? saved.warnings[0] : `Saved ${saved.name}`);
        state.sheet.render();
      } catch (e) {
        showErr(e.message);
        save.disabled = false;
      }
    });
    sec.append(err, save);

    if (ed && ed.source !== 'seed_approx') {
      const del = el('button', 'btn danger', 'Delete this food');
      del.type = 'button';
      del.dataset.action = 'delete';
      let armed = false;
      del.addEventListener('click', async () => {
        if (!armed) {
          armed = true; del.textContent = 'Tap again to delete';
          setTimeout(() => { armed = false; del.textContent = 'Delete this food'; }, 4000);
          return;
        }
        const path = ed.kind === 'dish' ? `/api/foods/${ed.id}` : `/api/ingredients/${ed.id}`;
        const ok = await guarded(() => api(path, { method: 'DELETE' }), 'Could not delete');
        if (ok !== undefined) { reloadFoods(); foodFilter.q = ''; toast('Deleted. Past meals keep their numbers.'); backToList(); }
      });
      sec.append(del);
    }
    root.append(sec);
  }

  function renderOnline(root) {
    const o = foodFilter.online;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', backToList);
    root.append(back);
    const sec = el('section');
    sec.append(el('h3', null, 'Search Open Food Facts'));
    sec.append(el('p', 'hint', 'Free community database of packaged foods. Needs internet on the laptop running FitChat. Numbers are per 100 g; check them against your pack.'));
    const bar = el('div', 'inline');
    const input = el('input', 'field');
    input.id = 'onlineQ';
    input.type = 'search';
    input.placeholder = 'e.g. amul high protein lassi';
    input.setAttribute('aria-label', 'Search Open Food Facts');
    input.value = o.q;
    const go = el('button', 'btn primary small', 'Search');
    go.type = 'button';
    go.dataset.action = 'run-online';
    bar.append(input, go);
    sec.append(bar);
    const status = el('p', 'hint');
    const list = el('div', 'list');
    list.style.marginTop = '8px';
    sec.append(status, list);
    root.append(sec);

    const paint = () => {
      list.innerHTML = '';
      status.textContent = o.busy ? 'Searching' : o.error || (o.results && !o.results.length ? 'No usable results (products need calories and protein on file). Try other words, or add it yourself.' : '');
      (o.results || []).forEach((r) => {
        const row = el('div', 'row weigh');
        const piece = r.serving_g ? `; serving ${fmtNum(r.serving_g, 1)} g` : '';
        row.innerHTML = `<div class="grow"><div class="name">${esc(r.name)}${r.brand ? ` <span class="tag">${esc(r.brand)}</span>` : ''}</div><div class="meta">per 100 g: ${fmtNum(r.calories_100g)} kcal, ${fmtNum(r.protein_100g, 1)} g protein, ${fmtNum(r.carbs_100g, 1)} g carbs, ${fmtNum(r.fat_100g, 1)} g fat${piece}</div></div>`;
        const save = el('button', 'btn primary small', 'Save to my foods');
        save.type = 'button';
        save.addEventListener('click', async () => {
          save.disabled = true;
          const name = `${r.name}${r.brand ? ` (${r.brand})` : ''}`.slice(0, 80);
          const body = { name, source: 'openfoodfacts', calories: r.calories_100g, protein_g: r.protein_100g, carbs_g: r.carbs_100g, fat_g: r.fat_100g, fibre_g: r.fibre_100g || 0 };
          if (r.serving_g) { body.serving_g = r.serving_g; body.serving_label = r.serving_label || '1 serving'; }
          try {
            const saved = await api('/api/ingredients', { method: 'POST', body });
            reloadFoods();
            foodFilter.mode = 'weight';
            foodFilter.q = saved.name;
            foodFilter.view = 'list';
            toast('Saved. Enter the grams to log it.');
            state.sheet.render();
          } catch (e) { toast(e.message); save.disabled = false; }
        });
        row.append(save);
        list.append(row);
      });
    };
    const run = async () => {
      o.q = input.value.trim();
      if (o.q.length < 2) { o.error = 'Type at least 2 letters.'; o.results = null; paint(); return; }
      o.busy = true; o.error = ''; o.results = null; go.disabled = true; paint();
      try { o.results = (await api(`/api/online-foods?q=${encodeURIComponent(o.q)}`, { timeout: 25000 })).results; }
      catch (e) { o.error = e.message; }
      o.busy = false; go.disabled = false; paint();
    };
    go.addEventListener('click', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
    paint();
    if (o.q && o.results == null && !o.error && !o.busy) run();
  }

  /* Workout: log sets, see last time, personal bests and a progress line */
  const wUI = { view: 'today', ex: null, draft: { reps: '10', weight: '' }, today: null, progress: null, history: null, q: '', results: null, busy: false };
  const fmtDay = (d) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  // "12 x 40 kg (3 sets)" instead of repeating identical sets
  const groupSets = (sets) => {
    const out = [];
    sets.forEach((s) => { const t = setText(s); const last = out[out.length - 1]; if (last && last.t === t) last.n += 1; else out.push({ t, n: 1 }); });
    return out.map((g) => (g.n > 1 ? `${g.t} (${g.n} sets)` : g.t)).join(', ');
  };
  const setText = (s) => `${s.reps} × ${s.weight_kg > 0 ? `${fmtNum(s.weight_kg, 2)} kg` : 'bodyweight'}`;

  function openWorkout(ex) {
    wUI.fromRoutine = null; wUI.routines = null;
    wUI.view = ex ? 'log' : 'today';
    wUI.ex = ex || null;
    wUI.progress = null;
    wUI.today = null;
    openSheet('Workout', renderWorkout);
  }

  function setBadgeWorkout(n) { setBadge('#badgeWorkout', n || '', false); }

  async function loadToday() {
    const t = await guarded(() => api('/api/workout/today'), 'Could not load today’s workout');
    if (t) { wUI.today = t; setBadgeWorkout(t.total_sets); }
    return t;
  }

  async function loadProgress() {
    const p = await guarded(() => api(`/api/workout/progress/${encodeURIComponent(wUI.ex.id)}`), 'Could not load progress');
    if (p) {
      wUI.progress = p;
      // Start the next set from what was just done, else from last time (with the suggested weight when there is one).
      const mine = p.today[p.today.length - 1];
      const last = p.last && p.last.sets[p.last.sets.length - 1];
      const hint = p.last && p.last.next_weight_kg;
      if (mine) wUI.draft = { reps: String(mine.reps), weight: mine.weight_kg ? String(mine.weight_kg) : '' };
      else if (last) wUI.draft = { reps: String(last.reps), weight: hint || last.weight_kg ? String(hint || last.weight_kg) : '' };
      else wUI.draft = { reps: '10', weight: '' };
    }
    return p;
  }

  async function renderWorkout(root) {
    if (wUI.view === 'log' && wUI.ex) return renderLogger(root);
    if (wUI.view === 'progress') return renderProgressList(root);
    if (wUI.view === 'routine') return renderRoutinePlan(root);
    if (wUI.view === 'rlist') return renderRoutineList(root);
    if (wUI.view === 'redit') return renderRoutineEdit(root);
    return renderWorkoutToday(root);
  }

  async function renderWorkoutToday(root) {
    if (!wUI.today) { root.innerHTML = '<p class="hint">Loading</p>'; await loadToday(); if (!wUI.today) { root.innerHTML = '<p class="hint">Could not load. Check the server and reopen.</p>'; return; } }
    const t = wUI.today;
    root.innerHTML = '';
    if (!wUI.routines) { wUI.routines = (await guarded(() => api('/api/routines'), 'Could not load routines')) || { routines: [], suggestion: null, templates: [] }; }
    paintRoutineCard(root);
    const sec = el('section');
    sec.append(el('h3', null, 'Today'));
    if (!t.exercises.length) sec.append(el('p', 'hint', 'No sets logged yet. Search an exercise below, or tap Log sets on an exercise card in the chat.'));
    else {
      sec.append(el('p', 'hint', `${t.total_sets} set${t.total_sets === 1 ? '' : 's'} across ${t.exercises.length} exercise${t.exercises.length === 1 ? '' : 's'}${t.training_day_bonus ? `. Training day: +${t.training_day_bonus} kcal added to today’s target.` : '. Log 6 sets to count today as a training day (+150 kcal).'}`));
      const list = el('div', 'list');
      t.exercises.forEach((g) => {
        const row = el('div', 'row wex');
        row.innerHTML = `<div class="grow"><div class="name">${esc(g.name)}</div><div class="meta">${esc(groupSets(g.sets))}</div></div>`;
        const open = el('button', 'btn small', 'Add set');
        open.type = 'button';
        open.setAttribute('aria-label', `Add a set of ${g.name}`);
        open.addEventListener('click', () => { wUI.fromRoutine = null; wUI.ex = { id: g.exercise_id, name: g.name }; wUI.view = 'log'; wUI.progress = null; state.sheet.render(); });
        row.append(open);
        list.append(row);
      });
      sec.append(list);
    }
    root.append(sec);

    const add = el('section');
    add.append(el('h3', null, 'Add an exercise'));
    const search = el('input', 'field');
    search.id = 'exSearch';
    search.type = 'search';
    search.placeholder = 'Search: bench press, lat pulldown, curl';
    search.setAttribute('aria-label', 'Search exercises');
    search.value = wUI.q;
    add.append(search);
    const list = el('div', 'list');
    list.style.marginTop = '8px';
    add.append(list);
    root.append(add);
    const prog = el('button', 'btn', 'My progress and personal bests');
    prog.type = 'button';
    prog.dataset.action = 'progress';
    prog.addEventListener('click', () => { wUI.view = 'progress'; wUI.history = null; state.sheet.render(); });
    root.append(prog);

    const pick = (id, name) => { wUI.fromRoutine = null; wUI.ex = { id, name }; wUI.view = 'log'; wUI.progress = null; state.sheet.render(); };
    const paint = () => {
      list.innerHTML = '';
      if (wUI.busy) { list.append(el('p', 'hint', 'Searching')); return; }
      if (!wUI.q.trim()) {
        const recent = wUI.history || [];
        if (recent.length) list.append(el('p', 'hint', 'Your recent lifts'));
        recent.slice(0, 6).forEach((h) => {
          const b = el('button', 'row pickrow');
          b.type = 'button';
          b.innerHTML = `<div class="grow"><div class="name">${esc(h.name)}</div><div class="meta">last ${esc(fmtDay(h.last_day))}</div></div>`;
          b.addEventListener('click', () => pick(h.exercise_id, h.name));
          list.append(b);
        });
        return;
      }
      if (!wUI.results || !wUI.results.length) { list.append(el('p', 'hint', 'No exercise found. Try fewer words.')); return; }
      wUI.results.forEach((c) => {
        const b = el('button', 'row pickrow');
        b.type = 'button';
        b.innerHTML = `<div class="grow"><div class="name">${esc(c.name)}</div><div class="meta">${esc([c.equipment, ...(c.primary_muscles || [])].filter(Boolean).join(', '))}</div></div>`;
        b.addEventListener('click', () => pick(c.id, c.name));
        list.append(b);
      });
    };
    let timer;
    search.addEventListener('input', () => {
      wUI.q = search.value;
      clearTimeout(timer);
      if (!wUI.q.trim()) { wUI.results = null; paint(); return; }
      timer = setTimeout(async () => {
        const q = wUI.q.trim();
        wUI.busy = true; paint();
        const r = await guarded(() => api(`/api/exercises?q=${encodeURIComponent(q)}&category=strength&limit=8`), 'Search failed');
        wUI.busy = false;
        if (q === wUI.q.trim()) wUI.results = r || [];
        paint();
      }, 250);
    });
    // re-render when the list arrives (a painter closure from an earlier render may already be detached)
    if (wUI.history == null) { wUI.history = []; api('/api/workout/history').then((h) => { wUI.history = h; if (state.sheet && wUI.view === 'today') state.sheet.render(); }).catch(() => {}); }
    paint();
  }

  /* Rest timer: lives in the sheet footer, survives re-renders */
  const rest = { end: 0, total: 0, timer: null };
  const restDefault = () => { try { const v = parseInt(localStorage.getItem('fitchat.rest'), 10); return [0, 60, 90, 120, 180].includes(v) ? v : 90; } catch (_) { return 90; } };
  const setRestDefault = (v) => { try { localStorage.setItem('fitchat.rest', String(v)); } catch (_) { /* private mode: keep going */ } };
  function paintRest() {
    const bars = $$('.restbar');
    const left = Math.max(0, Math.ceil((rest.end - Date.now()) / 1000));
    if (!rest.end) { bars.forEach((b) => { b.hidden = true; }); return; }
    bars.forEach((bar) => {
      bar.hidden = false;
      $('.resttime', bar).textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
      $('.restfill', bar).style.width = `${rest.total ? Math.min(100, (100 * (rest.total - left)) / rest.total) : 100}%`;
    });
    if (left <= 0) {
      clearInterval(rest.timer); rest.timer = null; rest.end = 0;
      toast('Rest over. Next set.');
      try { if (navigator.vibrate) navigator.vibrate([200, 100, 200]); } catch (_) { /* not supported */ }
      bars.forEach((b) => { b.hidden = true; });
    }
  }
  function startRest(sec) {
    clearInterval(rest.timer); rest.timer = null; rest.end = 0;
    if (!sec) { paintRest(); return; }
    rest.total = sec; rest.end = Date.now() + sec * 1000;
    rest.timer = setInterval(paintRest, 250);
    paintRest();
  }
  function adjustRest(delta) {
    if (!rest.end) return;
    rest.end += delta * 1000; rest.total = Math.max(15, rest.total + delta);
    paintRest();
  }
  $$('.restskip').forEach((b) => b.addEventListener('click', () => startRest(0)));
  $$('.restminus').forEach((b) => b.addEventListener('click', () => adjustRest(-15)));
  $$('.restplus').forEach((b) => b.addEventListener('click', () => adjustRest(15)));

  /* Routines */
  const repText = (i) => (i.rep_min === i.rep_max ? `${i.rep_min}` : `${i.rep_min}–${i.rep_max}`);
  const goRoutines = (view) => { wUI.view = view; state.sheet.render(); };

  function paintRoutineCard(root) {
    const R = wUI.routines;
    const sec = el('section');
    sec.append(el('h3', null, 'Routines'));
    if (!R.routines.length) {
      sec.append(el('p', 'hint', 'Save your split once, then start it each gym day with last time’s numbers and a rest timer.'));
    } else {
      const sg = R.suggestion;
      if (sg && sg.routine_id) sec.append(el('p', 'suggest', `<b>Up next: ${esc(sg.name)}.</b> ${esc(sg.reason)}`));
      else if (sg) sec.append(el('p', 'hint', esc(sg.reason)));
      const list = el('div', 'list');
      R.routines.forEach((r) => {
        const row = el('div', 'row');
        row.dataset.routine = r.name;
        row.innerHTML = `<div class="grow"><div class="name">${esc(r.name)}</div><div class="meta">${r.exercises.length} exercises, ${r.total_sets} sets${r.last_done ? `, last ${esc(fmtDay(r.last_done))}` : ''}</div></div>`;
        const go = el('button', 'btn primary small', 'Start');
        go.type = 'button';
        go.setAttribute('aria-label', `Start ${r.name}`);
        go.addEventListener('click', () => { wUI.routineId = r.id; wUI.plan = null; wUI.swaps = {}; wUI.view = 'routine'; state.sheet.render(); });
        row.append(go);
        list.append(row);
      });
      sec.append(list);
    }
    const manage = el('button', 'btn small', R.routines.length ? 'Edit routines' : 'Set up routines');
    manage.type = 'button';
    manage.dataset.action = 'routines';
    manage.addEventListener('click', () => goRoutines('rlist'));
    sec.append(manage);
    root.append(sec);
  }

  async function renderRoutinePlan(root) {
    if (!wUI.plan || wUI.plan.id !== wUI.routineId) {
      root.innerHTML = '<p class="hint">Loading</p>';
      wUI.plan = await guarded(() => api(`/api/routines/${wUI.routineId}/plan`), 'Could not load the routine');
      if (!wUI.plan) { root.innerHTML = '<p class="hint">Could not load this routine. Go back and try again.</p>'; return; }
    }
    const p = wUI.plan;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', () => { wUI.view = 'today'; wUI.today = null; wUI.routines = null; state.sheet.render(); });
    root.append(back);
    const head = el('section');
    head.append(el('h3', null, esc(p.name)));
    head.append(el('p', 'hint', `${p.done_sets} of ${p.target_sets} sets done${p.complete ? '. Routine complete, nice work.' : ''}`));
    const prog = el('div', 'bar'); prog.append(el('i')); prog.firstChild.style.width = `${p.target_sets ? Math.min(100, (100 * p.done_sets) / p.target_sets) : 0}%`;
    head.append(prog);
    if (p.readiness && p.readiness.advice) head.append(el('p', 'hint', esc(p.readiness.advice)));
    root.append(head);

    const list = el('div', 'list rplan');
    p.exercises.forEach((x) => {
      const alt = wUI.swaps[x.exercise_id];
      const useId = alt ? alt.exercise_id : x.exercise_id;
      const useName = alt ? alt.name : x.name;
      const card = el('div', 'rex');
      card.dataset.exercise = x.name;
      const done = Math.min(x.sets_done, x.sets);
      card.append(el('div', 'name', `${esc(useName)}${alt ? ' <span class="tag">swapped</span>' : ''}`));
      card.append(el('div', 'meta', `Target ${x.sets} &times; ${repText(x)} · ${done}/${x.sets} sets`));
      const lt = x.last_time;
      if (lt && !alt) card.append(el('div', 'meta', `Last (${esc(fmtDay(lt.day))}): ${esc(groupSets(lt.sets))}${lt.next_hint ? `. ${esc(lt.next_hint)}` : ''}`));
      if (x.blocked && !alt) {
        card.append(el('div', 'blocked', `Skip or swap: ${esc(x.blocked)}`));
        const sw = el('div', 'inline');
        (x.alternatives || []).forEach((a) => {
          const b = el('button', 'btn small', esc(a.name));
          b.type = 'button';
          b.setAttribute('aria-label', `Swap to ${a.name}`);
          b.addEventListener('click', () => { wUI.swaps[x.exercise_id] = a; state.sheet.render(); });
          sw.append(b);
        });
        if (sw.children.length) card.append(sw);
      }
      if (alt) {
        const un = el('button', 'btn small', 'Undo swap');
        un.type = 'button';
        un.addEventListener('click', () => { delete wUI.swaps[x.exercise_id]; state.sheet.render(); });
        card.append(un);
      }
      const go = el('button', done >= x.sets ? 'btn small' : 'btn primary small', done >= x.sets ? 'Add another set' : `Log set ${done + 1}`);
      go.type = 'button';
      go.dataset.action = 'rlog';
      go.addEventListener('click', () => { wUI.fromRoutine = p.id; wUI.restS = x.rest_s; wUI.ex = { id: useId, name: useName }; wUI.view = 'log'; wUI.progress = null; state.sheet.render(); });
      card.append(go);
      list.append(card);
    });
    root.append(list);
  }

  async function renderRoutineList(root) {
    if (!wUI.routines) wUI.routines = (await guarded(() => api('/api/routines'), 'Could not load routines')) || { routines: [], suggestion: null, templates: [] };
    const R = wUI.routines;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', () => { wUI.view = 'today'; wUI.today = null; state.sheet.render(); });
    root.append(back);
    const mine = el('section');
    mine.append(el('h3', null, 'Your routines'));
    if (!R.routines.length) mine.append(el('p', 'hint', 'None yet. Start from a template below, or build your own.'));
    const list = el('div', 'list');
    R.routines.forEach((r) => {
      const row = el('div', 'row');
      row.innerHTML = `<div class="grow"><div class="name">${esc(r.name)}</div><div class="meta">${r.exercises.map((e) => esc(e.name)).slice(0, 3).join(', ')}${r.exercises.length > 3 ? ` +${r.exercises.length - 3} more` : ''}</div></div>`;
      const ed = el('button', 'btn small', 'Edit');
      ed.type = 'button';
      ed.setAttribute('aria-label', `Edit ${r.name}`);
      ed.addEventListener('click', () => {
        wUI.edit = { id: r.id, name: r.name, items: r.exercises.map((e) => ({ exercise_id: e.exercise_id, name: e.name, sets: e.sets, rep_min: e.rep_min, rep_max: e.rep_max, rest_s: e.rest_s })), q: '', results: null, err: '' };
        goRoutines('redit');
      });
      row.append(ed);
      list.append(row);
    });
    mine.append(list);
    const nw = el('button', 'btn primary small', '+ New routine');
    nw.type = 'button';
    nw.dataset.action = 'new-routine';
    nw.addEventListener('click', () => { wUI.edit = { id: null, name: '', items: [], q: '', results: null, err: '' }; goRoutines('redit'); });
    mine.append(nw);
    root.append(mine);

    const tp = el('section');
    tp.append(el('h3', null, 'Start from a template'));
    tp.append(el('p', 'hint', 'You can change anything after adding it.'));
    const tl = el('div', 'list');
    R.templates.forEach((t) => {
      const row = el('div', 'row');
      row.innerHTML = `<div class="grow"><div class="name">${esc(t.name)}</div><div class="meta">${esc(t.description)} ${t.exercises} exercises.</div></div>`;
      const add = el('button', 'btn small', 'Add');
      add.type = 'button';
      add.setAttribute('aria-label', `Add template ${t.name}`);
      add.addEventListener('click', async () => {
        add.disabled = true;
        const r = await guarded(() => api('/api/routines/from-template', { method: 'POST', body: { key: t.key } }), 'Could not add');
        if (r) { toast(`Added ${r.name}`); wUI.routines = null; state.sheet.render(); } else add.disabled = false;
      });
      row.append(add);
      tl.append(row);
    });
    tp.append(tl);
    root.append(tp);
  }

  function renderRoutineEdit(root) {
    const E = wUI.edit;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', () => goRoutines('rlist'));
    root.append(back);

    const name = el('input', 'field');
    name.id = 'rName'; name.placeholder = 'Routine name, e.g. Push A'; name.maxLength = 60; name.value = E.name;
    name.setAttribute('aria-label', 'Routine name');
    name.addEventListener('input', () => { E.name = name.value; });
    root.append(name);

    const items = el('div', 'list');
    items.style.marginTop = '8px';
    const numField = (it, key, label, min, max) => {
      const w = el('label', 'mini');
      w.append(el('span', null, label));
      const i = el('input', 'field');
      i.type = 'number'; i.inputMode = 'numeric'; i.min = min; i.max = max; i.value = it[key];
      i.setAttribute('aria-label', `${label} for ${it.name}`);
      i.addEventListener('input', () => { const v = parseInt(i.value, 10); it[key] = Number.isFinite(v) ? v : ''; });
      w.append(i);
      return w;
    };
    if (!E.items.length) items.append(el('p', 'hint', 'No exercises yet. Search and add below.'));
    E.items.forEach((it, idx) => {
      const card = el('div', 'rex');
      card.append(el('div', 'name', esc(it.name)));
      const fields = el('div', 'minis');
      fields.append(numField(it, 'sets', 'Sets', 1, 10), numField(it, 'rep_min', 'Reps from', 1, 100), numField(it, 'rep_max', 'to', 1, 100), numField(it, 'rest_s', 'Rest s', 15, 600));
      card.append(fields);
      const ctl = el('div', 'inline');
      const mv = (label, d) => { const b = el('button', 'btn small', label); b.type = 'button'; b.disabled = idx + d < 0 || idx + d >= E.items.length; b.setAttribute('aria-label', `${label === 'Up' ? 'Move up' : 'Move down'} ${it.name}`); b.addEventListener('click', () => { const [x] = E.items.splice(idx, 1); E.items.splice(idx + d, 0, x); state.sheet.render(); }); return b; };
      const rm = el('button', 'btn small', 'Remove');
      rm.type = 'button'; rm.setAttribute('aria-label', `Remove ${it.name}`);
      rm.addEventListener('click', () => { E.items.splice(idx, 1); state.sheet.render(); });
      ctl.append(mv('Up', -1), mv('Down', 1), rm);
      card.append(ctl);
      items.append(card);
    });
    root.append(items);

    const add = el('section');
    add.append(el('h3', null, 'Add an exercise'));
    const search = el('input', 'field');
    search.id = 'rSearch'; search.type = 'search'; search.placeholder = 'Search: bench press, squat, curl'; search.value = E.q;
    search.setAttribute('aria-label', 'Search exercises to add');
    add.append(search);
    const res = el('div', 'list');
    res.style.marginTop = '8px';
    add.append(res);
    root.append(add);
    const paint = () => {
      res.innerHTML = '';
      if (E.busy) { res.append(el('p', 'hint', 'Searching')); return; }
      if (!E.q.trim()) return;
      if (!E.results || !E.results.length) { res.append(el('p', 'hint', 'No exercise found. Try fewer words.')); return; }
      E.results.forEach((c) => {
        const b = el('button', 'row pickrow');
        b.type = 'button';
        b.innerHTML = `<div class="grow"><div class="name">${esc(c.name)}</div><div class="meta">${esc([c.equipment, ...(c.primary_muscles || [])].filter(Boolean).join(', '))}</div></div>`;
        b.addEventListener('click', () => {
          if (E.items.some((x) => x.exercise_id === c.id)) { toast('Already in this routine'); return; }
          E.items.push({ exercise_id: c.id, name: c.name, sets: 3, rep_min: 8, rep_max: 12, rest_s: 90 });
          E.q = ''; E.results = null; state.sheet.render();
        });
        res.append(b);
      });
    };
    let timer;
    search.addEventListener('input', () => {
      E.q = search.value; clearTimeout(timer);
      if (!E.q.trim()) { E.results = null; paint(); return; }
      timer = setTimeout(async () => {
        const q = E.q.trim();
        E.busy = true; paint();
        const r = await guarded(() => api(`/api/exercises?q=${encodeURIComponent(q)}&category=strength&limit=8`), 'Search failed');
        E.busy = false;
        if (q === E.q.trim()) E.results = r || [];
        paint();
      }, 250);
    });
    paint();

    const err = el('p', 'err'); err.setAttribute('role', 'alert'); err.hidden = !E.err; err.textContent = E.err;
    const save = el('button', 'btn primary big', E.id ? 'Save changes' : 'Save routine');
    save.type = 'button'; save.dataset.action = 'save-routine';
    save.addEventListener('click', async () => {
      if (!E.name.trim()) { E.err = 'Give the routine a name.'; err.textContent = E.err; err.hidden = false; return; }
      if (!E.items.length) { E.err = 'Add at least one exercise.'; err.textContent = E.err; err.hidden = false; return; }
      const body = { name: E.name.trim(), exercises: E.items.map((i) => ({ exercise_id: i.exercise_id, sets: Number(i.sets) || 0, rep_min: Number(i.rep_min) || 0, rep_max: Number(i.rep_max) || 0, rest_s: Number(i.rest_s) || 0 })) };
      save.disabled = true;
      try {
        await api(E.id ? `/api/routines/${E.id}` : '/api/routines', { method: E.id ? 'PUT' : 'POST', body });
        toast('Routine saved'); wUI.routines = null; goRoutines('rlist');
      } catch (e) { E.err = e.message; err.textContent = e.message; err.hidden = false; save.disabled = false; }
    });
    root.append(err, save);
    if (E.id) {
      const del = el('button', 'btn danger', 'Delete routine');
      del.type = 'button'; del.dataset.action = 'delete-routine';
      del.addEventListener('click', async () => {
        if (!del.dataset.sure) { del.dataset.sure = '1'; del.textContent = 'Tap again to delete'; return; }
        const ok = await guarded(() => api(`/api/routines/${E.id}`, { method: 'DELETE' }).then(() => true), 'Could not delete');
        if (ok) { toast('Deleted. Logged sets are kept.'); wUI.routines = null; goRoutines('rlist'); }
      });
      root.append(del);
    }
  }

  function numStepper(label, key, step, min, max, hint) {
    const d = wUI.draft;
    const wrap = el('div', 'nstep-wrap');
    wrap.append(el('div', 'nlabel', esc(label) + (hint ? ` <span class="nhint">${esc(hint)}</span>` : '')));
    const row = el('div', 'nstep');
    const minus = el('button', 'btn', '&minus;');
    minus.type = 'button';
    minus.setAttribute('aria-label', `Less ${label}`);
    const input = el('input', 'field');
    input.type = 'number'; input.inputMode = 'decimal'; input.step = 'any'; input.min = String(min); input.max = String(max);
    input.name = key; input.value = d[key];
    input.setAttribute('aria-label', label);
    const plus = el('button', 'btn', '+');
    plus.type = 'button';
    plus.setAttribute('aria-label', `More ${label}`);
    const bump = (dir) => {
      const cur = parseFloat(input.value);
      const v = Math.min(max, Math.max(min, (Number.isFinite(cur) ? cur : 0) + dir * step));
      input.value = String(Math.round(v * 100) / 100);
      d[key] = input.value;
    };
    minus.addEventListener('click', () => bump(-1));
    plus.addEventListener('click', () => bump(1));
    input.addEventListener('input', () => { d[key] = input.value; });
    row.append(minus, input, plus);
    wrap.append(row);
    return wrap;
  }

  // Single-series line of estimated 1-rep max (or best reps for bodyweight work), one point per session.
  function progressChart(history) {
    const pts = history.slice().reverse().map((h) => ({ day: h.day, v: h.e1rm > 0 ? h.e1rm : h.top_set.reps, top: h.top_set, e: h.e1rm }));
    const unit = history.some((h) => h.e1rm > 0) ? 'kg est. 1RM' : 'reps';
    const box = el('div', 'chart');
    if (pts.length < 2) { box.append(el('p', 'hint', 'The trend line appears once this lift has two sessions logged.')); return box; }
    const W = 320, H = 120, L = 34, R = 12, T = 12, B = 22;
    const vs = pts.map((p) => p.v);
    let lo = Math.min(...vs), hi = Math.max(...vs);
    if (hi === lo) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.15; lo -= pad; hi += pad;
    const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Progress: ${pts.length} sessions, from ${fmtNum(pts[0].v, 1)} to ${fmtNum(pts[pts.length - 1].v, 1)} ${unit}`);
    const mk = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text != null) n.textContent = text; svg.append(n); return n; };
    [lo + pad, hi - pad].forEach((v) => {
      mk('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'c-grid' });
      mk('text', { x: L - 6, y: y(v) + 4, class: 'c-axis', 'text-anchor': 'end' }, fmtNum(v, 0));
    });
    mk('text', { x: L, y: H - 5, class: 'c-axis' }, fmtDay(pts[0].day));
    mk('text', { x: W - R, y: H - 5, class: 'c-axis', 'text-anchor': 'end' }, fmtDay(pts[pts.length - 1].day));
    mk('polyline', { points: pts.map((p, i) => `${x(i)},${y(p.v)}`).join(' '), class: 'c-line' });
    const readout = el('p', 'readout');
    const show = (p) => { readout.textContent = `${fmtDay(p.day)}: best set ${setText(p.top)}${p.e > 0 ? `, est. 1RM ${fmtNum(p.e, 1)} kg` : ''}`; };
    pts.forEach((p, i) => {
      mk('circle', { cx: x(i), cy: y(p.v), r: 4, class: 'c-dot' });
      const hit = mk('circle', { cx: x(i), cy: y(p.v), r: 16, class: 'c-hit', tabindex: 0, role: 'button', 'aria-label': `${fmtDay(p.day)} ${fmtNum(p.v, 1)} ${unit}` });
      hit.addEventListener('click', () => show(p));
      hit.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') show(p); });
    });
    show(pts[pts.length - 1]);
    box.append(svg, readout);
    return box;
  }

  async function renderLogger(root) {
    if (!wUI.progress || wUI.progress.exercise.id !== wUI.ex.id) {
      root.innerHTML = '<p class="hint">Loading</p>';
      if (!(await loadProgress())) { root.innerHTML = '<p class="hint">Could not load this exercise. Go back and try again.</p>'; return; }
    }
    const p = wUI.progress;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    if (wUI.fromRoutine) back.innerHTML = '&lsaquo; Back to routine';
    back.addEventListener('click', () => { wUI.view = wUI.fromRoutine ? 'routine' : 'today'; wUI.plan = null; wUI.today = null; wUI.history = null; state.sheet.render(); });
    root.append(back);

    const head = el('section');
    head.append(el('h3', null, esc(p.exercise.name)));
    if (p.last) {
      const top = groupSets(p.last.sets);
      head.append(el('p', 'last', `<b>Last time (${esc(fmtDay(p.last.day))}):</b> ${esc(top)}${p.last.next_hint ? `<br><span class="hintline">${esc(p.last.next_hint)}</span>` : ''}`));
    } else head.append(el('p', 'hint', 'First time logging this exercise. Start light and focus on form.'));
    const pb = p.personal_bests;
    if (pb.e1rm) head.append(el('p', 'hint', `Best estimated 1-rep max: ${fmtNum(pb.e1rm.value, 1)} kg (${esc(setText(pb.e1rm))}, ${esc(fmtDay(pb.e1rm.day))}). Heaviest: ${fmtNum(pb.heaviest.weight_kg, 2)} kg.`));
    else if (pb.bodyweight_reps) head.append(el('p', 'hint', `Best reps: ${pb.bodyweight_reps.reps} (${esc(fmtDay(pb.bodyweight_reps.day))}).`));
    root.append(head);

    const mine = el('section');
    mine.append(el('h3', null, `Today (${p.today.length} set${p.today.length === 1 ? '' : 's'})`));
    if (p.today.length) {
      const list = el('div', 'list');
      p.today.forEach((s) => {
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">Set ${s.set_number}: ${esc(setText(s))}</div></div>`;
        const del = el('button', 'btn small', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove set ${s.set_number}`);
        del.addEventListener('click', async () => {
          const r = await guarded(() => api(`/api/workout/sets/${s.id}`, { method: 'DELETE' }), 'Could not remove');
          if (r) { wUI.progress = null; wUI.today = null; refreshSummary(); state.sheet.render(); }
        });
        row.append(del);
        list.append(row);
      });
      mine.append(list);
    }
    root.append(mine);

    const form = el('section', 'setform');
    form.append(numStepper('Reps', 'reps', 1, 1, 100));
    form.append(numStepper('Weight (kg)', 'weight', 2.5, 0, 500, 'leave 0 for bodyweight'));
    const err = el('p', 'err');
    err.setAttribute('role', 'alert');
    err.hidden = true;
    const go = el('button', 'btn primary big', `Log set ${p.today.length + 1}`);
    go.type = 'button';
    go.dataset.action = 'log-set';
    go.addEventListener('click', async () => {
      const reps = parseInt(wUI.draft.reps, 10);
      const weight = wUI.draft.weight === '' ? 0 : parseFloat(wUI.draft.weight);
      if (!(reps >= 1 && reps <= 100)) { err.textContent = 'Reps must be 1 to 100.'; err.hidden = false; return; }
      if (!(weight >= 0 && weight <= 500)) { err.textContent = 'Weight must be 0 to 500 kg.'; err.hidden = false; return; }
      err.hidden = true;
      go.disabled = true;
      const r = await guarded(() => api('/api/workout/sets', { method: 'POST', body: { exercise_id: wUI.ex.id, sets: [{ reps, weight_kg: weight }] } }), 'Could not log');
      if (r) {
        toast(r.prs && r.prs.length ? `🏆 ${r.prs[0].text}` : `Set logged: ${setText({ reps, weight_kg: weight })}`);
        wUI.progress = null; wUI.today = r.today; wUI.plan = null;
        startRest(wUI.fromRoutine && wUI.restS ? wUI.restS : restDefault());
        setBadgeWorkout(r.today.total_sets);
        refreshSummary();
      }
      state.sheet.render();
    });
    form.append(err, go);
    if (!wUI.fromRoutine) {
      const rs = el('div', 'seg words restseg');
      rs.append(el('span', 'hint', 'Rest timer'));
      [[0, 'Off'], [60, '60 s'], [90, '90 s'], [120, '2 min'], [180, '3 min']].forEach(([v, label]) => {
        const b = el('button', null, label);
        b.type = 'button';
        b.setAttribute('aria-pressed', String(restDefault() === v));
        b.addEventListener('click', () => { setRestDefault(v); state.sheet.render(); });
        rs.append(b);
      });
      form.append(rs);
    }
    root.append(form);

    const prog = el('section');
    prog.append(el('h3', null, 'Progress'));
    prog.append(progressChart(p.history));
    if (p.history.length) {
      const tbl = el('table', 'sessions');
      tbl.innerHTML = '<thead><tr><th>Day</th><th>Sets</th><th>Volume</th></tr></thead>';
      const body = el('tbody');
      p.history.slice(0, 5).forEach((h) => {
        const tr = el('tr');
        tr.innerHTML = `<td>${esc(fmtDay(h.day))}</td><td>${esc(groupSets(h.sets))}</td><td>${h.volume_kg ? `${fmtNum(h.volume_kg)} kg` : '–'}</td>`;
        body.append(tr);
      });
      tbl.append(body);
      prog.append(tbl);
    }
    root.append(prog);
  }

  async function renderProgressList(root) {
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', () => { wUI.view = 'today'; state.sheet.render(); });
    root.append(back);
    const sec = el('section');
    sec.append(el('h3', null, 'My lifts'));
    root.append(sec);
    if (!wUI.history || !wUI.history.length) {
      const h = await guarded(() => api('/api/workout/history'), 'Could not load');
      wUI.history = h || [];
    }
    if (!wUI.history.length) { sec.append(el('p', 'hint', 'Nothing logged yet. Log your first set and it shows up here with your personal bests.')); return; }
    const list = el('div', 'list');
    wUI.history.forEach((h) => {
      const b = el('button', 'row pickrow');
      b.type = 'button';
      b.innerHTML = `<div class="grow"><div class="name">${esc(h.name)}</div><div class="meta">${h.best_e1rm ? `best est. 1RM ${fmtNum(h.best_e1rm, 1)} kg · ` : h.best_reps ? `best ${h.best_reps} reps · ` : ''}${h.sessions} session${h.sessions === 1 ? '' : 's'}, last ${esc(fmtDay(h.last_day))}</div></div>`;
      b.addEventListener('click', () => { wUI.ex = { id: h.exercise_id, name: h.name }; wUI.view = 'log'; wUI.progress = null; state.sheet.render(); });
      list.append(b);
    });
    sec.append(list);
  }

  /* Feeling today */
  function renderFeeling(root) {
    const rd = (state.summary && state.summary.readiness) || { energy: 3, soreness: 1, advice: '', reported_today: false };
    root.innerHTML = '';
    const scale = (label, field, ends, current) => {
      const sec = el('section');
      sec.append(el('h3', null, label));
      const seg = el('div', 'seg');
      for (let n = 1; n <= 5; n++) {
        const b = el('button', null, String(n));
        b.type = 'button';
        b.setAttribute('aria-pressed', String(rd.reported_today && current === n));
        b.setAttribute('aria-label', `${label} ${n} of 5`);
        b.addEventListener('click', async () => {
          const ok = await guarded(() => api('/api/state', { method: 'PUT', body: { [field]: n } }), 'Could not save');
          if (ok) { toast('Saved'); refreshSummary(); }
        });
        seg.append(b);
      }
      sec.append(seg, el('div', 'scale-ends', `<span>${ends[0]}</span><span>${ends[1]}</span>`));
      return sec;
    };
    root.append(
      scale('Energy', 'energy', ['Drained', 'Great'], rd.energy),
      scale('Soreness', 'soreness', ['None', 'Very sore'], rd.soreness),
    );
    if (rd.reported_today && rd.advice) root.append(el('p', 'advice', esc(rd.advice)));
    else root.append(el('p', 'hint', 'Tell the coach how you feel and it will adjust today’s workout. It resets each day.'));
  }

  /* Injuries */
  const AREAS = ['shoulder', 'knee', 'lower_back', 'elbow', 'wrist', 'neck', 'hip', 'ankle'];
  const injuryForm = { area: 'shoulder', severity: 'mild' };

  function renderInjuries(root) {
    root.innerHTML = '';
    const cur = el('section');
    cur.append(el('h3', null, 'Current injuries'));
    if (!state.injuries.length) {
      cur.append(el('p', 'hint', 'None recorded. Exercises are only filtered for injuries you add here.'));
    } else {
      const list = el('div', 'list');
      state.injuries.forEach((i) => {
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${esc(titleCase(i.area))}</div><div class="meta">${esc(i.severity)}${i.note ? `, ${esc(i.note)}` : ''}</div></div>`;
        const b = el('button', 'btn small', 'Recovered');
        b.type = 'button';
        b.addEventListener('click', async () => {
          await guarded(() => api(`/api/injuries/${encodeURIComponent(i.area)}`, { method: 'DELETE' }), 'Could not update');
          toast('Marked as recovered');
          refreshStatus();
        });
        row.append(b);
        list.append(row);
      });
      cur.append(list);
    }
    root.append(cur);

    const add = el('section');
    add.append(el('h3', null, 'Add an injury'));
    const areas = el('div', 'pills');
    AREAS.forEach((a) => {
      const p = el('button', 'pill', esc(titleCase(a)));
      p.type = 'button';
      p.setAttribute('aria-pressed', String(injuryForm.area === a));
      p.addEventListener('click', () => { injuryForm.area = a; $$('.pill', areas).forEach((x) => x.setAttribute('aria-pressed', String(x === p))); });
      areas.append(p);
    });
    const sev = el('div', 'seg words');
    sev.style.marginTop = '12px';
    ['mild', 'moderate', 'severe'].forEach((s) => {
      const b = el('button', null, s);
      b.type = 'button';
      b.setAttribute('aria-pressed', String(injuryForm.severity === s));
      b.addEventListener('click', () => { injuryForm.severity = s; $$('button', sev).forEach((x) => x.setAttribute('aria-pressed', String(x === b))); });
      sev.append(b);
    });
    const go = el('button', 'btn primary', 'Save injury');
    go.type = 'button';
    go.style.marginTop = '12px';
    go.style.width = '100%';
    go.addEventListener('click', async () => {
      const ok = await guarded(() => api('/api/injuries', { method: 'POST', body: { area: injuryForm.area, severity: injuryForm.severity } }), 'Could not save');
      if (ok) { toast('Injury saved'); refreshStatus(); }
    });
    add.append(areas, sev, go);
    add.append(el('p', 'hint', 'This only hides exercises that load the area. Sharp, lasting or worsening pain needs a doctor or physio, not an app.'));
    root.append(add);
  }

  /* Busy gear */
  const GEAR = ['barbell', 'dumbbell', 'machine', 'cable', 'body only', 'kettlebells', 'bands'];

  function renderGear(root) {
    root.innerHTML = '';
    const busy = new Set(state.unavailable);
    const sec = el('section');
    sec.append(el('h3', null, 'What is taken or broken right now?'));
    sec.append(el('p', 'hint', 'Tap to mark busy. The coach will leave these out until you free them.'));
    const pills = el('div', 'pills');
    pills.style.marginTop = '10px';
    [...new Set([...GEAR, ...state.unavailable])].forEach((g) => {
      const p = el('button', 'pill', esc(g));
      p.type = 'button';
      p.setAttribute('aria-pressed', String(busy.has(g)));
      p.addEventListener('click', async () => {
        const turningOn = !busy.has(g);
        const ok = await guarded(
          () => (turningOn
            ? api('/api/equipment/unavailable', { method: 'PUT', body: { items: [g] } })
            : api('/api/equipment/available', { method: 'POST', body: { items: [g] } })),
          'Could not update',
        );
        if (ok) refreshStatus();
      });
      pills.append(p);
    });
    sec.append(pills);
    root.append(sec);

    const one = el('section');
    one.append(el('h3', null, 'A specific machine'));
    const row = el('div', 'inline');
    const f = el('input', 'field');
    f.placeholder = 'For example: leg press';
    f.setAttribute('aria-label', 'Specific machine name');
    const b = el('button', 'btn', 'Mark busy');
    b.type = 'button';
    b.addEventListener('click', async () => {
      const v = f.value.trim();
      if (!v) return;
      const ok = await guarded(() => api('/api/equipment/unavailable', { method: 'PUT', body: { items: [v] } }), 'Could not update');
      if (ok) { f.value = ''; refreshStatus(); }
    });
    row.append(f, b);
    one.append(row);
    root.append(one);

    if (busy.size) {
      const all = el('button', 'btn', 'Everything is free again');
      all.type = 'button';
      all.addEventListener('click', async () => {
        await guarded(() => api('/api/equipment/unavailable', { method: 'DELETE' }), 'Could not update');
        toast('All gear marked free');
        refreshStatus();
      });
      root.append(all);
    }
  }

  /* This week: averages against targets, day bars, bodyweight log and trend */
  const weekUI = { data: null, days: 7, draft: '', busy: false };
  const loadWeek = async () => {
    const d = await guarded(() => api(`/api/week?days=${weekUI.days}`), 'Could not load the summary');
    if (d) weekUI.data = d;
    return d;
  };

  function lineChart(pts, unit, ariaName) {
    const box = el('div', 'chart');
    if (pts.length < 2) { box.append(el('p', 'hint', 'The trend line appears once you have two readings.')); return box; }
    const W = 320, H = 120, L = 34, R = 12, T = 12, B = 22;
    const vs = pts.map((p) => p.v);
    let lo = Math.min(...vs), hi = Math.max(...vs);
    if (hi === lo) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.15; lo -= pad; hi += pad;
    const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${ariaName}: ${pts.length} readings, from ${fmtNum(pts[0].v, 1)} to ${fmtNum(pts[pts.length - 1].v, 1)} ${unit}`);
    const mk = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text != null) n.textContent = text; svg.append(n); return n; };
    [lo + pad, hi - pad].forEach((v) => {
      mk('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'c-grid' });
      mk('text', { x: L - 6, y: y(v) + 4, class: 'c-axis', 'text-anchor': 'end' }, fmtNum(v, 1));
    });
    mk('text', { x: L, y: H - 5, class: 'c-axis' }, fmtDay(pts[0].day));
    mk('text', { x: W - R, y: H - 5, class: 'c-axis', 'text-anchor': 'end' }, fmtDay(pts[pts.length - 1].day));
    mk('polyline', { points: pts.map((p, i) => `${x(i)},${y(p.v)}`).join(' '), class: 'c-line' });
    const readout = el('p', 'readout');
    const show = (p) => { readout.textContent = `${fmtDay(p.day)}: ${fmtNum(p.v, 1)} ${unit}`; };
    pts.forEach((p, i) => {
      mk('circle', { cx: x(i), cy: y(p.v), r: 4, class: 'c-dot' });
      const hit = mk('circle', { cx: x(i), cy: y(p.v), r: 16, class: 'c-hit', tabindex: 0, role: 'button', 'aria-label': `${fmtDay(p.day)} ${fmtNum(p.v, 1)} ${unit}` });
      hit.addEventListener('click', () => show(p));
      hit.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') show(p); });
    });
    show(pts[pts.length - 1]);
    box.append(svg, readout);
    return box;
  }

  // One column per day: bar = calories eaten, tick = that day's calorie target, green bar = protein target reached.
  function dayBars(days) {
    const ns = 'http://www.w3.org/2000/svg';
    const W = 320, H = 130, L = 4, R = 4, T = 8, B = 24;
    const n = days.length;
    const max = Math.max(...days.map((d) => Math.max(d.calories, d.calorie_target))) * 1.08;
    const slot = (W - L - R) / n, bw = Math.min(28, slot * 0.62);
    const y = (v) => T + (1 - v / max) * (H - T - B);
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Calories eaten per day for the last ${n} days. The table or list below has the numbers.`);
    const mk = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); if (text != null) e.textContent = text; svg.append(e); return e; };
    mk('line', { x1: L, x2: W - R, y1: H - B, y2: H - B, class: 'c-grid' });
    days.forEach((d, i) => {
      const cx = L + slot * i + slot / 2;
      if (d.logged) mk('rect', { x: cx - bw / 2, y: y(d.calories), width: bw, height: Math.max(2, H - B - y(d.calories)), rx: 3, class: d.protein_hit ? 'bar-hit' : 'bar-miss' });
      mk('line', { x1: cx - bw / 2 - 2, x2: cx + bw / 2 + 2, y1: y(d.calorie_target), y2: y(d.calorie_target), class: 'bar-target' });
      const label = n <= 7 ? d.weekday.slice(0, 3) : (i % 7 === 0 || i === n - 1 ? fmtDay(d.day) : '');
      if (label) mk('text', { x: cx, y: H - 8, class: 'c-axis', 'text-anchor': n <= 7 ? 'middle' : (i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle') }, label);
      if (d.trained) mk('circle', { cx, cy: H - 1.5, r: 1.8, class: 'c-dot' });
    });
    const box = el('div', 'chart');
    box.append(svg);
    return box;
  }

  async function renderWeek(root) {
    if (!weekUI.data) {
      root.innerHTML = '<p class="hint">Loading</p>';
      if (!(await loadWeek())) { root.innerHTML = '<p class="hint">Could not load the summary. Check the server and try again.</p>'; return; }
    }
    const w = weekUI.data, t = w.totals;
    root.innerHTML = '';

    const seg = el('div', 'seg');
    [7, 28].forEach((n) => {
      const b = el('button', `btn small${weekUI.days === n ? ' primary' : ''}`, `${n} days`);
      b.type = 'button';
      b.setAttribute('aria-pressed', String(weekUI.days === n));
      b.addEventListener('click', () => { if (weekUI.days === n) return; weekUI.days = n; weekUI.data = null; state.sheet.render(); });
      seg.append(b);
    });
    root.append(seg);

    if (!t.days_logged) {
      root.append(el('p', 'hint', 'No food logged in this period yet. Log a meal and the averages show up here.'));
    } else {
      const tiles = el('div', 'tiles');
      const tile = (big, unit, label) => { const d = el('div', 'tile'); d.append(el('p', 'tile-num', `${esc(big)}<span class="unit"> ${esc(unit)}</span>`), el('p', 'tile-label', esc(label))); tiles.append(d); };
      tile(fmtNum(t.avg_calories), 'kcal', `average a day (target ${fmtNum(t.calorie_target)})`);
      tile(fmtNum(t.avg_protein_g, 0), 'g', `protein a day (target ${fmtNum(t.protein_target_g)})`);
      tile(`${t.protein_hit_days}/${t.days_logged}`, 'days', 'protein target reached');
      tile(String(t.training_days), t.training_days === 1 ? 'day' : 'days', `trained, ${fmtNum(t.total_sets)} sets`);
      root.append(tiles);

      root.append(el('h3', 'sec', 'Calories per day'));
      root.append(dayBars(w.days));
      root.append(el('p', 'legend', '<i class="sw hit"></i>protein target reached &nbsp; <i class="sw miss"></i>not reached &nbsp; <i class="sw tick"></i>calorie target &nbsp; &bull; trained'));
      if (w.days.length <= 7) {
        const tb = el('table', 'sessions');
        tb.innerHTML = '<thead><tr><th>Day</th><th>kcal</th><th>Protein</th><th>Sets</th></tr></thead>';
        const body = el('tbody');
        w.days.slice().reverse().forEach((d) => {
          const tr = el('tr');
          tr.innerHTML = d.logged || d.sets
            ? `<td>${esc(fmtDay(d.day))}</td><td>${d.logged ? fmtNum(d.calories) : '&ndash;'}</td><td>${d.logged ? `${fmtNum(d.protein_g, 0)} g${d.protein_hit ? ' &#10003;' : ''}` : '&ndash;'}</td><td>${d.sets || '&ndash;'}</td>`
            : `<td>${esc(fmtDay(d.day))}</td><td colspan="3" class="hint">nothing logged</td>`;
          const first = tr.firstElementChild;
          const lnk = el('button', 'linklike plain', first.textContent);
          lnk.type = 'button';
          lnk.setAttribute('aria-label', `Open the log for ${fmtDay(d.day)}`);
          lnk.addEventListener('click', () => openDay(d.day));
          first.textContent = '';
          first.append(lnk);
          body.append(tr);
        });
        tb.append(body);
        root.append(tb);
      }
      const ul = el('ul', 'lines');
      w.lines.forEach((l) => ul.append(el('li', null, esc(l))));
      root.append(ul);
    }

    // Bodyweight
    root.append(el('h3', 'sec', 'Bodyweight'));
    const wt = w.weights || [];
    const form = el('form', 'inline');
    const inp = el('input', 'field');
    inp.type = 'number'; inp.inputMode = 'decimal'; inp.step = '0.1'; inp.min = '25'; inp.max = '400';
    inp.placeholder = wt.length ? `Today (last: ${fmtNum(wt[wt.length - 1].weight_kg, 1)} kg)` : 'Today’s weight in kg';
    inp.setAttribute('aria-label', 'Bodyweight in kg');
    inp.value = weekUI.draft;
    inp.addEventListener('input', () => { weekUI.draft = inp.value; });
    const save = el('button', 'btn primary', 'Save');
    save.type = 'submit';
    form.append(inp, save);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const kg = parseFloat(inp.value);
      if (!(kg >= 25 && kg <= 400)) { toast('Enter a weight between 25 and 400 kg.'); return; }
      save.disabled = true;
      const r = await guarded(() => api('/api/weight', { method: 'POST', body: { weight_kg: kg } }), 'Could not save');
      save.disabled = false;
      if (!r) return;
      weekUI.draft = ''; weekUI.data = null;
      toast(`Saved ${fmtNum(r.weight_kg, 1)} kg`);
      if (state.sheet) state.sheet.render();
    });
    root.append(form);
    if (wt.length) {
      root.append(lineChart(wt.map((r) => ({ day: r.day, v: r.weight_kg })), 'kg', 'Bodyweight'));
      const wk = w.weight;
      if (wk.change_kg !== null) root.append(el('p', 'hint', `${wk.change_kg > 0 ? '+' : ''}${fmtNum(wk.change_kg, 1)} kg over the last ${wk.span_days} days. Daily readings swing by 0.5 to 1 kg (water, food in the gut), so look at the trend over weeks.`));
      const list = el('ul', 'lines wlist');
      wt.slice(-6).reverse().forEach((r) => {
        const li = el('li');
        li.append(el('span', null, `${esc(fmtDay(r.day))}: <b>${fmtNum(r.weight_kg, 1)} kg</b>`));
        const del = el('button', 'linklike', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove reading from ${fmtDay(r.day)}`);
        del.addEventListener('click', async () => {
          const ok = await guarded(() => api(`/api/weight/${r.day}`, { method: 'DELETE' }).then(() => true), 'Could not remove');
          if (ok) { weekUI.data = null; state.sheet.render(); }
        });
        li.append(del);
        list.append(li);
      });
      root.append(list);
    } else root.append(el('p', 'hint', 'Weigh yourself in the morning, same conditions, once or twice a week, and log it here.'));
  }

  const logBtn = $('#logBtn');
  if (logBtn) logBtn.addEventListener('click', () => openDay(null));
  const gutBtn = $('#gutLine');
  if (gutBtn) gutBtn.addEventListener('click', () => { gutUI.data = null; openSheet('Gut, water and fibre', renderGut); });
  const weekBtn = $('#weekBtn');
  if (weekBtn) weekBtn.addEventListener('click', () => { weekUI.data = null; openSheet('This week', renderWeek); });

  /* Gut: water, fibre and stool */
  const BRISTOL = [
    [1, 'Hard lumps', 'Separate hard lumps'], [2, 'Lumpy', 'Lumpy sausage'], [3, 'Cracked', 'Sausage with cracks'],
    [4, 'Smooth', 'Smooth, soft sausage'], [5, 'Soft blobs', 'Soft blobs, easy to pass'], [6, 'Mushy', 'Mushy, ragged edges'],
    [7, 'Watery', 'Watery, no solid bits'],
  ];
  const gutUI = { data: null, bristol: null, warning: false, ml: '', busy: false };
  const loadGut = async () => {
    const g = await guarded(() => api('/api/gut'), 'Could not load');
    if (g) gutUI.data = g;
    return g;
  };
  const gutChanged = () => { gutUI.data = null; refreshSummary(); if (state.sheet) state.sheet.render(); };

  async function renderGut(root) {
    if (!gutUI.data) {
      root.innerHTML = '<p class="hint">Loading</p>';
      if (!(await loadGut())) { root.innerHTML = '<p class="hint">Could not load. Check the server and try again.</p>'; return; }
    }
    const g = gutUI.data;
    root.innerHTML = '';
    if (g.alert === 'see_doctor') root.append(el('p', 'alert-box', esc(g.hints[0])));

    // Water
    const water = el('section');
    water.append(el('h3', null, 'Water'));
    water.append(el('p', 'bignum', `${fmtNum(g.water_ml)}<span class="unit"> of ${fmtNum(g.water_target_ml)} ml</span>`));
    const bar = el('div', 'bar wide', '<i></i>');
    bar.querySelector('i').style.width = `${Math.min(100, (g.water_ml / g.water_target_ml) * 100)}%`;
    bar.setAttribute('role', 'img');
    bar.setAttribute('aria-label', `${fmtNum(g.water_ml)} of ${fmtNum(g.water_target_ml)} ml`);
    water.append(bar);
    const quick = el('div', 'quick');
    const addWater = async (ml) => {
      const r = await guarded(() => api('/api/water', { method: 'POST', body: { ml } }), 'Could not add');
      if (r) { toast(r.summary); gutChanged(); }
    };
    [150, 250, 500, 750].forEach((ml) => {
      const b = el('button', 'btn', `+${ml} ml`);
      b.type = 'button';
      b.addEventListener('click', () => addWater(ml));
      quick.append(b);
    });
    water.append(quick);
    const custom = el('form', 'inline');
    const mlIn = el('input', 'field');
    mlIn.type = 'number'; mlIn.inputMode = 'numeric'; mlIn.min = '50'; mlIn.max = '2000'; mlIn.placeholder = 'Other amount in ml';
    mlIn.setAttribute('aria-label', 'Water in ml');
    mlIn.value = gutUI.ml;
    mlIn.addEventListener('input', () => { gutUI.ml = mlIn.value; });
    const addB = el('button', 'btn', 'Add');
    addB.type = 'submit';
    custom.append(mlIn, addB);
    custom.addEventListener('submit', (e) => {
      e.preventDefault();
      const ml = parseFloat(mlIn.value);
      if (!(ml >= 50 && ml <= 2000)) { toast('Enter 50 to 2000 ml.'); return; }
      gutUI.ml = '';
      addWater(ml);
    });
    water.append(custom);
    if (g.water_entries.length) {
      const ul = el('ul', 'lines wlist');
      g.water_entries.slice(-4).reverse().forEach((w) => {
        const li = el('li');
        li.append(el('span', null, `${esc(w.time)}: <b>${fmtNum(w.ml)} ml</b>`));
        const del = el('button', 'linklike', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove ${w.ml} ml at ${w.time}`);
        del.addEventListener('click', async () => { if (await guarded(() => api(`/api/water/${w.id}`, { method: 'DELETE' }).then(() => true), 'Could not remove')) gutChanged(); });
        li.append(del);
        ul.append(li);
      });
      water.append(ul);
    }
    root.append(water);

    // Fibre
    const fibre = el('section');
    fibre.append(el('h3', null, 'Fibre'));
    fibre.append(el('p', 'bignum', `${fmtNum(g.fibre_g, 1)}<span class="unit"> of ${fmtNum(g.fibre_target_g)} g</span>`));
    const fb = el('div', 'bar wide fibre', '<i></i>');
    fb.querySelector('i').style.width = `${Math.min(100, (g.fibre_g / g.fibre_target_g) * 100)}%`;
    fb.setAttribute('role', 'img');
    fb.setAttribute('aria-label', `${fmtNum(g.fibre_g, 1)} of ${fmtNum(g.fibre_target_g)} g fibre`);
    fibre.append(fb);
    fibre.append(el('p', 'hint', 'Counts only foods that have fibre data. Home-made dishes count through their ingredients.'));
    if (g.fibre_foods && g.fibre_foods.length) {
      fibre.append(el('p', 'sub', 'Good fibre sources from your foods'));
      const ul = el('ul', 'lines');
      g.fibre_foods.forEach((f) => ul.append(el('li', null, `${esc(f.food)} (${esc(f.serving)}): <b>${fmtNum(f.fibre_g, 1)} g</b> fibre, ${fmtNum(f.kcal)} kcal, ${fmtNum(f.protein_g, 1)} g protein`)));
      fibre.append(ul);
    }
    root.append(fibre);

    // Stool
    const stool = el('section');
    stool.append(el('h3', null, 'Bowel movement'));
    stool.append(el('p', 'hint', g.days_since_bowel == null ? 'Nothing logged yet.' : g.days_since_bowel === 0 ? 'Last one: today.' : `Last one: ${g.days_since_bowel} day${g.days_since_bowel === 1 ? '' : 's'} ago.`));
    const grid = el('div', 'bristol');
    grid.setAttribute('role', 'radiogroup');
    grid.setAttribute('aria-label', 'Stool type, Bristol scale');
    BRISTOL.forEach(([n, short, long]) => {
      const b = el('button', 'btype', `<b>${n}</b><span>${esc(short)}</span>`);
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(gutUI.bristol === n));
      b.setAttribute('aria-label', `Type ${n}: ${long}`);
      b.addEventListener('click', () => { gutUI.bristol = n; $$('.btype', grid).forEach((x, i) => x.setAttribute('aria-checked', String(i + 1 === n))); logBtn.disabled = false; });
      grid.append(b);
    });
    stool.append(grid);
    stool.append(el('p', 'hint', '1 to 2 means constipated, 3 to 5 is normal, 6 to 7 is loose.'));
    const warn = el('label', 'check');
    const cb = el('input');
    cb.type = 'checkbox'; cb.checked = gutUI.warning;
    cb.addEventListener('change', () => { gutUI.warning = cb.checked; });
    warn.append(cb, el('span', null, 'Blood, black stool or severe pain'));
    stool.append(warn);
    const logBtn = el('button', 'btn primary', 'Log it');
    logBtn.type = 'button';
    logBtn.disabled = gutUI.bristol == null;
    logBtn.addEventListener('click', async () => {
      logBtn.disabled = true;
      const r = await guarded(() => api('/api/bowel', { method: 'POST', body: { bristol: gutUI.bristol, warning_signs: gutUI.warning } }), 'Could not log');
      if (r) { toast(r.summary); gutUI.bristol = null; gutUI.warning = false; gutChanged(); } else logBtn.disabled = false;
    });
    stool.append(logBtn);
    if (g.bowel_today.length) {
      const ul = el('ul', 'lines wlist');
      g.bowel_today.forEach((b) => {
        const li = el('li');
        li.append(el('span', null, `${esc(b.time)}: type <b>${b.bristol}</b>, ${esc(b.meaning.toLowerCase())}${b.warning_signs ? ' (warning signs)' : ''}`));
        const del = el('button', 'linklike', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove stool entry at ${b.time}`);
        del.addEventListener('click', async () => { if (await guarded(() => api(`/api/bowel/${b.id}`, { method: 'DELETE' }).then(() => true), 'Could not remove')) gutChanged(); });
        li.append(del);
        ul.append(li);
      });
      stool.append(ul);
    }
    root.append(stool);

    const hints = g.alert === 'see_doctor' ? g.hints.slice(1) : g.hints;
    if (hints.length) {
      root.append(el('h3', 'sec', 'What to do'));
      const ul = el('ul', 'lines');
      hints.forEach((h) => ul.append(el('li', null, esc(h))));
      root.append(ul);
    }
    root.append(el('p', 'hint', 'These are habit tips, not medical advice. Ongoing changes in your bowel habit, blood, black stool or severe pain are a reason to see a doctor.'));

    const det = el('details', 'piece');
    det.append(el('summary', null, 'Daily targets'));
    const tf = el('form', 'fgrid');
    const mk = (label, val, min, max, step) => {
      const w = el('label', 'flabel');
      w.append(el('span', null, label));
      const i = el('input', 'field');
      i.type = 'number'; i.inputMode = 'decimal'; i.min = min; i.max = max; i.step = step; i.value = val;
      w.append(i);
      return [w, i];
    };
    const [wl, wi] = mk('Water (ml)', g.water_target_ml, 500, 10000, 100);
    const [fl, fi] = mk('Fibre (g)', g.fibre_target_g, 5, 100, 1);
    const sv = el('button', 'btn', 'Save targets');
    sv.type = 'submit';
    tf.append(wl, fl, sv);
    tf.addEventListener('submit', async (e) => {
      e.preventDefault();
      const r = await guarded(() => api('/api/profile', { method: 'PUT', body: { water_target_ml: parseFloat(wi.value), fibre_target_g: parseFloat(fi.value) } }), 'Could not save');
      if (r) { toast('Targets saved'); gutChanged(); }
    });
    det.append(tf);
    root.append(det);
  }

  /* Log: look at any past day */
  const dayUI = { day: null, data: null, recent: null };
  const fmtDayLong = (d) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
  const MEAL_LABEL = { breakfast: 'Breakfast', lunch: 'Lunch', snack: 'Snack', dinner: 'Dinner', other: 'Other' };

  function openDay(day) {
    dayUI.day = day || null;
    dayUI.data = null;
    openSheet('Daily log', renderDay);
  }

  async function renderDay(root) {
    const iso = dayUI.day || new Date().toLocaleDateString('en-CA');
    if (!dayUI.data || dayUI.data.day !== iso) {
      root.innerHTML = '<p class="hint">Loading</p>';
      const d = await guarded(() => api(`/api/day/${iso}`), 'Could not load that day');
      if (!d) { root.innerHTML = '<p class="hint">Could not load that day. Check the server and try again.</p>'; return; }
      dayUI.data = d;
      dayUI.recent = (await guarded(() => api('/api/days?limit=14'), 'Could not load recent days')) || [];
    }
    const d = dayUI.data;
    root.innerHTML = '';

    const nav = el('div', 'daynav');
    const prev = el('button', 'btn small', '&lsaquo;');
    prev.type = 'button'; prev.setAttribute('aria-label', 'Previous day');
    prev.addEventListener('click', () => { dayUI.day = d.prev_day; state.sheet.render(); });
    const next = el('button', 'btn small', '&rsaquo;');
    next.type = 'button'; next.setAttribute('aria-label', 'Next day'); next.disabled = !d.next_day;
    next.addEventListener('click', () => { dayUI.day = d.next_day; state.sheet.render(); });
    const pick = el('input', 'field');
    pick.type = 'date'; pick.max = new Date().toLocaleDateString('en-CA'); pick.value = d.day;
    pick.setAttribute('aria-label', 'Pick a date');
    pick.addEventListener('change', () => { if (pick.value && pick.value <= pick.max) { dayUI.day = pick.value; state.sheet.render(); } });
    nav.append(prev, el('div', 'daytitle', `<b>${esc(d.is_today ? 'Today' : fmtDayLong(d.day))}</b>`), next);
    root.append(nav);
    const jump = el('div', 'inline');
    jump.append(pick);
    if (!d.is_today) { const t = el('button', 'btn small', 'Today'); t.type = 'button'; t.addEventListener('click', () => { dayUI.day = null; state.sheet.render(); }); jump.append(t); }
    root.append(jump);

    const tt = d.totals, tg = d.targets;
    const tiles = el('div', 'tiles');
    const tile = (big, unit, label) => { const x = el('div', 'tile'); x.append(el('p', 'tile-num', `${esc(big)}<span class="unit"> ${esc(unit)}</span>`), el('p', 'tile-label', esc(label))); tiles.append(x); };
    tile(fmtNum(tt.calories), 'kcal', `of ${fmtNum(tg.calories)} target${tg.training_day_bonus ? ' (training day)' : ''}`);
    tile(fmtNum(tt.protein_g, 0), 'g', `protein, target ${fmtNum(tg.protein_g)}`);
    tile(fmtNum(tt.fibre_g, 0), 'g', `fibre, target ${fmtNum(tg.fibre_g)}`);
    tile(fmtNum(d.water.ml / 1000, 1), 'L', `water, target ${fmtNum(d.water.target_ml / 1000, 1)}`);
    root.append(tiles);

    root.append(el('h3', 'sec', 'Food'));
    if (!d.is_today) {
      const addf = el('button', 'btn small', '+ Add food to this day');
      addf.type = 'button';
      addf.dataset.action = 'add-food-day';
      addf.addEventListener('click', () => { foodFilter.day = d.day; foodFilter.dayData = null; foodFilter.mode = 'dishes'; foodFilter.view = 'list'; openSheet(`Add food: ${fmtDayLong(d.day)}`, renderFood); });
      root.append(addf);
    }
    if (!d.meals.length) root.append(el('p', 'hint', 'No food logged.'));
    d.meals.forEach((m) => {
      root.append(el('p', 'sub', `${esc(MEAL_LABEL[m.meal_type] || m.meal_type)} <span class="hint">${fmtNum(m.calories)} kcal, ${fmtNum(m.protein_g, 0)} g protein</span>`));
      const list = el('div', 'list');
      m.items.forEach((it) => {
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${it.qty === 1 ? '' : `${esc(it.qty)} &times; `}${esc(it.food)}${it.estimated ? ' (estimated)' : ''}</div><div class="meta">${fmtNum(it.kcal)} kcal, ${fmtNum(it.protein_g, 1)} g protein${it.fibre_g ? `, ${fmtNum(it.fibre_g, 1)} g fibre` : ''}</div></div>`;
        const del = el('button', 'btn small', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove ${it.food}`);
        del.addEventListener('click', async () => {
          if (await guarded(() => api(`/api/meals/${it.id}`, { method: 'DELETE' }).then(() => true), 'Could not remove')) { dayUI.data = null; refreshSummary(); state.sheet.render(); }
        });
        row.append(del);
        list.append(row);
      });
      root.append(list);
    });
    if (d.any_estimated) root.append(el('p', 'hint', 'Entries marked estimated were not computed from the food table.'));

    root.append(el('h3', 'sec', 'Workout'));
    if (!d.workout.exercises.length) root.append(el('p', 'hint', 'No sets logged.'));
    else {
      const ul = el('ul', 'lines plain');
      d.workout.exercises.forEach((e) => ul.append(el('li', null, `<b>${esc(e.name)}</b>: ${esc(groupSets(e.sets))}`)));
      root.append(ul);
      root.append(el('p', 'hint', `${d.workout.total_sets} sets${d.trained ? ', counted as a training day' : ''}.`));
    }

    root.append(el('h3', 'sec', 'Gut and body'));
    const ul = el('ul', 'lines plain');
    ul.append(el('li', null, `Water: ${fmtNum(d.water.ml)} ml`));
    ul.append(el('li', null, d.bowel.length ? `Bowel: ${d.bowel.map((b) => `type ${b.bristol}${b.warning_signs ? ' (warning signs)' : ''}`).join(', ')}` : 'Bowel: nothing logged'));
    if (d.feeling) ul.append(el('li', null, `Felt: energy ${d.feeling.energy}/5, soreness ${d.feeling.soreness}/5${d.feeling.note ? `, ${esc(d.feeling.note)}` : ''}`));
    if (d.weight_kg != null) ul.append(el('li', null, `Weight: ${fmtNum(d.weight_kg, 1)} kg`));
    root.append(ul);

    const others = (dayUI.recent || []).filter((r) => r.day !== d.day);
    if (others.length) {
      root.append(el('h3', 'sec', 'Other days'));
      const tb = el('table', 'sessions');
      tb.innerHTML = '<thead><tr><th>Day</th><th>kcal</th><th>Protein</th><th>Sets</th></tr></thead>';
      const body = el('tbody');
      others.forEach((r) => {
        const tr = el('tr');
        tr.innerHTML = `<td></td><td>${fmtNum(r.calories)}</td><td>${fmtNum(r.protein_g, 0)} g</td><td>${r.sets || '&ndash;'}</td>`;
        const b = el('button', 'linklike plain', esc(fmtDayLong(r.day)));
        b.type = 'button';
        b.addEventListener('click', () => { dayUI.day = r.day; state.sheet.render(); });
        tr.firstElementChild.append(b);
        body.append(tr);
      });
      tb.append(body);
      root.append(tb);
    }
  }

  /* Recipes: describe ingredients, see an honest breakdown, save, log by name */
  const UNITS = [['g', 'g'], ['kg', 'kg'], ['tbsp', 'tbsp'], ['tsp', 'tsp'], ['cup', 'cup'], ['ml', 'ml'], ['glass', 'glass'], ['katori', 'katori'], ['piece', 'piece']];
  const blankRecipe = () => ({ name: '', servings: '4', cooked: '', notes: '', lines: [{ name: '', amount: '', unit: 'g' }, { name: '', amount: '', unit: 'g' }] });
  const recipeUI = { draft: blankRecipe(), editing: null, analysis: null, seq: 0, err: '', timer: null };

  function startRecipe(rec) {
    recipeUI.editing = rec || null;
    recipeUI.analysis = null;
    recipeUI.err = '';
    recipeUI.draft = rec ? {
      name: rec.name, servings: String(rec.servings), cooked: rec.cooked_weight_g ? String(rec.cooked_weight_g) : '', notes: rec.notes || '',
      lines: rec.ingredients.map((l) => (l.grams != null ? { name: l.name, amount: String(l.grams), unit: 'g' } : { name: l.name, amount: String(l.amount ?? l.quantity ?? ''), unit: l.unit || 'piece' })),
    } : blankRecipe();
    foodFilter.view = 'recipe';
    state.sheet.render();
    if (rec) schedulePreview(0);
  }

  const recipeBody = () => {
    const d = recipeUI.draft;
    const lines = d.lines.filter((l) => l.name.trim() && parseFloat(l.amount) > 0).map((l) => ({ name: l.name.trim(), amount: parseFloat(l.amount), unit: l.unit }));
    return { lines, body: { ingredients: lines, servings: parseFloat(d.servings) || 0, cooked_weight_g: parseFloat(d.cooked) > 0 ? parseFloat(d.cooked) : null } };
  };

  function schedulePreview(delay = 500) {
    clearTimeout(recipeUI.timer);
    recipeUI.timer = setTimeout(async () => {
      const { lines, body } = recipeBody();
      const mine = ++recipeUI.seq;
      if (!lines.length) { recipeUI.analysis = null; paintAnalysis(); return; }
      try {
        const a = await api('/api/recipes/preview', { method: 'POST', body });
        if (mine === recipeUI.seq) { recipeUI.analysis = a; recipeUI.err = ''; }
      } catch (e) {
        if (mine === recipeUI.seq) { recipeUI.analysis = null; recipeUI.err = e.message; }
      }
      if (mine === recipeUI.seq) paintAnalysis();
    }, delay);
  }

  function paintAnalysis() {
    const box = $('#recipeResult');
    const save = $('#recipeSave');
    if (!box) return;
    box.innerHTML = '';
    const a = recipeUI.analysis;
    if (recipeUI.err) box.append(el('p', 'err', esc(recipeUI.err)));
    if (!a) {
      if (!recipeUI.err) box.append(el('p', 'hint', 'Add ingredients with amounts. The numbers appear here as you type.'));
      if (save) save.disabled = true;
      return;
    }
    if (!a.ok) {
      const ul = el('ul', 'lines');
      a.problems.forEach((p) => ul.append(el('li', 'err', esc(p))));
      box.append(el('p', 'sub', 'Fix these first'), ul);
      if (save) save.disabled = true;
      return;
    }
    const p = a.per_serving;
    box.append(el('p', 'sub', `Per serving (makes ${fmtNum(a.servings, 1)}${a.serving_g ? `, about ${fmtNum(a.serving_g)} g each` : ''})`));
    const tiles = el('div', 'tiles');
    [[fmtNum(p.calories), 'kcal', 'calories'], [fmtNum(p.protein_g, 1), 'g', 'protein'], [fmtNum(p.carbs_g, 1) + ' / ' + fmtNum(p.fat_g, 1), 'g', 'carbs / fat'], [fmtNum(p.fibre_g, 1), 'g', 'fibre']].forEach(([big, unit, label]) => {
      const t = el('div', 'tile');
      t.append(el('p', 'tile-num', `${esc(big)}<span class="unit"> ${esc(unit)}</span>`), el('p', 'tile-label', esc(label)));
      tiles.append(t);
    });
    box.append(tiles);
    box.append(el('p', 'hint', `Whole recipe: ${fmtNum(a.total.calories)} kcal, ${fmtNum(a.total.protein_g, 1)} g protein. Confidence: <b>${esc(a.confidence)}</b>. Home recipes vary, so treat this as within about 10 to 15%.`));
    [...a.assumptions, ...a.warnings].forEach((w) => box.append(el('p', 'note', esc(w))));
    const det = el('details', 'piece');
    det.append(el('summary', null, 'Line by line'));
    const tb = el('table', 'sessions');
    tb.innerHTML = '<thead><tr><th>Ingredient</th><th>g</th><th>kcal</th><th>Protein</th></tr></thead>';
    const body = el('tbody');
    a.lines.forEach((l) => { const tr = el('tr'); tr.innerHTML = `<td>${esc(l.ingredient)}</td><td>${fmtNum(l.grams, 1)}</td><td>${fmtNum(l.calories)}</td><td>${fmtNum(l.protein_g, 1)}</td>`; body.append(tr); });
    tb.append(body);
    det.append(tb);
    if (a.ignored.length) det.append(el('p', 'hint', `Counted as zero: ${a.ignored.map((i) => esc(i.name)).join(', ')}.`));
    box.append(det);
    if (save) save.disabled = !recipeUI.draft.name.trim();
  }

  function renderRecipeForm(root) {
    const d = recipeUI.draft, ed = recipeUI.editing;
    root.innerHTML = '';
    const back = el('button', 'btn small back', '&lsaquo; Back');
    back.type = 'button';
    back.addEventListener('click', () => { clearTimeout(recipeUI.timer); recipeUI.seq += 1; foodFilter.view = 'list'; foodFilter.mode = 'recipes'; state.sheet.render(); });
    root.append(back);
    const sec = el('section');
    sec.append(el('h3', null, ed ? 'Edit recipe' : 'New recipe'));
    sec.append(el('p', 'hint', 'List what goes into the pot, as you weigh or measure it before cooking. A bare name means raw or dry (rice, dal, chicken). Write "cooked rice" if it was already cooked. Spices in small amounts and water count as zero.'));

    const txt = (label, key, attrs = {}) => {
      const wrap = el('label', 'flabel');
      wrap.append(el('span', null, label));
      const i = el('input', 'field');
      i.type = attrs.type || 'text';
      if (attrs.type === 'number') { i.inputMode = 'decimal'; i.step = 'any'; i.min = '0'; }
      if (attrs.placeholder) i.placeholder = attrs.placeholder;
      i.value = d[key];
      i.addEventListener('input', () => { d[key] = i.value; schedulePreview(); paintAnalysis(); });
      wrap.append(i);
      return wrap;
    };
    sec.append(txt('Recipe name', 'name', { placeholder: 'e.g. Ghar ka rajma' }));
    const g = el('div', 'fgrid');
    g.append(txt('Makes how many servings', 'servings', { type: 'number', placeholder: '4' }), txt('Finished weight in g (optional)', 'cooked', { type: 'number', placeholder: 'weigh the full pot' }));
    sec.append(g);
    sec.append(el('p', 'hint', 'With the finished weight you can log by grams eaten ("300 g of my rajma") and the serving size becomes exact.'));

    const dl = el('datalist');
    dl.id = 'ingNames';
    (state.ingredients || []).forEach((i) => { const o = el('option'); o.value = i.name.replace(/,.*$/, ''); dl.append(o); });
    sec.append(dl);

    sec.append(el('h3', 'sec', 'Ingredients'));
    const lines = el('div', 'rlines');
    const paintLines = () => {
      lines.innerHTML = '';
      d.lines.forEach((l, idx) => {
        const row = el('div', 'rline');
        const n = el('input', 'field');
        n.setAttribute('list', 'ingNames'); n.placeholder = 'Ingredient'; n.value = l.name; n.setAttribute('aria-label', `Ingredient ${idx + 1} name`);
        n.addEventListener('input', () => { l.name = n.value; schedulePreview(); paintAnalysis(); });
        const a = el('input', 'field amt');
        a.type = 'number'; a.inputMode = 'decimal'; a.step = 'any'; a.min = '0'; a.placeholder = 'Amount'; a.value = l.amount; a.setAttribute('aria-label', `Ingredient ${idx + 1} amount`);
        a.addEventListener('input', () => { l.amount = a.value; schedulePreview(); });
        const u = el('select', 'field unitsel');
        u.setAttribute('aria-label', `Ingredient ${idx + 1} unit`);
        UNITS.forEach(([v, t]) => { const o = el('option', null, t); o.value = v; if (v === l.unit) o.selected = true; u.append(o); });
        u.addEventListener('change', () => { l.unit = u.value; schedulePreview(); });
        const x = el('button', 'btn small xbtn', '&times;');
        x.type = 'button'; x.setAttribute('aria-label', `Remove ingredient ${idx + 1}`);
        x.addEventListener('click', () => { if (d.lines.length > 1) d.lines.splice(idx, 1); else d.lines[0] = { name: '', amount: '', unit: 'g' }; paintLines(); schedulePreview(0); });
        row.append(n, a, u, x);
        lines.append(row);
      });
    };
    paintLines();
    sec.append(lines);
    const add = el('button', 'btn small', '+ Add ingredient');
    add.type = 'button';
    add.addEventListener('click', () => { d.lines.push({ name: '', amount: '', unit: 'g' }); paintLines(); const ins = $$('.rline input', lines); const last = ins[ins.length - 2]; if (last) last.focus(); });
    sec.append(add);
    sec.append(el('p', 'hint', 'Or just tell the coach: "I make rajma with 200 g rajma, 2 onions, 2 tbsp oil, makes 4 servings". It builds, checks and saves it for you.'));

    const result = el('div');
    result.id = 'recipeResult';
    result.setAttribute('aria-live', 'polite');
    sec.append(result);

    const notes = el('label', 'flabel');
    notes.append(el('span', null, 'Notes (optional)'));
    const ni = el('input', 'field'); ni.value = d.notes; ni.maxLength = 500;
    ni.addEventListener('input', () => { d.notes = ni.value; });
    notes.append(ni);
    sec.append(notes);

    const err = el('p', 'err');
    err.id = 'recipeErr'; err.setAttribute('role', 'alert'); err.hidden = true;
    const save = el('button', 'btn primary big', ed ? 'Save changes' : 'Save recipe');
    save.type = 'button'; save.id = 'recipeSave'; save.disabled = true;
    save.addEventListener('click', async () => {
      err.hidden = true;
      const { lines: ls, body } = recipeBody();
      if (!d.name.trim()) { err.textContent = 'Give the recipe a name.'; err.hidden = false; return; }
      save.disabled = true;
      try {
        const saved = await api(ed ? `/api/recipes/${ed.id}` : '/api/recipes', { method: ed ? 'PUT' : 'POST', body: { ...body, name: d.name.trim(), notes: d.notes || null } });
        reloadFoods();
        foodFilter.view = 'list'; foodFilter.mode = 'recipes'; foodFilter.q = '';
        toast(`Saved ${saved.name}: ${fmtNum(saved.per_serving.calories)} kcal per serving`);
        state.sheet.render();
      } catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
    });
    sec.append(err, save);
    if (ed) {
      const del = el('button', 'btn danger', 'Delete this recipe');
      del.type = 'button';
      let armed = false;
      del.addEventListener('click', async () => {
        if (!armed) { armed = true; del.textContent = 'Tap again to delete'; setTimeout(() => { armed = false; del.textContent = 'Delete this recipe'; }, 4000); return; }
        if (await guarded(() => api(`/api/recipes/${ed.id}`, { method: 'DELETE' }).then(() => true), 'Could not delete')) {
          reloadFoods(); foodFilter.view = 'list'; foodFilter.mode = 'recipes'; toast('Deleted. Past meals keep their numbers.'); state.sheet.render();
        }
      });
      sec.append(del);
    }
    root.append(sec);
    paintAnalysis();
  }

  const SHEETS = {
    food: ['Add food', renderFood],
    workout: ['Workout', renderWorkout],
    state: ['How you feel today', renderFeeling],
    gut: ['Gut, water and fibre', renderGut],
    injury: ['Injuries', renderInjuries],
    gear: ['Busy gear', renderGear],
  };
  $$('.chip').forEach((c) => c.addEventListener('click', () => {
    if (c.dataset.sheet === 'workout') { openWorkout(null); return; }
    if (c.dataset.sheet === 'food') { foodFilter.day = null; foodFilter.dayData = null; }
    const [title, render] = SHEETS[c.dataset.sheet];
    openSheet(title, render);
  }));

  /* ---------- start ---------- */
  async function init() {
    try {
      const hist = await api('/api/chat/history?limit=50');
      hist.forEach((m) => addMessage(m.role, m.content));
    } catch (_) {
      const hosted = window.FCAuth && window.FCAuth.config.auth === 'supabase';
      addMessage('assistant', hosted ? "Can't reach FitChat. Check your connection, then reload this page."
        : "Can't reach the server. Check that it's running and that your phone is on the same Wi-Fi as the laptop, then reload this page.", { error: true });
    }
    syncEmpty();
    scrollDown();
    refreshSummary();
    refreshStatus();
  }
  /* Bridge for the extra screens (ui2.js, body.js, weekplan.js) */
  window.FC = {
    $, $$, el, esc, fmtNum, fmtDay, fmtDayLong, api, toast, guarded, openSheet, closeSheet, openPage, leavePage, state, refreshSummary,
    openDay, openWorkout, openLightbox, setBadge, renderWeek, weekUI, renderGut, gutUI, renderFeeling, renderInjuries, renderGear,
    renderWorkout, renderFood, foodFilter, wUI, planUI, foodChanged, groupSets,
  };

  init();
})();
