/* FitChat: Account sheet (sign-in details, coach allowance, own Gemini key, pause switch, your data). */
(() => {
  'use strict';
  const FC = window.FC;
  if (!FC) return;
  const { el, esc, api, toast, guarded, openSheet } = FC;
  const cfg = () => (window.FCAuth && window.FCAuth.config) || { auth: 'none' };

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
  FC.accountSub = () => (cfg().auth === 'supabase' ? 'Sign-in, coach limit, your data' : 'Back up your data');
})();
