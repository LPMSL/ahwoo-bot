"""
session_handler.py — Redis 對話 session 持久化
使用 Upstash Redis REST API，重啟後對話歷史與輪數不會消失
"""

import json
import logging
import os
from upstash_redis.asyncio import Redis

logger = logging.getLogger(__name__)

# TTL：對話 session 保留 24 小時（秒）
SESSION_TTL = 86400
MAX_HISTORY = 40  # 最多保留 40 則訊息（20 輪）

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(
            url=os.environ["UPSTASH_REDIS_REST_URL"],
            token=os.environ["UPSTASH_REDIS_REST_TOKEN"],
        )
    return _redis


async def get_turns(user_id: str) -> int:
    """取得該用戶目前對話輪數"""
    try:
        val = await _get_redis().get(f"turns:{user_id}")
        return int(val) if val else 0
    except Exception as e:
        logger.error(f"Redis get_turns 失敗: {e}")
        return 0


async def increment_turns(user_id: str) -> int:
    """輪數 +1，回傳新值，並重設 TTL"""
    try:
        r = _get_redis()
        new_val = await r.incr(f"turns:{user_id}")
        await r.expire(f"turns:{user_id}", SESSION_TTL)
        return new_val
    except Exception as e:
        logger.error(f"Redis increment_turns 失敗: {e}")
        return 1


async def get_history(user_id: str) -> list[dict]:
    """取得對話歷史"""
    try:
        raw = await _get_redis().get(f"history:{user_id}")
        return json.loads(raw) if raw else []
    except Exception as e:
        logger.error(f"Redis get_history 失敗: {e}")
        return []


async def append_history(user_id: str, user_msg: str, bot_reply: str) -> None:
    """新增一輪對話到歷史，並修剪到 MAX_HISTORY，重設 TTL"""
    try:
        r = _get_redis()
        history = await get_history(user_id)
        history.append({"role": "user",      "content": user_msg})
        history.append({"role": "assistant", "content": bot_reply})
        # 只保留最近 MAX_HISTORY 則
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        await r.set(f"history:{user_id}", json.dumps(history, ensure_ascii=False), ex=SESSION_TTL)
    except Exception as e:
        logger.error(f"Redis append_history 失敗: {e}")
