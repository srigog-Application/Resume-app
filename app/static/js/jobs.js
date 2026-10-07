/* Job tracker board: columns by status, drag & drop, add/edit modal. */
(() => {
  'use strict';
  const { h, icon, api, toast, modal, field, safeUrl } = window.UI;
  const boot = JSON.parse(document.getElementById('boot').textContent);
  const STATUS_LIST = boot.statuses; // [[key, label], ...] in board order
  const STATUSES = Object.fromEntries(STATUS_LIST);
  let jobs = boot.jobs;

  function render() {
    const board = document.getElementById('board');
    board.replaceChildren();
    for (const [key, label] of STATUS_LIST) {
      const list = jobs.filter(j => j.status === key);
      const col = h('section', { class: 'column', 'data-status': key, 'aria-label': label },
        h('div', { class: 'column-head' }, h('span', {}, h('span', { class: `status-dot dot-${key}` }), label), h('span', { class: 'count', text: String(list.length) })),
        list.map(card));
      col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('over'); });
      col.addEventListener('dragleave', () => col.classList.remove('over'));
      col.addEventListener('drop', async (e) => {
        e.preventDefault(); col.classList.remove('over');
        const id = Number(e.dataTransfer.getData('text/plain'));
        await move(id, key);
      });
      board.append(col);
    }
    renderStats();
  }

  function card(job) {
    const el = h('article', { class: 'card job-card', draggable: 'true', tabindex: '0', 'aria-label': `${job.title} at ${job.company}` },
      h('b', { text: job.title || 'Untitled role' }),
      h('div', { class: 'company', text: job.company || '' }),
      h('div', { class: 'meta' },
        job.location ? h('span', { class: 'chip', text: job.location }) : null,
        job.salary ? h('span', { class: 'chip', text: job.salary }) : null,
        job.resume_id ? h('span', { class: 'chip ok', text: 'Resume linked' }) : null,
        boot.letters.some(l => l.job_id === job.id) ? h('span', { class: 'chip ok', text: 'Cover letter' }) : null));
    el.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', String(job.id)); el.classList.add('dragging'); });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
    el.addEventListener('click', () => openJob(job));
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openJob(job); });
    return el;
  }

  function renderStats() {
    const applied = jobs.filter(j => j.status !== 'saved').length;
    const interviews = jobs.filter(j => ['interviewing', 'offer'].includes(j.status)).length;
    const rate = applied ? Math.round(100 * interviews / applied) : 0;
    const stat = (n, label) => h('div', { class: 'card stat' }, h('b', { text: String(n) }), h('span', { class: 'small muted', text: label }));
    document.getElementById('stats').replaceChildren(
      stat(jobs.length, 'Tracked'), stat(applied, 'Applied'), stat(interviews, 'Interviews'),
      stat(`${rate}%`, 'Interview rate'), stat(jobs.filter(j => j.status === 'offer').length, 'Offers'));
  }

  async function move(id, status) {
    const job = jobs.find(j => j.id === id);
    if (!job || job.status === status) return;
    const prev = job.status;
    job.status = status; render();
    try { Object.assign(job, await api('PATCH', `/api/jobs/${id}/status`, { status })); render(); }
    catch (e) { job.status = prev; render(); toast(e.message, 'error'); }
  }

  function openJob(job) {
    const isNew = !job;
    const j = job ? { ...job } : { company: '', title: '', url: '', location: '', salary: '', status: 'saved', description: '', notes: '', resume_id: null };
    const input = (key, attrs = {}) => h('input', { type: 'text', value: j[key] || '', oninput: (e) => { j[key] = e.target.value; }, ...attrs });
    const status = h('select', { onchange: (e) => { j.status = e.target.value; } },
      STATUS_LIST.map(([k, v]) => h('option', { value: k, text: v })));
    status.value = j.status;
    const resumeSel = h('select', { onchange: (e) => { j.resume_id = e.target.value ? Number(e.target.value) : null; } },
      h('option', { value: '', text: 'None' }), boot.resumes.map(r => h('option', { value: String(r.id), text: r.title })));
    resumeSel.value = j.resume_id ? String(j.resume_id) : '';
    const desc = h('textarea', { rows: 7, placeholder: 'Paste the job description. It powers tailoring, match scores and cover letters.', value: j.description, oninput: (e) => { j.description = e.target.value; } });
    const notes = h('textarea', { rows: 3, placeholder: 'Recruiter name, interview dates, follow-ups…', value: j.notes, oninput: (e) => { j.notes = e.target.value; } });

    const link = safeUrl(j.url);
    const body = h('div', {},
      h('div', { class: 'grid-2' }, field('Job title', input('title', { placeholder: 'Product Designer', autofocus: true })), field('Company', input('company', { placeholder: 'Acme' }))),
      h('div', { class: 'grid-2' }, field('Status', status), field('Location', input('location', { placeholder: 'Remote' }))),
      h('div', { class: 'grid-2' }, field('Posting URL', input('url', { placeholder: 'https://…' })), field('Salary', input('salary', { placeholder: '$120k–140k' }))),
      field('Resume used', resumeSel),
      field('Job description', desc),
      field('Notes', notes),
      !isNew ? h('div', { class: 'row' },
        link ? h('a', { class: 'btn btn-ghost btn-sm', href: link, target: '_blank', rel: 'noopener noreferrer' }, icon('external'), ' Open posting') : null,
        h('button', { class: 'btn btn-ai btn-sm', type: 'button', onclick: () => tailorFor(j) }, icon('target'), ' Tailor a resume to this job'),
        h('a', { class: 'btn btn-secondary btn-sm', href: `/app/letters?job=${j.id}` }, icon('mail'), ' Write the cover letter')) : null);

    modal(isNew ? 'Add a job' : (j.title || 'Edit job'), body, (close) => [
      h('button', { class: 'btn btn-primary', type: 'button', onclick: async (e) => {
        try {
          const saved = await api(isNew ? 'POST' : 'PUT', isNew ? '/api/jobs' : `/api/jobs/${j.id}`, j);
          if (isNew) jobs.unshift(saved); else Object.assign(jobs.find(x => x.id === saved.id), saved);
          render(); close();
        } catch (err) { toast(err.message, 'error'); }
      } }, isNew ? 'Add job' : 'Save'),
      h('button', { class: 'btn btn-ghost', type: 'button', onclick: close }, 'Cancel'),
      h('div', { class: 'spacer' }),
      !isNew ? h('button', { class: 'btn btn-danger', type: 'button', onclick: async () => {
        if (!confirm('Delete this job?')) return;
        try { await api('DELETE', `/api/jobs/${j.id}`); jobs = jobs.filter(x => x.id !== j.id); render(); close(); }
        catch (err) { toast(err.message, 'error'); }
      } }, 'Delete') : null,
    ]);
  }

  function tailorFor(job) {
    if (!job.description || job.description.trim().length < 80) { toast('Paste the job description first, then save.', 'info'); return; }
    const rid = job.resume_id || (boot.resumes[0] && boot.resumes[0].id);
    if (!rid) { toast('Create a resume first.', 'info'); return; }
    window.location = `/app/resumes/${rid}?job=${job.id}#tailor`;
  }

  document.getElementById('add-job').addEventListener('click', () => openJob(null));
  render();
  const params = new URLSearchParams(location.search);
  if (params.get('new')) openJob(null);
  if (params.get('open')) { const j = jobs.find(x => x.id === Number(params.get('open'))); if (j) openJob(j); }
})();
