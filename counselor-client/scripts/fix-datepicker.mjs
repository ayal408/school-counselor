import { readFileSync, writeFileSync } from 'node:fs'
// Upstream 1.1.3 adds one day and serializes local midnight as UTC.
// Format the actual selected Gregorian civil date in the local timezone.
const folder = new URL('../node_modules/react-hebrew-datepicker/', import.meta.url)
const pkg = JSON.parse(readFileSync(new URL('package.json', folder), 'utf8'))
if (pkg.version !== '1.1.3') throw new Error('Recheck the date conversion patch before changing datepicker versions')
const original = /new ([\w$.]+)\((\w+)\+1,(\w+),(\w+)\)\.greg\(\)\.toISOString\(\)\.slice\(0,10\)/g
const marker = 'function(rhdpDate){return [rhdpDate.getFullYear(),String(rhdpDate.getMonth()+1).padStart(2,"0"),String(rhdpDate.getDate()).padStart(2,"0")].join("-")}'
for (const file of ['dist/index.esm.js', 'dist/index.js']) {
 const path = new URL(file, folder)
 const source = readFileSync(path, 'utf8')
 if (source.includes(marker)) continue
 let matches = 0
 const fixed = source.replace(original, (_, constructor, day, month, year) => {
  matches++
  return `${marker}(new ${constructor}(${day},${month},${year}).greg())`
 })
 if (matches !== 1) throw new Error(`Expected one date conversion to patch in ${file}; got ${matches}`)
 writeFileSync(path, fixed)
}
console.log('Hebrew datepicker local date conversion verified')
