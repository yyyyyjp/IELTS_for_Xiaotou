"""间隔复习调度（SM-2 的简化版）。

不做花哨的自适应：四个档位，间隔按 ease 增长，答错 10 分钟后再来。
复习算法的收益主要来自「每天清空到期队列」这个习惯，不来自参数微调。
"""
from __future__ import annotations

DAY = 86400
RELEARN_SECONDS = 600
MIN_EASE = 1.3
MAX_EASE = 3.0
MAX_INTERVAL = 365.0

GRADES = ("again", "hard", "good", "easy")


def review(state: dict, grade: str, now: int) -> dict:
    """返回更新后的调度字段。state 需含 ease/interval_days/reps/lapses。"""
    if grade not in GRADES:
        raise ValueError(f"未知评分档位：{grade}")

    ease = float(state.get("ease") or 2.4)
    interval = float(state.get("interval_days") or 0)
    reps = int(state.get("reps") or 0)
    lapses = int(state.get("lapses") or 0)

    if grade == "again":
        lapses += 1
        ease = max(MIN_EASE, ease - 0.2)
        interval = 0.0
        relearn = True
        new_state = "learning"
    elif grade == "hard":
        ease = max(MIN_EASE, ease - 0.05)
        interval = max(1.0, interval * 1.2)
        relearn = False
        new_state = "review"
    elif grade == "good":
        if reps == 0:
            interval = 1.0
        elif reps == 1:
            interval = 3.0
        else:
            interval = max(1.0, interval * ease)
        relearn = False
        new_state = "review"
    else:  # easy
        if reps == 0:
            interval = 3.0
        else:
            interval = max(3.0, interval * ease * 1.3)
        ease = min(MAX_EASE, ease + 0.1)
        relearn = False
        new_state = "review"

    interval = min(interval, MAX_INTERVAL)
    due_at = now + (RELEARN_SECONDS if relearn else int(round(interval * DAY)))
    return {
        "state": new_state,
        "ease": round(ease, 3),
        "interval_days": round(interval, 2),
        "reps": reps + 1,
        "lapses": lapses,
        "due_at": due_at,
        "last_reviewed_at": now,
        "next_interval": interval,
    }
