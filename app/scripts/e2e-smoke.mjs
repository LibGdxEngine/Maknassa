// E2E smoke: launch the BUILT Electron app via Playwright's Electron driver,
// wait for the renderer to confirm the backend health round-trip, screenshot it.
//
//   node scripts/e2e-smoke.mjs [screenshot-path]
//
// MAKNASSA_BACKEND_CMD selects the backend (defaults to the repo venv backend);
// MAKNASSA_DATA_DIR should point at a scratch dir so the smoke never touches
// real user data. Exits 0 only when the renderer shows "Backend: ok".
import { _electron as electron } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const appDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repoDir = path.dirname(appDir)
const shot = process.argv[2] ?? path.join(repoDir, '.omc', 'artifacts', 'electron-ui.png')

const env = {
  ...process.env,
  MAKNASSA_BACKEND_CMD:
    process.env.MAKNASSA_BACKEND_CMD ??
    `${path.join(repoDir, '.venv', 'bin', 'python')} -m reactions.backend`,
}

const app = await electron.launch({ args: [path.join(appDir, 'out', 'main', 'index.js')], env })
try {
  const window = await app.firstWindow()
  await window.waitForSelector('text=Backend: ok', { timeout: 30_000 })
  const text = await window.locator('body').innerText()
  console.log('RENDERER OK:', text.split('\n').find((l) => l.includes('Backend:')))
  await window.screenshot({ path: shot })
  console.log('SCREENSHOT:', shot)
  console.log('SMOKE RESULT: PASS')
} catch (err) {
  console.error('SMOKE RESULT: FAIL —', err.message)
  process.exitCode = 1
} finally {
  await app.close()
}
