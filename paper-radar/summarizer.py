# -*- coding: utf-8 -*-
"""为每篇论文生成中文要点介绍。

默认规则式:从英文摘要中抽取「任务背景 / 方法贡献 / 实验结果」三类句子,
拼成结构化中文导读(关键句保留英文原文,避免机器误译)。

可选 LLM 模式:配置 DEEPSEEK_API_KEY 后,自动调用 DeepSeek 生成真正的中文摘要,
失败时自动回退到规则式,保证更新流程永不因外部服务中断。
"""
import json
import logging
import re

import requests

import config

log = logging.getLogger("paper-radar.summarizer")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_METHOD_RE = re.compile(r"\b(we propose|we present|we introduce|we develop|this paper proposes|"
                        r"this paper presents|this paper introduces|we design|our (method|approach|model|framework))\b",
                        re.IGNORECASE)
_RESULT_RE = re.compile(r"\b(experiments?|results?|outperform|achieve|state[- ]of[- ]the[- ]art|sota|"
                        r"improve|surpass|gain|evaluation shows)\b", re.IGNORECASE)


def _sentences(abstract):
    return [s.strip() for s in _SENT_SPLIT.split(abstract or "") if s.strip()]


def rule_based_summary(paper, field_names):
    """规则式中文导读。"""
    sents = _sentences(paper.abstract)
    if not sents:
        return "(该论文暂无摘要)"

    background = sents[0]
    method = next((s for s in sents if _METHOD_RE.search(s)), None)
    result = next((s for s in reversed(sents) if _RESULT_RE.search(s)), None)

    parts = ["【领域】" + " / ".join(field_names)]
    if paper.venue:
        parts.append("【发表】" + paper.venue)
    parts.append("【研究问题】" + background)
    if method and method != background:
        parts.append("【方法贡献】" + method)
    if result and result not in (background, method):
        parts.append("【实验结果】" + result)
    return "\n".join(parts)


def llm_summary(paper, field_names):
    """调用 DeepSeek API 生成中文摘要,失败返回 None。"""
    if not config.DEEPSEEK_API_KEY:
        return None
    prompt = (
        "请用中文为下面这篇论文写 3-4 句要点介绍,依次说明:研究问题、核心方法、主要结果。"
        "直接输出介绍文字,不要任何前言。\n\n"
        "标题: {title}\n领域: {fields}\n摘要: {abstract}"
    ).format(title=paper.title, fields=" / ".join(field_names), abstract=paper.abstract[:2500])
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + config.DEEPSEEK_API_KEY,
                "content-type": "application/json",
            },
            data=json.dumps({
                "model": config.LLM_MODEL,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            }),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return text or None
    except Exception as e:
        log.warning("LLM 摘要失败,回退规则式: %s", e)
        return None


def summarize(paper):
    """生成中文介绍并写入 paper.summary_zh。"""
    field_names = [config.FIELDS[f]["name"] for f in paper.fields if f in config.FIELDS]
    text = llm_summary(paper, field_names) if config.DEEPSEEK_API_KEY else None
    paper.summary_zh = text or rule_based_summary(paper, field_names)
    return paper.summary_zh
