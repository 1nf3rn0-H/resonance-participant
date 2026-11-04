import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import assert from 'node:assert/strict'
import {contentHash,integrityHash} from './canonical.mjs'
const require=createRequire(new URL('../../offline_bundle/v1/package.json',import.meta.url))
const Ajv=require('ajv/dist/2020.js'),formats=require('ajv-formats')
const ajv=new Ajv({strict:false,allErrors:true});formats(ajv)
const load=name=>JSON.parse(readFileSync(new URL(name,import.meta.url)))
const validate=ajv.compile(load('./schema.json')),vectors=load('./vectors/hashes.json')
for(const v of vectors){const bundle=load('./'+v.fixture);assert.ok(validate(bundle),JSON.stringify(validate.errors));assert.equal(contentHash(bundle),v.content_hash);assert.equal(integrityHash(bundle),v.integrity_hash)}
console.log(JSON.stringify({status:'PASS',h6_contract:'1.0.0',cross_language_bundle_vectors:vectors.length}))
