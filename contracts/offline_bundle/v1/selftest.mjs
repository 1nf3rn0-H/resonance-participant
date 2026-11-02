import { readFileSync } from 'node:fs'
import { canonical,sha256,scientificHash,integrityHash } from './canonical.mjs'
import { validateSchema,validateQuestionBank,validateSampling,questionBank,samplingConfig } from './schema.mjs'
const read=file=>JSON.parse(readFileSync(new URL(file,import.meta.url),'utf8'))
if(!validateQuestionBank(questionBank)||!validateSampling(samplingConfig))throw Error('Definition schema mismatch')
for(const vector of read('./vectors/canonical.json'))if(canonical(vector.input)!==vector.canonical_utf8||sha256(vector.input)!==vector.sha256)throw Error('Cross-language canonical vector mismatch')
for(const name of ['valid-history.json','valid-responses-only.json','valid-non-recall.json','valid-feasibility.json']) {
 const value=read('./fixtures/'+name)
 if(!validateSchema(value)||scientificHash(value)!==value.manifest.content_hash||integrityHash(value)!==value.manifest.integrity_hash)throw Error('Producer/consumer compatibility mismatch')
}
console.log(JSON.stringify({status:'PASS',contract_version:'1.0.0',runtime:'JavaScript',canonical_vectors:4,bundle_cases:4}))
