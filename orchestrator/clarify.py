"""
Lightweight clarification gate — runs BEFORE main routing in /chat.

LLM cost guarantee:
  - _is_vague() is pure rules, 0 LLM calls.
  - _generate_question() is called ONLY when _is_vague() is True → 1 LLM call.
  - Clear/complete input → 0 LLM calls total.
  - Maximum 1 LLM call per clarification trigger.

Tuneable surface:
  - CLARIFY_MIN_LEN          — char threshold for "definitely too short"
  - CLARIFY_MAX_NO_VERB_LEN  — if no action verb detected and shorter than this → vague
  - ACTION_RE / QUESTION_STARTERS — widen or narrow trigger sensitivity
  - merge_task()             — how original + answer are combined for re-routing
"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import litellm  # top-level import so tests can patch orchestrator.clarify.litellm

from dotenv import load_dotenv
load_dotenv()

# ── tuneable thresholds ───────────────────────────────────────────────────────

CLARIFY_MIN_LEN = 10          # chars: always vague if shorter
CLARIFY_MAX_NO_VERB_LEN = 20  # chars: vague if shorter AND no action verb
CLARIFY_MODEL = "agnes"       # fast/cheap model for question generation

# ── detection patterns ────────────────────────────────────────────────────────

# Question starters: these indicate the user knows what they want → not vague
_QUESTION_STARTERS = (
    "什麼", "為什麼", "如何", "怎麼", "哪", "是否", "有沒有", "請問",
    "what", "why", "how", "where", "when", "who", "is ", "are ",
    "can ", "does ", "do ", "explain", "describe", "tell me",
)

# Chinese question particles anywhere in the sentence indicate a question
_CHINESE_QUESTION_PARTICLES = re.compile(
    r'(什麼|為什麼|如何|怎麼|哪[裡個]|是否|有沒有|'
    r'嗎$|呢$|吧$|'
    r'多[長大重少久高寬深]|'      # 多長、多大、多重、多少、多久…
    r'誰|幾[個次天月年]|什麼時候)'
)

# Action verbs: presence means the user has a concrete intent → not vague
_ACTION_RE = re.compile(
    # Chinese action verbs (character-level, no word boundary needed)
    r'(做|建立|建|測試|測|寫|改|加入|加|設計|實作|實現|生成|幫|分析|查詢|查|找|列出|列'
    r'|計算|算|解決|解|執行|跑|產生|整理|比較|評估|修復|修|優化|翻譯|翻|轉換|轉'
    r'|抓取|抓|取得|取|刪除|刪|更新|驗證|驗|示範|展示|說明|解釋|說|講|問'
    # English action verbs (word boundary)
    r'|\bmake\b|\bbuild\b|\btest\b|\bwrite\b|\bcreate\b|\bimplement\b'
    r'|\badd\b|\bfix\b|\banalyze\b|\bexplain\b|\bfind\b|\blist\b'
    r'|\bcalculate\b|\bsolve\b|\brun\b|\bgenerate\b|\borganize\b'
    r'|\bcompare\b|\bevaluate\b|\boptimize\b|\btranslate\b|\bconvert\b'
    r'|\bfetch\b|\bget\b|\bdelete\b|\bupdate\b|\bvalidate\b|\bcheck\b'
    r'|\bshow\b|\bdisplay\b|\bformat\b|\bparse\b|\bextract\b'
    r'|\bsummarize\b|\bdescribe\b|\brefactor\b)',
    re.IGNORECASE,
)


# ── core functions ────────────────────────────────────────────────────────────

def _is_vague(text: str) -> bool:
    """
    Pure rules, 0 LLM calls.
    True → input needs clarification before routing.
    Lean toward True (宜寬不宜緊).
    """
    t = text.strip()
    lo = t.lower()

    # Questions are clear by nature — don't block them
    if t.endswith("?") or t.endswith("？"):
        return False
    if any(lo.startswith(q) for q in _QUESTION_STARTERS):
        return False
    if _CHINESE_QUESTION_PARTICLES.search(t):
        return False

    # Has a concrete action verb → likely complete enough (check before min length
    # so short-but-complete commands like "說你好" aren't wrongly flagged)
    if _ACTION_RE.search(t):
        return False

    # Hard minimum length — only now that verbs & questions have been ruled out
    if len(t) < CLARIFY_MIN_LEN:
        return True

    # Single word (no whitespace, no verb already matched above)
    if not re.search(r'\s', t):
        return True

    # Short sentence with no action → still vague
    if len(t) < CLARIFY_MAX_NO_VERB_LEN:
        return True

    return False


def _generate_question(text: str) -> str:
    """
    1 LLM call. Returns a context-aware one-sentence clarifying question in
    the same language as the input.
    Falls back to a generic template on error — never raises.
    """
    import litellm
    from orchestrator.model_registry import resolve as _resolve

    prompt = (
        "The user sent an incomplete or ambiguous task description: "
        f"「{text}」\n\n"
        "Ask ONE short, specific clarifying question (1 sentence) to understand "
        "what they want. Reply in the same language as the input. "
        "Do NOT add explanations or multiple questions. Just the question."
    )
    try:
        params = _resolve(CLARIFY_MODEL)
        resp = litellm.completion(  # patched in tests as orchestrator.clarify.litellm.completion
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0.3,
            **params,
        )
        return resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception:
        # Fallback template — still useful even without context
        return f"「{text}」能再說清楚一點嗎？你想要我做什麼？"


def needs_clarification(text: str) -> tuple[bool, str]:
    """
    Entry point for the clarification gate.

    Returns:
        (False, "")          — input is clear enough, proceed to routing
        (True,  "question")  — input is vague; question is what to show the user

    LLM cost: 0 if clear, 1 if vague (question generation only).
    """
    if not _is_vague(text.strip()):
        return False, ""
    question = _generate_question(text.strip())
    return True, question


def merge_task(original: str, answer: str) -> str:
    """
    Combine original vague task + user's clarification answer into a single
    natural task description suitable for the router.

    Rules (0 LLM):
    1. If answer already contains the original keyword (first 3 chars), use answer only.
    2. Otherwise prepend original to answer.

    Adjust this function to tune merge behaviour independently.
    """
    orig = original.strip()
    ans = answer.strip()
    if not ans:
        return orig
    # Answer subsumes original keyword → use answer as-is
    # Use first char as key so "測試" (2-char) matches answer starting with "測"
    orig_key = orig[0].lower() if orig else ""
    if orig_key and len(ans) > len(orig) and ans.lower().startswith(orig_key):
        return ans
    # Prepend original context
    sep = " " if not orig.endswith(" ") else ""
    return f"{orig}{sep}{ans}"
