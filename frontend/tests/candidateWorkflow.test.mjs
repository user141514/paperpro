import test from 'node:test';
import assert from 'node:assert/strict';
import { createDraftSaver, draftDifferences } from '../src/candidateWorkflow.js';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('autosave acknowledges consecutive revisions without losing edits made during a save', async () => {
  const first = deferred();
  const calls = [], accepted = [];
  const saver = createDraftSaver({
    save: async (id, revision, state) => {
      calls.push({ id, revision, state });
      if (calls.length === 1) await first.promise;
      return { id, revision: revision + 1, state };
    },
    onSaved: value => accepted.push(value),
  });
  saver.bind({ id: 'owned-a', revision: 1 });
  saver.schedule({ resume: { name: 'first edit' } });
  const running = saver.flush();
  saver.schedule({ resume: { name: 'newer edit' } });
  first.resolve();
  await running;
  assert.deepEqual(calls.map(value => value.revision), [1, 2]);
  assert.equal(accepted.at(-1).state.resume.name, 'newer edit');
  assert.equal(saver.dirty, false);
});

test('a failed save preserves the latest draft and original revision for an explicit retry', async () => {
  let fail = true;
  const saver = createDraftSaver({ save: async (id, revision, state) => {
    if (fail) throw new Error('版本冲突');
    return { id, revision: revision + 1, state };
  } });
  saver.bind({ id: 'owned-a', revision: 4 });
  saver.schedule({ target: { role: 'my unsaved role' } });
  await assert.rejects(saver.flush(), /版本冲突/);
  assert.equal(saver.dirty, true);
  assert.equal(saver.task.revision, 4);
  fail = false;
  await saver.flush();
  assert.equal(saver.task.state.target.role, 'my unsaved role');
  assert.equal(saver.task.revision, 5);
});

test('switching to a different task cannot accept an older save response', async () => {
  const blocked = deferred();
  const accepted = [];
  const saver = createDraftSaver({
    save: async () => blocked.promise,
    onSaved: task => accepted.push(task.id),
  });
  saver.bind({ id: 'owned-a', revision: 1 });
  saver.schedule({ resume: { name: 'a' } });
  const running = saver.flush();
  saver.bind({ id: 'owned-b', revision: 7 });
  blocked.resolve({ id: 'owned-a', revision: 2, state: {} });
  await running;
  assert.equal(saver.task.id, 'owned-b');
  assert.deepEqual(accepted, []);
});

test('conflict review exposes the actual field differences instead of silently accepting last write', () => {
  const differences = draftDifferences(
    { resume: { name: 'local', skills: ['Python'] }, target: { role: '后端' }, step: 2 },
    { resume: { name: 'server', skills: ['Python', 'SQL'] }, target: { role: '后端' }, step: 1 },
  );
  assert.deepEqual(differences.map(item => item.path), ['resume.name', 'resume.skills']);
  assert.equal(differences[0].local, 'local');
  assert.equal(differences[0].server, 'server');
});

test('a cancellation response may advance only an unchanged accepted input revision, preserving pending edits', async () => {
  const calls=[];
  const state={target:{role:'old'},step:2};
  const saver=createDraftSaver({save:async(id,revision,value)=>{
    calls.push(revision);return{id,revision:revision+1,state:value};
  }});
  saver.bind({id:'a',revision:4,state});
  saver.schedule({target:{role:'new'},step:2});
  assert.equal(saver.acceptUnchangedRevision({id:'a',revision:5,state:{...state,step:3}}),true);
  await saver.flush();
  assert.deepEqual(calls,[5]);
  assert.equal(saver.task.state.target.role,'new');
  assert.equal(saver.acceptUnchangedRevision({id:'a',revision:9,state:{target:{role:'another tab'},step:2}}),false);
  assert.equal(saver.task.revision,6);
});

test('an already-sent stale save retries only after a proven unchanged server revision was accepted',async()=>{
  const first=deferred();const revisions=[];
  const state={target:{role:'old'}};
  const saver=createDraftSaver({save:async(id,revision,value)=>{
    revisions.push(revision);if(revisions.length===1)await first.promise;
    return{id,revision:revision+1,state:value};
  }});
  saver.bind({id:'a',revision:4,state});saver.schedule({target:{role:'new'}});
  const running=saver.flush();
  assert.equal(saver.acceptUnchangedRevision({id:'a',revision:5,state}),true);
  const error=new Error('revision conflict');error.status=409;first.reject(error);
  await running;
  assert.deepEqual(revisions,[4,5]);
  assert.equal(saver.task.state.target.role,'new');
});
