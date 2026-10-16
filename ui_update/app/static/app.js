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

  const state = { summary: null, injuries: [], unavailable: [], foods: null, sending: false, sheet: null };

  /* ---------- API ---------- */
  async function api(path, { method = 'GET', body, timeout = 20000 } = {}) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    try {
      const res = await fetch(path, {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: ctl.signal,
      });
      if (!res.ok) {
        let msg = res.statusText;
        try {
          const j = await res.json();
          msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch (_) { /* keep statusText */ }
        throw new Error(msg);
      }
      return res.status === 204 ? null : res.json();
    } finally {
      clearTimeout(timer);
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
      addMessage('assistant', "Can't reach the server. Check that it's running and that your phone is on the same Wi-Fi as the laptop, then send it again.", { error: true });
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
  }

  function setBadge(id, n, warn) {
    const b = $(id);
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
    } catch (_) {
      $('#macros').classList.add('stale');
    }
  }

  async function refreshStatus() {
    try {
      const [inj, gear] = await Promise.all([api('/api/injuries'), api('/api/equipment/unavailable')]);
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

  function openSheet(title, render) {
    $('#sheetTitle').textContent = title;
    state.sheet = { render: () => render(sheetBody) };
    state.sheet.render();
    if (!sheet.open) sheet.showModal();
  }
  function closeSheet() { if (sheet.open) sheet.close(); }
  sheet.addEventListener('close', () => { state.sheet = null; });
  sheet.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); });
  $('#sheetClose').addEventListener('click', closeSheet);

  async function guarded(fn, failText) {
    try { return await fn(); } catch (err) { toast(`${failText}: ${err.message}`); return undefined; }
  }

  /* Add food */
  const foodFilter = { q: '', qty: {} };

  async function renderFood(root) {
    if (!state.foods) {
      root.innerHTML = '<p class="hint">Loading foods</p>';
      state.foods = await guarded(() => api('/api/foods'), 'Could not load foods');
      if (!state.foods) { root.innerHTML = '<p class="hint">Could not load the food list. Check the server and try again.</p>'; return; }
    }
    const keepFocus = document.activeElement && document.activeElement.id === 'foodSearch';
    root.innerHTML = '';

    const items = (state.summary && state.summary.totals.items) || [];
    const today = el('section');
    today.append(el('h3', null, 'Eaten today'));
    if (!items.length) {
      today.append(el('p', 'hint', 'Nothing logged yet. Add something below, or just tell the coach what you ate.'));
    } else {
      const list = el('div', 'list');
      items.forEach((it) => {
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${esc(it.qty)} &times; ${esc(it.food)}${it.estimated ? ' (estimated)' : ''}</div><div class="meta">${fmtNum(it.kcal)} kcal, ${fmtNum(it.protein_g, 1)} g protein</div></div>`;
        const del = el('button', 'btn small', 'Remove');
        del.type = 'button';
        del.setAttribute('aria-label', `Remove ${it.food}`);
        del.addEventListener('click', async () => {
          await guarded(() => api(`/api/meals/${it.id}`, { method: 'DELETE' }), 'Could not remove');
          toast('Removed');
          refreshSummary();
        });
        row.append(del);
        list.append(row);
      });
      today.append(list);
    }
    root.append(today);

    const add = el('section');
    add.append(el('h3', null, 'Add from your foods'));
    const search = el('input', 'field');
    search.id = 'foodSearch';
    search.type = 'search';
    search.placeholder = 'Search roti, paneer, whey';
    search.setAttribute('aria-label', 'Search foods');
    search.value = foodFilter.q;
    add.append(search);
    const list = el('div', 'list');
    list.style.marginTop = '8px';
    add.append(list);
    add.append(el('p', 'hint', 'Not listed? Tell the coach in the chat and it will log an estimate, clearly marked as one.'));
    root.append(add);

    const paint = () => {
      const q = foodFilter.q.trim().toLowerCase();
      list.innerHTML = '';
      const shown = state.foods.filter((f) => !q || f.name.toLowerCase().includes(q));
      if (!shown.length) list.append(el('p', 'hint', 'No match. Try the chat for anything not in the list.'));
      shown.forEach((f) => {
        const qty = foodFilter.qty[f.id] || 1;
        const row = el('div', 'row');
        row.innerHTML = `<div class="grow"><div class="name">${esc(f.name)}</div><div class="meta">${esc(f.serving)}: ${fmtNum(f.calories)} kcal, ${fmtNum(f.protein_g, 1)} g protein</div></div>`;
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
          const r = await guarded(() => api('/api/meals', { method: 'POST', body: { name: f.name, quantity: n } }), 'Could not add');
          go.disabled = false;
          if (r) { toast(`Added ${fmtNum(n, 1)} × ${f.name}`); foodFilter.qty[f.id] = 1; refreshSummary(); }
        });
        row.append(step, go);
        list.append(row);
      });
    };
    search.addEventListener('input', () => { foodFilter.q = search.value; paint(); });
    paint();
    if (keepFocus) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
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

  const SHEETS = {
    food: ['Add food', renderFood],
    state: ['How you feel today', renderFeeling],
    injury: ['Injuries', renderInjuries],
    gear: ['Busy gear', renderGear],
  };
  $$('.chip').forEach((c) => c.addEventListener('click', () => {
    const [title, render] = SHEETS[c.dataset.sheet];
    openSheet(title, render);
  }));

  /* ---------- start ---------- */
  async function init() {
    try {
      const hist = await api('/api/chat/history?limit=50');
      hist.forEach((m) => addMessage(m.role, m.content));
    } catch (_) {
      addMessage('assistant', "Can't reach the server. Check that it's running and that your phone is on the same Wi-Fi as the laptop, then reload this page.", { error: true });
    }
    syncEmpty();
    scrollDown();
    refreshSummary();
    refreshStatus();
  }
  init();
})();
