"""Llama reads the 5 documents and answers the 4 questions (same instructions as the earlier reader agent)."""
import json, sys, time, urllib.request
S = "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad"
model, out = sys.argv[1], sys.argv[2]
docs = "\n\n".join(open(f"{S}/kg/docs/doc{i}.txt").read() for i in range(1, 6))
qs = json.load(open(f"{S}/read5/questions.json"))
SYSTEM = ("You answer questions about a company's internal documents. The documents are split into numbered passages "
          "('[section N]'). Answer as a careful colleague would: complete and specific (exact names, numbers, labels, "
          "thresholds, dates, steps), based only on what the documents say. Do not guess or use outside knowledge. Where "
          "documents disagree or describe different incidents, say which applies to the question and do not mix them up. "
          "After each claim, cite the document and section like (doc3 §9).")
answers, stats = {}, {}
for qid, q in qs.items():
    body = {"model": model, "stream": False, "keep_alive": "30m",
            "options": {"num_ctx": 20480, "temperature": 0, "num_predict": 1500},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"{docs}\n\nQuestion: {q}"}]}
    t = time.time()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=7200))
    answers[qid] = r["message"]["content"]
    stats[qid] = {"seconds": round(time.time() - t), "prompt_tokens": r.get("prompt_eval_count"), "output_tokens": r.get("eval_count"),
                  "prompt_tok_per_s": round(r.get("prompt_eval_count", 0) / (r.get("prompt_eval_duration", 1) / 1e9), 1),
                  "output_tok_per_s": round(r.get("eval_count", 0) / (r.get("eval_duration", 1) / 1e9), 1)}
    print(qid, stats[qid], flush=True)
    json.dump(answers, open(out, "w"), indent=1)
    json.dump(stats, open(out.replace(".json", "_stats.json"), "w"), indent=1)
print("done")
