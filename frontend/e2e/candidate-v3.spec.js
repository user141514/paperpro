import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
const browserErrors=new WeakMap();
test.beforeEach(async({page})=>{
  const errors=[];browserErrors.set(page,errors);page.on('pageerror',error=>errors.push(error.message));
});
test.afterEach(async({page})=>{expect(browserErrors.get(page)||[]).toEqual([]);});

async function reviewedDemo(page) {
  await page.goto('/');
  await page.getByRole('button', { name: '填入虚构演示资料' }).click();
  await expect(page.getByTestId('candidate-parse-text')).toBeDisabled();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await expect(page.getByTestId('candidate-name')).toHaveValue('陈晓明');
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  await page.getByTestId('candidate-target-company').fill('纯合成企业');
  await expect(page.getByTestId('candidate-generate')).toBeDisabled();
  await page.getByTestId('candidate-target-role').fill('后端开发工程师');
  await page.getByTestId('candidate-prepare-requirements').click();
  await expect(page.getByTestId('candidate-requirements')).toBeVisible();
  await page.getByTestId('candidate-requirements-confirmed').check();
  const completed=page.waitForResponse(response=>/\/api\/diagnosis\/tasks\/[^/]+\/run$/.test(response.url())&&response.request().method()==='POST');
  await page.getByTestId('candidate-generate').click();
  await expect(page.getByTestId('dimension-match')).toBeVisible();
  return (await (await completed).json()).current_run;
}

test('V3 adoption needs actual text, completion is independent, reload continues owned task', async ({ page }) => {
  await reviewedDemo(page);
  await page.getByTestId('candidate-next-todo').click();
  const advice = page.locator('[data-testid^="advice-advice-"]').first();
  await advice.getByRole('button', { name: '采纳到待办', exact: true }).click();
  await expect(advice.getByLabel('实际修改内容')).toBeFocused();
  await expect(advice).toContainText('请先填写实际修改内容');
  await expect(page.getByTestId('candidate-download-txt')).toBeDisabled();
  await advice.getByLabel('实际修改内容').fill('仅根据本人真实经历补充对应的岗位表达。');
  await advice.getByRole('button', { name: '采纳到待办', exact: true }).click();
  await expect(advice).toContainText('已采纳 · 待办');
  await expect(page.getByTestId('candidate-completion')).toContainText('已完成 0');
  await advice.getByRole('button', { name: '标记完成', exact: true }).click();
  await expect(advice).toContainText('已完成');
  await expect(page.getByTestId('candidate-completion')).toContainText('已完成 1');
  await page.reload();
  await expect(page.locator('.diag-task-list')).toContainText('后端开发工程师');
  await page.getByRole('button', { name: '继续任务', exact: true }).first().click();
  await expect(page.getByTestId('candidate-completion')).toContainText('已完成 1');
  const saved = page.locator('[data-testid^="advice-advice-"]').first();
  await expect(saved.getByLabel('实际修改内容')).toHaveValue('仅根据本人真实经历补充对应的岗位表达。');
  await saved.getByRole('button', { name: '重新打开', exact: true }).click();
  await expect(saved).toContainText('已采纳 · 待办');
  await saved.screenshot({path:'E:/codex-acceptance/paperpro-v3-20261030/frontend-todo-card.png'});
  const downloaded = page.waitForEvent('download');
  await page.getByTestId('candidate-download-txt').click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toMatch(/后端开发工程师.*v\d+.*\.txt$/);
  const body = (await fs.readFile(await file.path())).toString('utf8');
  expect(body).toContain('仅根据本人真实经历补充对应的岗位表达。');
  expect(body).toContain('待办');
});

test('V3 changing input retains history and saved target after reload', async ({ page }) => {
  await reviewedDemo(page);
  await page.getByTestId('candidate-history').click();
  await expect(page.getByTestId('candidate-history-panel')).toBeVisible();
  await page.getByRole('button', { name: '返回修改目标', exact: true }).click();
  await page.getByTestId('candidate-target-role').fill('数据分析师');
  await expect(page.getByTestId('candidate-save-status')).toContainText('已保存');
  await expect(page.getByTestId('candidate-requirements-confirmed')).toHaveCount(0);
  await page.reload();
  await page.getByRole('button', { name: '继续任务', exact: true }).first().click();
  await expect(page.getByTestId('candidate-target-role')).toHaveValue('数据分析师');
  await page.getByTestId('candidate-history').click();
  await expect(page.getByTestId('candidate-history-panel')).toContainText('诊断');
});

test('V3 demo replacement during delayed parse rejects the earlier source', async ({ page }) => {
  const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto('/');
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-paste').fill('甲合成候选人\n专业技能\nPython, SQL');
  let release,seen;
  const pending=new Promise(resolve=>{seen=resolve;});
  await page.route('**/api/diagnosis/tasks/*/parse',async route=>{
    const response=await route.fetch();
    release=()=>route.fulfill({response});seen();
  },{times:1});
  await page.getByTestId('candidate-parse-text').click();
  await pending;
  await page.getByRole('button',{name:'填入虚构演示资料'}).click();
  await release();
  await expect(page.getByTestId('candidate-paste')).toHaveValue(/陈晓明/);
  await expect(page.getByTestId('candidate-name')).toHaveCount(0);
  await page.getByTestId('candidate-parse-text').click();
  await expect(page.getByTestId('candidate-name')).toHaveValue('陈晓明');
  expect(pageErrors).toEqual([]);
});

test('V3 completed edits reopen as todo and delayed save never erases newer text', async ({ page }) => {
  await reviewedDemo(page);
  await page.getByTestId('candidate-next-todo').click();
  const advice=page.locator('[data-testid^="advice-advice-"]').first();
  const input=advice.getByLabel('实际修改内容');
  await input.fill('已核对本人真实修改。');
  await advice.getByRole('button',{name:'采纳到待办',exact:true}).click();
  await advice.getByRole('button',{name:'标记完成',exact:true}).click();
  await expect(page.getByTestId('candidate-completion')).toContainText('已完成 1');
  await input.fill('第一次修改，准备保存。');
  let release,seen;
  const pending=new Promise(resolve=>{seen=resolve;});
  await page.route('**/api/diagnosis/tasks/*/suggestions/*',async route=>{
    const response=await route.fetch();
    release=()=>route.fulfill({response});seen();
  },{times:1});
  await advice.getByRole('button',{name:'保存修改草稿',exact:true}).click();
  await pending;
  await input.fill('保存期间输入的新内容，必须保留。');
  await release();
  await expect(input).toHaveValue('保存期间输入的新内容，必须保留。');
  await expect(advice).toContainText('已采纳 · 待办');
  await expect(page.getByTestId('candidate-completion')).toContainText('已完成 0');
  await expect(page.getByTestId('candidate-download-txt')).toBeDisabled();
  await advice.getByRole('button',{name:'保存修改草稿',exact:true}).click();
  await expect(page.getByTestId('candidate-download-txt')).toBeEnabled();
});

test('V3 mobile scope, independent ignore/restore, history restoration and deletion', async ({ page }) => {
  const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.setViewportSize({width:390,height:844});
  await reviewedDemo(page);
  await expect(page.getByTestId('candidate-report-scope')).toContainText('完整诊断报告');
  await page.screenshot({path:'E:/codex-acceptance/paperpro-v3-20261030/frontend-mobile-report.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.getByTestId('candidate-next-todo').click();
  const advice=page.locator('[data-testid^="advice-advice-"]').first();
  await advice.getByRole('button',{name:'忽略建议',exact:true}).click();
  await expect(advice).toContainText('已忽略');
  await advice.getByRole('button',{name:'恢复建议',exact:true}).click();
  await expect(advice).toContainText('待处理');
  await page.getByTestId('candidate-history').click();
  await page.getByTestId('candidate-history-panel').getByRole('button',{name:'恢复为新版本',exact:true}).first().click();
  await expect(page.getByText(/历史内容已恢复为新的当前版本/)).toBeVisible();
  await expect(page.getByTestId('candidate-review-confirmed')).not.toBeChecked();
  await expect(page.getByTestId('candidate-next-target')).toBeDisabled();
  await page.getByRole('button',{name:'删除任务及数据',exact:true}).click();
  await expect(page.getByText(/任务、原始资料与历史记录已删除/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button',{name:'继续任务',exact:true})).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('V3 partial module responses show scope and support an independent retry', async ({ page }) => {
  let failPotential=true;
  await page.route('**/api/diagnosis/tasks/**',async route=>{
    if(route.request().url().includes('/retry/potential'))failPotential=false;
    const response=await route.fetch();
    const contentType=response.headers()['content-type']||'';
    if(!contentType.includes('application/json'))return route.fulfill({response});
    const value=await response.json();
    if(failPotential&&value.current_run?.report) {
      value.current_run.report.dimensions.potential={status:'error',conclusion:'合成模块失败，允许独立重试。'};
      value.current_run.module_status.potential='error';
    }
    await route.fulfill({response,json:value});
  });
  await reviewedDemo(page);
  await expect(page.getByTestId('candidate-report-scope')).toContainText('部分诊断报告');
  await expect(page.getByTestId('dimension-potential')).toContainText('合成模块失败');
  await page.getByTestId('dimension-potential').getByRole('button',{name:'重试此模块',exact:true}).click();
  await expect(page.getByTestId('dimension-potential')).toContainText(/已生成|已重算|已复用/);
  await expect(page.getByTestId('candidate-report-scope')).toContainText('完整诊断报告');
});

test('V3 cancelling a delayed completed response keeps completed results reachable and rejects late navigation', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'填入虚构演示资料'}).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  await page.getByTestId('candidate-target-role').fill('后端开发工程师');
  await page.getByTestId('candidate-prepare-requirements').click();
  await page.getByTestId('candidate-requirements-confirmed').check();
  let release,seen;
  const pending=new Promise(resolve=>{seen=resolve;});
  await page.route('**/api/diagnosis/tasks/*/run',async route=>{
    const response=await route.fetch();
    release=()=>route.fulfill({response});seen();
  },{times:1});
  await page.getByTestId('candidate-generate').click();
  await pending;
  await page.getByRole('button',{name:'取消处理',exact:true}).click();
  await release();
  await expect(page.getByText(/已取消未完成的处理/)).toBeVisible();
  await expect(page.getByTestId('dimension-match')).toBeVisible();
  await expect(page.getByTestId('candidate-history')).toBeEnabled();
});

test('V3 save conflicts keep the local unsaved draft and block diagnosis', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '填入虚构演示资料' }).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await expect(page.getByTestId('candidate-name')).toBeVisible();
  await page.route('**/api/diagnosis/tasks/*', route => {
    if (route.request().method() !== 'PATCH') return route.continue();
    return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '版本冲突，请重新载入后合并' }) });
  });
  await page.getByTestId('candidate-name').fill('尚未保存的真实修改');
  await expect(page.getByTestId('candidate-save-status')).toContainText('未保存');
  await expect(page.getByTestId('candidate-name')).toHaveValue('尚未保存的真实修改');
  await expect(page.getByTestId('candidate-next-target')).toBeDisabled();
  await expect(page.getByRole('button', { name: '重试保存', exact: true })).toBeVisible();
});

test('V3 two-tab conflicts show actual differences and require explicit version confirmation', async ({ page, context }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'填入虚构演示资料'}).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await expect(page.getByTestId('candidate-name')).toBeVisible();
  const other=await context.newPage();
  await other.goto('/');
  await other.getByRole('button',{name:'继续任务',exact:true}).first().click();
  await expect(other.getByTestId('candidate-name')).toHaveValue('陈晓明');
  await page.getByTestId('candidate-name').fill('服务器较新内容 A');
  await expect(page.getByTestId('candidate-save-status')).toContainText('已保存');
  await other.getByTestId('candidate-name').fill('需要保留的本页内容 B');
  await expect(other.getByTestId('candidate-save-status')).toContainText('未保存：');
  await other.getByRole('button',{name:'核对服务器版本',exact:true}).click();
  await expect(other.getByText('本页：需要保留的本页内容 B',{exact:true})).toBeVisible();
  await expect(other.getByText('服务器：服务器较新内容 A',{exact:true})).toBeVisible();
  await other.getByRole('button',{name:'确认以本页内容保存为新版本',exact:true}).click();
  await expect(other.getByTestId('candidate-save-status')).toContainText('已保存');
  await expect(other.getByTestId('candidate-name')).toHaveValue('需要保留的本页内容 B');
  await other.reload();
  await other.getByRole('button',{name:'继续任务',exact:true}).first().click();
  await expect(other.getByTestId('candidate-name')).toHaveValue('需要保留的本页内容 B');
  await other.close();
});

test('V3 invalid total weights and all-disabled modules cannot start diagnosis', async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'填入虚构演示资料'}).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  await page.getByTestId('candidate-target-role').fill('后端开发工程师');
  await page.getByTestId('candidate-prepare-requirements').click();
  await page.getByLabel('能力项 1 权重（%）',{exact:true}).fill('0');
  await expect(page.getByTestId('candidate-requirements-confirmed')).toBeDisabled();
  await expect(page.getByTestId('candidate-generate')).toBeDisabled();
  await page.getByRole('button',{name:'按比例归一到 100%',exact:true}).click();
  await page.getByTestId('candidate-requirements-confirmed').check();
  for(const name of ['任职资格匹配度','工作经验研判','学习能力与发展潜力','简历针对性','简历疑点与风险提示']) {
    await page.getByRole('checkbox',{name,exact:true}).uncheck();
  }
  await expect(page.getByTestId('candidate-generate')).toBeDisabled();
  await expect(page.getByText(/请至少开启一个诊断模块/)).toBeVisible();
});

test('V3 critical fields can be confirmed individually, filtered, and only changed paths reopen',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'填入虚构演示资料'}).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  const queue=page.getByTestId('candidate-critical-fields');
  await expect(page.getByTestId('confirm-field-name')).toBeVisible();
  const count=await queue.getByRole('checkbox').count();
  expect(count).toBeGreaterThan(1);
  await page.getByTestId('confirm-field-name').check();
  await expect(page.getByTestId('candidate-save-status')).toContainText('已保存');
  await page.getByRole('checkbox',{name:'只看待核对',exact:true}).check();
  await expect(page.getByTestId('confirm-field-name')).toHaveCount(0);
  await page.getByTestId('candidate-review-confirmed').check();
  await expect(page.getByTestId('candidate-next-target')).toBeEnabled();
  await page.getByTestId('candidate-name').fill('仅更改姓名的合成候选人');
  await expect(page.getByTestId('candidate-save-status')).toContainText('已保存');
  await expect(page.getByTestId('confirm-field-name')).not.toBeChecked();
  await expect(queue.getByRole('checkbox')).toHaveCount(1);
  await expect(page.getByTestId('candidate-next-target')).toBeDisabled();
  await page.getByTestId('confirm-field-name').click();
  await expect(page.getByTestId('candidate-next-target')).toBeEnabled();
});

test('V3 all-failed module contract blocks advice and export while keeping module retry usable',async({page})=>{
  let failed=true;
  await page.route('**/api/diagnosis/tasks/**',async route=>{
    if(route.request().url().includes('/retry/match'))failed=false;
    const response=await route.fetch();
    if(!(response.headers()['content-type']||'').includes('application/json'))return route.fulfill({response});
    const value=await response.json();
    if(failed&&value.current_run?.report){
      value.current_run.status='failed';
      for(const key of Object.keys(value.current_run.report.dimensions)){
        value.current_run.report.dimensions[key]={status:'error',conclusion:'合成模块失败，可重试此模块。'};
        value.current_run.module_status[key]='error';
      }
      value.current_run.report.suggestions=[];
      value.current_run.report.interview_questions=[];
    }
    await route.fulfill({response,json:value});
  });
  await reviewedDemo(page);
  await expect(page.getByTestId('candidate-next-todo')).toBeDisabled();
  await expect(page.getByTestId('candidate-download-report')).toBeDisabled();
  const retry=page.getByTestId('dimension-match').getByRole('button',{name:'重试此模块',exact:true});
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(page.getByTestId('dimension-match')).toContainText(/已生成|已重算|已复用/);
});

test('V3 minimal recompute: summary change keeps experience result and reuses its source',async({page})=>{
  const previous=await reviewedDemo(page);
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  await page.getByRole('button',{name:'返回修改简历',exact:true}).click();
  await page.getByRole('textbox',{name:'个人简介',exact:true}).fill('本人已参与 Python 与 SQL 后端接口开发，按真实职责突出与目标岗位相关的经验。');
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  const plan=page.getByTestId('candidate-recompute-plan');
  await expect(plan).toContainText('个人简介');
  await expect(plan.getByTestId('candidate-recompute-reused')).toContainText('工作经验研判');
  await page.getByTestId('candidate-recompute-view-report').click();
  await expect(page.getByTestId('dimension-experience')).toContainText('可复用');
  await expect(page.getByTestId('candidate-download-report')).toBeDisabled();
  await expect(page.getByTestId('candidate-next-todo')).toBeDisabled();
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  const completed=page.waitForResponse(response=>/\/api\/diagnosis\/tasks\/[^/]+\/run$/.test(response.url())&&response.request().method()==='POST');
  await page.getByTestId('candidate-generate').click();
  await expect(page.getByTestId('dimension-experience')).toContainText('已复用');
  const next=(await (await completed).json()).current_run;
  expect(next.report.meta.recompute.reused).toContain('experience');
  expect(next.report.meta.recompute.recomputed).not.toContain('experience');
  expect(next.report.meta.recompute.source_run_id).toBe(previous.id);
  expect(next.report.dimensions.experience.months_total).toBe(previous.report.dimensions.experience.months_total);
  await fs.writeFile('E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-summary-network.json',JSON.stringify({
    source_run_id:previous.id,current_run_id:next.id,recompute:next.report.meta.recompute,
    experience_provenance:next.report.meta.module_provenance.experience,
    previous_months:previous.report.dimensions.experience.months_total,current_months:next.report.dimensions.experience.months_total,
  },null,2));
  await page.getByTestId('dimension-experience').screenshot({path:'E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-experience-reused.png'});
  await expect(page.getByTestId('candidate-recompute-result')).toContainText('工作经验研判');
  const source=page.waitForResponse(response=>response.url().endsWith('/history')&&response.request().method()==='GET');
  await page.getByTestId('dimension-experience').getByRole('button',{name:'查看结果来源',exact:true}).click();
  const history=await (await source).json();
  expect(history.runs.some(item=>item.id===previous.id)).toBe(true);
  await expect(page.getByTestId('candidate-history-panel')).toContainText('历史诊断只读内容');
  await expect(page.getByText(previous.id,{exact:true})).toHaveCount(0);
});

test('V3 minimal recompute: weights change recalculates match and reuses other four modules',async({page})=>{
  const previous=await reviewedDemo(page);
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  const first=page.getByLabel('能力项 1 权重（%）',{exact:true});
  const second=page.getByLabel('能力项 2 权重（%）',{exact:true});
  const firstWeight=Number(await first.inputValue());
  const secondWeight=Number(await second.inputValue());
  expect(secondWeight).toBeGreaterThan(1);
  await first.fill(String(firstWeight+1));
  await second.fill(String(secondWeight-1));
  await page.getByTestId('candidate-requirements-confirmed').check();
  const plan=page.getByTestId('candidate-recompute-plan');
  await expect(plan.getByTestId('candidate-recompute-recomputed')).toHaveText(/任职资格匹配度/);
  await expect(plan.getByTestId('candidate-recompute-recomputed')).not.toContainText('工作经验研判');
  await expect(plan.getByTestId('candidate-recompute-reused')).toContainText('工作经验研判');
  await plan.screenshot({path:'E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-weight-plan.png'});
  await page.getByTestId('candidate-recompute-view-report').click();
  await expect(page.getByTestId('dimension-match')).toContainText('待重算');
  await expect(page.getByTestId('dimension-experience')).toContainText('可复用');
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  const completed=page.waitForResponse(response=>/\/api\/diagnosis\/tasks\/[^/]+\/run$/.test(response.url())&&response.request().method()==='POST');
  await page.getByTestId('candidate-generate').click();
  const next=(await (await completed).json()).current_run;
  expect(next.report.meta.recompute.recomputed).toEqual(['match']);
  expect(new Set(next.report.meta.recompute.reused)).toEqual(new Set(['experience','potential','motivation','verification']));
  expect(next.report.meta.recompute.source_run_id).toBe(previous.id);
  await fs.writeFile('E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-weights-network.json',JSON.stringify({
    source_run_id:previous.id,current_run_id:next.id,recompute:next.report.meta.recompute,
    module_provenance:next.report.meta.module_provenance,
  },null,2));
  await expect(page.getByTestId('dimension-match')).toContainText('已重算');
  await expect(page.getByTestId('dimension-experience')).toContainText('已复用');
  await page.getByTestId('candidate-recompute-result').screenshot({path:'E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-weight-result.png'});
});

test('V3 minimal recompute: company edit preserves custom requirements and recalculates motivation only',async({page})=>{
  await reviewedDemo(page);
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  const first=page.getByLabel('能力项 1 权重（%）',{exact:true});
  const second=page.getByLabel('能力项 2 权重（%）',{exact:true});
  const firstWeight=Number(await first.inputValue())+1;
  const secondWeight=Number(await second.inputValue())-1;
  const customDescription='本人确认的岗位要求：Python 接口开发与 SQL 数据处理，保留本次自定义评分口径。';
  await first.fill(String(firstWeight));
  await second.fill(String(secondWeight));
  await page.getByLabel('能力项 1 要求描述',{exact:true}).fill(customDescription);
  await page.getByTestId('candidate-requirements-confirmed').check();
  const baselineResponse=page.waitForResponse(response=>/\/api\/diagnosis\/tasks\/[^/]+\/run$/.test(response.url())&&response.request().method()==='POST');
  await page.getByTestId('candidate-generate').click();
  const baseline=await (await baselineResponse).json();
  await expect(page.getByTestId('dimension-match')).toBeVisible();
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  await page.getByTestId('candidate-target-company').fill('另一家纯合成企业');
  await expect(first).toHaveValue(String(firstWeight));
  await expect(second).toHaveValue(String(secondWeight));
  await expect(page.getByLabel('能力项 1 要求描述',{exact:true})).toHaveValue(customDescription);
  await expect(page.getByTestId('candidate-requirements-confirmed')).not.toBeChecked();
  await expect(page.getByTestId('candidate-generate')).toBeDisabled();
  await page.getByTestId('candidate-requirements-confirmed').check();
  const plan=page.getByTestId('candidate-recompute-plan');
  await expect(plan).toContainText('目标 · 公司');
  await expect(plan.getByTestId('candidate-recompute-recomputed')).toHaveText('简历针对性');
  await expect(plan.getByTestId('candidate-recompute-reused')).toContainText('任职资格匹配度');
  await plan.screenshot({path:'E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-company-plan.png'});
  const completed=page.waitForResponse(response=>/\/api\/diagnosis\/tasks\/[^/]+\/run$/.test(response.url())&&response.request().method()==='POST');
  await page.getByTestId('candidate-generate').click();
  const next=await (await completed).json();
  expect(next.state.requirements).toEqual(baseline.state.requirements);
  expect(next.current_run.report.meta.recompute.changed_fields).toEqual(['target.company']);
  expect(next.current_run.report.meta.recompute.recomputed).toEqual(['motivation']);
  expect(new Set(next.current_run.report.meta.recompute.reused)).toEqual(new Set(['match','experience','potential','verification']));
  expect(next.current_run.report.meta.recompute.source_run_id).toBe(baseline.current_run.id);
  await expect(page.getByTestId('dimension-match')).toContainText('已复用');
  await expect(page.getByTestId('dimension-motivation')).toContainText('已重算');
  await fs.writeFile('E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-company-network.json',JSON.stringify({
    source_run_id:baseline.current_run.id,current_run_id:next.current_run.id,
    requirements_before:baseline.state.requirements,requirements_after:next.state.requirements,
    recompute:next.current_run.report.meta.recompute,module_provenance:next.current_run.report.meta.module_provenance,
  },null,2));
  await page.getByTestId('candidate-recompute-result').screenshot({path:'E:/codex-acceptance/paperpro-field-recompute-20261030/frontend-company-result.png'});
  // Changing the JD still requires extracting and confirming the job requirements again.
  await page.getByRole('button',{name:'返回修改目标',exact:true}).click();
  await page.getByRole('textbox',{name:'目标岗位 JD（可选，但推荐）',exact:true}).fill('新的合成岗位职责：负责数据平台开发。');
  await expect(page.getByTestId('candidate-requirements')).toHaveCount(0);
  await expect(page.getByTestId('candidate-generate')).toBeDisabled();
});
