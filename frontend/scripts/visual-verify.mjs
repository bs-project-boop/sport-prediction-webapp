import { chromium } from 'playwright'
import fs from 'node:fs'

const executablePath = `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell`
const outputDir = `${process.env.HOME}/sport-prediction-dev/docs/screenshots`
fs.mkdirSync(outputDir, { recursive: true })

for (const [name, width, height] of [
  ['mobile-375', 375, 812],
  ['desktop-1440', 1440, 900],
]) {
  const browser = await chromium.launch({ executablePath, headless: true })
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
  page.on('request', (request) => console.log(JSON.stringify({ request: request.method(), url: request.url() })))
  page.on('response', (response) => console.log(JSON.stringify({ response: response.status(), url: response.url() })))
  page.on('console', (message) => console.log(JSON.stringify({ console: message.type(), text: message.text() })))
  page.on('pageerror', (error) => console.log(JSON.stringify({ pageerror: error.message })))
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' })
  await page.screenshot({ path: `${outputDir}/login-${name}.png`, fullPage: true })
  await page.locator('#pin-entry').fill('123456')
  console.log(JSON.stringify({ value: await page.locator('#pin-entry').inputValue(), disabled: await page.getByRole('button', { name: /Open dashboard/ }).isDisabled() }))
  await page.locator('form').evaluate((form) => form.requestSubmit())
  await page.waitForTimeout(1000)
  console.log((await page.locator('body').innerText()).slice(0, 500))
  await page.getByText('Recent matches').waitFor({ state: 'visible', timeout: 15000 })
  await page.screenshot({ path: `${outputDir}/dashboard-${name}.png`, fullPage: true })
  const metrics = await page.locator('.metric-grid').innerText()
  const statuses = await page.locator('.status-pill').allTextContents()
  const layout = await page.evaluate(() => {
    const width = document.documentElement.clientWidth
    const cards = [...document.querySelectorAll('.match-card')].map((node) => Math.round(node.getBoundingClientRect().width))
    const chart = document.querySelector('.chart-panel')?.getBoundingClientRect()
    return { scrollWidth: document.documentElement.scrollWidth, clientWidth: width, cards, chartWidth: chart ? Math.round(chart.width) : null }
  })
  console.log(JSON.stringify({ name, metrics, statuses, layout }))
  await browser.close()
}
