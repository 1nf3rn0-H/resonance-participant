import canonicalize from 'canonicalize'
import { createHash } from 'node:crypto'

export function canonical(value) {
  function check(v) {
    if(typeof v==='string') {
      for(let i=0;i<v.length;i++) {
        const c=v.charCodeAt(i)
        if(c>=0xd800&&c<=0xdbff) { const next=v.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))throw Error('Lone surrogate') }
        else if(c>=0xdc00&&c<=0xdfff)throw Error('Lone surrogate')
      }
    } else if(typeof v==='number') { if(!Number.isFinite(v))throw Error('Non-finite number') }
    else if(Array.isArray(v)){for(let i=0;i<v.length;i++){if(!(i in v))throw Error('Sparse array');check(v[i])}}
    else if(v&&typeof v==='object'){if(![Object.prototype,null].includes(Object.getPrototypeOf(v)))throw Error('Not a JSON object');Object.entries(v).forEach(([k,item])=>{check(k);check(item)})}
    else if(v!==null&&typeof v!=='boolean')throw Error('Not a JSON value')
  }
  check(value)
  return canonicalize(value)
}
export const sha256=value=>createHash('sha256').update(canonical(value),'utf8').digest('hex')
export const recordHash=record=>sha256(Object.fromEntries(Object.entries(record).filter(([key])=>key!=='record_hash')))
export const integrityHash=bundle=>sha256({...bundle,manifest:Object.fromEntries(Object.entries(bundle.manifest).filter(([key])=>key!=='integrity_hash'))})

const sections=['consent','history_imports','tracks','events','episode_snapshots','eligible_windows','native_candidates','mappings','assignments','prompt_packets','submissions','locks','prompt_events']
const volatile=new Set(['record_id','record_hash','created_at','generated_at','actual_imported_at','received_at'])
const refs=new Set(['import_id','track_id','episode_id','window_id','assignment_id','prompt_packet_id','submission_id','neutral_submission_id','event_ids','native_candidate_ids','frame_window_ids','winning_window_ids','prior_assignment_ids','lock_id'])
export function scientificHash(bundle) {
  const identities=new Map(),parts={}
  function project(value,key) {
    if(Array.isArray(value))return value.map(v=>project(v,key))
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!volatile.has(k)).map(([k,v])=>[k,project(v,k)]))
    if(refs.has(key)&&typeof value==='string') {if(!identities.has(value))throw Error(`Unknown scientific reference ${value}`);return identities.get(value)}
    return value
  }
  for(const section of sections) {
    const records=section==='consent'?[bundle.consent]:(bundle[section]||[])
    parts[section]=records.map(record=>{const payload=project(record);identities.set(record.record_id,sha256({domain:'resonance-record-science-v1',type:section,content:payload}));return payload})
      .sort((a,b)=>Buffer.compare(Buffer.from(canonical(a)),Buffer.from(canonical(b))))
  }
  const m=bundle.manifest
  return sha256({domain:'resonance-bundle-science-v1',schema_version:m.schema_version,study_id:m.study_id,participant_pseudonym:m.participant_pseudonym,protocol_version:m.protocol_version,trial_type:m.trial_type,question_bank_hash:m.question_bank_hash,sampling_config_hash:m.sampling_config_hash,records:parts,provenance:bundle.provenance})
}
export function seal(bundle) {
  for(const section of sections)for(const r of section==='consent'?[bundle.consent]:(bundle[section]||[]))r.record_hash=recordHash(r)
  bundle.manifest.content_hash=scientificHash(bundle)
  bundle.manifest.integrity_hash=integrityHash(bundle)
  return bundle
}
