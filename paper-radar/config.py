# -*- coding: utf-8 -*-
"""全局配置:领域定义、关键词、arXiv 类别、顶会列表、调度参数。

所有可运维参数均支持环境变量覆盖,便于上线后不改代码调整。
"""
import os

# ---------------------------------------------------------------- 基础配置
DB_PATH = os.environ.get("PR_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "papers.db"))
TIMEZONE = os.environ.get("PR_TIMEZONE", "Asia/Shanghai")   # 每日更新所用时区
UPDATE_HOUR = int(os.environ.get("PR_UPDATE_HOUR", "6"))     # 每天 06:00 更新
UPDATE_MINUTE = int(os.environ.get("PR_UPDATE_MINUTE", "0"))
REFRESH_TOKEN = os.environ.get("PR_REFRESH_TOKEN", "")       # /api/refresh 鉴权 token,留空则禁用该接口

# 每个 arXiv 类别拉取的最近论文数(按提交时间倒序)
FETCH_PER_CATEGORY = int(os.environ.get("PR_FETCH_PER_CATEGORY", "150"))
# 只保留最近 N 天内提交/更新的论文
RECENT_DAYS = int(os.environ.get("PR_RECENT_DAYS", "7"))
# 每个领域每天最多展示的论文数
TOP_K_PER_FIELD = int(os.environ.get("PR_TOP_K", "20"))
# arXiv API 限速(秒),官方建议 >= 3s
ARXIV_DELAY = float(os.environ.get("PR_ARXIV_DELAY", "3.0"))

# 可选:配置 Anthropic API Key 后,中文介绍改由 LLM 生成
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("PR_LLM_MODEL", "claude-sonnet-4-20250514")

# ---------------------------------------------------------------- arXiv 类别
ARXIV_CATEGORIES = [
    "cs.CL",    # 计算语言学:机器翻译 / 大模型 / 评测
    "cs.CV",    # 计算机视觉:图像识别 / OCR
    "cs.SD",    # 声音:ASR / TTS
    "eess.AS",  # 音频与语音处理
    "cs.AI",    # 人工智能:Agent
    "cs.LG",    # 机器学习:大模型训练
    "cs.MA",    # 多智能体
]

# ---------------------------------------------------------------- 顶会质量信号
# 在 arXiv comments 中检测到这些会议的接收信息时给予质量加分
TOP_VENUES = [
    "ACL", "EMNLP", "NAACL", "COLING", "EACL", "TACL", "AACL",
    "NeurIPS", "ICML", "ICLR", "AAAI", "IJCAI", "KDD",
    "CVPR", "ICCV", "ECCV", "WACV", "ICDAR",
    "INTERSPEECH", "ICASSP", "ASRU", "SLT", "IWSLT", "WMT",
    "COLM", "SIGIR", "WWW", "MM", "ACMMM",
]

# ---------------------------------------------------------------- 领域定义
# 每个领域:中文名、强关键词(命中即归类)、弱关键词(辅助加分)、排除词
FIELDS = {
    "mt": {
        "name": "机器翻译",
        "strong": [
            "machine translation", "neural machine translation", " nmt ",
            "multilingual translation", "translation model", "low-resource translation",
            "document-level translation", "translation quality",
        ],
        "weak": ["multilingual", "cross-lingual", "bilingual", "translation"],
        "exclude": ["speech translation", "image translation", "style translation"],
    },
    "st": {
        "name": "语音翻译",
        "strong": [
            "speech translation", "speech-to-text translation", "speech-to-speech",
            "simultaneous translation", "simultaneous interpretation", "end-to-end speech translation",
        ],
        "weak": ["streaming translation", "cascaded"],
        "exclude": [],
    },
    "asr": {
        "name": "语音识别 ASR",
        "strong": [
            "speech recognition", " asr ", "automatic speech recognition",
            "speech-to-text", "audio transcription", "whisper",
        ],
        "weak": ["acoustic model", "speech encoder", "voice activity"],
        "exclude": ["emotion recognition"],
    },
    "tts": {
        "name": "语音合成 TTS",
        "strong": [
            "text-to-speech", " tts ", "speech synthesis", "voice cloning",
            "voice conversion", "speech generation", "zero-shot tts", "neural vocoder",
        ],
        "weak": ["prosody", "speaker embedding", "audio generation"],
        "exclude": [],
    },
    "cv": {
        "name": "图像识别",
        "strong": [
            "image recognition", "image classification", "object detection",
            "visual recognition", "semantic segmentation", "instance segmentation",
            "vision transformer", "image segmentation",
        ],
        "weak": ["backbone", "visual representation", "detection"],
        "exclude": ["optical character", "text recognition", "ocr"],
    },
    "ocr": {
        "name": "OCR 文字识别",
        "strong": [
            " ocr ", "optical character recognition", "text recognition",
            "scene text", "handwriting recognition", "document understanding",
            "document parsing", "text detection", "layout analysis", "document ai",
        ],
        "weak": ["document image", "table recognition", "formula recognition"],
        "exclude": [],
    },
    "llm": {
        "name": "大模型 LLM",
        "strong": [
            "large language model", " llm", "foundation model", "instruction tuning",
            "rlhf", "reinforcement learning from human feedback", "chain-of-thought",
            "reasoning model", "mixture-of-experts", "in-context learning",
            "preference optimization", "pretraining", "pre-training",
        ],
        "weak": ["transformer", "fine-tuning", "alignment", "scaling law", "long context"],
        "exclude": [],
    },
    "mteval": {
        "name": "机器翻译评测",
        "strong": [
            "translation evaluation", "mt evaluation", "quality estimation",
            "translation quality assessment", " comet", " bleu", " mqm",
            "reference-free evaluation", "translation metric",
        ],
        "weak": ["human evaluation", "automatic metric", "error annotation"],
        "exclude": [],
    },
    "agent": {
        "name": "智能体 Agent",
        "strong": [
            "language agent", "llm agent", "multi-agent", "agentic",
            "tool use", "tool learning", "computer use", "gui agent",
            "web agent", "autonomous agent", "agent framework",
        ],
        "weak": ["planning", "tool calling", "function calling", "embodied"],
        "exclude": ["reinforcement learning agent for games"],
    },
}

FIELD_ORDER = ["mt", "st", "asr", "tts", "cv", "ocr", "llm", "mteval", "agent"]
