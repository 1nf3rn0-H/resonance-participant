import { analyzeEvents } from './v03.ts'
let raw=''
for await(const chunk of process.stdin)raw+=chunk
try {
 const request=JSON.parse(raw)
 process.stdout.write(JSON.stringify(analyzeEvents(request.events,undefined,{maxEpisodes:10})))
} catch(error){process.stderr.write('Frozen v0.3 sampler rejected its input');process.exitCode=1}
