import { useEffect, useRef, useState } from 'react';

export const EMPTY_DRAFT = {
  resume: null, target: { role: '', company: '', job_description: '' },
  requirements: [], enabled_sections: ['match', 'experience', 'potential', 'motivation', 'verification'],
  as_of: new Date().toISOString().slice(0, 10), review_confirmed: false, confirmed_fields: [],
  requirements_confirmed: false, step: 1,
};

export function normalizeDraft(state = {}) {
  return { ...EMPTY_DRAFT, ...state, target: { ...EMPTY_DRAFT.target, ...state.target } };
}

export function draftDifferences(local, server, prefix = '') {
  const changes = [];
  for (const key of new Set([...Object.keys(local || {}), ...Object.keys(server || {})])) {
    if (!prefix && key === 'step') continue;
    const left = local?.[key], right = server?.[key];
    const path = prefix ? prefix + '.' + key : key;
    if (JSON.stringify(left) === JSON.stringify(right)) continue;
    if (left && right && typeof left === 'object' && typeof right === 'object' && !Array.isArray(left) && !Array.isArray(right)) {
      changes.push(...draftDifferences(left, right, path));
    } else changes.push({ path, local: left, server: right });
  }
  return changes;
}

export async function workflowRequest(path, { method = 'GET', json, body, signal } = {}) {
  const response = await fetch(path, {
    method, credentials: 'same-origin', signal,
    headers: json === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: json === undefined ? body : JSON.stringify(json),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof value.detail === 'string' ? value.detail : '请求未完成，请检查输入后重试。');
    error.status = response.status;
    throw error;
  }
  return value;
}

// This queue buffers unsaved edits. Revisions and accepted state always come
// from the task API; a save never guesses the next revision or overwrites a
// newer browser draft with an older acknowledgment.
export function createDraftSaver({ save, onSaved = () => {}, onStatus = () => {} }) {
  let task = null, pending = null, active = null, generation = 0;
  function bind(value) {
    generation += 1;
    task = value;
    pending = null;
    active = null;
    onStatus('saved');
  }
  function schedule(state) {
    pending = structuredClone(state);
    onStatus('dirty');
  }
  function acceptUnchangedRevision(value) {
    if (!task?.state || value?.id !== task.id || value.revision <= task.revision
      || draftDifferences(task.state, value.state).length) return false;
    task = value;
    onSaved(value, { pending: !!pending });
    onStatus(pending ? 'dirty' : 'saved');
    return true;
  }
  function flush() {
    if (active) return active;
    if (!task || !pending) return Promise.resolve(task);
    const identity = generation;
    const running = (async () => {
      try {
        while (pending && identity === generation) {
          const sent = pending;
          const revision = task.revision;
          onStatus('saving');
          let result;
          try { result = await save(task.id, revision, sent); }
          catch (error) {
            // Only a separately verified unchanged-input acknowledgment can
            // advance this revision. A genuine concurrent edit still fails.
            if (identity === generation && error.status === 409 && task.revision > revision) continue;
            throw error;
          }
          if (identity !== generation) return task;
          task = result;
          if (pending === sent) pending = null;
          onSaved(result, { pending: !!pending });
        }
        if (identity === generation) onStatus('saved');
        return task;
      } catch (error) {
        if (identity === generation) onStatus('error', error);
        throw error;
      } finally {
        if (active === running) active = null;
      }
    })();
    active = running;
    return running;
  }
  return {
    bind, schedule, flush, acceptUnchangedRevision,
    get task() { return task; },
    get dirty() { return !!pending; },
  };
}

export function useCandidateWorkflow() {
  const [task, setTask] = useState(null);
  const [draft, setDraft] = useState(() => normalizeDraft());
  const [saveStatus, setSaveStatus] = useState('saved');
  const [saveError, setSaveError] = useState('');
  const draftRef = useRef(draft);
  const taskRef = useRef(task);
  const saver = useRef(null);
  if (!saver.current) saver.current = createDraftSaver({
    save: (id, revision, state) => workflowRequest('/api/diagnosis/tasks/' + encodeURIComponent(id), {
      method: 'PATCH', json: { expected_revision: revision, state },
    }),
    onSaved: (value, { pending }) => {
      taskRef.current = value;
      setTask(value);
      if (!pending) {
        draftRef.current = normalizeDraft(value.state);
        setDraft(draftRef.current);
      }
    },
    onStatus: (status, error) => { setSaveStatus(status); setSaveError(error?.message || ''); },
  });

  useEffect(() => {
    if (!task || saveStatus !== 'dirty') return undefined;
    const timer = setTimeout(() => saver.current.flush().catch(() => {}), 550);
    return () => clearTimeout(timer);
  }, [task, draft, saveStatus]);

  function bindTask(value) {
    taskRef.current = value;
    setTask(value);
    draftRef.current = normalizeDraft(value?.state);
    setDraft(draftRef.current);
    saver.current.bind(value);
  }
  function updateDraft(update) {
    const value = typeof update === 'function' ? update(draftRef.current) : update;
    draftRef.current = normalizeDraft(value);
    setDraft(draftRef.current);
    if (taskRef.current) saver.current.schedule(draftRef.current);
  }
  // During an operation, server progress is a read-only projection. It must
  // not replace unsaved edits or the queue's accepted revision.
  function observeTask(value) {
    if (!value || value.id !== taskRef.current?.id || value.revision < taskRef.current.revision) return;
    setTask(previous => ({ ...previous, current_run: value.current_run,
      status: value.status, active_operation: value.active_operation }));
  }
  async function flush() {
    await saver.current.flush();
    return saver.current.task;
  }
  return { task, draft, taskRef, draftRef, saveStatus, saveError, bindTask, updateDraft, observeTask, flush,
    acceptUnchangedRevision: value => saver.current.acceptUnchangedRevision(value) };
}

export async function downloadTaskExport(taskId, runId, kind, format) {
  const query = new URLSearchParams({ kind, format, run_id: runId });
  const response = await fetch('/api/diagnosis/tasks/' + encodeURIComponent(taskId) + '/export?' + query, {
    credentials: 'same-origin',
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw new Error(typeof value.detail === 'string' ? value.detail : '导出未成功，请重试。');
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  let name = 'paperpro_' + kind + '.' + format;
  try { name = utf8 ? decodeURIComponent(utf8[1]) : plain?.[1] || name; } catch { /* use safe fallback */ }
  name = name.replace(/[\\/]/g, '_');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
