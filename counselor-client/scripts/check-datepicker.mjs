import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
import { HDate } from '@hebcal/core'
if (!process.env.DATEPICKER_CHECK_CHILD) {
 for (const zone of ['Asia/Jerusalem', 'UTC', 'America/New_York']) {
  const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {env:{...process.env, TZ:zone, DATEPICKER_CHECK_CHILD:'1'},encoding:'utf8'})
  assert.equal(result.status,0,result.stderr)
  process.stdout.write(result.stdout)
 }
} else {
 const source = readFileSync(new URL('../node_modules/react-hebrew-datepicker/dist/index.esm.js',import.meta.url),'utf8')
 const match = source.match(/function\((\w+),(\w+),(\w+)\)\{return (function\(rhdpDate\)\{[^}]+\}\(new [\w.$]+\([^)]*\)\.greg\(\)\))\}/)
 assert.ok(match, 'Patched calendar conversion must be present')
 const expression = match[4].replace(/new [\w.$]+\(/,'new HDate(')
 const convert = new Function('HDate',match[1],match[2],match[3],`return ${expression}`)
 assert.equal(convert(HDate,1,7,5787),'2026-09-12')
 assert.equal(convert(HDate,26,7,5787),'2026-10-07')
 console.log(`${process.env.TZ}: selected Hebrew day maps to the correct Gregorian date`)
}
