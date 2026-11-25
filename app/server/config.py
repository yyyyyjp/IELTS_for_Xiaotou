"""运行期配置：路径与默认参数集中在这里，其他模块不再各自拼路径。

路径均可通过环境变量覆盖，便于测试与部署：
  XIAOTOU_DATA_DIR     数据库与音频缓存目录（默认 server/data）
  XIAOTOU_CONTENT_DIR  内容包目录（默认 server/content）
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.getenv("XIAOTOU_DATA_DIR") or BASE_DIR / "data")
CONTENT_DIR = Path(os.getenv("XIAOTOU_CONTENT_DIR") or BASE_DIR / "content")
AUDIO_DIR = DATA_DIR / "audio"
PACK_DIR = CONTENT_DIR / "packs"
DB_PATH = DATA_DIR / "app.db"
DICT_DB_PATH = Path(os.getenv("XIAOTOU_DICT_DB") or DATA_DIR / "ecdict.db")
CORE_DICT_PATH = Path(os.getenv("XIAOTOU_CORE_DICT") or DATA_DIR / "core_dict.json.gz")
SYNC_TOKEN = os.getenv("XIAOTOU_SYNC_TOKEN", "").strip()
WEB_DIST = BASE_DIR.parent / "web" / "dist"

DEFAULT_VOICE = "en-GB-SoniaNeural"
DEFAULT_RATE = "-5%"          # 0.95 倍速，约等于雅思听力语速
TTS_CONCURRENCY = 4
TTS_MAX_CHARS = 600           # 单条合成上限，防止误传整篇文章
TTS_MAX_BATCH = 200

# 开发模式前端地址；生产同端口托管，不需要跨域
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

for _d in (DATA_DIR, AUDIO_DIR, PACK_DIR):
    _d.mkdir(parents=True, exist_ok=True)
