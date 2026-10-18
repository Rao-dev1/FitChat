/* FitChat sign-in. Loaded first. On a laptop (no accounts) it does nothing. When hosted, every request waits here until
   the person is signed in; the screens behind simply stay empty until then. Talks to Supabase's sign-in service directly. */
(() => {
  'use strict';
  const KEY = 'fc_session';
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (_) { return null; } },
    set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (_) { /* private mode: stays signed in until reload */ } },
    clear() { try { localStorage.removeItem(KEY); } catch (_) { /* nothing to clear */ } },
  };
  let memory = null;       // fallback when localStorage is blocked
  let config = { auth: 'none' };
  let resolveReady;
  const ready = new Promise((r) => { resolveReady = r; });
  let gate = null;

  const tz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) { return ''; } })();
  const session = () => store.get() || memory;
  const save = (s) => { memory = s; store.set(s); };

  function normalise(j) {
    const exp = j.expires_at || Math.floor(Date.now() / 1000) + (j.expires_in || 3600);
    return { access_token: j.access_token, refresh_token: j.refresh_token, expires_at: exp };
  }

  async function sb(path, body, token) {
    const res = await fetch(`${config.supabase_url}/auth/v1${path}`, {
      method: body === undefined ? 'GET' : (token && path === '/user' ? 'PUT' : 'POST'),
      headers: { apikey: config.supabase_anon_key, 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let j = {};
    try { j = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) throw new Error(friendly(j.error_description || j.msg || j.message || j.error || 'Something went wrong', j.error_code || j.code));
    return j;
  }
  function friendly(msg, code) {
    const m = String(msg).toLowerCase();
    if (m.includes('invalid login')) return 'Wrong email or password.';
    if (m.includes('email not confirmed')) return 'Please confirm your email first. Check your inbox for the link.';
    if (m.includes('already registered') || code === 'user_already_exists') return 'That email already has an account. Try signing in.';
    if (m.includes('password should be') || code === 'weak_password') return 'Choose a longer password (at least 8 characters).';
    if (m.includes('rate limit') || code === 'over_email_send_rate_limit') return 'Too many attempts. Wait a minute and try again.';
    if (m.includes('valid email') || code === 'email_address_invalid') return 'That email address does not look right.';
    return msg;
  }

  async function refresh() {
    const s = session();
    if (!s || !s.refresh_token) return null;
    try {
      const j = await sb('/token?grant_type=refresh_token', { refresh_token: s.refresh_token });
      const n = normalise(j); save(n); return n;
    } catch (_) { return null; }
  }

  /* ---------- the sign-in screen ---------- */
  function h(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function showGate(mode, note) {
    if (gate) gate.remove();
    gate = h('div', 'authgate');
    const card = h('form', 'authcard');
    card.noValidate = true;
    const state = { mode: mode || 'in' };  // in | up | forgot | newpass | confirm
    const paint = () => {
      const m = state.mode;
      const titles = { in: 'Welcome back', up: 'Create your account', forgot: 'Reset your password', newpass: 'Choose a new password', confirm: 'Check your email' };
      card.innerHTML = `<h1>FitChat</h1><h2>${titles[m]}</h2>`;
      if (config.paused && m === 'in') card.append(h('p', 'authnote', 'FitChat is paused right now. You can still sign in, but only the owner can use it until it is switched back on.'));
      if (note) card.append(h('p', 'authnote', note));
      if (m === 'confirm') {
        card.append(h('p', 'hint', state.msg || 'We sent you a link. Tap it, then come back here and sign in.'));
        const b = h('button', 'btn primary', 'Back to sign in'); b.type = 'button'; b.onclick = () => { state.mode = 'in'; state.msg = ''; paint(); };
        card.append(b); return;
      }
      if (m !== 'newpass') card.append(h('label', null, 'Email<input type="email" name="email" autocomplete="email" inputmode="email" required>'));
      if (m !== 'forgot') card.append(h('label', null, `${m === 'newpass' ? 'New password' : 'Password'}<input type="password" name="password" autocomplete="${m === 'in' ? 'current-password' : 'new-password'}" minlength="8" required>`));
      const err = h('p', 'autherr'); err.hidden = true; err.setAttribute('role', 'alert'); card.append(err);
      const go = h('button', 'btn primary', { in: 'Sign in', up: 'Create account', forgot: 'Send reset link', newpass: 'Save password' }[m]); go.type = 'submit'; card.append(go);
      const links = h('p', 'authlinks');
      const link = (txt, to) => { const a = h('button', 'linkbtn', txt); a.type = 'button'; a.onclick = () => { state.mode = to; paint(); }; links.append(a); };
      if (m === 'in') { link('Create an account', 'up'); link('Forgot password?', 'forgot'); }
      if (m === 'up' || m === 'forgot') link('Back to sign in', 'in');
      card.append(links);
      if (m === 'up') card.append(h('p', 'hint', 'Your food, workouts and body data are private to your account. Use a password you do not use elsewhere.'));
      card.onsubmit = async (ev) => {
        ev.preventDefault();
        err.hidden = true; go.disabled = true;
        const fd = new FormData(card);
        const email = String(fd.get('email') || '').trim(); const password = String(fd.get('password') || '');
        try {
          if (m === 'in') {
            const j = await sb('/token?grant_type=password', { email, password });
            save(normalise(j)); finish();
          } else if (m === 'up') {
            if (password.length < 8) throw new Error('Choose a longer password (at least 8 characters).');
            const j = await sb('/signup', { email, password });
            if (j.access_token) { save(normalise(j)); finish(); } else { state.mode = 'confirm'; state.msg = `We sent a confirmation link to ${email}. Tap it, then come back and sign in.`; paint(); }
          } else if (m === 'forgot') {
            await sb('/recover', { email });
            state.mode = 'confirm'; state.msg = `If ${email} has an account, a reset link is on its way.`; paint();
          } else if (m === 'newpass') {
            if (password.length < 8) throw new Error('Choose a longer password (at least 8 characters).');
            await sb('/user', { password }, state.token);
            save(state.session); finish();
          }
        } catch (e) { err.textContent = e.message; err.hidden = false; go.disabled = false; }
      };
    };
    state.token = showGate.recovery && showGate.recovery.access_token;
    state.session = showGate.recovery;
    paint();
    gate.append(card);
    document.body.append(gate);
    const first = card.querySelector('input'); if (first) setTimeout(() => first.focus(), 50);
  }
  function finish() { if (gate) { gate.remove(); gate = null; } resolveReady(); }

  function showPaused() {
    if (document.querySelector('.authgate.paused')) return;
    const g = h('div', 'authgate paused');
    const c = h('div', 'authcard', '<h1>FitChat</h1><h2>Paused for now</h2><p class="hint">The owner has switched FitChat off for a while. Your data is safe. Please check back later.</p>');
    const retry = h('button', 'btn primary', 'Try again'); retry.onclick = () => location.reload();
    const out = h('button', 'btn', 'Sign out'); out.onclick = () => signOut();
    c.append(retry, out); g.append(c); document.body.append(g);
  }

  function signOut() { memory = null; store.clear(); location.reload(); }

  /* ---------- public bits ---------- */
  async function token() {
    await ready;
    if (config.auth !== 'supabase') return null;
    let s = session();
    if (s && s.expires_at - 60 < Date.now() / 1000) s = await refresh();
    if (!s) { showGate('in', 'Please sign in again.'); await new Promise((r) => { const t = setInterval(() => { if (session()) { clearInterval(t); r(); } }, 300); }); s = session(); }
    return s.access_token;
  }
  async function headers() {
    const t = await token();
    return { ...(t ? { Authorization: `Bearer ${t}` } : {}), ...(tz ? { 'X-TZ': tz } : {}) };
  }
  // A 401 from our server: try one refresh, otherwise ask for the password again.
  async function expired() {
    const n = await refresh();
    if (n) return true;
    store.clear(); memory = null;
    showGate('in', 'Your session expired. Please sign in again.');
    return false;
  }

  // An email link opened while the app is already open in this tab only changes the address after '#'.
  window.addEventListener('hashchange', () => { if (/access_token=|error_description=/.test(location.hash)) location.reload(); });

  window.FCAuth = { ready, token, headers, expired, signOut, showPaused, get config() { return config; }, tz };

  (async () => {
    try {
      const r = await fetch('/api/config', { headers: tz ? { 'X-TZ': tz } : {} });
      config = await r.json();
    } catch (_) { config = { auth: 'none' }; }
    if (config.auth !== 'supabase') { resolveReady(); return; }
    // Coming back from an email link (confirm, or reset password): the tokens are in the address after '#'.
    const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
    if (hash.get('access_token') && hash.get('refresh_token')) {
      const s = normalise({ access_token: hash.get('access_token'), refresh_token: hash.get('refresh_token'), expires_in: +hash.get('expires_in') || 3600 });
      history.replaceState(null, '', location.pathname + location.search);
      if (hash.get('type') === 'recovery') { showGate.recovery = s; showGate('newpass'); return; }
      save(s); resolveReady(); return;
    }
    if (hash.get('error_description')) { const msg = hash.get('error_description').replace(/\+/g, ' '); history.replaceState(null, '', location.pathname); showGate('in', msg); return; }
    let s = session();
    if (s && s.expires_at - 60 < Date.now() / 1000) s = await refresh();
    if (s) { resolveReady(); return; }
    showGate('in');
  })();
})();
