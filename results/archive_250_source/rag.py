"""Small, inspectable manual RAG: BM25 + character TF-IDF, RRF, conditional warnings.

The second retriever is sparse lexical TF-IDF, NOT a learned semantic embedding.
The guarded answer renderer only emits curated, source-linked facts. LLM drafts
are retained for comparison, never treated as proof of factual correctness.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import re

DATA = Path(__file__).parent / "data" / "manual.json"


def tokens(text: str) -> list[str]:
    text = text.lower()
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    return re.findall(r"[a-z0-9]+", text) + [s[i:i+2] for s in han for i in range(max(0, len(s)-1))] + list("".join(han))


def topic(text: str) -> str | None:
    for name, words in {
        "child": ["儿童", "宝宝", "婴儿", "安全座椅", "isofix", "i-size", "气囊", "增高垫"],
        "tire": ["胎压", "轮胎", "气压"],
        "coolant": ["冷却", "水箱", "过热", "防冻液"],
        "charging": ["充电", "充电枪"],
    }.items():
        if any(w in text.lower() for w in words):
            return name
    return None


class ManualRAG:
    def __init__(self):
        self.chunks = json.loads(DATA.read_text(encoding="utf-8"))
        self.by_id = {c["id"]: c for c in self.chunks}
        self.docs = [Counter(tokens(c["title"] + " " + c["text"] + " " + " ".join(c["keywords"]))) for c in self.chunks]
        self.df = Counter(t for d in self.docs for t in d)
        self.avg_len = sum(sum(d.values()) for d in self.docs) / len(self.docs)
        self.fingerprint = hashlib.sha256(DATA.read_bytes()).hexdigest()

    def retrieve(self, query: str, k=3, hybrid=True, rerank=True):
        qt = Counter(tokens(query))
        n = len(self.docs)
        bm, cos = [], []
        qvec = {t: v * math.log(1 + n / (1 + self.df[t])) for t, v in qt.items()}
        qnorm = math.sqrt(sum(v*v for v in qvec.values())) or 1
        for i, d in enumerate(self.docs):
            dl = sum(d.values())
            score = sum(math.log(1 + (n-self.df[t]+.5)/(self.df[t]+.5)) * d[t]*2.2/(d[t]+1.2*(.25+.75*dl/self.avg_len)) for t in qt if d[t])
            vec = {t: v*math.log(1+n/(1+self.df[t])) for t, v in d.items()}
            cn = math.sqrt(sum(v*v for v in vec.values())) or 1
            bm.append((score, i))
            cos.append((sum(qvec[t]*vec.get(t, 0) for t in qvec)/(qnorm*cn), i))
        bm.sort(reverse=True)
        cos.sort(reverse=True)
        scores = Counter()
        for ranking in [bm, cos] if hybrid else [bm]:
            for rank, (score, i) in enumerate(ranking):
                if score > 0:
                    scores[i] += 1 / (60 + rank + 1)
        family = topic(query)
        # Metadata-based reranking: keep applicable sections together.
        for i in scores:
            if rerank and self.chunks[i]["topic"] == family:
                scores[i] += .05
        return [dict(self.chunks[i], retrieval_score=round(scores[i], 6)) for i, _ in scores.most_common(k)]

    def relevant_ids(self, query: str):
        family = topic(query)
        if family == "child":
            ids = ["child.scope", "child.fit"]
            front = any(w in query for w in ["副驾", "前排", "前座"])
            back = any(w in query for w in ["后排", "后座"])
            # A mention of the passenger airbag does not establish the installation
            # position: "装后排，要关副驾气囊吗" is about a rear-seat installation.
            if re.search(r"(?:放|装|安装|固定|在).{0,3}(?:后排|后座)", query):
                front, back = False, True
            orientation_text = re.sub(r"(?:不是|并非|不要|非)(?:后向|前向|朝后|朝前|反向|正向|向后|向前)", "", query)
            rear_facing = any(w in orientation_text for w in ["后向", "反向", "朝后", "向后"])
            forward_facing = any(w in orientation_text for w in ["前向", "正向", "朝前", "向前"])
            if front and rear_facing and forward_facing:
                ids += ["child.rear_front", "child.forward_front"]
            elif front and rear_facing:
                ids += ["child.rear_front"]
            elif front and forward_facing:
                ids += ["child.forward_front"]
            elif back:
                ids += ["child.rear_seat"]
            else:
                ids += ["child.rear_front", "child.forward_front"]
            if "isofix" in query.lower() or "接口" in query or "固定" in query or "安装" in query:
                ids += ["child.isofix"]
            return ids
        return {
            "tire": ["tire.cold", "tire.label"],
            "coolant": ["coolant.hot"],
            "charging": ["charging.inspect", "charging.wet"],
        }.get(family, [])

    def prepare(self, query: str, mode="guarded"):
        retrieved = self.retrieve(query, k=3 if mode != "baseline" else 1,
                                  hybrid=mode not in {"baseline", "no_hybrid"}, rerank=mode != "baseline")
        ids = self.relevant_ids(query)
        # Evidence missing / model-specific details are not guessed from a similar manual.
        unsupported = (not ids or any(w in query for w in ["扭矩", "维修密码", "保险丝编号", "紧急解锁", "拖车钩", "牵引", "气囊开关在哪", "开关位置", "多少牛米"]))
        unsupported = unsupported or (any(w in query.lower() for w in ["特斯拉", "model y", "宝马", "比亚迪", "理想", "小鹏"]) and topic(query) == "child")
        if topic(query) == "child":
            requested_years = re.findall(r"20\d{2}", query)
            if any(year != "2026" for year in requested_years) or any(w in query.lower() for w in ["北美", "美国", "加拿大", "美版", "中国版", "国内版", "ex30", "xc90"]):
                unsupported = True
        applicable = [dict(self.by_id[i]) for i in ids]
        # The warning graph expands a retrieved topic; it is not a substitute for
        # retrieving a relevant manual section in the first place.
        if topic(query) and not any(c["topic"] == topic(query) for c in retrieved):
            unsupported = True
        method = "BM25 top-1" if mode == "baseline" else ("BM25 + topic rerank" if mode == "no_hybrid" else "BM25 + character TF-IDF + RRF + topic rerank")
        return {"retrieved": retrieved, "applicable": applicable, "unsupported": unsupported,
                "fingerprint": self.fingerprint, "retrieval_method": method}

    def answer(self, query: str, mode="guarded", candidate: str | None = None):
        p = self.prepare(query, mode)
        guarded = mode != "baseline"
        trace = [{"stage": "retrieval", "status": "pass", "detail": {"method": p["retrieval_method"] if mode != "baseline" else "BM25 top-1", "ids": [c["id"] for c in p["retrieved"]], "corpus_sha256": self.fingerprint}}]
        if guarded and p["unsupported"]:
            message = "现有手册证据不足，无法确认这款车的具体操作或参数。请提供车型、年款、销售地区及对应说明书；不会把其他车型的说明套用到你的车。"
            evidence, status = [], "clarify"
        elif guarded:
            evidence = p["retrieved"] if mode == "no_warning" else p["applicable"]
            message = "\n\n".join(f"{c['text']} [{c['id']}]" for c in evidence)
            orientation_text = re.sub(r"(?:不是|并非|不要|非)(?:后向|前向|朝后|朝前|反向|正向|向后|向前)", "", query)
            mixed_orientation = any(w in orientation_text for w in ["后向", "反向", "朝后", "向后"]) and any(w in orientation_text for w in ["前向", "正向", "朝前", "向前"])
            if topic(query) == "child" and (mixed_orientation or not any(w in query for w in ["后排", "后座", "副驾", "前排", "前座"])):
                message = "需要先确认车型、年款、销售地区、安装位置和座椅朝向。以下是手册示例的条件说明：\n\n" + message
                status = "clarify"
            else:
                status = "answered"
            trace.append({"stage": "safety_warning_expansion", "status": "skipped" if mode == "no_warning" else "pass", "detail": {"required_ids": [c["id"] for c in evidence], "policy": "condition-linked warning graph; incompatible variants excluded"}})
            trace.append({"stage": "grounding", "status": "pass", "detail": "答案由经来源审阅的事实块拼接，保留条件与引用；模型草稿不能覆盖安全事实。"})
        else:
            evidence = p["retrieved"]
            message = candidate or (evidence[0]["text"] if evidence else "当前没有检索到资料。")
            status = "answered"
        if candidate is not None:
            trace.append({"stage": "llm_draft", "status": "info", "detail": {"text": candidate, "used_verbatim": not guarded}})
        return {"status": status, "message": message, "evidence": evidence, "trace": trace,
                "fact_ids": [c["id"] for c in evidence] if guarded and not p["unsupported"] else [],
                "candidate": candidate, "source": "manual_reference", "retrieval": p}
