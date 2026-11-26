"""本地离线词典接口：全站划词/点词查释义 + 词典就绪状态。"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Query, Request, Response

import config
import services.dictionary as dictionary

router = APIRouter(tags=["dict"])


@router.get("/dict/status")
def dict_status():
    stat = dictionary.status()
    core_exists = config.CORE_DICT_PATH.exists()
    stat["coreReady"] = core_exists
    stat["coreSize"] = config.CORE_DICT_PATH.stat().st_size if core_exists else 0
    return stat


@router.get("/dict/bundle")
def dict_bundle(request: Request):
    """下发预压缩的核心离线词库（约 2MB gzip），供前端缓存到浏览器 IndexedDB 实现 0ms 离线查词。"""
    path = config.CORE_DICT_PATH
    if not path.exists():
        raise HTTPException(404, "核心词库包尚未生成（请运行 tools/build_core_dict.py）")
    st = path.stat()
    etag = f'"{hashlib.md5(f"{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    raw_gz = path.read_bytes()
    accept_enc = request.headers.get("accept-encoding", "")
    if "gzip" in accept_enc.lower():
        return Response(
            content=raw_gz,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Encoding": "gzip",
                "ETag": etag,
                "Cache-Control": "public, max-age=86400",
            },
        )
    import gzip

    return Response(
        content=gzip.decompress(raw_gz),
        media_type="application/json; charset=utf-8",
        headers={"ETag": etag, "Cache-Control": "public, max-age=86400"},
    )


@router.get("/dict/shard/{letter}")
def dict_shard(letter: str, request: Request):
    """按首字母下发 R2/本地静态词典分片（用于 6.6 万核心库未命中的生僻词）。"""
    clean = letter.lower()
    if clean != "other" and (len(clean) != 1 or not ("a" <= clean <= "z")):
        raise HTTPException(400, "非法分片名")
    path = config.DATA_DIR / "dict_shards" / f"{clean}.json.gz"
    if not path.exists():
        raise HTTPException(404, "词典分片尚未生成（请运行 tools/build_dict_shards.py）")
    raw_gz = path.read_bytes()
    accept_enc = request.headers.get("accept-encoding", "")
    if "gzip" in accept_enc.lower():
        return Response(
            content=raw_gz,
            media_type="application/json; charset=utf-8",
            headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=604800"},
        )
    import gzip

    return Response(
        content=gzip.decompress(raw_gz),
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/dict/lookup")
def dict_lookup(
    q: str = Query(default="", max_length=200, description="待查单词或短语"),
    packId: str = Query(default="", max_length=120, description="可选：优先叠加该文章包的语境词表"),
):
    return dictionary.lookup(q, pack_id=packId)
