/* FitChat screens: bottom tabs, Home, Progress, Winter Arc, reminders. Uses the bridge that app.js exposes. */
(() => {
  'use strict';
  const FC = window.FC;
  if (!FC) return;
  const { $, $$, el, esc, fmtNum, api, toast, guarded, openSheet, openPage, leavePage, state, foodFilter, wUI } = FC;
  const app = $('.app');
  const homeView = $('#homeView');
  const chatView = $('#scroller');
  const pageView = $('#pageView');

  /* tiny safe storage (private mode or blocked storage must never break the app) */
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* ignore */ } },
  };
  const today = () => new Date().toLocaleDateString('en-CA');

  /* ---------- tabs ---------- */
  let tab = 'home';
  function go(name) {
    const again = name === tab;
    tab = name;
    app.dataset.view = name;
    $$('.tab').forEach((t) => { if (t.dataset.tab === name) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current'); });
    homeView.hidden = name !== 'home';
    chatView.hidden = name !== 'coach';
    pageView.hidden = !['food', 'gym', 'progress'].includes(name);
    if (name === 'home') { leavePage(); renderHome(); homeView.scrollTop = 0; }
    else if (name === 'coach') { leavePage(); chatView.scrollTop = chatView.scrollHeight; }
    else if (name === 'food') {
      foodFilter.day = null; foodFilter.dayData = null;
      if (again) foodFilter.view = 'list';
      openPage('Food', FC.renderFood);
    } else if (name === 'gym') {
      wUI.today = null; wUI.routines = null;
      if (again && wUI.view !== 'routine') wUI.view = 'today';
      openPage('Gym', renderGym);
    } else if (name === 'progress') openPage('Progress', renderProgress);
  }
  $$('.tab').forEach((t) => t.addEventListener('click', () => go(t.dataset.tab)));
  FC.go = go;

  const startRoutine = (id) => { wUI.fromRoutine = null; wUI.routineId = id; wUI.plan = null; wUI.swaps = {}; wUI.view = 'routine'; go('gym'); };

  /* ---------- Gym page: the workout screens plus two links ---------- */
  async function renderGym(root) {
    await FC.renderWorkout(root);
    if (wUI.view !== 'today' || state.page == null || root.querySelector('.gymextras')) return;
    const sec = el('section', 'gymextras');
    sec.append(el('h3', null, 'Also'));
    const list = el('div', 'plist');
    const inj = (state.injuries || []).length;
    const gear = (state.unavailable || []).length;
    [['Injuries', inj ? `${inj} active` : 'None logged', () => openSheet('Injuries', FC.renderInjuries)],
      ['Busy gear', gear ? `${gear} marked busy` : 'Nothing marked busy', () => openSheet('Busy gear', FC.renderGear)]].forEach(([t, sub, fn]) => {
      const b = el('button', 'prow', `<div class="grow"><b>${esc(t)}</b><span>${esc(sub)}</span></div>`);
      b.type = 'button';
      b.addEventListener('click', fn);
      list.append(b);
    });
    sec.append(list);
    root.append(sec);
  }

  /* ---------- reminders (nudges) ---------- */
  const NUDGE_LABELS = {
    food: 'Log your food', water: 'Drink water', protein: 'Protein is short', gym: 'Gym time', weight: 'Weekly weigh-in',
    measure: 'Measurements and photo', sleep: 'Log sleep', steps: 'Log steps', gut: 'Digestion',
  };
  let nudgeList = [];
  const muted = () => store.get('fitchat.mute', []);
  const dismissed = () => { const d = store.get('fitchat.dismiss', {}); return d.day === today() ? d.kinds || [] : []; };
  const visibleNudges = () => nudgeList.filter((n) => !muted().includes(n.kind) && !dismissed().includes(n.kind)).slice(0, 2);
  function paintDot() {
    const n = visibleNudges().length;
    const dot = $('#homeDot');
    dot.hidden = !n;
  }
  const notified = new Set();
  function maybeNotify(list) {
    try {
      if (!store.get('fitchat.notify', false) || !window.isSecureContext || !('Notification' in window) || Notification.permission !== 'granted') return;
      list.forEach((n) => {
        const key = `${today()}:${n.kind}`;
        if (notified.has(key)) return;
        notified.add(key);
        new Notification('FitChat', { body: n.text });
      });
    } catch (_) { /* notifications are a bonus */ }
  }
  async function loadNudges() {
    try {
      const r = await api('/api/nudges');
      nudgeList = r.nudges || [];
    } catch (_) { nudgeList = []; }
    paintDot();
    maybeNotify(visibleNudges());
  }
  function runAction(n) {
    const a = n.action || {};
    if (a.type === 'water') {
      api('/api/water', { method: 'POST', body: { ml: a.ml || 250 } }).then(() => { toast(`+${a.ml || 250} ml water`); FC.refreshSummary(); loadNudges().then(() => { if (tab === 'home') renderHome(); }); }).catch((e) => toast(e.message));
      return;
    }
    switch (a.target) {
      case 'food': go('food'); break;
      case 'plan': foodFilter.mode = 'plan'; go('food'); break;
      case 'gym': go('gym'); break;
      case 'gut': FC.gutUI.data = null; openSheet('Gut, water and fibre', FC.renderGut); break;
      case 'weight': FC.weekUI.data = null; openSheet('This week', FC.renderWeek); break;
      case 'body': FC.openBody(); break;
      case 'sleep': FC.openSleep(); break;
      default: break;
    }
  }

  /* ---------- Home ---------- */
  let homeSeq = 0;
  async function renderHome() {
    const seq = ++homeSeq;
    const get = (p) => api(p).catch(() => null);
    const [routines, workout, plan, arc] = await Promise.all([get('/api/routines'), get('/api/workout/today'), get('/api/plan'), get('/api/arc'), loadNudges()]);
    if (seq !== homeSeq) return;
    const home = el('div', 'home');

    visibleNudges().forEach((n) => {
      const box = el('div', 'nudge');
      box.append(el('p', null, esc(n.text)));
      const act = el('button', 'btn small primary', n.action && n.action.type === 'water' ? '+250 ml' : 'Open');
      act.type = 'button';
      act.addEventListener('click', () => runAction(n));
      const x = el('button', 'x', '&times;');
      x.type = 'button';
      x.setAttribute('aria-label', 'Dismiss for today');
      x.addEventListener('click', () => { const d = store.get('fitchat.dismiss', {}); const kinds = d.day === today() ? d.kinds || [] : []; store.set('fitchat.dismiss', { day: today(), kinds: [...kinds, n.kind] }); paintDot(); renderHome(); });
      box.append(act, x);
      home.append(box);
    });

    /* workout */
    const w = el('div', 'hcard');
    w.dataset.card = 'workout';
    const sg = routines && routines.suggestion;
    if (workout && workout.total_sets > 0) {
      w.append(el('h3', null, 'Workout today'), el('p', 'sub', `${workout.total_sets} sets across ${workout.exercises.length} exercises so far.`));
      const b = el('button', 'btn small', 'Continue'); b.type = 'button'; b.addEventListener('click', () => go('gym')); w.append(b);
    } else if (sg && sg.routine_id) {
      w.append(el('h3', null, `Up next: ${esc(sg.name)}`), el('p', 'sub', esc(sg.reason)));
      const b = el('button', 'btn primary small', 'Start workout'); b.type = 'button'; b.dataset.action = 'home-start'; b.addEventListener('click', () => startRoutine(sg.routine_id)); w.append(b);
    } else if (routines && routines.routines.length) {
      w.append(el('h3', null, 'Workout'), el('p', 'sub', esc((sg && sg.reason) || 'Pick a routine or log a lift.')));
      const b = el('button', 'btn small', 'Open Gym'); b.type = 'button'; b.addEventListener('click', () => go('gym')); w.append(b);
    } else {
      w.append(el('h3', null, 'Set up your workouts'), el('p', 'sub', 'Save your split once, then start it each gym day.'));
      const b = el('button', 'btn primary small', 'Set up'); b.type = 'button'; b.addEventListener('click', () => { wUI.view = 'rlist'; go('gym'); }); w.append(b);
    }
    home.append(w);

    /* water */
    const g = state.summary && state.summary.gut;
    if (g) {
      const c = el('div', 'hcard');
      c.dataset.card = 'water';
      c.append(el('h3', null, 'Water'));
      c.append(el('p', 'sub', `<b>${fmtNum(g.water_ml / 1000, 1)}</b> of ${fmtNum(g.water_target_ml / 1000, 1)} L`));
      const bar = el('div', 'mini-bar'); bar.append(el('i')); bar.firstChild.style.width = `${Math.min(100, (100 * g.water_ml) / g.water_target_ml)}%`; c.append(bar);
      const row = el('div', 'hrow');
      [250, 500].forEach((ml) => {
        const b = el('button', 'btn small', `+${ml} ml`);
        b.type = 'button';
        b.addEventListener('click', async () => {
          b.disabled = true;
          const r = await guarded(() => api('/api/water', { method: 'POST', body: { ml } }), 'Could not add');
          if (r) toast(`+${ml} ml water`);
          b.disabled = false;
          FC.refreshSummary();
        });
        row.append(b);
      });
      c.append(row);
      home.append(c);
    }

    /* meal idea */
    const m = el('div', 'hcard');
    m.dataset.card = 'meal';
    m.append(el('h3', null, 'Next meal'));
    if (plan && plan.status === 'plan' && plan.slots.length) {
      const sl = plan.slots[0];
      m.append(el('p', 'sub', `<b>${esc(sl.label)}:</b> ${sl.items.map((i) => `${fmtNum(i.servings, 1)} × ${esc(i.food)}`).join(', ')} <span class="hint">(${fmtNum(sl.totals.calories)} kcal, ${fmtNum(sl.totals.protein_g, 0)} g protein)</span>`));
    } else m.append(el('p', 'sub', esc((plan && plan.summary) || 'Plan what is left of your day.')));
    const mr = el('div', 'hrow');
    const mb = el('button', 'btn small primary', 'See plan'); mb.type = 'button'; mb.addEventListener('click', () => { foodFilter.mode = 'plan'; go('food'); });
    const wk = el('button', 'btn small', 'Plan my week'); wk.type = 'button'; wk.dataset.action = 'home-week'; wk.addEventListener('click', () => FC.openWeekPlan());
    mr.append(mb, wk);
    m.append(mr);
    home.append(m);

    /* Winter Arc */
    if (arc && arc.phase !== 'before') {
      const a = el('button', 'hcard');
      a.type = 'button';
      a.dataset.card = 'arc';
      a.append(el('h3', null, `Winter Arc: day ${arc.day_number} of ${arc.total_days}`));
      const bar = el('div', 'mini-bar'); bar.append(el('i')); bar.firstChild.style.width = `${arc.pct}%`; a.append(bar);
      const pills = el('div', 'pills');
      pills.append(el('span', 'pill', `Protein ${arc.streaks.protein_days} d`), el('span', 'pill', `Water ${arc.streaks.water_days} d`), el('span', 'pill', `Gym ${arc.gym_week.trained}/${arc.gym_week.goal} this week`));
      a.append(pills);
      a.addEventListener('click', () => openSheet('Winter Arc', renderArc));
      home.append(a);
    }

    /* two quiet shortcuts */
    const q = el('div', 'hrow');
    const s1 = el('button', 'btn small', 'Sleep and steps'); s1.type = 'button'; s1.addEventListener('click', () => FC.openSleep());
    const s2 = el('button', 'btn small', 'How do you feel?'); s2.type = 'button'; s2.addEventListener('click', () => openSheet('How you feel today', FC.renderFeeling));
    q.append(s1, s2);
    home.append(q);
    homeView.replaceChildren(home);
  }
  let homeTimer;
  document.addEventListener('fc:summary', () => {
    clearTimeout(homeTimer);
    homeTimer = setTimeout(() => { if (tab === 'home') renderHome(); else loadNudges(); }, 250);
  });
  setInterval(() => { if (document.visibilityState === 'visible') { if (tab === 'home') renderHome(); else loadNudges(); } }, 5 * 60 * 1000);

  /* ---------- Progress list ---------- */
  async function renderProgress(root) {
    root.innerHTML = '<p class="hint">Loading</p>';
    const get = (p) => api(p).catch(() => null);
    const [arc, week, body, ds] = await Promise.all([get('/api/arc'), get('/api/week?days=7'), get('/api/body'), get('/api/daystats?days=14')]);
    if (state.page == null || tab !== 'progress') return;
    root.innerHTML = '';
    const g = state.summary && state.summary.gut;
    const rows = [
      ['Winter Arc', arc ? (arc.phase === 'before' ? `Starts ${arc.start}` : `Day ${arc.day_number} of ${arc.total_days} · protein streak ${arc.streaks.protein_days} d`) : 'Streaks and your 92-day progress', () => openSheet('Winter Arc', renderArc)],
      ['This week', week ? `${week.totals.days_logged} of 7 days logged · ${week.totals.training_days} gym days${week.weight.latest ? ` · ${fmtNum(week.weight.latest.weight_kg, 1)} kg` : ''}` : 'Averages, weight and charts', () => { FC.weekUI.data = null; openSheet('This week', FC.renderWeek); }],
      ['Daily log', 'See any past day, or add food you forgot', () => FC.openDay(null)],
      ['Body', body && body.measures.length ? body.summary.split(';')[0] : 'Measurements and progress photos', () => FC.openBody()],
      ['Sleep and steps', ds && (ds.avg_sleep_h != null || ds.avg_steps != null) ? [ds.avg_sleep_h != null ? `${ds.avg_sleep_h} h sleep` : '', ds.avg_steps != null ? `${fmtNum(ds.avg_steps)} steps` : ''].filter(Boolean).join(' · ') + ' (14-day average)' : 'Log once a day', () => FC.openSleep()],
      ['Water, fibre and stool', g ? `Water ${fmtNum(g.water_ml / 1000, 1)} of ${fmtNum(g.water_target_ml / 1000, 1)} L today` : 'Digestion tracker', () => { FC.gutUI.data = null; openSheet('Gut, water and fibre', FC.renderGut); }],
      ['Reminders', `${Object.keys(NUDGE_LABELS).length - muted().length} of ${Object.keys(NUDGE_LABELS).length} on`, () => openSheet('Reminders', renderReminders)],
      ['Account', FC.accountSub ? FC.accountSub() : 'Your data', () => FC.openAccount && FC.openAccount()],
    ];
    const list = el('div', 'plist');
    rows.forEach(([t, sub, fn]) => {
      const b = el('button', 'prow', `<div class="grow"><b>${esc(t)}</b><span>${esc(sub)}</span></div>`);
      b.type = 'button';
      b.dataset.row = t;
      b.addEventListener('click', fn);
      list.append(b);
    });
    root.append(list);
  }

  /* ---------- Winter Arc sheet ---------- */
  async function renderArc(root) {
    root.innerHTML = '<p class="hint">Loading</p>';
    const a = await guarded(() => api('/api/arc'), 'Could not load the Winter Arc');
    if (!a) { root.innerHTML = '<p class="hint">Could not load. Check the server and try again.</p>'; return; }
    root.innerHTML = '';
    if (a.phase === 'before') { root.append(el('p', 'hint', `The Winter Arc starts on ${esc(a.start)}.`)); return; }
    const head = el('section');
    head.append(el('div', 'arcbig', `<span class="big">${a.day_number}</span><span class="unit">of ${a.total_days} days${a.phase === 'finished' ? ' · finished' : ` · ${a.days_left} left`}</span>`));
    const bar = el('div', 'mini-bar'); bar.append(el('i')); bar.firstChild.style.width = `${a.pct}%`; head.append(bar);
    head.append(el('p', 'hint', `${a.full_days} days fully on track (food logged and protein target hit).`));
    root.append(head);

    const tiles = el('div', 'tiles');
    const tile = (n, unit, label) => { const x = el('div', 'tile'); x.append(el('p', 'tile-num', `${esc(n)}<span class="unit"> ${esc(unit)}</span>`), el('p', 'tile-label', esc(label))); tiles.append(x); };
    tile(a.streaks.protein_days, 'days', 'protein streak');
    tile(a.streaks.water_days, 'days', 'water streak');
    tile(a.streaks.logging_days, 'days', 'food logged in a row');
    tile(a.streaks.gym_weeks, 'weeks', 'gym goal met in a row');
    root.append(tiles);

    const gym = el('section');
    gym.append(el('h3', null, 'Gym this week'));
    gym.append(el('p', 'hint', `<b>${a.gym_week.trained}</b> of ${a.gym_week.goal} days (a day counts with 6 or more sets).`));
    const row = el('div', 'hrow');
    const mk = (label, d) => {
      const b = el('button', 'btn small', label);
      b.type = 'button';
      b.setAttribute('aria-label', d > 0 ? 'More gym days a week' : 'Fewer gym days a week');
      b.disabled = a.gym_week.goal + d < 1 || a.gym_week.goal + d > 7;
      b.addEventListener('click', async () => { if (await guarded(() => api('/api/profile', { method: 'PUT', body: { gym_days_goal: a.gym_week.goal + d } }).then(() => true), 'Could not change')) state.sheet.render(); });
      return b;
    };
    row.append(el('span', 'hint', 'Weekly goal'), mk('−', -1), mk('+', 1));
    gym.append(row);
    root.append(gym);

    const days = el('section');
    days.append(el('h3', null, 'Every day so far'));
    const dots = el('div', 'dots');
    a.dots.forEach((d) => { const x = el('i', `dot ${d.state}${d.trained ? ' trained' : ''}${d.today ? ' today' : ''}`); x.title = d.day; dots.append(x); });
    days.append(dots);
    days.append(el('div', 'legend', '<span><i style="background:var(--green)"></i>On track</span><span><i style="background:var(--blue);opacity:.65"></i>Logged</span><span><i style="background:var(--track)"></i>Missed</span><span><i style="background:var(--yellow);height:3px;vertical-align:2px"></i>Gym day</span>'));
    root.append(days);

    const w = a.weight;
    const wt = el('section');
    wt.append(el('h3', null, 'Weight'));
    if (!w.readings) wt.append(el('p', 'hint', 'No weight logged yet. Weigh in once a week from Progress, This week.'));
    else {
      wt.append(el('p', null, w.change_kg != null ? `<b>${fmtNum(w.start_kg, 1)}</b> to <b>${fmtNum(w.latest_kg, 1)} kg</b> (${w.change_kg > 0 ? '+' : ''}${fmtNum(w.change_kg, 1)} kg)` : `<b>${fmtNum(w.latest_kg, 1)} kg</b>`));
      if (w.per_week_kg != null) wt.append(el('p', 'hint', `Recent pace: ${w.per_week_kg > 0 ? '+' : ''}${fmtNum(w.per_week_kg, 2)} kg a week.`));
      if (w.projected_end_kg != null) wt.append(el('p', 'hint', `If that pace held, you would be near ${fmtNum(w.projected_end_kg, 1)} kg on ${esc(a.end)}. This is an estimate, not a promise.`));
    }
    root.append(wt);
  }

  /* ---------- Reminders sheet ---------- */
  function renderReminders(root) {
    root.innerHTML = '';
    root.append(el('p', 'hint', 'Reminders show on Home and as a dot on the Home tab. Switch off the ones you do not want.'));
    const list = el('div');
    Object.entries(NUDGE_LABELS).forEach(([kind, label]) => {
      const row = el('label', 'toggle', `<span>${esc(label)}</span>`);
      const cb = el('input'); cb.type = 'checkbox'; cb.checked = !muted().includes(kind);
      cb.setAttribute('aria-label', label);
      cb.addEventListener('change', () => { const m = muted().filter((k) => k !== kind); if (!cb.checked) m.push(kind); store.set('fitchat.mute', m); paintDot(); });
      row.append(cb);
      list.append(row);
    });
    root.append(list);
    if (window.isSecureContext && 'Notification' in window) {
      const row = el('label', 'toggle', '<span>Phone alerts while the app is open</span>');
      const cb = el('input'); cb.type = 'checkbox'; cb.checked = store.get('fitchat.notify', false) && Notification.permission === 'granted';
      cb.addEventListener('change', async () => {
        if (cb.checked) { const p = await Notification.requestPermission(); cb.checked = p === 'granted'; }
        store.set('fitchat.notify', cb.checked);
      });
      row.append(cb);
      root.append(row);
    } else {
      root.append(el('p', 'hint', 'Phone alerts when the app is closed need the app hosted on HTTPS. Until then, reminders appear inside the app.'));
    }
  }

  FC.renderArc = renderArc;
  go('home');
})();
