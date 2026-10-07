/* Small helpers shared by the app pages. User text is always inserted with textContent. */
window.UI = (() => {
  'use strict';

  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  async function api(method, url, body) {
    const res = await fetch(url, {
      method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let payload = null;
    try { payload = await res.json(); } catch { /* non-JSON */ }
    if (res.status === 401) { window.location = `/login?next=${encodeURIComponent(location.pathname)}`; throw new Error('Logged out'); }
    if (!res.ok) {
      let msg = payload && payload.detail;
      if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('; ');
      const err = new Error(msg || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return payload;
  }

  function toast(message, kind = 'info') {
    let wrap = document.querySelector('.flash-wrap');
    if (!wrap) { wrap = h('div', { class: 'flash-wrap' }); document.body.append(wrap); }
    const el = h('div', { class: `alert alert-${kind}`, role: 'status' }, message);
    if (kind === 'warning' && /upgrade|elite/i.test(message)) el.append(' ', h('a', { href: '/app/account', text: 'See plans →' }));
    wrap.append(el);
    setTimeout(() => el.remove(), 7000);
  }

  function modal(title, body, footer) {
    const backdrop = h('div', { class: 'modal-backdrop' });
    const close = () => { backdrop.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', onKey);
    backdrop.append(h('div', { class: 'modal', role: 'dialog', 'aria-label': title },
      h('div', { class: 'modal-head' }, h('h3', { text: title }), h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: close }, '✕')),
      h('div', { class: 'modal-body' }, body),
      footer ? h('div', { class: 'modal-foot' }, footer(close)) : null));
    document.body.append(backdrop);
    return close;
  }

  function field(label, input, hint) {
    const id = `f-${Math.random().toString(36).slice(2, 9)}`;
    input.id = id;
    return h('div', { class: 'field' }, h('label', { for: id, text: label }), input, hint ? h('div', { class: 'hint', text: hint }) : null);
  }

  /** Run an async action with a spinner on the button. */
  async function busy(btn, label, fn) {
    const original = Array.from(btn.childNodes);
    btn.disabled = true;
    btn.replaceChildren(h('span', { class: 'spinner' }), ` ${label}`);
    try { return await fn(); }
    finally { btn.disabled = false; btn.replaceChildren(...original); }
  }

  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : null; }

  return { h, api, toast, modal, field, busy, safeUrl };
})();
