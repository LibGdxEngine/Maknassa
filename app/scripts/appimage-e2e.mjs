// Definitive E2E against the SHIPPED AppImage (not the dev bundle): launches it with
// a CDP port, then asserts (1) the embedded frozen backend answers health over the
// token API, (2) the renderer painted the real UI and loaded settings via that API,
// (3) the production CSP is enforced, (4) closing the window leaves no orphan backend.
//
//   node scripts/appimage-e2e.mjs /abs/path/Maknassa.AppImage
import { chromium } from 'playwright'
import { spawn, execSync } from 'child_process'

const appImage = process.argv[2]
if (!appImage) {
  console.error('usage: node appimage-e2e.mjs <Maknassa.AppImage>')
  process.exit(2)
}

const CDP = 9444
const env = { ...process.env, MAKNASSA_DATA_DIR: execSync('mktemp -d').toString().trim() }
const proc = spawn(appImage, [`--remote-debugging-port=${CDP}`], { env, stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const orphans = () => {
  try {
    return execSync('pgrep -fc "backend/maknassa-backen[d]"').toString().trim()
  } catch {
    return '0'
  }
}

let ok = true
const check = (name, cond) => {
  console.log(`${cond ? 'PASS' : 'FAIL'}: ${name}`)
  if (!cond) ok = false
}

try {
  // Wait for the CDP endpoint (proves Electron main came up after the handshake).
  let browser = null
  for (let i = 0; i < 45 && !browser; i++) {
    try {
      browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP}`)
    } catch {
      await sleep(1000)
    }
  }
  check('AppImage launched + CDP reachable', !!browser)
  if (!browser) throw new Error('CDP never came up')

  // The renderer page may not be attached the instant CDP connects; poll for it.
  let page = null
  for (let i = 0; i < 30 && !page; i++) {
    page = browser.contexts().flatMap((c) => c.pages()).find((p) => /index\.html/.test(p.url()))
    if (!page) await sleep(500)
  }
  check('renderer page target present', !!page)
  if (!page) throw new Error('renderer page never attached')
  await page.waitForSelector('text=Connect to Facebook', { timeout: 30_000 })
  await page.waitForSelector('text=Fetch reactors', { timeout: 10_000 })
  const body = await page.locator('body').innerText()
  check('renderer painted the full UI', /Maknassa/.test(body) && /Fetch reactors/.test(body))
  check('settings loaded via the token API (Profile dir + Headless)',
    /Profile dir/.test(body) && /Headless/.test(body))
  check('backend health reached the renderer', /Backend v/i.test(body))

  // CSP enforcement: a cross-origin connect must be refused by policy.
  const csp = await page.evaluate(
    () =>
      new Promise((resolve) => {
        let v = null
        document.addEventListener('securitypolicyviolation', (e) => (v = e.violatedDirective))
        fetch('https://example.com/').then(() => setTimeout(() => resolve(v), 300)).catch(() => setTimeout(() => resolve(v), 300))
      })
  )
  check('production CSP enforced (cross-origin connect blocked)', /connect-src/.test(csp || ''))

  check('embedded backend running before close', orphans() !== '0')
  await browser.close()
  // Close the window the way a user would; the parent-pid watchdog should reap the backend.
  proc.kill('SIGTERM')
  await sleep(7000)
  check('no orphan backend after window close', orphans() === '0')
} catch (err) {
  console.error('ERROR —', err.message)
  ok = false
} finally {
  try { proc.kill('SIGKILL') } catch {}
  try { execSync('pkill -9 -f "backend/maknassa-backen[d]" 2>/dev/null') } catch {}
}

console.log(`APPIMAGE E2E: ${ok ? 'PASS' : 'FAIL'}`)
process.exit(ok ? 0 : 1)
