/* Resume editor: guided steps, autosave, live preview, AI assist, versions.
 * Plain DOM, no framework. All user-provided text is inserted with textContent. */
(() => {
  'use strict';

  const boot = JSON.parse(document.getElementById('boot').textContent);
  const RID = boot.resumeId;
  const TEMPLATES = boot.templates;
  let data = boot.data;
  let creditsLeft = boot.creditsLeft;

  // ------------------------------------------------------------ helpers
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
  const $ = (sel) => document.querySelector(sel);

  /** Text with [placeholders] highlighted, built safely. */
  function withPlaceholders(text) {
    const frag = document.createDocumentFragment();
    const parts = String(text).split(/(\[[^\]]{1,40}\])/g);
    for (const p of parts) {
      if (!p) continue;
      if (/^\[[^\]]+\]$/.test(p)) frag.append(h('span', { class: 'placeholder-hl', text: p }));
      else frag.append(document.createTextNode(p.replace(/\*\*/g, '')));
    }
    return frag;
  }

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
    let payload = null;
    try { payload = await res.json(); } catch { /* non-JSON */ }
    if (res.status === 401) { window.location = `/login?next=/app/resumes/${RID}`; throw new Error('Logged out'); }
    if (!res.ok) {
      const err = new Error((payload && payload.detail) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return payload;
  }

  function toast(message, kind = 'info') {
    let wrap = $('.flash-wrap');
    if (!wrap) { wrap = h('div', { class: 'flash-wrap' }); document.body.append(wrap); }
    const el = h('div', { class: `alert alert-${kind}`, role: 'status' }, message);
    if (kind === 'warning' && /upgrade/i.test(message)) {
      el.append(' ', h('a', { href: '/app/account', text: 'See plans →' }));
    }
    wrap.append(el);
    setTimeout(() => el.remove(), 6000);
  }

  function setCredits(n) {
    if (typeof n !== 'number') return;
    creditsLeft = n;
    $('#credits').textContent = `✨ ${n} credits`;
  }

  // ------------------------------------------------------------ save + preview
  let saveTimer = null, previewTimer = null, saving = false, dirty = false, previewSeq = 0;
  const saveState = $('#save-state');

  function changed({ preview = true } = {}) {
    dirty = true;
    saveState.textContent = 'Unsaved changes';
    saveState.className = 'save-state dirty';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 800);
    if (preview) { clearTimeout(previewTimer); previewTimer = setTimeout(refreshPreview, 450); }
  }

  async function save() {
    if (saving) { clearTimeout(saveTimer); saveTimer = setTimeout(save, 300); return; }
    if (!dirty) return;
    saving = true; dirty = false;
    saveState.textContent = 'Saving…'; saveState.className = 'save-state';
    try {
      await api('PUT', `/api/resumes/${RID}`, { title: $('#title').value, data });
      if (!dirty) { saveState.textContent = 'All changes saved'; saveState.className = 'save-state'; }
    } catch (e) {
      dirty = true;
      saveState.textContent = 'Save failed, retrying…'; saveState.className = 'save-state error';
      saveTimer = setTimeout(save, 4000);
    } finally { saving = false; }
  }

  async function flushSave() {
    clearTimeout(saveTimer);
    while (saving) await new Promise(r => setTimeout(r, 100));
    if (dirty) await save();
  }

  window.addEventListener('beforeunload', (e) => {
    if (dirty || saving) { e.preventDefault(); e.returnValue = ''; }
  });

  async function refreshPreview() {
    const seq = ++previewSeq;
    const box = $('#preview');
    box.classList.add('loading');
    try {
      const res = await api('POST', '/api/preview', { data });
      if (seq !== previewSeq) return; // A newer preview is on its way.
      box.replaceChildren();
      if (res.locked) {
        box.append(h('div', { class: 'alert alert-warning locked-banner' },
          `${TEMPLATES[data.design.template].name} is a Pro template. Preview it freely; `,
          h('a', { href: '/app/account', text: 'upgrade' }), ' to download it.'));
      }
      if (res.error) box.append(h('div', { class: 'alert alert-error preview-msg', text: res.error }));
      for (const w of res.warnings || []) box.append(h('div', { class: 'alert alert-warning preview-msg', text: w }));
      res.pages.forEach((src, i) => box.append(h('img', { src, alt: `Resume page ${i + 1}` })));
      $('#page-count').textContent = res.pages.length ? `${res.pages.length} page${res.pages.length > 1 ? 's' : ''}` : '';
      if (res.pages.length > 1) {
        $('#page-count').textContent += ' · tip: most resumes should fit on one page';
      }
    } catch (e) {
      if (seq === previewSeq) box.replaceChildren(h('div', { class: 'alert alert-error preview-msg', text: e.message }));
    } finally {
      if (seq === previewSeq) box.classList.remove('loading');
    }
  }

  // ------------------------------------------------------------ form widgets
  function field(label, obj, key, opts = {}) {
    const id = `f-${Math.random().toString(36).slice(2, 9)}`;
    const common = {
      id, placeholder: opts.placeholder || '', value: obj[key] ?? '',
      oninput: (e) => { obj[key] = e.target.value; opts.onchange?.(); changed(); },
    };
    let input;
    if (opts.textarea) input = h('textarea', { ...common, rows: opts.rows || 4 });
    else input = h('input', { ...common, type: opts.type || 'text', autocomplete: opts.autocomplete || 'off' });
    return h('div', { class: 'field' },
      h('label', { for: id, text: label }), input,
      opts.hint ? h('div', { class: 'hint', text: opts.hint }) : null);
  }

  function aiButton(label, onclick) {
    const btn = h('button', { class: 'btn btn-ai btn-sm', type: 'button' }, `✨ ${label}`);
    btn.addEventListener('click', async () => {
      if (creditsLeft <= 0) { toast('You are out of AI credits this month. Upgrade to Pro for more.', 'warning'); return; }
      const original = btn.textContent;
      btn.disabled = true;
      btn.replaceChildren(h('span', { class: 'spinner' }), ' Thinking…');
      try { await onclick(btn); }
      catch (e) { toast(e.message, e.status === 402 ? 'warning' : 'error'); }
      finally { btn.disabled = false; btn.textContent = original; }
    });
    return btn;
  }

  function suggestionBox(title, bodyEl, actions) {
    const box = h('div', { class: 'suggest' },
      h('div', { class: 'suggest-head' }, `✨ ${title}`),
      bodyEl,
      h('div', { class: 'row' }, ...actions(() => box.remove())));
    return box;
  }

  function moveItem(list, i, delta) {
    const j = i + delta;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    changed(); renderStep();
  }

  /** Card for one repeatable entry (job, school, project...). */
  function entryCard(list, i, titleFn, bodyFn, noun) {
    const item = list[i];
    const card = h('div', { class: 'card entry' });
    const titleEl = h('div', { class: 'title' });
    const updateTitle = () => {
      const t = titleFn(item);
      titleEl.textContent = t || `New ${noun}`;
      titleEl.classList.toggle('placeholder', !t);
    };
    updateTitle();
    card.append(
      h('div', { class: 'entry-head' },
        h('button', { class: 'icon-btn', type: 'button', title: 'Collapse', 'aria-label': 'Collapse',
          onclick: () => card.classList.toggle('collapsed') }, '▾'),
        titleEl,
        h('button', { class: 'icon-btn', type: 'button', title: 'Move up', 'aria-label': 'Move up', onclick: () => moveItem(list, i, -1) }, '↑'),
        h('button', { class: 'icon-btn', type: 'button', title: 'Move down', 'aria-label': 'Move down', onclick: () => moveItem(list, i, 1) }, '↓'),
        h('button', { class: 'icon-btn', type: 'button', title: `Remove ${noun}`, 'aria-label': `Remove ${noun}`,
          onclick: () => { if (confirm(`Remove this ${noun}?`)) { list.splice(i, 1); changed(); renderStep(); } } }, '✕')),
      h('div', { class: 'entry-body' }, bodyFn(item, updateTitle)));
    return card;
  }

  /** Editable bullet list with per-bullet and whole-list AI rewrite. */
  function bulletEditor(owner, key, ctx = {}) {
    const wrap = h('div');
    const draw = () => {
      const list = owner[key];
      const rows = list.map((b, i) => {
        const ta = h('textarea', {
          rows: 2, value: b, placeholder: ctx.placeholder || 'Start with an action verb: Led, Built, Increased…',
          oninput: (e) => { list[i] = e.target.value; changed(); },
          onkeydown: (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault(); list.splice(i + 1, 0, ''); changed({ preview: false }); draw();
              wrap.querySelectorAll('textarea')[i + 1]?.focus();
            }
          },
        });
        const tools = [];
        if (ctx.ai) {
          tools.push(h('button', {
            class: 'icon-btn', type: 'button', title: 'Rewrite this bullet with AI', 'aria-label': 'Rewrite this bullet with AI',
            onclick: async (e) => {
              const btn = e.currentTarget;
              if (!list[i].trim()) return;
              if (creditsLeft <= 0) { toast('You are out of AI credits this month. Upgrade to Pro for more.', 'warning'); return; }
              btn.disabled = true; btn.replaceChildren(h('span', { class: 'spinner' }));
              try {
                const res = await api('POST', '/api/ai/bullets', { bullets: [list[i]], ...ctx.ai() });
                setCredits(res.credits_left);
                const box = suggestionBox('Suggested rewrite', h('p', { class: 'diff-new' }, withPlaceholders(res.bullets[0])), (close) => [
                  h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => { list[i] = res.bullets[0]; changed(); draw(); } }, 'Use this'),
                  h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: close }, 'Dismiss')]);
                rowEl.after(box);
              } catch (err) { toast(err.message, err.status === 402 ? 'warning' : 'error'); }
              finally { btn.disabled = false; btn.textContent = '✨'; }
            },
          }, '✨'));
        }
        tools.push(h('button', {
          class: 'icon-btn', type: 'button', title: 'Remove bullet', 'aria-label': 'Remove bullet',
          onclick: () => { list.splice(i, 1); changed(); draw(); },
        }, '✕'));
        const rowEl = h('div', { class: 'bullet' }, h('span', { class: 'dot' }, '•'), ta, ...tools);
        return rowEl;
      });
      const toolbar = h('div', { class: 'bullet-tools' },
        h('button', { class: 'btn btn-secondary btn-sm', type: 'button', onclick: () => { list.push(''); changed({ preview: false }); draw(); wrap.querySelectorAll('textarea')[list.length - 1]?.focus(); } }, '＋ Add bullet'));
      if (ctx.ai) {
        toolbar.append(aiButton('Improve all bullets', async () => {
          const bullets = list.filter(b => b.trim());
          if (!bullets.length) { toast('Write a few bullets first. Rough notes are fine!', 'info'); return; }
          const res = await api('POST', '/api/ai/bullets', { bullets, ...ctx.ai() });
          setCredits(res.credits_left);
          const body = h('ul', {}, res.bullets.map((b, i) => h('li', {},
            h('div', { class: 'diff-old', text: bullets[i] }), h('div', { class: 'diff-new' }, withPlaceholders(b)))));
          wrap.querySelector('.suggest')?.remove();
          wrap.append(suggestionBox('Suggested rewrites', body, (close) => [
            h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => { owner[key] = res.bullets.slice(); changed(); draw(); } }, 'Replace all'),
            h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: close }, 'Dismiss')]));
        }));
      }
      wrap.replaceChildren(h('div', { class: 'bullets' }, rows), toolbar);
      if (/\[[^\]]+\]/.test(list.join(' '))) {
        wrap.append(h('div', { class: 'hint' }, 'Replace the ', h('span', { class: 'placeholder-hl', text: '[placeholders]' }), ' with your real numbers before downloading.'));
      }
    };
    draw();
    return wrap;
  }

  // ------------------------------------------------------------ steps
  const jobKey = `jd-${RID}`;
  const store = {
    get(k) { try { return localStorage.getItem(k) || ''; } catch { return ''; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const STEPS = [
    { key: 'contact', label: 'Contact', icon: '👤', done: () => !!(data.basics.name && data.basics.email), render: stepContact },
    { key: 'experience', label: 'Experience', icon: '💼', done: () => data.experience.some(e => e.company), render: stepExperience },
    { key: 'education', label: 'Education', icon: '🎓', done: () => data.education.some(e => e.institution), render: stepEducation },
    { key: 'skills', label: 'Skills', icon: '🛠', done: () => data.skills.some(s => s.details), render: stepSkills },
    { key: 'projects', label: 'Projects', icon: '🚀', done: () => data.projects.some(p => p.name), render: stepProjects },
    { key: 'extras', label: 'Certifications', icon: '🏅', done: () => data.certifications.some(c => c.name), render: stepExtras },
    { key: 'summary', label: 'Summary', icon: '📝', done: () => !!data.summary, render: stepSummary },
    { key: 'design', label: 'Design', icon: '🎨', divider: true, done: () => true, render: stepDesign },
    { key: 'tailor', label: 'Tailor to a job', icon: '🎯', done: () => false, render: stepTailor },
  ];
  let current = 0;

  function renderNav() {
    const nav = $('#steps');
    nav.replaceChildren();
    STEPS.forEach((s, i) => {
      if (s.divider) nav.append(h('hr'));
      nav.append(h('button', {
        type: 'button', class: `${i === current ? 'active' : ''} ${s.done() && i !== current ? 'done' : ''}`,
        onclick: () => go(i), title: s.label,
      }, h('span', { class: 'num' }, s.done() && i !== current ? '✓' : s.icon), h('span', { class: 'lbl', text: s.label })));
    });
  }

  function go(i) {
    current = Math.max(0, Math.min(STEPS.length - 1, i));
    try { history.replaceState(null, '', `#${STEPS[current].key}`); } catch { /* ignore */ }
    renderStep();
    $('#form').scrollTop = 0;
    window.scrollTo(0, 0);
  }

  function renderStep() {
    renderNav();
    const step = STEPS[current];
    const form = $('#form');
    form.replaceChildren(step.render());
    const foot = h('div', { class: 'step-foot' },
      current > 0 ? h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => go(current - 1) }, `← ${STEPS[current - 1].label}`) : h('span'),
      current < STEPS.length - 1 ? h('button', { class: 'btn btn-primary', type: 'button', onclick: () => go(current + 1) }, `Next: ${STEPS[current + 1].label} →`)
        : h('a', { class: 'btn btn-primary', href: `/app/resumes/${RID}/pdf`, onclick: downloadClick }, '⬇ Download PDF'));
    form.append(foot);
  }

  function head(title, sub) {
    return h('div', { class: 'step-head' }, h('h2', { text: title }), h('p', { text: sub }));
  }

  function stepContact() {
    const b = data.basics;
    return h('div', {},
      head('Contact details', 'How recruiters reach you. Keep it simple; a city and state is enough for location.'),
      field('Full name', b, 'name', { placeholder: 'Alex Morgan', autocomplete: 'name' }),
      field('Headline', b, 'headline', { placeholder: 'Senior Product Engineer', hint: 'Your target title. Matching the job title helps ATS ranking.' }),
      h('div', { class: 'grid-2' },
        field('Email', b, 'email', { type: 'email', placeholder: 'you@example.com', autocomplete: 'email' }),
        field('Phone', b, 'phone', { type: 'tel', placeholder: '+1 415 555 0142', autocomplete: 'tel', hint: 'Include the country code for non-US numbers.' })),
      field('Location', b, 'location', { placeholder: 'San Francisco, CA' }),
      h('div', { class: 'grid-2' },
        field('LinkedIn', b, 'linkedin', { placeholder: 'linkedin.com/in/username' }),
        field('GitHub', b, 'github', { placeholder: 'github.com/username' })),
      field('Website / portfolio', b, 'website', { placeholder: 'yourname.dev' }));
  }

  function stepSummary() {
    const out = h('div', {},
      head('Professional summary', 'Two or three sentences on who you are and the value you bring. Write it last, once the rest is filled in.'));
    const ta = field('Summary', data, 'summary', { textarea: true, rows: 5, placeholder: 'Product-minded engineer with 7 years…' });
    out.append(ta);
    const jd = store.get(jobKey);
    out.append(h('div', { class: 'row' }, aiButton(jd ? 'Write summary for my target job' : 'Write summary with AI', async () => {
      const res = await api('POST', '/api/ai/summary', { data, job_description: jd });
      setCredits(res.credits_left);
      out.querySelector('.suggest')?.remove();
      out.append(suggestionBox('Suggested summary', h('p', { class: 'diff-new' }, withPlaceholders(res.summary)), (close) => [
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => { data.summary = res.summary; changed(); renderStep(); } }, 'Use this'),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: close }, 'Dismiss')]));
    })));
    if (jd) out.append(h('p', { class: 'hint', text: 'Uses the job description saved in “Tailor to a job”.' }));
    return out;
  }

  function stepExperience() {
    const out = h('div', {}, head('Work experience', 'Most recent first. Aim for 3–5 bullets per role that show results, not duties.'));
    data.experience.forEach((_, i) => {
      out.append(entryCard(data.experience, i,
        (e) => [e.position, e.company].filter(Boolean).join(' · '),
        (e, updateTitle) => {
          const cur = h('input', { type: 'checkbox', checked: e.current, onchange: (ev) => { e.current = ev.target.checked; endField.querySelector('input').disabled = e.current; changed(); } });
          const endField = field('End date', e, 'end_date', { type: 'month' });
          endField.querySelector('input').disabled = e.current;
          return h('div', {},
            h('div', { class: 'grid-2' },
              field('Job title', e, 'position', { placeholder: 'Software Engineer', onchange: updateTitle }),
              field('Company', e, 'company', { placeholder: 'Acme Inc.', onchange: updateTitle })),
            field('Location', e, 'location', { placeholder: 'Remote' }),
            h('div', { class: 'grid-2' }, field('Start date', e, 'start_date', { type: 'month' }), endField),
            h('label', { class: 'check', style: 'margin:-4px 0 14px' }, cur, 'I currently work here'),
            h('label', { text: 'Achievements' }),
            bulletEditor(e, 'bullets', { ai: () => ({ position: e.position, company: e.company, job_description: store.get(jobKey) }) }));
        }, 'position'));
    });
    out.append(h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => {
      data.experience.push({ position: '', company: '', location: '', start_date: '', end_date: '', current: false, bullets: [''] });
      changed({ preview: false }); renderStep();
    } }, '＋ Add position'));
    return out;
  }

  function stepEducation() {
    const out = h('div', {}, head('Education', 'Degrees, bootcamps or relevant coursework. Add honors or GPA if they help.'));
    data.education.forEach((_, i) => {
      out.append(entryCard(data.education, i,
        (e) => [e.degree, e.area, e.institution].filter(Boolean).join(' · '),
        (e, updateTitle) => h('div', {},
          field('School', e, 'institution', { placeholder: 'University of Michigan', onchange: updateTitle }),
          h('div', { class: 'grid-2' },
            field('Degree', e, 'degree', { placeholder: 'BS', onchange: updateTitle }),
            field('Field of study', e, 'area', { placeholder: 'Computer Science', onchange: updateTitle })),
          field('Location', e, 'location', { placeholder: 'Ann Arbor, MI' }),
          h('div', { class: 'grid-2' }, field('Start date', e, 'start_date', { type: 'month' }), field('End date', e, 'end_date', { type: 'month' })),
          h('label', { text: 'Details (optional)' }),
          bulletEditor(e, 'details', { placeholder: 'GPA 3.8/4.0, Dean’s List' })), 'school'));
    });
    out.append(h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => {
      data.education.push({ institution: '', degree: '', area: '', location: '', start_date: '', end_date: '', details: [] });
      changed({ preview: false }); renderStep();
    } }, '＋ Add education'));
    return out;
  }

  function stepProjects() {
    const out = h('div', {}, head('Projects', 'Side projects, open source or notable work. Great for career changers and new grads.'));
    data.projects.forEach((_, i) => {
      out.append(entryCard(data.projects, i, (p) => p.name,
        (p, updateTitle) => h('div', {},
          h('div', { class: 'grid-2' },
            field('Project name', p, 'name', { placeholder: 'OpenMetrics Dashboard', onchange: updateTitle }),
            field('Link (optional)', p, 'link', { placeholder: 'github.com/you/project' })),
          h('div', { class: 'grid-2' }, field('Start date', p, 'start_date', { type: 'month' }), field('End date', p, 'end_date', { type: 'month' })),
          h('label', { text: 'Highlights' }),
          bulletEditor(p, 'bullets', { ai: () => ({ position: p.name, company: 'personal project', job_description: store.get(jobKey) }) })), 'project'));
    });
    out.append(h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => {
      data.projects.push({ name: '', link: '', start_date: '', end_date: '', bullets: [''] });
      changed({ preview: false }); renderStep();
    } }, '＋ Add project'));
    return out;
  }

  function stepSkills() {
    const out = h('div', {}, head('Skills', 'Group skills into short labeled lines. List the tools named in the job posting you actually know.'));
    data.skills.forEach((s, i) => {
      out.append(h('div', { class: 'card entry' },
        h('div', { class: 'grid-2', style: 'grid-template-columns: 160px 1fr auto; align-items:end' },
          field('Category', s, 'label', { placeholder: 'Languages' }),
          field('Skills', s, 'details', { placeholder: 'Python, SQL, TypeScript' }),
          h('button', { class: 'icon-btn', type: 'button', style: 'margin-bottom:18px', title: 'Remove', 'aria-label': 'Remove skill group',
            onclick: () => { data.skills.splice(i, 1); changed(); renderStep(); } }, '✕'))));
    });
    out.append(h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => { data.skills.push({ label: '', details: '' }); changed({ preview: false }); renderStep(); } }, '＋ Add skill group'));
    return out;
  }

  function stepExtras() {
    const out = h('div', {}, head('Certifications', 'Licenses and certifications that matter for the roles you want.'));
    data.certifications.forEach((c, i) => {
      out.append(entryCard(data.certifications, i, (c) => c.name,
        (c, updateTitle) => h('div', {},
          field('Certification', c, 'name', { placeholder: 'AWS Certified Solutions Architect', onchange: updateTitle }),
          h('div', { class: 'grid-2' }, field('Issuer', c, 'issuer', { placeholder: 'Amazon' }), field('Year', c, 'date', { placeholder: '2024' }))), 'certification'));
    });
    out.append(h('button', { class: 'btn btn-secondary', type: 'button', onclick: () => { data.certifications.push({ name: '', issuer: '', date: '' }); changed({ preview: false }); renderStep(); } }, '＋ Add certification'));
    return out;
  }

  const COLORS = ['', '#1f3a93', '#004f90', '#0f766e', '#15803d', '#7c2d12', '#9f1239', '#6d28d9', '#111827'];

  function stepDesign() {
    const d = data.design;
    const out = h('div', {}, head('Design', 'Every template is single-column and ATS-safe. Pick the one that fits your industry.'));
    const grid = h('div', { class: 'tpl-picker' });
    for (const [key, t] of Object.entries(TEMPLATES)) {
      grid.append(h('button', {
        type: 'button', class: `tpl-option ${d.template === key ? 'selected' : ''}`,
        onclick: () => { d.template = key; $('#quick-template').value = key; changed(); renderStep(); },
      }, h('img', { src: `/static/img/templates/${key}.png`, alt: '', loading: 'lazy' }),
      h('span', {}, t.name, t.free ? null : h('span', { class: 'badge badge-pro', text: boot.isPro ? 'Pro' : 'Pro 🔒' }))));
    }
    out.append(grid);
    const sw = h('div', { class: 'swatches' });
    for (const c of COLORS) {
      sw.append(h('button', {
        type: 'button', class: `swatch ${d.accent_color === c ? 'selected' : ''}`,
        style: c ? `background:${c}` : 'background: conic-gradient(#ddd 0 25%, #fff 0 50%, #ddd 0 75%, #fff 0)',
        title: c || 'Template default', 'aria-label': c ? `Accent color ${c}` : 'Template default color',
        onclick: () => { d.accent_color = c; changed(); renderStep(); },
      }));
    }
    out.append(h('div', { class: 'field', style: 'margin-top:22px' }, h('label', { text: 'Accent color' }), sw));
    const size = h('select', { onchange: (e) => { d.page_size = e.target.value; changed(); } },
      h('option', { value: 'us-letter', text: 'US Letter (8.5 × 11 in)' }), h('option', { value: 'a4', text: 'A4 (210 × 297 mm)' }));
    size.value = d.page_size;
    out.append(h('div', { class: 'field' }, h('label', { text: 'Page size' }), size));
    return out;
  }

  function stepTailor() {
    const out = h('div', {}, head('Tailor to a job', 'Paste a job description to see how well you match. Then let AI tailor your summary and bullets.'));
    const ta = h('textarea', { rows: 9, placeholder: 'Paste the full job description here…', value: store.get(jobKey),
      oninput: (e) => store.set(jobKey, e.target.value) });
    out.append(h('div', { class: 'field' }, h('label', { text: 'Job description' }), ta));
    const results = h('div');
    const checkBtn = h('button', { class: 'btn btn-secondary', type: 'button', onclick: async () => {
      if (ta.value.trim().length < 80) { toast('Paste the full job description (at least a few sentences).', 'info'); return; }
      try { showScore(results, await api('POST', '/api/keywords', { data, job_description: ta.value })); }
      catch (e) { toast(e.message, 'error'); }
    } }, '📊 Check match score (free)');
    const tailorBtn = aiButton('Tailor my resume', async () => {
      if (ta.value.trim().length < 80) { toast('Paste the full job description (at least a few sentences).', 'info'); return; }
      await flushSave();
      const [score, res] = await Promise.all([
        api('POST', '/api/keywords', { data, job_description: ta.value }),
        api('POST', '/api/ai/tailor', { data, job_description: ta.value }),
      ]);
      setCredits(res.credits_left);
      showScore(results, score);
      showTailoring(results, res);
    });
    out.append(h('div', { class: 'row' }, checkBtn, tailorBtn), h('div', { style: 'height:16px' }), results);
    if (!boot.aiEnabled) out.append(h('p', { class: 'hint', text: 'Demo mode: the server has no ANTHROPIC_API_KEY, so AI suggestions are simple heuristics.' }));
    return out;
  }

  function showScore(container, rep) {
    container.querySelector('.score-card')?.remove();
    const color = rep.score >= 75 ? 'var(--success)' : rep.score >= 50 ? '#ca8a04' : 'var(--danger)';
    const card = h('div', { class: 'card score-card', style: 'margin-bottom:14px' },
      h('div', { class: 'score-box' },
        h('div', { class: 'score-ring', style: `--p:${rep.score}; background: conic-gradient(${color} calc(var(--p) * 1%), var(--surface-2) 0)` }, h('b', { text: String(rep.score) })),
        h('div', {},
          h('b', { text: 'Keyword match' }),
          h('div', { class: 'small muted', text: `${rep.matched.length} of ${rep.matched.length + rep.missing.length} key terms from the job appear in your resume.` }))),
      h('div', { style: 'padding: 0 16px 16px' },
        rep.missing.length ? h('div', { class: 'small', style: 'margin-bottom:6px' }, h('b', { text: 'Missing: ' }), 'add these where they truthfully apply') : null,
        h('div', { class: 'chips', style: 'margin-bottom:10px' }, rep.missing.map(k => h('span', { class: 'chip miss', text: k }))),
        rep.matched.length ? h('div', { class: 'small', style: 'margin-bottom:6px' }, h('b', { text: 'Matched' })) : null,
        h('div', { class: 'chips' }, rep.matched.map(k => h('span', { class: 'chip ok', text: k })))));
    container.prepend(card);
  }

  function showTailoring(container, res) {
    container.querySelector('.tailor-card')?.remove();
    const pending = { summary: res.summary, experience: res.experience, skills: res.skills_to_add };
    const applyTo = (target) => {
      if (pending.summary) target.summary = pending.summary;
      for (const e of pending.experience) if (target.experience[e.index]) target.experience[e.index].bullets = e.bullets.slice();
      if (pending.skills.length) {
        let group = target.skills.find(s => /additional|other/i.test(s.label));
        if (!group) { group = { label: 'Additional', details: '' }; target.skills.push(group); }
        const existing = group.details ? group.details.split(/,\s*/) : [];
        group.details = [...new Set([...existing, ...pending.skills])].filter(Boolean).join(', ');
      }
      return target;
    };

    const card = h('div', { class: 'suggest tailor-card' },
      h('div', { class: 'suggest-head' }, '✨ Tailoring suggestions'),
      res.notes?.length ? h('ul', {}, res.notes.map(n => h('li', { text: n }))) : null);

    card.append(h('h4', { text: 'Summary' }), h('p', { class: 'diff-new' }, withPlaceholders(res.summary)));
    for (const e of res.experience) {
      const src = data.experience[e.index];
      card.append(h('h4', { text: [src.position, src.company].filter(Boolean).join(' · ') || `Position ${e.index + 1}` }),
        h('ul', {}, e.bullets.map(b => h('li', { class: 'diff-new' }, withPlaceholders(b)))));
    }
    if (res.skills_to_add.length) {
      card.append(h('h4', { text: 'Skills to add' }), h('div', { class: 'chips', style: 'margin-bottom:10px' }, res.skills_to_add.map(s => h('span', { class: 'chip', text: s }))));
    }
    card.append(h('p', { class: 'hint', text: 'Tip: save a version first so you can always go back to your original.' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: async () => {
          applyTo(data); changed(); toast('Applied tailoring to this resume.', 'success'); card.remove();
        } }, 'Apply to this resume'),
        h('button', { class: 'btn btn-secondary btn-sm', type: 'button', onclick: async () => {
          const title = prompt('Name the tailored copy', `${$('#title').value} (tailored)`);
          if (!title) return;
          try {
            await flushSave();
            const copy = applyTo(structuredClone(data));
            const out = await api('POST', `/api/resumes/${RID}/duplicate`, { title, data: copy });
            window.location = out.url;
          } catch (e) { toast(e.message, e.status === 402 ? 'warning' : 'error'); }
        } }, 'Save as tailored copy'),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => card.remove() }, 'Dismiss')));
    container.append(card);
  }

  // ------------------------------------------------------------ versions drawer
  async function openVersions() {
    const backdrop = h('div', { class: 'drawer-backdrop', onclick: () => close() });
    const body = h('div', { class: 'drawer-body' }, h('p', { class: 'muted' }, h('span', { class: 'spinner' }), ' Loading…'));
    const labelInput = h('input', { type: 'text', placeholder: 'e.g. Before tailoring · Google SWE', maxlength: 200 });
    const drawer = h('aside', { class: 'drawer', role: 'dialog', 'aria-label': 'Versions' },
      h('div', { class: 'drawer-head' }, h('h3', { text: 'Versions' }), h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: () => close() }, '✕')),
      h('div', { style: 'padding: 16px 18px; border-bottom: 1px solid var(--border)' },
        h('label', { text: 'Save a snapshot of the current resume' }),
        h('div', { class: 'row', style: 'flex-wrap:nowrap' }, labelInput,
          h('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
            const label = labelInput.value.trim() || `Snapshot ${new Date().toLocaleString()}`;
            try { await flushSave(); await api('POST', `/api/resumes/${RID}/versions`, { label }); labelInput.value = ''; load(); toast('Version saved.', 'success'); }
            catch (e) { toast(e.message, e.status === 402 ? 'warning' : 'error'); }
          } }, 'Save'))),
      body);
    const close = () => { backdrop.remove(); drawer.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    document.body.append(backdrop, drawer);
    labelInput.focus();

    async function load() {
      try {
        const { versions } = await api('GET', `/api/resumes/${RID}/versions`);
        if (!versions.length) { body.replaceChildren(h('p', { class: 'muted', text: 'No versions yet. Save one before big edits or tailoring, so you can always go back.' })); return; }
        body.replaceChildren(...versions.map(v => h('div', { class: 'version' },
          h('div', { class: 'info' }, h('b', { text: v.label }), h('span', { class: 'tiny muted', text: `${new Date(v.created_at).toLocaleString()} · ${v.template}` })),
          h('a', { class: 'btn btn-ghost btn-sm', href: `/app/resumes/${RID}/versions/${v.id}/pdf`, title: 'Download PDF' }, 'PDF'),
          h('button', { class: 'btn btn-secondary btn-sm', type: 'button', onclick: async () => {
            if (!confirm(`Restore “${v.label}”? Your current content will be replaced. Save a version first if you want to keep it.`)) return;
            await flushSave();
            const res = await api('POST', `/api/resumes/${RID}/versions/${v.id}/restore`);
            data = res.data; $('#quick-template').value = data.design.template;
            renderStep(); refreshPreview(); close(); toast('Version restored.', 'success');
          } }, 'Restore'),
          h('button', { class: 'icon-btn', type: 'button', title: 'Delete version', 'aria-label': 'Delete version', onclick: async () => {
            if (!confirm('Delete this version?')) return;
            await api('DELETE', `/api/resumes/${RID}/versions/${v.id}`); load();
          } }, '🗑'))));
      } catch (e) { body.replaceChildren(h('div', { class: 'alert alert-error', text: e.message })); }
    }
    load();
  }

  // ------------------------------------------------------------ wiring
  async function downloadClick(e) {
    e.preventDefault();
    const href = e.currentTarget.href;
    await flushSave();
    window.location = href;
  }

  $('#title').addEventListener('input', () => changed({ preview: false }));
  $('#btn-versions').addEventListener('click', openVersions);
  $('#btn-download').addEventListener('click', downloadClick);
  $('#quick-template').value = data.design.template;
  $('#quick-template').addEventListener('change', (e) => {
    data.design.template = e.target.value; changed();
    if (STEPS[current].key === 'design') renderStep();
  });
  $('#mobile-switch').addEventListener('click', () => {
    const on = document.body.classList.toggle('show-preview');
    $('#mobile-switch').textContent = on ? '✎ Edit' : '👁 Preview';
    if (on) refreshPreview();
  });

  const initial = STEPS.findIndex(s => `#${s.key}` === location.hash);
  go(initial >= 0 ? initial : 0);
  refreshPreview();
})();
