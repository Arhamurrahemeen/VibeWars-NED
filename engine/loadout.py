from . import config

KITS = {
    "KIT_RAILGUN": "RAILGUN",
    "KIT_MEDPACK": "MEDPACK",
    "KIT_SMOKE": "SMOKE",
    "KIT_RADAR": "RADAR",
}

def shop_offer(credits, map_index=0, placements=()):
    return {
        "credits": credits,
        "prices": dict(config.SHOP),
        "roles": list(config.ROLES),
        "map": map_index + 1,
        "your_placements": list(placements),
        "credit_cap": config.CREDIT_CAP,
    }

def normalize_buy(purchase, credits, default_role=None):
    role = default_role if default_role in config.ROLES else None
    if purchase is None:
        return role, [], None
    if not isinstance(purchase, dict):
        return role, [], "buy() must return a dict"
    asked_role = purchase.get("role", role)
    if asked_role is None or asked_role in config.ROLES:
        role = asked_role
    else:
        return role, [], f"unknown role {asked_role!r}"
    items = purchase.get("items", [])
    if not isinstance(items, (list, tuple)) or not all(isinstance(i, str) for i in items):
        return role, [], "items must be a list of item names"
    if len(set(items)) != len(items):
        return role, [], "each item can be bought only once"
    unknown = [i for i in items if i not in config.SHOP]
    if unknown:
        return role, [], f"unknown item(s) {unknown}"
    kits = [i for i in items if i in KITS]
    if len(kits) > 1:
        return role, [], "only one KIT_ item (one item slot)"
    cost = sum(config.SHOP[i] for i in items)
    if cost > credits:
        return role, [], f"costs {cost}, only {credits} credits"
    return role, sorted(items), None

def apply_loadout(bot, role, items):
    bot.role = role
    bot.loadout = list(items)
    if role == "RUNNER":
        bot.max_hp -= config.RUNNER_HP_PENALTY
        bot.cooldown_turns -= config.RUNNER_COOLDOWN_BONUS
    if role == "HAULER":
        bot.cargo_capacity += config.HAULER_EXTRA_CARGO
    if role == "WARDEN":
        bot.cargo_capacity -= config.WARDEN_CARGO_PENALTY
    for item in items:
        if item == "ARMOR":
            bot.max_hp += config.ARMOR_HP
        elif item == "POCKETS":
            bot.cargo_capacity += 1
        elif item == "QUICK_RESPAWN":
            bot.respawn_delay -= 1
        elif item == "OVERCLOCK":
            bot.cooldown_turns -= config.OVERCLOCK_TURNS
        elif item == "SCOPE":
            bot.vision_bonus += 1
        elif item in KITS:
            bot.item = KITS[item]
    bot.cooldown_turns = max(config.MIN_COOLDOWN_TURNS, bot.cooldown_turns)
    bot.hp = bot.max_hp

def spend(items):
    return sum(config.SHOP[i] for i in items)

def income(position, loss_streak):
    bonus = config.CREDIT_LOSS_BONUS[min(position, len(config.CREDIT_LOSS_BONUS) - 1)]
    streak = min(loss_streak * config.CREDIT_STREAK_BONUS, config.CREDIT_STREAK_CAP)
    return config.CREDIT_BASE_INCOME + bonus + streak
