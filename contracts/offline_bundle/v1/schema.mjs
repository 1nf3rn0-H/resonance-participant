import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import { readFileSync } from 'node:fs'

const read=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'))
// Embedded/local resources only. No async loadSchema or network resolver is configured.
const ajv=new Ajv2020({strict:false,allErrors:true,validateFormats:true})
addFormats(ajv)
ajv.addFormat('date-time',value=>{try{return !value.startsWith('0000')&&new Date(value).toISOString()===value}catch{return false}})
ajv.addFormat('date',value=>{try{return !value.startsWith('0000')&&new Date(value+'T00:00:00.000Z').toISOString().slice(0,10)===value}catch{return false}})
export const bundleSchema=read('./schemas/bundle.schema.json')
export const questionBank=read('./questions.json')
export const samplingConfig=read('./sampling.json')
export const validateSchema=ajv.compile(bundleSchema)
export const validateQuestionBank=ajv.compile(read('./schemas/question-bank.schema.json'))
export const validateSampling=ajv.compile(read('./schemas/sampling.schema.json'))
