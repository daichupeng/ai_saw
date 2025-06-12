# AI Saw

## Updates
v0.5 
Added a self-intro mechanism, to allow players to do self introduction to form initial opinions.


v 0.4
- Added a Lynch mechanism, to allow multiple players to vote another player out to pass the round
- Added a final mindset mechanism to produce the final mindset of a dying player.


v 0.3
- Added dynamic scenario generation for each round
- Enhanced mindset tracking with improved response parsing
- Added test script for mindset updates
- Improved game state logging and debugging output

v 0.2
Added mindset mechanism to track the mindset changes of players. Added story backgrounds of each round.

v 0.1
Prototype

## Description
This is a game inspired by the movie Saw.

This game involves multiple AI agent (aka player) in a multi-round setup. Each of the players' purpose is to survive throught the round with minimum damage possible.

5 players play the game. Each player starts with 7 amount of health points (HP). Each round can be passed by 1 of the following ways:
- Cause total 6 amount of HP of damage to 1 or more player
- 1 or more players loses all of their HP

At each round, the game generates a unique scenario and process that sets the context for player decisions.

### Phase 1: negotiation.
During the negotiation phase, each player produces a speech and an action based on their current mindset and the round's scenario. The sequence is randomly determined. The speech can be used to persuade, beg for mercy, offer to collaborate, etc, but has no impact to the game proceeding itself. The action is 1 of the following:
- Offer: Offer to take a certain amount of HP damage
- Refuse: Refuse to take any damage
- Kill: Take 2 HP damage, and force another player with less HP points than the acting player to die and pass the round.
- Lynch: Invite 1 or more user to vote a player out by taking 1 HP damage each

If one of the players decide to kill, the negotiation phase ends and all the remaining players advance to the next round.

If no players decide to kill after all players have made their choice, the system compares the sum of all the offered HP points to the HP points required to pass the round. If it's not sufficient, the negotiation starts over.

Every 3 failed negotiation phases in a round will result in 1 HP damage to each of the surviving players. If any player dies due to the failed negotiations, the round is NOT passed.

### Phase 2: execution.
When the players have agreed to offer sufficient HP, the game enters the sacrifice stage, where the players who offer HP will take turns to decide if they will backstab the rest. The sequence is determined randomly. 

If a player decides to backstab, there is 30% of chance the backstab succeeds, and they do not need to take the damage. The damange that is supposed to be taken will be shared equally among the other players. Regardless of whether the backstab succeeds, the chance of success of their next backstab decreases by 5%.

If all the players successfully backstab, the last remaining player is forced to take all the damage for this round.


## Game design

### Player
Each player has the following attributes:
- Name
- Model
- Background prompt
- Mindset (tracks psychological state)
- HP (starts with 7)
- Opinions of other players
- Backstab success rate (starts at 30%)

Each player has the following actions:
- Negotiation, which outputs:
  - Current mindset
  - Thinking process
  - Speech content
  - Action (Offer/Refuse/Kill)
- Update mindset based on game events
- Update opinion about other players
- Execution decision (backstab or not)

### Game
The game contains a list of rounds and a description to give a story to the game. Each round features a unique scenario and process that influences player decisions.

#### Round
A round has the following attributes:
- Damage required (default 6)
- Scenario (unique situation for the round)
- Process (how the scenario plays out)
- Status (Not Completed/Completed)
- Current negotiation attempt count
- Player action sequence (randomly determined each phase)
- Active players list

#### Game actions
- Story generation:
  - Generate unique scenarios for each round
  - Create detailed process descriptions
  - Update player mindsets based on scenarios

- Phase management:
  - Switch between negotiation and execution phases
  - Determine random player sequence for each phase
  - Track negotiation attempts (apply damage after 3 failures)

- Round validation:
  - Check for sufficient damage offers
  - Process immediate round completion on Kill action
  - Validate player death conditions
  - Track round completion status

- Damage management:
  - Apply negotiation failure damage (-1 HP to all players)
  - Process backstab attempts:
    - Calculate success chance (30% - 5% per previous attempt)
    - Distribute damage on successful backstab
    - Force remaining damage to last player if all backstab
  - Apply direct damage from offers
  - Handle player death events

- Player management:
  - Track active players and their mindsets
  - Update player opinions and psychological states
  - Manage player turn order
  - Handle player elimination

## Game Records
The game maintains detailed records of each session, including:
- Initial player states and backgrounds
- Round scenarios and processes
- Player mindset changes
- Negotiation attempts and outcomes
- Execution phase decisions
- Final game statistics