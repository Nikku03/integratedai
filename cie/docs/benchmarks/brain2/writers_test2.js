export const meta = {
  name: 'brain2-writers-test',
  description: 'Step 2 of the company-brain round-2 test: blind writers write descriptive, free-text and held-out questions about test documents, sealed (written to files, counts returned)',
  phases: [{ title: 'Write', detail: 'one writer per batch, each in a different role' }],
}
// Run as a Workflow with args = the JSON object step 1 prints last: {sets: [{dir, out, batches: [...]}, ...]}. Each writer reads
// one batch file, writes its questions to <out>/<batch>.jsonl and returns only how many it wrote, so that nobody but the
// scoring code reads them.
const ROLES = [
  'a project manager who checks status across teams every morning',
  'a support engineer on call who needs facts fast',
  'a sales lead preparing for a customer call',
  'a new hire in their second week, still learning the names of things',
  'a finance analyst who cares about dates and owners',
  'a VP typing on a phone between meetings, terse and informal',
  'a solutions engineer who works closely with customers',
  'a security and compliance reviewer',
  'an engineering manager planning the next sprint',
  'an operations lead tracking incidents and follow-ups',
]
const JOBS = []
for (const s of args.sets) for (const b of s.batches) JOBS.push({ dir: s.dir, out: s.out, b })
const DONE = { type: 'object', properties: { written: { type: 'integer' } }, required: ['written'] }
const results = await parallel(JOBS.map((j, i) => () => agent(
  `You are ${ROLES[(i + 7) % ROLES.length]} at a company. Read the JSON file ${j.dir}/${j.b}.json (use the Read tool on that one file only; do not open, search or run anything else). It holds up to 10 packets. Each packet has an instruction and one document. For EACH packet, follow its instruction exactly and write the question the way you, in your role, would naturally ask a colleague. Vary your phrasing across packets. Then use the Write tool once to create ${j.out}/${j.b}.jsonl with one JSON object per line, one per packet: {"packet_id": ..., "question": ...} and, when the instruction asks for them, "answer_facts": [...] with each fact copied character for character from the document text. Reply with only the number of lines you wrote.`,
  { label: `write:${j.b}`, phase: 'Write', schema: DONE }).then(r => ({ batch: j.b, written: r ? r.written : null }))))
return { batches: results }
