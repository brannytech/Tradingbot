import {test,expect} from '@playwright/test';
test('owner dashboard, evidence, risk and backtest controls',async({page})=>{
  let errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await page.getByLabel('Owner password',{exact:true}).fill('E2E-test-only-8767');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#login')).toBeHidden();
  await expect(page.locator('#notice')).toContainText('SYNTHETIC EXAMPLE');
  await expect(page.locator('#env')).toContainText('LIVE LOCKED');
  await page.getByText('Advanced tools',{exact:true}).click();
  const labels={'Strategy Intelligence':'Signals','Active positions':'Positions','Risk management':'Risk'};
  for(let view of ['Connect Bybit','Market scanner','Strategy Intelligence','Agent activity','Consensus matrix','Active positions','Order history','Trade history','Performance analytics','Risk management','System alerts','Settings','Implementation and Readiness']){
    await page.getByRole('button',{name:labels[view]||view,exact:true}).click();
    await expect(page.locator('#title')).toHaveText(labels[view]||view);
    await expect(page.locator('#content')).not.toBeEmpty();
  }
  await page.getByRole('button',{name:'Inspect Gate 0 Repository Discovery',exact:true}).click();
  await expect(page.locator('#detail')).toBeVisible();
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Emergency stop',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('EMERGENCY STOP ACTIVE');
  await page.getByRole('button',{name:'Resume research entries',exact:true}).click();
  await expect(page.getByRole('button',{name:'Emergency stop',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Risk',exact:true}).click();
  await page.getByLabel('risk fraction',{exact:true}).fill('0.004');
  await page.getByRole('button',{name:'Save research risk limits',exact:true}).click();
  await expect(page.getByLabel('risk fraction',{exact:true})).toHaveValue('0.004');
  await page.getByRole('button',{name:'Backtesting',exact:true}).click();
  await page.getByRole('combobox',{name:'Backtest strategy',exact:true}).selectOption('momentum_trend');
  await page.getByRole('button',{name:'Run backtest & walk-forward',exact:true}).click();
  await expect(page.locator('#content')).toContainText('Live eligibility: false',{timeout:30000});
  const widths=await page.evaluate(()=>({w:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
  expect(widths.scroll).toBeLessThanOrEqual(widths.w+1);
  expect(errors).toEqual([]);
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('#login')).toBeVisible();
});
