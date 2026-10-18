/* FitChat: body measurements + progress photos, and sleep + steps. */
(() => {
  'use strict';
  const FC = window.FC;
  if (!FC) return;
  const { $, el, esc, fmtNum, fmtDay, api, toast, guarded, openSheet, state } = FC;
  const todayIso = () => new Date().toLocaleDateString('en-CA');
  const rerender = () => { if (state.sheet) state.sheet.render(); };

  /* ---------- Body ---------- */
  const bodyUI = { tab: 'measures', data: null, pose: 'front', busy: false, sure: null };
  const FIELDS = [['waist_cm', 'Waist'], ['chest_cm', 'Chest'], ['hips_cm', 'Hips'], ['arm_cm', 'Arm'], ['thigh_cm', 'Thigh']];

  FC.openBody = () => { bodyUI.data = null; bodyUI.sure = null; openSheet('Body', renderBody); };

  function seg(items, current, onPick, cls = 'seg words') {
    const wrap = el('div', cls);
    items.forEach(([key, label]) => {
      const b = el('button', null, label);
      b.type = 'button';
      b.dataset.key = key;
      b.setAttribute('aria-pressed', String(current === key));
      b.addEventListener('click', () => onPick(key));
      wrap.append(b);
    });
    return wrap;
  }

  async function renderBody(root) {
    if (!bodyUI.data) {
      root.innerHTML = '<p class="hint">Loading</p>';
      bodyUI.data = await guarded(() => api('/api/body'), 'Could not load');
      if (!bodyUI.data) { root.innerHTML = '<p class="hint">Could not load. Check the server and try again.</p>'; return; }
    }
    root.innerHTML = '';
    const photosOn = !(window.FCAuth && window.FCAuth.config.photos === false);
    if (!photosOn) bodyUI.tab = 'measures';
    if (photosOn) root.append(seg([['measures', 'Measurements'], ['photos', 'Photos']], bodyUI.tab, (k) => { bodyUI.tab = k; rerender(); }));
    (bodyUI.tab === 'photos' ? paintPhotos : paintMeasures)(root, bodyUI.data);
  }

  function paintMeasures(root, d) {
    const form = el('section');
    form.append(el('h3', null, 'Add measurements'));
    form.append(el('p', 'hint', 'Every two weeks, same time of day, relaxed. Fill in only what you measured. Waist at the navel, chest at the nipple line, arm flexed at the biggest point.'));
    const grid = el('div', 'mgrid');
    const inputs = {};
    FIELDS.forEach(([k, label]) => {
      const last = d.changes[k];
      const lab = el('label', null, `${esc(label)} (cm)${last ? ` · last ${fmtNum(last.latest, 1)}` : ''}`);
      const i = el('input', 'field');
      i.type = 'number'; i.inputMode = 'decimal'; i.step = '0.1'; i.min = '10'; i.max = '250';
      i.setAttribute('aria-label', `${label} in cm`);
      inputs[k] = i;
      lab.append(i);
      grid.append(lab);
    });
    form.append(grid);
    const err = el('p', 'err'); err.setAttribute('role', 'alert'); err.hidden = true;
    const save = el('button', 'btn primary big', 'Save measurements');
    save.type = 'button'; save.dataset.action = 'save-measures';
    save.addEventListener('click', async () => {
      const body = {};
      FIELDS.forEach(([k]) => { const v = parseFloat(inputs[k].value); if (Number.isFinite(v)) body[k] = v; });
      if (!Object.keys(body).length) { err.textContent = 'Enter at least one measurement.'; err.hidden = false; return; }
      err.hidden = true; save.disabled = true;
      try { await api('/api/body/measures', { method: 'POST', body }); toast('Saved'); bodyUI.data = null; rerender(); } catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
    });
    form.append(err, save);
    root.append(form);

    const keys = Object.keys(d.changes);
    const ch = el('section');
    ch.append(el('h3', null, 'Change since your first entry'));
    if (!keys.length) ch.append(el('p', 'hint', 'Nothing yet. Your first entry is the starting line.'));
    else {
      const ul = el('ul', 'lines plain');
      keys.forEach((k) => { const c = d.changes[k]; ul.append(el('li', null, `<b>${esc(c.label)}</b>: ${fmtNum(c.latest, 1)} cm${c.change_cm != null ? ` (${c.change_cm > 0 ? '+' : ''}${fmtNum(c.change_cm, 1)} cm)` : ''}`)); });
      ch.append(ul);
      ch.append(el('p', 'hint', 'Waist going down while your weight holds or rises is the best sign of fat loss with muscle gain.'));
    }
    root.append(ch);

    if (d.measures.length) {
      const hist = el('section');
      hist.append(el('h3', null, 'History'));
      const list = el('div', 'list');
      [...d.measures].reverse().slice(0, 6).forEach((m) => {
        const row = el('div', 'row');
        const vals = FIELDS.filter(([k]) => m[k] != null).map(([k, l]) => `${l} ${fmtNum(m[k], 1)}`).join(', ');
        row.innerHTML = `<div class="grow"><div class="name">${esc(fmtDay(m.day))}</div><div class="meta">${esc(vals)}</div></div>`;
        const del = el('button', 'btn small', 'Delete');
        del.type = 'button';
        del.setAttribute('aria-label', `Delete measurements from ${fmtDay(m.day)}`);
        del.addEventListener('click', async () => { if (await guarded(() => api(`/api/body/measures/${m.day}`, { method: 'DELETE' }).then(() => true), 'Could not delete')) { bodyUI.data = null; rerender(); } });
        row.append(del);
        list.append(row);
      });
      hist.append(list);
      root.append(hist);
    }
  }

  /* shrink a phone photo (often 4000 px, 5 MB) to about 1000 px before sending: fast on Wi-Fi, small on disk */
  async function toJpeg(file, max = 1000, q = 0.82) {
    let bmp;
    try { bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch (_) {
      bmp = await new Promise((ok, bad) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => bad(new Error('That file is not an image.')); im.src = URL.createObjectURL(file); });
    }
    const w = bmp.width || bmp.naturalWidth, h = bmp.height || bmp.naturalHeight;
    const k = Math.min(1, max / Math.max(w, h));
    const c = document.createElement('canvas');
    c.width = Math.round(w * k); c.height = Math.round(h * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', q);
  }

  function paintPhotos(root, d) {
    const add = el('section');
    add.append(el('h3', null, 'Progress photos'));
    add.append(el('p', 'hint', 'Same spot, same light, same pose, every two weeks. Photos are stored only on your laptop.'));
    add.append(seg([['front', 'Front'], ['side', 'Side'], ['back', 'Back']], bodyUI.pose, (k) => { bodyUI.pose = k; rerender(); }));
    const lab = el('label', 'btn primary filebtn', bodyUI.busy ? 'Saving' : `Add ${bodyUI.pose} photo`);
    lab.style.marginTop = '8px';
    const f = el('input'); f.type = 'file'; f.accept = 'image/*'; f.setAttribute('aria-label', `Add ${bodyUI.pose} photo`); f.disabled = bodyUI.busy;
    f.addEventListener('change', async () => {
      const file = f.files && f.files[0];
      if (!file) return;
      bodyUI.busy = true; rerender();
      try {
        const image = await toJpeg(file);
        await api('/api/body/photos', { method: 'POST', body: { pose: bodyUI.pose, image }, timeout: 60000 });
        toast('Photo saved');
        bodyUI.data = null;
      } catch (e) { toast(e.message || 'Could not save the photo'); }
      bodyUI.busy = false; rerender();
    });
    lab.append(f);
    add.append(lab);
    root.append(add);

    const mine = d.photos.filter((p) => p.pose === bodyUI.pose);
    if (mine.length >= 2) {
      const first = mine[mine.length - 1], last = mine[0];
      const cmp = el('section');
      cmp.append(el('h3', null, 'Then and now'));
      const box = el('div', 'compare');
      [first, last].forEach((p, i) => { const fig = el('figure'); fig.append(el('img')); fig.firstChild.src = p.url; fig.firstChild.alt = `${i ? 'Latest' : 'First'} ${bodyUI.pose} photo, ${p.day}`; fig.append(el('figcaption', null, `${i ? 'Latest' : 'First'}: ${esc(fmtDay(p.day))}`)); box.append(fig); });
      cmp.append(box);
      root.append(cmp);
    }
    const all = el('section');
    all.append(el('h3', null, mine.length ? 'All photos' : 'No photos yet'));
    const grid = el('div', 'photos');
    mine.forEach((p) => {
      const t = el('div', 'photo');
      const img = el('img'); img.loading = 'lazy'; img.src = p.url; img.alt = `${p.pose} photo ${p.day}`;
      const open = el('button', 'open'); open.type = 'button'; open.setAttribute('aria-label', `View ${p.pose} photo from ${fmtDay(p.day)}`);
      open.addEventListener('click', () => FC.openLightbox(p.url, `${p.pose} photo ${p.day}`));
      const del = el('button', 'del', bodyUI.sure === p.id ? 'Sure?' : '&times;'); del.type = 'button'; del.setAttribute('aria-label', `Delete photo from ${fmtDay(p.day)}`);
      del.addEventListener('click', async () => {
        if (bodyUI.sure !== p.id) { bodyUI.sure = p.id; rerender(); return; }
        if (await guarded(() => api(`/api/body/photos/${p.id}`, { method: 'DELETE' }).then(() => true), 'Could not delete')) { bodyUI.sure = null; bodyUI.data = null; rerender(); }
      });
      t.append(img, open, el('em', null, esc(fmtDay(p.day))), del);
      grid.append(t);
    });
    all.append(grid);
    root.append(all);
  }

  /* ---------- Sleep and steps ---------- */
  const sleepUI = { data: null, day: null, sleep: '', steps: '' };
  FC.openSleep = () => { sleepUI.data = null; sleepUI.day = null; sleepUI.sleep = ''; sleepUI.steps = ''; openSheet('Sleep and steps', renderSleep); };

  async function renderSleep(root) {
    if (!sleepUI.data) {
      root.innerHTML = '<p class="hint">Loading</p>';
      sleepUI.data = await guarded(() => api('/api/daystats?days=14'), 'Could not load');
      if (!sleepUI.data) { root.innerHTML = '<p class="hint">Could not load. Check the server and try again.</p>'; return; }
      const t = sleepUI.data.today;
      if (!sleepUI.sleep) sleepUI.sleep = t && t.sleep_h != null ? String(t.sleep_h) : '7';
      if (!sleepUI.steps && t && t.steps != null) sleepUI.steps = String(t.steps);
    }
    const d = sleepUI.data;
    root.innerHTML = '';
    const day = sleepUI.day || todayIso();
    const dp = el('div', 'datepick');
    dp.append(el('span', 'hint', 'For'));
    const date = el('input', 'field'); date.type = 'date'; date.max = todayIso(); date.value = day; date.setAttribute('aria-label', 'Day');
    date.addEventListener('change', () => { if (date.value && date.value <= date.max) sleepUI.day = date.value; });
    dp.append(date);
    root.append(dp);

    const s = el('section');
    s.append(el('h3', null, 'Sleep'));
    s.append(el('p', 'hint', 'Hours you slept the night before. Under 7 h makes workouts feel harder and appetite louder.'));
    const row = el('div', 'nstep');
    const minus = el('button', 'btn', '&minus;'); minus.type = 'button'; minus.setAttribute('aria-label', 'Less sleep');
    const inp = el('input', 'field'); inp.type = 'number'; inp.inputMode = 'decimal'; inp.step = '0.25'; inp.min = '0.5'; inp.max = '24'; inp.value = sleepUI.sleep; inp.setAttribute('aria-label', 'Hours of sleep');
    const plus = el('button', 'btn', '+'); plus.type = 'button'; plus.setAttribute('aria-label', 'More sleep');
    const bump = (dlt) => { const v = Math.max(0.5, Math.min(24, (parseFloat(inp.value) || 7) + dlt)); inp.value = String(v); sleepUI.sleep = inp.value; };
    minus.addEventListener('click', () => bump(-0.5)); plus.addEventListener('click', () => bump(0.5));
    inp.addEventListener('input', () => { sleepUI.sleep = inp.value; });
    row.append(minus, inp, plus);
    s.append(row);
    root.append(s);

    const st = el('section');
    st.append(el('h3', null, 'Steps'));
    st.append(el('p', 'hint', 'Your phone or watch shows the total. Type it in at the end of the day.'));
    const si = el('input', 'field'); si.type = 'number'; si.inputMode = 'numeric'; si.min = '0'; si.max = '100000'; si.placeholder = 'e.g. 8500'; si.value = sleepUI.steps; si.setAttribute('aria-label', 'Steps');
    si.addEventListener('input', () => { sleepUI.steps = si.value; });
    st.append(si);
    root.append(st);

    const err = el('p', 'err'); err.setAttribute('role', 'alert'); err.hidden = true;
    const save = el('button', 'btn primary big', 'Save');
    save.type = 'button'; save.dataset.action = 'save-stats';
    save.addEventListener('click', async () => {
      const body = { day };
      const h = parseFloat(sleepUI.sleep), n = parseInt(sleepUI.steps, 10);
      if (Number.isFinite(h)) body.sleep_h = h;
      if (Number.isFinite(n)) body.steps = n;
      if (body.sleep_h == null && body.steps == null) { err.textContent = 'Enter sleep, steps, or both.'; err.hidden = false; return; }
      err.hidden = true; save.disabled = true;
      try { const r = await api('/api/daystats', { method: 'POST', body }); toast(r.summary); sleepUI.data = null; FC.refreshSummary(); rerender(); } catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
    });
    root.append(err, save);

    const recent = el('section');
    recent.append(el('h3', null, 'Last 14 days'));
    recent.append(el('p', 'hint', esc(d.summary)));
    if (d.days.length) {
      const tb = el('table', 'sessions');
      tb.innerHTML = '<thead><tr><th>Day</th><th>Sleep</th><th>Steps</th></tr></thead>';
      const body = el('tbody');
      [...d.days].reverse().forEach((r) => { const tr = el('tr'); tr.innerHTML = `<td>${esc(fmtDay(r.day))}</td><td>${r.sleep_h != null ? `${fmtNum(r.sleep_h, 2)} h` : '&ndash;'}</td><td>${r.steps != null ? fmtNum(r.steps) : '&ndash;'}</td>`; body.append(tr); });
      tb.append(body);
      recent.append(tb);
    }
    root.append(recent);
  }
})();
