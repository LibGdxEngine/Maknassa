// Verify the production CSP is actually enforced in the BUILT app: a connect to a
// disallowed origin must be refused by policy (not merely fail on the network).
import { _electron as electron } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const appDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repoDir = path.dirname(appDir)
const env = {
  ...process.env,
  MAKNASSA_BACKEND_CMD: `node ${path.join(appDir, 'scripts', 'fake-backend.mjs')}`
}

const app = await electron.launch({ args: [path.join(appDir, 'out', 'main', 'index.js')], env })
try {
  const win = await app.firstWindow()
  await win.waitForSelector('text=Connect to Facebook', { timeout: 30_000 })

  // A disallowed cross-origin connect should be refused by CSP (connect-src only
  // permits http://127.0.0.1:*). We distinguish "blocked by policy" from a plain
  // network failure by listening for the CSP violation event.
  const result = await win.evaluate(
    () =>
      new Promise((resolve) => {
        let violation = null
        document.addEventListener('securitypolicyviolation', (e) => {
          violation = { blockedURI: e.blockedURI, directive: e.violatedDirective }
        })
        fetch('https://example.com/')
          .then(() => setTimeout(() => resolve({ fetched: true, violation }), 300))
          .catch(() => setTimeout(() => resolve({ fetched: false, violation }), 300))
      })
  )
  const enforced = result.violation && /connect-src/.test(result.violation.directive)
  console.log('CSP probe:', JSON.stringify(result))
  console.log('CSP ENFORCED:', enforced ? 'YES' : 'NO')
  process.exitCode = enforced ? 0 : 1
} catch (err) {
  console.error('CSP probe FAIL —', err.message)
  process.exitCode = 1
} finally {
  await app.close()
}
