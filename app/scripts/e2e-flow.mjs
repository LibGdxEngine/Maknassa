// Full-flow E2E against the BUILT Electron app + the canned fake backend:
// connect -> fetch -> grid renders -> select all -> confirm -> block with live
// progress (incl. one canned failure) -> results summary -> Unblock available.
//
//   node scripts/e2e-flow.mjs
//
// Screenshots land in <repo>/.omc/artifacts/. Exits non-zero on any failed step.
import { _electron as electron } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const appDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repoDir = path.dirname(appDir)
const art = (name) => path.join(repoDir, '.omc', 'artifacts', name)

const env = {
  ...process.env,
  MAKNASSA_BACKEND_CMD: `node ${path.join(appDir, 'scripts', 'fake-backend.mjs')}`,
}

const app = await electron.launch({ args: [path.join(appDir, 'out', 'main', 'index.js')], env })
try {
  const win = await app.firstWindow()
  const step = async (name, fn) => {
    await fn()
    console.log(`STEP OK: ${name}`)
  }

  await step('connect gate renders', () =>
    win.waitForSelector('text=Connect to Facebook', { timeout: 30_000 }))

  await step('login flow connects', async () => {
    await win.click('text=Connect to Facebook')
    await win.waitForSelector('text=100012345', { timeout: 15_000 })
  })

  await step('fetch returns the canned grid', async () => {
    await win.fill('input[placeholder*="facebook.com"]', 'https://www.facebook.com/x/posts/1')
    await win.click('button:has-text("Fetch reactors")')
    await win.waitForSelector('text=Amira Haddad', { timeout: 15_000 })
    await win.waitForSelector('text=Walid Hamdi', { timeout: 5_000 })
  })

  await step('summary meter shows captured vs expected', () =>
    win.waitForSelector('text=/12.*of.*14/', { timeout: 5_000 }))

  await win.screenshot({ path: art('electron-ui-grid.png') })
  console.log('SCREENSHOT:', art('electron-ui-grid.png'))

  await step('select all -> 12 selected', async () => {
    await win.click('button:has-text("Select all")')
    await win.waitForSelector('text=/12\\s*selected/', { timeout: 5_000 })
  })

  await step('block flow: confirm -> live progress -> summary', async () => {
    await win.click('button:has-text("Block selected (12)")')
    await win.click('button:has-text("Confirm block (12)")')
    await win.waitForSelector('text=/11 blocked/', { timeout: 30_000 })
    await win.waitForSelector('text=/1 failed/', { timeout: 5_000 })
  })

  await step('canned failure row + Unblock action present', async () => {
    await win.waitForSelector('text=confirm dialog never appeared', { timeout: 5_000 })
    await win.waitForSelector('button:has-text("Unblock")', { timeout: 5_000 })
  })

  await win.screenshot({ path: art('electron-ui-block.png'), fullPage: true })
  console.log('SCREENSHOT:', art('electron-ui-block.png'))

  await step('unblock one profile round-trips', async () => {
    await win.locator('button:has-text("Unblock")').first().click()
    await win.waitForSelector('text=/unblocked/i', { timeout: 15_000 })
  })

  console.log('FLOW RESULT: PASS')
} catch (err) {
  console.error('FLOW RESULT: FAIL —', err.message)
  try {
    const win = await app.firstWindow()
    await win.screenshot({ path: art('electron-ui-flow-failure.png') })
    console.error('failure screenshot:', art('electron-ui-flow-failure.png'))
  } catch {}
  process.exitCode = 1
} finally {
  await app.close()
}
