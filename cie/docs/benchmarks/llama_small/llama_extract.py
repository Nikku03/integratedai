"""Load-time extraction with Llama: each passage of a document becomes a list of standalone facts (no question)."""
import json, re, sys, time, urllib.request
S = "/tmp/claude-0/-home-user-integratedai/275b943f-979b-5741-9af5-2a07879accea/scratchpad"
model, doc, out = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(f"{S}/kg/docs/{doc}.txt").read()
parts = re.split(r"\n(?=\[section \d+\])", text)
passages = [p for p in parts if p.startswith("[section")]
PROMPT = ("List every fact stated in this passage of a company document, one per line, as short standalone sentences. "
          "Keep every number, unit, name, label, date, threshold and condition exactly. Name the thing each fact is about "
          "instead of writing 'it'. Do not add anything that is not in the passage.\n\nPassage:\n")
facts, stats = [], []
for i, p in enumerate(passages):
    body = {"model": model, "stream": False, "keep_alive": "30m", "options": {"num_ctx": 4096, "temperature": 0, "num_predict": 700},
            "messages": [{"role": "user", "content": PROMPT + p}]}
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                                                                  headers={"Content-Type": "application/json"}), timeout=3600))
    lines = [l.strip(" -*•\t") for l in r["message"]["content"].splitlines() if len(l.strip(" -*•\t")) > 8]
    facts += [{"section": i, "fact": l} for l in lines]
    stats.append({"section": i, "seconds": round(time.time() - t), "in": r.get("prompt_eval_count"), "out": r.get("eval_count")})
    print(stats[-1], len(lines), "facts", flush=True)
    json.dump({"facts": facts, "stats": stats}, open(out, "w"), indent=1)
print("done", len(facts), "facts")
