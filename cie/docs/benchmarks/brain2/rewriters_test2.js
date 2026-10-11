export const meta = {
  name: 'brain2-rewriters-test',
  description: 'Step 4 of the company-brain round-2 test: blind rewriters reword the generated test questions the way people type, sealed (written to files, counts returned)',
  phases: [{ title: 'Rewrite', detail: 'one rewriter per batch, each in a different role' }],
}
// Run as a Workflow with args = {dir, out, batches: [...]} as run_brain2_2.sh prints last. Each rewriter reads one batch file
// (questions only: no documents, no answers), writes its rewrites to <out>/<batch>.jsonl and returns only how many it wrote,
// so that nobody but the scoring code reads them.
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
const DONE = { type: 'object', properties: { written: { type: 'integer' } }, required: ['written'] }
const results = await parallel(args.batches.map((b, i) => () => agent(
  `You are ${ROLES[(i + 2) % ROLES.length]} at a company. Read the JSON file ${args.dir}/${b}.json (use the Read tool on that one file only; do not open, search or run anything else). It holds an instruction and up to 40 questions. Follow the instruction for EACH question, as you in your role would type it. Vary your style across questions. Then use the Write tool once to create ${args.out}/${b}.jsonl with one JSON object per line, one per question: {"packet_id": ..., "question": "<your rewrite>"}. Reply with only the number of lines you wrote.`,
  { label: `rewrite:${b}`, phase: 'Rewrite', schema: DONE }).then(r => ({ batch: b, written: r ? r.written : null }))))
return { batches: results }
