# -*- coding: utf-8 -*-
"""端到端自测:mock arXiv Atom XML → 解析 → 分类打分 → 入库 → Flask 路由。

运行: python test_e2e.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["PR_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PR_ENABLE_SCHEDULER"] = "0"
os.environ["PR_BOOTSTRAP_FETCH"] = "0"

import arxiv_client  # noqa: E402
import pipeline      # noqa: E402
import ranker        # noqa: E402

NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


ENTRY_TPL = """
<entry>
  <id>http://arxiv.org/abs/{aid}v1</id>
  <title>{title}</title>
  <summary>{abstract}</summary>
  <published>{published}</published>
  <updated>{published}</updated>
  {authors}
  <arxiv:comment xmlns:arxiv="http://arxiv.org/schemas/atom">{comment}</arxiv:comment>
  <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="{cat}"/>
  <category term="{cat}"/>
  <link title="pdf" href="https://arxiv.org/pdf/{aid}" rel="related" type="application/pdf"/>
</entry>"""

PAPERS = [
    dict(aid="2606.00001", cat="cs.CL", comment="Accepted at ACL 2026 (main conference)",
         title="Scaling Document-Level Neural Machine Translation with Context Compression",
         abstract="Neural machine translation struggles with long documents. We propose a context "
                  "compression framework for document-level translation. Experiments on WMT benchmarks "
                  "show our method outperforms strong baselines and achieves state-of-the-art BLEU.",
         published=iso(1), authors=["Alice Wang", "Bob Li"]),
    dict(aid="2606.00002", cat="eess.AS", comment="Submitted to INTERSPEECH 2026",
         title="StreamST: Simultaneous Speech Translation with Adaptive Latency",
         abstract="End-to-end speech translation systems face a latency-quality tradeoff. We present "
                  "StreamST, a simultaneous translation model. Results show significant quality gains.",
         published=iso(2), authors=["Carol Chen"]),
    dict(aid="2606.00003", cat="eess.AS", comment="",
         title="Robust Automatic Speech Recognition under Noisy Conditions",
         abstract="Automatic speech recognition degrades in noise. We introduce a noise-aware ASR "
                  "encoder. Experiments demonstrate improved word error rate on LibriSpeech.",
         published=iso(3), authors=["Dan Zhao", "Eve Sun"]),
    dict(aid="2606.00004", cat="cs.SD", comment="Accepted by ICASSP 2026",
         title="ZeroVoice: Zero-Shot TTS with Disentangled Speaker Representations",
         abstract="Text-to-speech systems require speaker data. We propose a zero-shot TTS model with "
                  "voice cloning capability. Our speech synthesis approach achieves superior naturalness.",
         published=iso(1), authors=["Frank Liu"]),
    dict(aid="2606.00005", cat="cs.CV", comment="CVPR 2026 camera-ready",
         title="Hierarchical Vision Transformer for Fine-Grained Image Recognition",
         abstract="Image classification on fine-grained categories is challenging. We present a "
                  "hierarchical vision transformer. Our object detection and image recognition results "
                  "surpass previous state-of-the-art on ImageNet.",
         published=iso(2), authors=["Grace Kim", "Henry Park"]),
    dict(aid="2606.00006", cat="cs.CV", comment="Accepted at ICDAR 2026",
         title="DocParse: Unified OCR and Layout Analysis for Document Understanding",
         abstract="Optical character recognition and document parsing are usually separate. We "
                  "introduce DocParse, a unified scene text recognition and layout analysis model. "
                  "It achieves state-of-the-art on document understanding benchmarks.",
         published=iso(1), authors=["Ivy Zhou"]),
    dict(aid="2606.00007", cat="cs.LG", comment="",
         title="Efficient Pretraining of Large Language Models via Curriculum Data Mixing",
         abstract="Large language model pretraining is costly. We propose a curriculum data mixing "
                  "strategy for LLM pre-training. Experiments show improved downstream reasoning.",
         published=iso(2), authors=["Jack Ma", "Kate Hu", "Leo Gao"]),
    dict(aid="2606.00008", cat="cs.CL", comment="Findings of ACL 2026",
         title="Rethinking MT Evaluation: A Reference-Free Quality Estimation Metric",
         abstract="Translation evaluation relies on references. We present a reference-free quality "
                  "estimation metric for machine translation evaluation, correlating better with MQM "
                  "human judgments than COMET and BLEU.",
         published=iso(1), authors=["Mia Xu"]),
    dict(aid="2606.00009", cat="cs.AI", comment="",
         title="WebPilot: A Multi-Agent Framework for Autonomous Web Navigation",
         abstract="LLM agents struggle with complex web tasks. We propose WebPilot, a multi-agent "
                  "framework with tool use and planning. Experiments on WebArena show our agentic "
                  "system achieves new state-of-the-art success rates.",
         published=iso(1), authors=["Noah Lee", "Olivia Brown"]),
    # 干扰项:不属于任何目标领域
    dict(aid="2606.00010", cat="cs.LG", comment="",
         title="A Study of Graph Coloring Heuristics",
         abstract="We analyze classical graph coloring heuristics on random graphs.",
         published=iso(2), authors=["Pat Quinn"]),
    # 干扰项:过旧(超出近 7 天窗口)
    dict(aid="2605.09999", cat="cs.CL", comment="Accepted at NAACL 2026",
         title="Old Machine Translation Paper Beyond Window",
         abstract="We propose a machine translation method.", published=iso(30),
         authors=["Ray Old"]),
]


def build_xml():
    entries = []
    for p in PAPERS:
        kw = dict(p)
        kw["authors"] = "".join("<author><name>%s</name></author>" % a for a in p["authors"])
        entries.append(ENTRY_TPL.format(**kw))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>")


def main():
    failures = []

    def check(name, cond, detail=""):
        print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + detail) if detail and not cond else ""))
        if not cond:
            failures.append(name)

    # 1. 解析
    papers = arxiv_client.parse_atom(build_xml())
    check("Atom 解析出全部条目", len(papers) == len(PAPERS), "got %d" % len(papers))
    check("arxiv_id 去版本号", papers[0].arxiv_id == "2606.00001")
    check("PDF 链接解析", papers[0].pdf_url.endswith("2606.00001"))

    # 2. 分类与打分
    ranked = ranker.rank(list(papers))
    by_id = {p.arxiv_id: p for p in ranked}
    check("干扰项(图染色)被过滤", "2606.00010" not in by_id)
    check("MT 论文归类正确", "mt" in by_id["2606.00001"].fields)
    check("语音翻译归类正确", "st" in by_id["2606.00002"].fields)
    check("ASR 归类正确", "asr" in by_id["2606.00003"].fields)
    check("TTS 归类正确", "tts" in by_id["2606.00004"].fields)
    check("图像识别归类正确", "cv" in by_id["2606.00005"].fields)
    check("OCR 归类正确,且不误入图像识别", "ocr" in by_id["2606.00006"].fields and "cv" not in by_id["2606.00006"].fields)
    check("LLM 归类正确", "llm" in by_id["2606.00007"].fields)
    check("MT评测归类正确", "mteval" in by_id["2606.00008"].fields)
    check("Agent 归类正确", "agent" in by_id["2606.00009"].fields)
    check("顶会接收的论文识别出 venue", by_id["2606.00001"].venue.startswith("ACL"))
    check("评分在 0-10 区间", all(0 <= p.score <= 10 for p in ranked))
    check("有顶会标记的 MT 论文评分高于无标记 ASR",
          by_id["2606.00001"].score > by_id["2606.00003"].score)

    # 3. pipeline 入库(注入 mock,不访问网络)
    count, date = pipeline.run_update(papers=papers)
    check("pipeline 入库篇数正确(9 篇有效)", count == 9, "got %d" % count)

    import storage
    check("过旧论文未入库", all(p["arxiv_id"] != "2605.09999" for p in storage.query_papers()))
    sample = storage.query_papers(field="mt")[0]
    check("中文介绍已生成", "【研究问题】" in sample["summary_zh"])
    check("介绍含方法贡献段", "【方法贡献】" in sample["summary_zh"])

    # 4. Flask 路由
    from app import app
    client = app.test_client()
    r = client.get("/")
    check("首页 200", r.status_code == 200)
    html = r.get_data(as_text=True)
    check("首页渲染论文标题", "StreamST" in html)
    check("首页渲染中文介绍", "【研究问题】" in html)
    check("首页渲染领域标签", "机器翻译评测" in html)

    r = client.get("/api/papers?field=agent")
    check("API 按领域过滤", r.status_code == 200 and r.get_json()["count"] == 1)
    r = client.get("/api/papers?field=bad")
    check("API 未知领域返回 400", r.status_code == 400)
    r = client.get("/api/papers?q=speech")
    check("API 搜索可用", r.get_json()["count"] >= 2)
    r = client.get("/api/status")
    check("status 接口", r.get_json()["latest_count"] == 9)
    r = client.get("/healthz")
    check("健康检查", r.status_code == 200)
    r = client.post("/api/refresh")
    check("未配置 token 时 refresh 被禁用", r.status_code == 403)

    # 5. 调度器时间计算
    import scheduler
    wait, target = scheduler.seconds_until_next_run()
    check("下次运行在 24h 内", 0 < wait <= 86400)
    check("目标时刻为 06:00", target.hour == 6 and target.minute == 0)

    print("\n%s: %d 项检查, %d 失败" % ("自测完成", 28, len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
