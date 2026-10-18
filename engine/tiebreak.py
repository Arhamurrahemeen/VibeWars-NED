def _sort_key(bot):
    return (
        -bot.score,
        -bot.kills,
        bot.deaths,
        -bot.banked_value,
        -bot.resources_collected,
        bot.id,
    )

def rank_all(state):
    return [b.id for b in sorted(state.bots.values(), key=_sort_key)]

def determine_winner(state):
    return rank_all(state)[0]
