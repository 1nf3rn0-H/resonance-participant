import {sha256,integrityHash} from '../../offline_bundle/v1/canonical.mjs'
export {sha256,integrityHash}
const sections=['event_evidence','sessionization_runs','sessions','followup_selections','followup_exposures','followup_submissions','followup_completions']
export function contentHash(bundle){
 const core=bundle.core,ext=bundle.extension,ids=new Map(core.events.map(e=>[e.record_id,e.event_key]))
 const assignments=new Map(core.assignments.map(a=>[a.record_id,a])),windows=new Map(core.eligible_windows.map(w=>[w.record_id,w]))
 for(const p of core.prompt_packets){const a=assignments.get(p.assignment_id);ids.set(p.record_id,sha256({window:windows.get(a.window_id).window_key,day:a.collection_day,slot:a.slot_ordinal}))}
 for(const lock of core.locks)ids.set(lock.record_id,sha256([ids.get(lock.prompt_packet_id),lock.answer_set_hash]))
 for(const run of ext.sessionization_runs)ids.set(run.record_id,sha256([run.input_event_refs,run.parameters]))
 for(const selected of ext.followup_selections)ids.set(selected.record_id,sha256([ids.get(selected.prompt_packet_id),selected.policy_version]))
 const refs=new Set(['event_id','prompt_packet_id','neutral_lock_id','run_id','selection_id']),volatile=new Set(['record_id','record_hash','created_at','generated_at','artifact_generated_at','input_hash'])
 function project(value,key){if(Array.isArray(value))return value.map(v=>project(v,key));if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!volatile.has(k)).map(([k,v])=>[k,project(v,k)]));return refs.has(key)&&typeof value==='string'?(ids.get(value)||value):value}
 const parts=Object.fromEntries(sections.map(name=>[name,ext[name].map(r=>project(r)).sort((a,b)=>sha256(a).localeCompare(sha256(b),'en'))]))
 return sha256({domain:'resonance-h6-scientific-1.0.0',core_content_hash:core.manifest.content_hash,consent:project(ext.consent),availability:ext.availability,sections:parts})
}
