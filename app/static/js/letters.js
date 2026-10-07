/* Cover letters: generator form (list page) and autosaving editor (detail page). */
(() => {
  'use strict';
  const { h, icon, api, toast, field, busy } = window.UI;
  const boot = JSON.parse(document.getElementById('boot').textContent);

  // ------------------------------------------------------------ generator
  const formHost = document.getElementById('gen-form');
  if (formHost) {
    const left = boot.left;
    document.getElementById('gen-left').textContent =
      left === null ? 'Unlimited letters on your plan.' : `${left} cover letter${left === 1 ? '' : 's'} left this month.`;
    if (!boot.resumes.length) {
      formHost.append(h('p', { class: 'muted' }, 'You need a resume first. ', h('a', { href: '/app', text: 'Create or upload one' })));
      return;
    }
    const st = { resume_id: boot.resumes[0].id, job_id: null, company: '', title: '', job_description: '', tone: 'professional', notes: '' };
    const params = new URLSearchParams(location.search);
    const preJob = boot.jobs.find(j => j.id === Number(params.get('job')));

    const resumeSel = h('select', { onchange: (e) => { st.resume_id = Number(e.target.value); } },
      boot.resumes.map(r => h('option', { value: String(r.id), text: r.title })));
    const company = h('input', { type: 'text', placeholder: 'Acme', oninput: (e) => { st.company = e.target.value; } });
    const title = h('input', { type: 'text', placeholder: 'Product Manager', oninput: (e) => { st.title = e.target.value; } });
    const jd = h('textarea', { rows: 6, placeholder: 'Paste the job description (recommended)', oninput: (e) => { st.job_description = e.target.value; } });
    const jobSel = h('select', { onchange: (e) => pickJob(Number(e.target.value) || null) },
      h('option', { value: '', text: 'Not linked to a tracked job' }),
      boot.jobs.map(j => h('option', { value: String(j.id), text: [j.title, j.company].filter(Boolean).join(' at ') || 'Untitled job' })));
    const tone = h('select', { onchange: (e) => { st.tone = e.target.value; } },
      h('option', { value: 'professional', text: 'Professional' }), h('option', { value: 'enthusiastic', text: 'Enthusiastic' }), h('option', { value: 'concise', text: 'Short & direct' }));
    const notes = h('textarea', { rows: 2, placeholder: 'Anything to emphasise? e.g. relocating to Austin, referral from Sam', oninput: (e) => { st.notes = e.target.value; } });

    function pickJob(id) {
      st.job_id = id;
      const j = boot.jobs.find(x => x.id === id);
      if (!j) return;
      jobSel.value = String(id);
      company.value = st.company = j.company; title.value = st.title = j.title;
      jd.value = st.job_description = j.description;
      if (j.resume_id) { resumeSel.value = String(j.resume_id); st.resume_id = j.resume_id; }
    }

    const btn = h('button', { class: 'btn btn-ai btn-block', type: 'button' }, icon('spark'), ' Write cover letter');
    btn.addEventListener('click', () => busy(btn, 'Writing…', async () => {
      try {
        const out = await api('POST', '/api/letters/generate', st);
        window.location = out.url;
      } catch (e) { toast(e.message, e.status === 402 ? 'warning' : 'error'); }
    }));

    formHost.append(
      boot.jobs.length ? field('Tracked job', jobSel) : null,
      field('Resume', resumeSel),
      h('div', { class: 'grid-2' }, field('Company', company), field('Role', title)),
      field('Job description', jd), field('Tone', tone), field('Extra notes (optional)', notes), btn);
    if (preJob) pickJob(preJob.id);
  }

  // ------------------------------------------------------------ editor
  const bodyEl = document.getElementById('body');
  if (bodyEl) {
    const titleEl = document.getElementById('title'), state = document.getElementById('save-state');
    let timer = null, dirty = false, saving = null;
    const warn = () => {
      const n = (bodyEl.value.match(/\[[^\]]{1,40}\]/g) || []).length;
      document.getElementById('placeholder-warn').textContent = n ? `${n} placeholder${n > 1 ? 's' : ''} still to fill in.` : '';
    };
    async function save() {
      if (!dirty) return;
      dirty = false; state.textContent = 'Saving…'; state.className = 'save-state';
      saving = api('PUT', `/api/letters/${boot.id}`, { title: titleEl.value || 'Cover letter', body: bodyEl.value });
      try { await saving; if (!dirty) state.textContent = 'All changes saved'; }
      catch (e) { dirty = true; state.textContent = 'Save failed'; state.className = 'save-state error'; }
      finally { saving = null; }
    }
    const changed = () => { dirty = true; warn(); state.textContent = 'Unsaved changes'; state.className = 'save-state dirty'; clearTimeout(timer); timer = setTimeout(save, 700); };
    bodyEl.addEventListener('input', changed);
    titleEl.addEventListener('input', changed);
    window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
    document.getElementById('download').addEventListener('click', async (e) => {
      e.preventDefault(); clearTimeout(timer);
      if (saving) await saving.catch(() => {});
      await save();
      window.location = e.currentTarget.href;
    });
    document.getElementById('copy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(bodyEl.value); toast('Copied to clipboard.', 'success'); }
      catch { bodyEl.select(); document.execCommand('copy'); }
    });
    warn();
  }

  document.querySelectorAll('time[data-ts]').forEach(t => {
    const d = new Date(t.dataset.ts);
    if (!isNaN(d)) t.textContent = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  });
})();
