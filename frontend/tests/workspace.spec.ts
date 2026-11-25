import { test, expect } from '@playwright/test'

test('organizer creates an event and reopens its saved plan', async ({page,request})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.goto('/#events')
  await page.getByRole('button',{name:'Create event',exact:true}).first().click()
  const form=page.getByRole('dialog')
  await form.getByLabel('Event name',{exact:false}).fill('Prototype Night')
  await form.getByLabel('College or organization',{exact:false}).fill('RIT')
  await form.getByLabel('Venue',{exact:false}).fill('Studio 2')
  await form.getByRole('button',{name:'Continue'}).click()
  await form.getByLabel('Initial club budget',{exact:false}).fill('10000')
  await form.getByRole('button',{name:'Continue'}).click()
  await form.getByLabel('Event goals').fill('Introduce student designers to interactive prototyping.')
  await form.getByRole('button',{name:'Launch AI Planning'}).click()
  await expect(form).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Switch event'})).toContainText('Prototype Night')
  await page.reload()
  await expect(page.getByRole('button',{name:'Switch event'})).toContainText('Prototype Night')
  const events=await (await request.get('/api/events')).json()
  const created=events.find((e:{name:string})=>e.name==='Prototype Night')
  const data=await (await request.get('/api/events/'+created.id)).json()
  expect(data.tasks.length).toBeGreaterThan(0)
  expect(data.runs.length).toBeGreaterThan(0)
  expect(errors).toEqual([])
})

test('every operational view renders with the demo data', async ({page})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  for(const view of ['dashboard','sponsors','finance','agents','tasks','operations','marketing','risks','approvals','reports','copilot','workspace']){
    await page.goto('/#'+view)
    await expect(page.getByRole('main').locator('h1').first()).toBeVisible()
  }
  expect(errors).toEqual([])
})

test('mobile navigation and keyboard search', async ({page})=>{
  await page.setViewportSize({width:390,height:844})
  await page.goto('/')
  await page.getByRole('button',{name:'Open navigation'}).click()
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Finance'}).click()
  await expect(page.getByRole('main').locator('h1')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true)
  await page.setViewportSize({width:1280,height:850})
  await page.getByRole('button',{name:'Search workspace'}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('withdrawal opens a funding recovery plan and approval changes persisted allocations', async ({page,request})=>{
  await page.goto('/#risks')
  await page.getByRole('button',{name:'Demo scenarios'}).click()
  await page.locator('article').filter({has:page.getByRole('heading',{name:'Sponsor withdrawal'})}).getByRole('button',{name:'Run scenario'}).click()
  await page.getByRole('dialog').getByRole('button',{name:'Run scenario'}).click()
  await expect(page.getByRole('heading',{name:'Recover the funding shortfall'})).toBeVisible()
  const events=await (await request.get('/api/events')).json()
  const snapshot=async ()=>(await request.get('/api/events/'+events[0].id)).json()
  const withdrawn=await snapshot()
  expect(withdrawn.metrics.shortfall).toBe(1500000)
  await page.getByRole('button',{name:'Approve plan',exact:true}).click()
  await page.getByRole('dialog').getByRole('button',{name:'Approve and apply',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Recover the funding shortfall'})).toBeVisible()
  await expect.poll(async ()=>(await snapshot()).metrics.planned).toBeLessThan(6000000)
  expect((await snapshot()).metrics.projected_funding).toBe(4500000)
})
