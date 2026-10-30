import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('two opposing current resume statements are visible, reviewable and exported together', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '填入虚构演示资料' }).click();
  await page.getByTestId('candidate-privacy-consent').check();
  await page.getByTestId('candidate-parse-text').click();
  await page.getByRole('textbox',{name:'个人简介',exact:true}).fill('我熟悉 Python，可进行 API 开发。');
  await page.getByLabel('技能（每行一项）').fill('Python：不会\nSQL');
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  await page.getByTestId('candidate-target-role').fill('后端开发工程师');
  await page.getByTestId('candidate-prepare-requirements').click();
  await page.getByTestId('candidate-requirements-confirmed').check();
  await page.getByTestId('candidate-generate').click();

  const conflicting = page.getByTestId('dimension-verification')
    .locator('.diag-issue')
    .filter({ hasText: '简历描述相互矛盾' });
  await expect(conflicting).toHaveCount(1);
  await expect(conflicting).toContainText('我熟悉 Python');
  await expect(conflicting.getByTestId('verification-opposing-claim')).toContainText('skills.0');
  await expect(conflicting.getByTestId('verification-opposing-claim')).toContainText('Python：不会');

  await page.getByTestId('candidate-next-todo').click();
  const advice = page.locator('[data-testid^="advice-advice-claim-conflict-"]');
  await expect(advice).toHaveCount(1);
  await expect(advice).toContainText('核对两处矛盾描述');
  await expect(advice.getByTestId('advice-opposing-claim')).toContainText('Python：不会');
  await advice.getByLabel('实际修改内容').fill('依据本人真实掌握情况核实两处表述，并统一为准确的技能描述。');
  await advice.getByRole('button',{name:'采纳到待办',exact:true}).click();

  const downloaded = page.waitForEvent('download');
  await page.getByTestId('candidate-download-txt').click();
  const item = await downloaded;
  const output = (await fs.readFile(await item.path())).toString('utf8');
  expect(output).toContain('原文：我熟悉 Python');
  expect(output).toContain('对照位置：skills.0');
  expect(output).toContain('对照原文：Python：不会');

  await page.getByRole('button', { name: '返回诊断报告' }).click();
  await page.getByRole('button', { name: '返回修改目标' }).click();
  await page.getByRole('button', { name: '返回修改简历' }).click();
  await page.getByLabel('技能（每行一项）').fill('Python\nSQL');
  await page.getByTestId('candidate-review-confirmed').check();
  await page.getByTestId('candidate-next-target').click();
  await page.getByTestId('candidate-prepare-requirements').click();
  await page.getByTestId('candidate-requirements-confirmed').check();
  await page.getByTestId('candidate-generate').click();
  await expect(page.getByTestId('dimension-verification')
    .locator('.diag-issue')
    .filter({ hasText: '简历描述相互矛盾' })).toHaveCount(0);
});
