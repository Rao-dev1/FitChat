/* FitChat: Account sheet (sign-in details, coach allowance, own Gemini key, pause switch, your data). */
(() => {
  'use strict';
  const FC = window.FC;
  if (!FC) return;
  const { el, esc, api, toast, guarded, openSheet } = FC;
  const cfg = () => (window.FCAuth && window.FCAuth.config) || { auth: 'none' };

  const GOALS = [['fat_loss', 'Lose fat'], ['maintain', 'Maintain'], ['muscle_gain', 'Build muscle']];

  function field(label, input) {
    const l = el('label', 'flabel', `<span>${esc(label)}</span>`);
    l.append(input);
    return l;
  }
  function numInput(value, ph, min, max, step) {
    const i = el('input', 'field'); i.type = 'number'; i.inputMode = 'decimal'; i.placeholder = ph;
    i.min = min; i.max = max; i.step = step || 'any'; i.value = value == null ? '' : value;
    return i;
  }
  function select(opts, value) {
    const s = el('select', 'field');
    opts.forEach(([v, l]) => { const o = el('option', null, esc(l)); o.value = v; if (v === value) o.selected = true; s.append(o); });
    return s;
  }

  async function bodySection(root) {
    const sec = el('section', 'acct');
    sec.append(el('h3', null, 'Body and targets'));
    root.append(sec);
    const p = await guarded(() => api('/api/profile'), 'Could not load your details');
    if (!p) { sec.append(el('p', 'hint', 'Could not load your details.')); return; }

    sec.append(el('p', 'hint', 'Enter your details and FitChat works out your BMI and a daily calorie and protein target. Workouts and steps you log add extra calories on the day.'));
    const grid = el('div', 'fgrid');
    const weight = numInput(p.weight_kg, 'kg', 25, 300, '0.1');
    const height = numInput(p.height_cm, 'cm', 100, 250, '0.5');
    const age = numInput(p.age, 'years', 10, 100, '1');
    const sex = select([['', 'Choose'], ['male', 'Male'], ['female', 'Female'], ['other', 'Other / skip']], p.sex || '');
    grid.append(field('Weight (kg)', weight), field('Height (cm)', height), field('Age', age), field('Sex', sex));
    const act = select(p.activity_options.map((o) => [o.value, o.label]), p.activity);
    const goal = select(GOALS, p.goal);
    sec.append(grid, field('Everyday movement (before workouts)', act), field('Goal', goal));

    const err = el('p', 'err'); err.hidden = true;
    const save = el('button', 'btn primary', 'Save and calculate'); save.type = 'button';
    const result = el('div', 'acctresult');
    sec.append(save, err, result);

    const targets = el('div', 'acct');
    const cal = numInput(p.calorie_target, 'kcal', 800, 8000, '10');
    const pro = numInput(p.protein_target_g, 'g', 20, 400, '5');
    const auto = el('label', 'toggle', '<span>Keep my targets calculated automatically</span>');
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = !!p.auto_targets; cb.setAttribute('aria-label', 'Keep my targets calculated automatically');
    auto.append(cb);
    const useBtn = el('button', 'btn', 'Use suggested targets'); useBtn.type = 'button';
    const saveT = el('button', 'btn', 'Save targets'); saveT.type = 'button';
    const tgrid = el('div', 'fgrid'); tgrid.append(field('Calories a day', cal), field('Protein a day (g)', pro));
    targets.append(el('h3', null, 'Daily targets'), tgrid, auto, el('p', 'hint', 'With the switch on, your targets update when you log a new weight or change your details. Turn it off to type your own numbers.'), useBtn, saveT);
    sec.append(targets);

    function draw(prof) {
      const sg = prof.suggestion || {};
      result.innerHTML = '';
      if (sg.bmi != null) {
        result.append(el('p', null, `<b>BMI ${esc(sg.bmi)}</b>${sg.bmi_category ? ` \u00b7 ${esc(sg.bmi_category)}` : ''}`));
      }
      if (sg.ready) {
        result.append(el('p', null, `You burn about <b>${esc(sg.maintenance)} kcal</b> on an ordinary day. For your goal, aim for <b>${esc(sg.calories)} kcal</b> and <b>${esc(sg.protein_g)} g protein</b>.`));
      } else if (sg.missing && sg.missing.length) {
        result.append(el('p', 'hint', `Add ${esc(sg.missing.join(', '))} to get your targets.`));
      }
      (sg.notes || []).forEach((n) => result.append(el('p', 'hint', esc(n))));
      cal.value = prof.calorie_target; pro.value = prof.protein_target_g; cb.checked = !!prof.auto_targets;
      cal.disabled = pro.disabled = saveT.disabled = cb.checked;
      useBtn.hidden = !sg.ready || cb.checked;
    }
    draw(p);

    const num = (i) => (i.value === '' ? null : Number(i.value));
    save.addEventListener('click', async () => {
      err.hidden = true; save.disabled = true;
      const body = { weight_kg: num(weight), height_cm: num(height), age: num(age), sex: sex.value || null, activity: act.value, goal: goal.value };
      Object.keys(body).forEach((k) => body[k] == null && delete body[k]);
      try { const r = await api('/api/profile', { method: 'PUT', body }); draw(r); toast('Saved'); if (FC.refreshSummary) FC.refreshSummary(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
      save.disabled = false;
    });
    cb.addEventListener('change', async () => {
      err.hidden = true;
      try {
        let r = await api('/api/profile', { method: 'PUT', body: { auto_targets: cb.checked } });
        if (cb.checked && r.suggestion && r.suggestion.ready) r = await api('/api/profile/apply-suggested', { method: 'POST' });
        draw(r); toast(cb.checked ? 'Targets will update automatically' : 'Automatic targets off'); if (FC.refreshSummary) FC.refreshSummary();
      } catch (e) { cb.checked = !cb.checked; err.textContent = e.message; err.hidden = false; }
    });
    useBtn.addEventListener('click', async () => {
      err.hidden = true;
      try { draw(await api('/api/profile/apply-suggested', { method: 'POST' })); toast('Targets updated'); if (FC.refreshSummary) FC.refreshSummary(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
    });
    saveT.addEventListener('click', async () => {
      err.hidden = true;
      try { draw(await api('/api/profile', { method: 'PUT', body: { calorie_target: num(cal), protein_target_g: num(pro) } })); toast('Targets saved'); if (FC.refreshSummary) FC.refreshSummary(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
    });
  }

  async function renderAccount(root) {
    root.innerHTML = '<p class="hint">Loading</p>';
    const me = await guarded(() => api('/api/me'), 'Could not load your account');
    if (!me) { root.innerHTML = '<p class="hint">Could not load. Try again.</p>'; return; }
    root.innerHTML = '';
    const rerender = () => renderAccount(root);

    if (me.hosted) {
      const box = el('section', 'acct');
      box.append(el('h3', null, 'Signed in'));
      box.append(el('p', null, `<b>${esc(me.email || '')}</b>`));
      const out = el('button', 'btn', 'Sign out'); out.type = 'button';
      out.addEventListener('click', () => window.FCAuth.signOut());
      box.append(out);
      root.append(box);

      const chat = el('section', 'acct');
      chat.append(el('h3', null, 'Coach messages'));
      const c = me.chat;
      chat.append(el('p', null, c.limit == null ? (c.own_key ? 'Unlimited, using your own Gemini key.' : 'Unlimited.')
        : `${c.used} of ${c.limit} used today. Resets at midnight.`));
      chat.append(el('p', 'hint', 'Buttons, plans and dashboards never use the coach, so they are not limited.'));
      if (c.own_key_available) {
        if (c.own_key) {
          const rm = el('button', 'btn', 'Remove my Gemini key'); rm.type = 'button';
          rm.addEventListener('click', async () => { if (await guarded(() => api('/api/me/gemini-key', { method: 'DELETE' }).then(() => true), 'Could not remove')) { toast('Key removed'); rerender(); } });
          chat.append(rm);
        } else {
          chat.append(el('p', 'hint', 'Want no limit? Make a free key in Google AI Studio (aistudio.google.com) and paste it here. It is stored encrypted and used only for your messages.'));
          const f = el('input', 'field'); f.type = 'password'; f.placeholder = 'Paste your Gemini API key'; f.autocomplete = 'off'; f.setAttribute('aria-label', 'Gemini API key');
          const save = el('button', 'btn primary', 'Save key'); save.type = 'button';
          const err = el('p', 'err'); err.hidden = true;
          save.addEventListener('click', async () => {
            err.hidden = true; save.disabled = true;
            try { await api('/api/me/gemini-key', { method: 'PUT', body: { key: f.value.trim() } }); toast('Key saved'); rerender(); }
            catch (e) { err.textContent = e.message; err.hidden = false; save.disabled = false; }
          });
          chat.append(f, save, err);
        }
      }
      root.append(chat);
    }

    if (me.admin && me.hosted) {
      const box = el('section', 'acct');
      box.append(el('h3', null, 'Site switch (owner only)'));
      box.append(el('p', 'hint', 'Pause FitChat for everyone except you. Other people see a "paused" screen. Their data is untouched, and you can switch it back on any time.'));
      const row = el('label', 'toggle', '<span>FitChat is on</span>');
      const cb = el('input'); cb.type = 'checkbox'; cb.checked = !me.paused; cb.setAttribute('aria-label', 'FitChat is on');
      cb.addEventListener('change', async () => {
        cb.disabled = true;
        try { await api('/api/admin/pause', { method: 'POST', body: { paused: !cb.checked } }); toast(cb.checked ? 'FitChat is on' : 'FitChat is paused'); }
        catch (e) { cb.checked = !cb.checked; toast(e.message); }
        cb.disabled = false;
      });
      row.append(cb); box.append(row);
      root.append(box);
    }

    await bodySection(root);

    const data = el('section', 'acct');
    data.append(el('h3', null, 'Your data'));
    data.append(el('p', 'hint', 'Download everything you have logged as a file you can keep as a backup.'));
    const dl = el('button', 'btn', 'Download my data'); dl.type = 'button';
    dl.addEventListener('click', async () => {
      dl.disabled = true;
      try {
        const j = await api('/api/export', { timeout: 60000 });
        const blob = new Blob([JSON.stringify(j, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = `fitchat-${new Date().toLocaleDateString('en-CA')}.json`;
        document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      } catch (e) { toast(e.message || 'Could not export'); }
      dl.disabled = false;
    });
    data.append(dl);
    data.append(el('p', 'hint', 'Restore from a backup file. This replaces everything in this account with the file. Use it to move your laptop data to the hosted app, or to recover.'));
    const pick = el('input', 'field'); pick.type = 'file'; pick.accept = 'application/json,.json'; pick.setAttribute('aria-label', 'Backup file');
    const word = el('input', 'field'); word.placeholder = 'Type REPLACE to confirm'; word.autocomplete = 'off'; word.setAttribute('aria-label', 'Type REPLACE to confirm');
    const restore = el('button', 'btn', 'Restore from file'); restore.type = 'button';
    const rerr = el('p', 'err'); rerr.hidden = true;
    restore.addEventListener('click', async () => {
      rerr.hidden = true;
      const file = pick.files && pick.files[0];
      if (!file) { rerr.textContent = 'Choose a backup file first.'; rerr.hidden = false; return; }
      if (word.value.trim() !== 'REPLACE') { rerr.textContent = 'Type REPLACE to confirm.'; rerr.hidden = false; return; }
      restore.disabled = true;
      try {
        const parsed = JSON.parse(await file.text());
        const r = await api('/api/me/import', { method: 'POST', body: { data: parsed, confirm: 'REPLACE' }, timeout: 120000 });
        toast(`Restored ${r.restored_rows} rows`);
        setTimeout(() => location.reload(), 900);
      } catch (e) { rerr.textContent = e instanceof SyntaxError ? 'That file is not a FitChat backup.' : e.message; rerr.hidden = false; restore.disabled = false; }
    });
    data.append(pick, word, restore, rerr);
    if (me.hosted) {
      data.append(el('p', 'hint', 'Delete everything you have logged. Your sign-in stays, and you start fresh. This cannot be undone.'));
      const f = el('input', 'field'); f.placeholder = 'Type DELETE to confirm'; f.autocomplete = 'off'; f.setAttribute('aria-label', 'Type DELETE to confirm');
      const del = el('button', 'btn danger', 'Delete my data'); del.type = 'button';
      del.addEventListener('click', async () => {
        if (f.value.trim() !== 'DELETE') { toast('Type DELETE first'); return; }
        del.disabled = true;
        try { await api('/api/me/delete-data', { method: 'POST', body: { confirm: 'DELETE' } }); toast('Your data was deleted'); setTimeout(() => location.reload(), 700); }
        catch (e) { toast(e.message); del.disabled = false; }
      });
      data.append(f, del);
    }
    root.append(data);
  }

  FC.openAccount = () => openSheet('Account', renderAccount);
  FC.accountSub = () => (cfg().auth === 'supabase' ? 'Weight, height, targets, sign-in, data' : 'Weight, height, targets, backup');
})();
