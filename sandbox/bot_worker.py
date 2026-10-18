import contextlib
import importlib
import json
import sys
from dataclasses import asdict

from vibe_sdk import Bot
from engine.actions import Action
from engine import ACTION_PROTOCOL_VERSION
from engine import config

def _load(module_name, class_name, bot_id):
    with contextlib.redirect_stdout(sys.stderr):
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        if not isinstance(cls, type) or not issubclass(cls, Bot):
            raise TypeError(f"{class_name} must subclass vibe_sdk.Bot")
        ability = getattr(cls, "ABILITY", None)
        if ability is not None and ability not in config.ABILITIES:
            raise ValueError(f"unknown ABILITY {ability!r}")
        bot = cls(bot_id)
        if not callable(getattr(bot, "decide", None)):
            raise TypeError("bot must implement decide(view)")
    return bot, ability

def _metadata(module_name, class_name, ability, role=None):
    return {
        "module": module_name,
        "class": class_name,
        "ability": ability,
        "role": role if role in config.ROLES else None,
        "action_protocol_version": ACTION_PROTOCOL_VERSION,
    }

def _emit(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)

def _sanitize_buy(purchase):
    if not isinstance(purchase, dict):
        return None
    role = purchase.get("role")
    items = purchase.get("items", [])
    if role is not None and not isinstance(role, str):
        return None
    if not isinstance(items, (list, tuple)) or not all(isinstance(i, str) for i in items):
        return None
    return {"role": role, "items": [str(i)[:32] for i in list(items)[:16]]}

def describe(module_name, class_name, bot_id):
    bot, ability = _load(module_name, class_name, bot_id)
    _emit({"status": "READY", "metadata": _metadata(
        module_name, class_name, ability, getattr(bot, "ROLE", None),
    )})

def serve(module_name, class_name, bot_id):
    bot, ability = _load(module_name, class_name, bot_id)
    _emit({"status": "READY", "metadata": _metadata(
        module_name, class_name, ability, getattr(bot, "ROLE", None),
    )})
    for line in sys.stdin:
        try:
            view = json.loads(line)
        except ValueError:
            _emit({"status": "CRASH", "detail": "malformed request"})
            return 1
        if isinstance(view, dict) and "__buy__" in view:
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    purchase = bot.buy(view["__buy__"])
                _emit({"status": "OK", "buy": _sanitize_buy(purchase)})
            except (Exception, SystemExit) as exc:
                _emit({"status": "BUY_FAILED", "detail": (str(exc) or type(exc).__name__)[:200]})
            continue
        try:
            with contextlib.redirect_stdout(sys.stderr):
                action = bot.decide(view)
            if action is None:
                _emit({"status": "NO_ACTION"})
            elif type(action) is not Action:
                _emit({"status": "INVALID_OUTPUT", "detail": repr(action)[:200]})
            else:
                _emit({"status": "OK", "action": asdict(action)})
        except (Exception, SystemExit) as exc:
            detail = str(exc) or type(exc).__name__
            _emit({"status": "CRASH", "detail": detail[:300]})
            return 1
    return 0

def main():
    if len(sys.argv) != 5 or sys.argv[1] not in ("--describe", "--serve"):
        raise SystemExit("usage: bot_worker (--describe|--serve) MODULE CLASS BOT_ID")
    mode, module_name, class_name, bot_id = sys.argv[1:]
    if mode == "--describe":
        describe(module_name, class_name, bot_id)
        return 0
    return serve(module_name, class_name, bot_id)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
