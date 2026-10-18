class Bot:
    """
    Participant bots subclass this and implement decide().

    ABILITY is set once as a class attribute -- it's the bot's fixed
    special ability for the whole match, not something chosen per-turn.
    One of: "DASH", "SHIELD", "BLINK", "BOMB", "SHOVE", or None.

    ROLE is the default role (HUNTER, HAULER, RUNNER, WARDEN or None). It can
    be changed per map by returning a role from buy().
    """
    ABILITY = None
    ROLE = None

    def __init__(self, bot_id):
        self.id = bot_id

    def buy(self, shop: dict):
        """Called once before every map, before decide().

        ``shop`` holds your credits, the prices, the roles, which map of the
        series this is and your own previous placements -- nothing about any
        rival. Return ``{"role": "HUNTER", "items": ["ARMOR", ...]}``, or None
        to keep ROLE and buy nothing. Anything invalid or unaffordable buys
        nothing; it is never an error.
        """
        return None

    def decide(self, view: dict):
        """
        view is your fog-of-war-limited state (docs/BOT_SDK_CONTRACT.md).
        Must return a vibe_sdk Action. Returning None, raising or running
        past the 200 ms deadline loses the turn (and fails conformance).
        """
        raise NotImplementedError
