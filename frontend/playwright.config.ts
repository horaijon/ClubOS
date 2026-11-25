import { defineConfig } from '@playwright/test'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const brave = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
const directory = mkdtempSync(join(tmpdir(), 'clubos-e2e-'))
export default defineConfig({
  testDir: './tests', timeout: 45000, workers: 1,
  use: { baseURL:'http://127.0.0.1:8028', viewport:{width:1440,height:960},
    launchOptions:{executablePath:process.env.CHROMIUM_PATH || (existsSync(brave)?brave:undefined)} },
  webServer:{
    command:'../.venv/bin/uvicorn clubos.main:app --app-dir ../backend --port 8028 --host 127.0.0.1',
    url:'http://127.0.0.1:8028/api/health', reuseExistingServer:false,
    env:{CLUBOS_DB:join(directory,'test.sqlite3'),GEMINI_API_KEY:''}
  }
})
