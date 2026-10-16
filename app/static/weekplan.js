/* FitChat: 7-day meal plan and grocery list. */
(() => {
  'use strict';
  const FC = window.FC;
  if (!FC) return;
  const { el, esc, fmtNum, fmtDay, api, toast, guarded, openSheet, state } = FC;
  const rerender = () => { if (state.sheet) state.sheet.render(); };
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* ignore */ } },
  };
  const wp = { plan: null, loaded: false, tab: 'plan', day: 0, busy: false };

  FC.openWeekPlan = () => { wp.loaded = false; wp.tab = 'plan'; wp.day = 0; openSheet('Week plan', renderWeekPlan); };

  async function generate(reshuffle) {
    wp.busy = true; rerender();
    const r = await guarded(() => api('/api/mealprep', { method: 'POST', body: { reshuffle: !!reshuffle }, timeout: 60000 }), 'Could not make a plan');
    wp.busy = false;
    if (r) { wp.plan = r.plan; wp.day = 0; toast(reshuffle ? 'New version ready' : 'Plan ready'); }
    rerender();
  }

  async function renderWeekPlan(root) {
    if (!wp.loaded) {
      root.innerHTML = '<p class="hint">Loading</p>';
      const r = await guarded(() => api('/api/mealprep'), 'Could not load');
      if (!r) { root.innerHTML = '<p class="hint">Could not load. Check the server and try again.</p>'; return; }
      wp.plan = r.plan; wp.loaded = true;
    }
    root.innerHTML = '';
    if (wp.busy) { root.append(el('p', 'hint', 'Planning your week. This takes a few seconds.')); return; }
    if (!wp.plan) {
      root.append(el('p', null, 'Get a 7-day plan built from your own foods and recipes, sized to your calorie and protein targets, plus a shopping list you can tick off.'));
      const b = el('button', 'btn primary big', 'Make my 7-day plan');
      b.type = 'button'; b.dataset.action = 'make-week';
      b.addEventListener('click', () => generate(false));
      root.append(b);
      return;
    }
    const p = wp.plan;
    const seg = el('div', 'seg words');
    [['plan', 'Meals'], ['shop', 'Shopping list']].forEach(([k, label]) => {
      const b = el('button', null, label); b.type = 'button'; b.dataset.key = k; b.setAttribute('aria-pressed', String(wp.tab === k));
      b.addEventListener('click', () => { wp.tab = k; rerender(); });
      seg.append(b);
    });
    root.append(seg);
    const age = Math.round((new Date(new Date().toLocaleDateString('en-CA')) - new Date(p.start)) / 86400000);
    if (age > 6) root.append(el('p', 'hint', 'This plan is from an earlier week. Make a fresh one below.'));
    (wp.tab === 'shop' ? paintShop : paintMeals)(root, p);
    const acts = el('div', 'actions');
    const again = el('button', 'btn small', 'Another version'); again.type = 'button'; again.dataset.action = 'reshuffle'; again.addEventListener('click', () => generate(true));
    const fresh = el('button', 'btn small', 'New plan from today'); fresh.type = 'button'; fresh.addEventListener('click', () => generate(false));
    acts.append(again, fresh);
    root.append(acts);
  }

  function paintMeals(root, p) {
    root.append(el('p', 'hint', esc(p.summary)));
    const seg = el('div', 'dayseg');
    p.days.forEach((d, i) => {
      const b = el('button', null, `${esc(d.weekday)} ${new Date(`${d.day}T00:00:00`).getDate()}`);
      b.type = 'button'; b.setAttribute('aria-pressed', String(wp.day === i));
      b.addEventListener('click', () => { wp.day = i; rerender(); });
      seg.append(b);
    });
    root.append(seg);
    const d = p.days[Math.min(wp.day, p.days.length - 1)];
    root.append(el('p', 'hint', `${fmtNum(d.totals.calories)} kcal · ${fmtNum(d.totals.protein_g, 0)} g protein · ${fmtNum(d.totals.fibre_g, 0)} g fibre`));
    const isToday = d.day === new Date().toLocaleDateString('en-CA');
    d.slots.forEach((sl) => {
      const card = el('div', 'plancard');
      card.dataset.slot = sl.slot;
      card.append(el('h4', null, `${esc(sl.label)} <span class="hint">${fmtNum(sl.totals.calories)} kcal, ${fmtNum(sl.totals.protein_g, 0)} g protein</span>`));
      sl.items.forEach((i) => card.append(el('div', 'planrow', `<span class="grow">${fmtNum(i.servings, 1)} &times; ${esc(i.food)} <span class="hint">${esc(i.serving)}</span></span>`)));
      if (isToday) {
        const log = el('button', 'btn small', `Log ${sl.label.toLowerCase()}`);
        log.type = 'button';
        log.addEventListener('click', async () => {
          log.disabled = true;
          for (const i of sl.items) {
            const r = await guarded(() => api('/api/meals', { method: 'POST', body: { name: i.food, quantity: i.servings, meal_type: sl.slot } }), `Could not log ${i.food}`);
            if (!r) { log.disabled = false; FC.foodChanged(); return; }
          }
          toast(`${sl.label} logged`);
          FC.foodChanged();
        });
        card.append(log);
      }
      root.append(card);
    });
  }

  function paintShop(root, p) {
    const key = `fitchat.grocery.${p.start}`;
    const done = new Set(store.get(key, []));
    const total = p.grocery.reduce((n, g) => n + g.items.length, 0);
    const left = el('p', 'hint');
    const upd = () => { left.textContent = `${total - done.size} of ${total} items left to buy`; };
    upd();
    root.append(left);
    p.grocery.forEach((g) => {
      const sec = el('section', 'aisle');
      sec.append(el('h4', null, esc(g.aisle)));
      g.items.forEach((i) => {
        const id = `${g.aisle}|${i.name}`;
        const row = el('label', 'check');
        const cb = el('input'); cb.type = 'checkbox'; cb.checked = done.has(id); cb.setAttribute('aria-label', `${i.name}, ${i.text}`);
        cb.addEventListener('change', () => { if (cb.checked) done.add(id); else done.delete(id); store.set(key, [...done]); upd(); });
        row.append(cb, el('span', null, esc(i.name)), el('em', null, esc(i.text)));
        sec.append(row);
      });
      root.append(sec);
    });
    root.append(el('p', 'hint', 'Amounts are raw or dry weights for the whole week, rounded up. Check what you already have at home.'));
    const acts = el('div', 'actions');
    const copy = el('button', 'btn small', 'Copy list'); copy.type = 'button'; copy.dataset.action = 'copy-list';
    copy.addEventListener('click', async () => {
      try { if (navigator.share) { await navigator.share({ title: 'Grocery list', text: p.grocery_text }); return; } } catch (_) { return; }
      try { await navigator.clipboard.writeText(p.grocery_text); toast('List copied'); } catch (_) {
        const ta = el('textarea'); ta.value = p.grocery_text; document.body.append(ta); ta.select();
        try { document.execCommand('copy'); toast('List copied'); } catch (__) { toast('Could not copy'); }
        ta.remove();
      }
    });
    const clear = el('button', 'btn small', 'Untick all'); clear.type = 'button';
    clear.addEventListener('click', () => { store.set(key, []); rerender(); });
    acts.append(copy, clear);
    root.append(acts);
  }
})();
