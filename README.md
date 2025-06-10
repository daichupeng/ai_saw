# AI Saw

v 0.1
## Description
This is a game inspired by the movie Saw.

This game involves multiple AI agent (aka player) in a multi-round setup. Each of the players' purpose is to survive throught the round with minimum damage possible.

Each player starts with X amount of health points (HP). Each round can be passed by 1 of the following ways:
- Cause total Y amount of HP of damage to 1 or more player
- 1 or more players loses all of their HP

At each round, there are 2 phases:

#Phase 1: negotiation.
During the negotiation phase, each player produces a speech and an action. The sequence is randomly determined. The speech can be used to persuade, beg for mercy, offer to collaborate, etc, but has no impact to the game proceeding itself. The action is 1 of the following:
- Offer: Offer to take a certain amount of HP damage
- Refuse: Refuse to take any damage
- Kill: Take 1 HP damage, and force another player with less HP points than the acting player to die and pass the round.

If one of the players decide to kill, the negotiation phase ends and all the remaining players advance to the next round.

If no players decide to kill after all players have made their choice, the system compares the sum of all the offered HP points to the HP points required to pass the round. If it's not sufficient, the negotiation starts over.

Every 3 failed negotiation phases will result in 1 HP damage to each of the surviving players.

#Phase 2: sacrifice.
When the players have agreed to offer sufficient HP, the game enters the sacrifice stage, where the players who offer HP will take turns to decide if they will backstab the rest. The sequence is determined randomly. 

If a player decides to backstab, there is a x% of chance the backstab succeeds, and they do not need to take the damage. The damange that is supposed to be taken will be shared equally among the other players. Regardless of whether the backstab succeeds, the chance of success of their next backstab increases by y%.

If all the players successfully backstab, the last remaining player is forced to take all the damage for this round.


## 