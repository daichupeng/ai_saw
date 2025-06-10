from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple
import random
from player import Player, PlayerAction

# TODO: Define proper data structures for game_state and context dictionaries
# - Create TypedDict classes for game_state in handle_negotiation_phase and handle_execution_phase
# - Create TypedDict for context in update_all_opinions
# This will improve type safety and make the expected structure more explicit

class GamePhase(Enum):
    """Enum for game phases."""
    NEGOTIATION = "negotiation"
    EXECUTION = "execution"

class RoundStatus(Enum):
    """Enum for round status."""
    NOT_COMPLETED = "not_completed"
    COMPLETED = "completed"

@dataclass
class Round:
    """Represents a round in the game."""
    number: int
    damage_required: int = 6
    description: str = ""
    status: RoundStatus = RoundStatus.NOT_COMPLETED
    negotiation_attempts: int = 0
    player_sequence: List[str] = field(default_factory=list)
    active_players: List[str] = field(default_factory=list)
    player_actions: Dict[str, PlayerAction] = field(default_factory=dict)
    damage_taken: Dict[str, int] = field(default_factory=dict)

    def reset_player_sequence(self, players: List[str]) -> None:
        """Randomize the player sequence for this round."""
        self.player_sequence = list(players)
        random.shuffle(self.player_sequence)

    def total_damage_offered(self) -> int:
        """Calculate total damage offered in current negotiation."""
        return sum(action.damage_amount or 0 
                  for action in self.player_actions.values() 
                  if action.action_type == "Offer")

    def has_kill_action(self) -> bool:
        """Check if any player chose to kill in this round."""
        return any(action.action_type == "Kill" 
                  for action in self.player_actions.values())

    def get_kill_action(self) -> Optional[Tuple[str, PlayerAction]]:
        """Get the player and action if there was a kill action."""
        for player, action in self.player_actions.items():
            if action.action_type == "Kill":
                return player, action
        return None

class Game:
    """Main game class that manages the game flow."""
    def __init__(self, players: List[Player], description: str = ""):
        self.description = description
        self.players = {player.name: player for player in players}
        self.rounds: List[Round] = []
        self.current_round: Optional[Round] = None
        self.phase = GamePhase.NEGOTIATION
        self.active_players = list(self.players.keys())

    def start_new_round(self) -> None:
        """Start a new round."""
        round_num = len(self.rounds) + 1
        self.current_round = Round(
            number=round_num,
            active_players=list(self.active_players)
        )
        self.current_round.reset_player_sequence(self.active_players)
        self.rounds.append(self.current_round)
        self.phase = GamePhase.NEGOTIATION
        print(f"\n🎲 Starting Round {round_num}")

    def handle_negotiation_phase(self) -> bool:
        """
        Handle one complete negotiation phase.
        Returns True if negotiation was successful, False otherwise.
        """
        if not self.current_round:
            raise ValueError("No active round")

        print("\n💬 Starting Negotiation Phase")
        self.current_round.negotiation_attempts += 1
        self.current_round.player_actions.clear()
        
        # Get actions from each player in sequence
        for player_name in self.current_round.player_sequence:
            player = self.players[player_name]
            
            # Create game state for player decision
            game_state = {
                "round_number": self.current_round.number,
                "damage_required": self.current_round.damage_required,
                "negotiation_attempt": self.current_round.negotiation_attempts,
                "player_states": {
                    name: {"hp": self.players[name].hp}
                    for name in self.active_players
                },
                "previous_actions": [
                    {
                        "player": name,
                        "action_type": action.action_type,
                        "damage_amount": action.damage_amount,
                        "target": action.target_player,
                        "speech": action.speech
                    }
                    for name, action in self.current_round.player_actions.items()
                ]
            }
            
            # Get player's action
            action = player.negotiate(game_state)
            self.current_round.player_actions[player_name] = action
            
            # Check for kill action
            if action.action_type == "Kill":
                return self.handle_kill_action(player_name, action)
        
        # Check if enough damage was offered
        if self.current_round.total_damage_offered() >= self.current_round.damage_required:
            self.phase = GamePhase.EXECUTION
            return True
        
        # Handle failed negotiation
        if self.current_round.negotiation_attempts >= 3:
            self.apply_negotiation_failure_damage()
            self.current_round.negotiation_attempts = 0
            
        return False

    def handle_kill_action(self, killer_name: str, action: PlayerAction) -> bool:
        """Handle a kill action during negotiation."""
        if not action.target_player:
            raise ValueError("Kill action must have a target")
            
        killer = self.players[killer_name]
        target = self.players[action.target_player]
        
        # Validate kill conditions
        if killer.hp <= target.hp:
            print(f"❌ Kill action failed: {killer_name} cannot kill {action.target_player} (invalid HP condition)")
            return False
            
        # Apply damage
        killer.hp -= 1
        target.hp = 0
        
        # Update opinions and handle elimination
        self.update_all_opinions(action.target_player, "killed", {
            "killer": killer_name,
            "round": self.current_round.number
        })
        self.eliminate_player(action.target_player)
        
        # Complete round
        self.current_round.status = RoundStatus.COMPLETED
        return True

    def handle_execution_phase(self) -> None:
        """Handle the execution phase."""
        if not self.current_round:
            raise ValueError("No active round")

        print("\n⚔️ Starting Execution Phase")
        
        # Reset player sequence for execution phase
        self.current_round.reset_player_sequence([
            player for player in self.current_round.player_sequence
            if self.current_round.player_actions[player].action_type == "Offer"
        ])
        
        successful_backstabs = []
        
        # Handle backstab attempts
        for player_name in self.current_round.player_sequence:
            player = self.players[player_name]
            action = self.current_round.player_actions[player_name]
            
            # Create game state for backstab decision
            game_state = {
                "round": self.current_round.number,
                "your_damage": action.damage_amount,
                "player_damages": {
                    name: self.current_round.player_actions[name].damage_amount or 0
                    for name in self.active_players
                    if self.current_round.player_actions[name].action_type == "Offer"
                }
            }
            
            # Get backstab decision
            will_backstab, thinking = player.decide_backstab(game_state)
            
            if will_backstab:
                success = random.random() < player.get_current_backstab_chance()
                if success:
                    successful_backstabs.append(player_name)
                    player.backstab_attempts += 1
                    print(f"🗡️ {player_name}'s backstab succeeded!")
                else:
                    print(f"❌ {player_name}'s backstab failed!")
                    self.apply_damage(player_name, action.damage_amount or 0)
            else:
                print(f"✋ {player_name} chose not to backstab")
                self.apply_damage(player_name, action.damage_amount or 0)
        
        # Handle successful backstabs
        if successful_backstabs:
            remaining_players = [
                name for name in self.active_players
                if name not in successful_backstabs and 
                self.current_round.player_actions[name].action_type == "Offer"
            ]
            
            if remaining_players:
                # Distribute damage from successful backstabbers
                total_damage = sum(
                    self.current_round.player_actions[name].damage_amount or 0
                    for name in successful_backstabs
                )
                damage_per_player = total_damage / len(remaining_players)
                
                for player_name in remaining_players:
                    self.apply_damage(player_name, damage_per_player)
            else:
                # If everyone backstabbed successfully, last player takes all damage
                last_player = successful_backstabs[-1]
                total_damage = sum(
                    self.current_round.player_actions[name].damage_amount or 0
                    for name in successful_backstabs
                )
                self.apply_damage(last_player, total_damage)
        
        # Complete round
        self.current_round.status = RoundStatus.COMPLETED

    def apply_damage(self, player_name: str, damage: float) -> None:
        """Apply damage to a player."""
        player = self.players[player_name]
        player.hp -= damage
        self.current_round.damage_taken[player_name] = damage
        
        if player.hp <= 0:
            player.hp = 0
            self.eliminate_player(player_name)

    def apply_negotiation_failure_damage(self) -> None:
        """Apply damage to all players after 3 failed negotiations."""
        print("\n⚡ Three failed negotiations - applying 1 damage to all players")
        for player_name in self.active_players:
            self.apply_damage(player_name, 1)

    def eliminate_player(self, player_name: str) -> None:
        """Handle player elimination."""
        if player_name in self.active_players:
            self.active_players.remove(player_name)
            print(f"\n💀 {player_name} has been eliminated!")

    def update_all_opinions(self, target_player: str, action_type: str, context: Dict) -> None:
        """Update all players' opinions about an action."""
        for player_name in self.active_players:
            if player_name != target_player:
                self.players[player_name].update_opinion(target_player, action_type, context)

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return len(self.active_players) <= 1

    def get_winner(self) -> Optional[str]:
        """Get the winner of the game if there is one."""
        return self.active_players[0] if len(self.active_players) == 1 else None

    def play(self) -> str:
        """
        Play the game until completion.
        Returns the name of the winner.
        """
        while not self.is_game_over():
            self.start_new_round()
            
            # Negotiation phase
            while self.phase == GamePhase.NEGOTIATION:
                success = self.handle_negotiation_phase()
                if success:
                    break
                    
            # Check if round was completed by a kill action
            if self.current_round.status == RoundStatus.COMPLETED:
                continue
                
            # Execution phase
            if self.phase == GamePhase.EXECUTION:
                self.handle_execution_phase()
        
        winner = self.get_winner()
        if winner:
            print(f"\n👑 Game Over! {winner} wins!")
            return winner
        else:
            print("\n🎮 Game Over! No winner!")
            return "No winner"
