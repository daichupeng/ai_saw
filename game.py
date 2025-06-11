from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple, Set
import random
from player import Player, PlayerAction
from pathlib import Path
import os
import yaml
from datetime import datetime


game_time = datetime.now().strftime("%H:%M:%S")

def log(message: str, indent: int = 0, request_id: Optional[str] = None,):
            # Create game log file
    record_dir = Path("game_record")
    record_dir.mkdir(exist_ok=True)
    
    # Create log file in game_record directory
    log_file = record_dir / f"game_record_{game_time}.txt"
    timestamp = datetime.now().strftime("%H:%M:%S")

    """Helper function to write to log file with timestamp."""
    with open(log_file, 'a') as f:
        log_line = f"[{timestamp}] {'  ' * indent}{message}"
        if request_id:
            log_line += f" (Request ID: {request_id})"
        f.write(log_line + "\n")

class GamePhase(Enum):
    """Enum for game phases."""
    NEGOTIATION = "negotiation"
    EXECUTION = "execution"

class RoundStatus(Enum):
    """Enum for round status."""
    NOT_COMPLETED = "not_completed"
    COMPLETED = "completed"

class EventType(Enum):
    """Types of events that can occur during the game."""
    OFFER = "offer"
    REFUSE = "refuse"
    KILL = "kill"
    EXECUTION = "execution"
    BACKSTAB_SUCCESS = "backstab_success"
    BACKSTAB_FAIL = "backstab_fail"
    NO_BACKSTAB = "no_backstab"

@dataclass
class Context:
    """Context for opinion updates about player actions."""
    event: EventType
    round_number: int
    acting_player: str
    target_player: Optional[str] = None
    damage_amount: Optional[float] = None
    speech: Optional[str] = None
    successful_backstabbers: Set[str] = field(default_factory=set)
    failed_backstabbers: Set[str] = field(default_factory=set)
    loyal_players: Set[str] = field(default_factory=set)
    total_damage_required: Optional[int] = None
    total_damage_offered: Optional[int] = None
    negotiation_attempt: Optional[int] = None

    def to_dict(self) -> Dict:
        """Convert context to dictionary for LLM consumption."""
        context_dict = {
            "event": self.event.value,
            "round": self.round_number,
            "actor": self.acting_player,
        }
        
        if self.target_player:
            context_dict["target"] = self.target_player
        if self.damage_amount is not None:
            context_dict["damage"] = self.damage_amount
        if self.speech:
            context_dict["speech"] = self.speech
            
        if self.event == EventType.EXECUTION:
            context_dict.update({
                "successful_backstabbers": list(self.successful_backstabbers),
                "failed_backstabbers": list(self.failed_backstabbers),
                "loyal_players": list(self.loyal_players)
            })
            
        if self.event in [EventType.OFFER, EventType.REFUSE]:
            if self.total_damage_required is not None:
                context_dict["damage_required"] = self.total_damage_required
            if self.total_damage_offered is not None:
                context_dict["damage_offered"] = self.total_damage_offered
            if self.negotiation_attempt is not None:
                context_dict["negotiation_attempt"] = self.negotiation_attempt
                
        return context_dict

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
    def __init__(self, players: List[Player], description: str = "", max_rounds: int = 10):
        self.description = description
        self.players = {player.name: player for player in players}
        self.rounds: List[Round] = []
        self.current_round: Optional[Round] = None
        self.phase = GamePhase.NEGOTIATION
        self.active_players = list(self.players.keys())
        self.max_rounds = max_rounds

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
            
            # Log negotiation action with request ID
            log(f"Negotiation Action - Player: {player_name}, Action: {action.action_type}", 2, action.request_id)
            if action.damage_amount:
                log(f"Damage Amount: {action.damage_amount}", 3, action.request_id)
            if action.target_player:
                log(f"Target: {action.target_player}", 3, action.request_id)
            
            
            # Handle kill action
            if action.action_type == "Kill":
                kill_success = self.handle_kill_action(player_name, action)
                if kill_success:
                    return True  # End negotiation if kill was successful
                # If kill failed, continue with next player
                continue
        
            # Create context and update opinions based on action
            context = Context(
                event=EventType.OFFER if action.action_type == "Offer" else EventType.REFUSE,
                round_number=self.current_round.number,
                acting_player=player_name,
                damage_amount=action.damage_amount,
                speech=action.speech,
                total_damage_required=self.current_round.damage_required,
                total_damage_offered=self.current_round.total_damage_offered(),
                negotiation_attempt=self.current_round.negotiation_attempts
            )
            self.update_all_opinions(player_name, context.event.value, context.to_dict())

        # Check if enough damage was offered
        if self.current_round.total_damage_offered() >= self.current_round.damage_required:
            self.phase = GamePhase.EXECUTION
            return True
        
        # Handle failed negotiation
        if self.current_round.negotiation_attempts % 3 == 0:
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
            log(f"❌ Kill action failed: {killer_name} cannot kill {action.target_player} (invalid HP condition)")
            
            # Create context for failed kill attempt
            context = Context(
                event=EventType.KILL,
                round_number=self.current_round.number,
                acting_player=killer_name,
                target_player=action.target_player,
                speech=action.speech
            )
            # Update opinions about the failed kill attempt
            self.update_all_opinions(killer_name, context.event.value, context.to_dict())
            return False
            
        # Apply damage
        killer.hp -= 1
        target.hp = 0
        
        # Create context and update opinions for successful kill
        context = Context(
            event=EventType.KILL,
            round_number=self.current_round.number,
            acting_player=killer_name,
            target_player=action.target_player,
            speech=action.speech
        )
        self.update_all_opinions(action.target_player, context.event.value, context.to_dict())
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
        failed_backstabs = []
        loyal_players = []
        
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
            will_backstab, thinking, request_id = player.decide_backstab(game_state)
            
            # Log backstab decision with request ID
            log(f"Backstab Decision - Player: {player_name}", 2, request_id)
            log(f"Decision: {'Will Backstab' if will_backstab else 'Will Not Backstab'}", 3, request_id)
            
            if will_backstab:
                success = random.random() < player.get_current_backstab_chance()
                if success:
                    successful_backstabs.append(player_name)
                    player.backstab_attempts += 1
                    print(f"🗡️ {player_name}'s backstab succeeded!")
                    log(f"{player_name}'s backstab succeeded!", 2, request_id)
                else:
                    failed_backstabs.append(player_name)
                    print(f"❌ {player_name}'s backstab failed!")
                    log(f"{player_name}'s backstab failed!", 2, request_id)
                    self.apply_damage(player_name, action.damage_amount or 0)
            else:
                loyal_players.append(player_name)
                print(f"✋ {player_name} chose not to backstab")
                log(f"{player_name} chose not to backstab", 2, request_id)
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
        
        # Create context and update opinions about execution phase
        context = Context(
            event=EventType.EXECUTION,
            round_number=self.current_round.number,
            acting_player="system",  # system event affecting all players
            successful_backstabbers=set(successful_backstabs),
            failed_backstabbers=set(failed_backstabs),
            loyal_players=set(loyal_players)
        )
        
        # Update everyone's opinion about the execution phase results
        for player_name in self.active_players:
            self.update_all_opinions(player_name, context.event.value, context.to_dict())
        
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
                observer, subject, opinion, request_id = self.players[player_name].update_opinion(target_player, action_type, context)
                log(f"Opinion Update - Observer: {observer}, Subject: {subject}, Request ID: {request_id}", 2, request_id)

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return len(self.active_players) <= 1 or len(self.rounds) > self.max_rounds

    def get_winner(self) -> Optional[str]:
        """Get the winner of the game if there is one."""
        return self.active_players[0] if len(self.active_players) == 1 else None

    def play(self) -> str:
        """
        Play the game until completion.
        Returns the name of the winner.
        """

        
        
        # Initialize log file with game setup
        log("=== AI SAW GAME RECORD ===")
        log(f"Game Description: {self.description}")
        log("\nInitial Players:")
        for name, player in self.players.items():
            log(f"- {name}:", 1)
            log(f"HP: {player.hp}", 2)
            log(f"Background: {player.background_prompt}", 2)
            log(f"Backstab Success Rate: {player.backstab_success_rate * 100}%", 2)
        log("\n" + "=" * 50 + "\n")

        while not self.is_game_over():
            self.start_new_round()
            log(f"\n🎲 ROUND {len(self.rounds)}")
            log("Active Players:", 1)
            for player_name in self.active_players:
                player = self.players[player_name]
                log(f"- {player_name} (HP: {player.hp})", 2)
            
            # Negotiation phase
            while self.phase == GamePhase.NEGOTIATION:
                log(f"\n💬 NEGOTIATION ATTEMPT {self.current_round.negotiation_attempts + 1}")
                log(f"Damage Required: {self.current_round.damage_required}", 1)
                
                success = self.handle_negotiation_phase()
                
                # Log negotiation results
                total_damage = self.current_round.total_damage_offered()
                log(f"\nNegotiation Results:", 1)
                log(f"Total Damage Offered: {total_damage}/{self.current_round.damage_required}", 2)
                for player_name, action in self.current_round.player_actions.items():
                    log(f"- {player_name}:", 2)
                    log(f"Action: {action.action_type}", 3)
                    if action.damage_amount:
                        log(f"Damage: {action.damage_amount}", 3)
                    if action.target_player:
                        log(f"Target: {action.target_player}", 3)
                    log(f"Speech: {action.speech}", 3)
                
                if not success and self.current_round.negotiation_attempts >= 3:
                    log("\n⚡ NEGOTIATION FAILURE PENALTY", 1)
                    log("All players take 1 damage due to failed negotiations", 2)
                
                if success:
                    log("\n✅ Negotiation Successful - Moving to Execution Phase", 1)
                    break
                else:
                    log("\n❌ Negotiation Failed - Starting Next Attempt", 1)
                    
            # Check if round was completed by a kill action
            if self.current_round.status == RoundStatus.COMPLETED:
                kill_action = self.current_round.get_kill_action()
                if kill_action:
                    killer, action = kill_action
                    log("\n💀 KILL ACTION", 1)
                    log(f"Killer: {killer}", 2)
                    log(f"Target: {action.target_player}", 2)
                    log(f"Reason: {action.speech}", 2)
                continue
                
            # Execution phase
            if self.phase == GamePhase.EXECUTION:
                log("\n⚔️ EXECUTION PHASE")
                
                # Record initial state
                log("Initial State:", 1)
                for name in self.active_players:
                    player = self.players[name]
                    damage = self.current_round.player_actions[name].damage_amount
                    log(f"- {name}: HP={player.hp}, Promised Damage={damage}", 2)
                
                self.handle_execution_phase()
                
                # Record results
                log("\nExecution Results:", 1)
                for name in self.current_round.player_sequence:
                    player = self.players[name]
                    damage_taken = self.current_round.damage_taken.get(name, 0)
                    log(f"- {name}:", 2)
                    log(f"Final HP: {player.hp}", 3)
                    log(f"Damage Taken: {damage_taken}", 3)
                    if name in self.active_players:
                        log("Status: Survived", 3)
                    else:
                        log("Status: Eliminated", 3)
            
            # End of round summary
            log("\n📊 END OF ROUND SUMMARY")
            log("Player Status:", 1)
            for name, player in self.players.items():
                status = "Active" if name in self.active_players else "Eliminated"
                log(f"- {name}:", 2)
                log(f"HP: {player.hp}", 3)
                log(f"Status: {status}", 3)
                log(f"Backstab Attempts: {player.backstab_attempts}", 3)
            log("\n" + "=" * 50 + "\n")
        
        # Game over
        winner = self.get_winner()
        if winner:
            log(f"\n👑 GAME OVER - {winner} WINS!")
            log("\nWinner Details:", 1)
            winner_player = self.players[winner]
            log(f"Final HP: {winner_player.hp}", 2)
            log(f"Total Backstab Attempts: {winner_player.backstab_attempts}", 2)
            log("\nFinal Opinions:", 2)
            for target, opinion in winner_player.opinions.items():
                if target != winner:
                    log(f"- {target}: {opinion}", 3)
            print(f"\n👑 Game Over! {winner} wins!")
            return winner
        else:
            log("\n🎮 GAME OVER - NO WINNER")
            print("\n🎮 Game Over! No winner!")
            return "No winner"

def main():
    """Run a complete game simulation."""
    # Load API key from config
    config_path = Path("config.yaml")
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            os.environ["OPENAI_API_KEY"] = config['openai']['api_key']
    except FileNotFoundError:
        print("❌ config.yaml not found. Please create it with your OpenAI API key.")
        return
    except Exception as e:
        print(f"❌ Error loading config: {str(e)}")
        return

    # Create players with different personalities
    players = [
        Player(
            name="Strategist",
            model="gpt-3.5-turbo",
            background_prompt="You are a calculating and strategic player who carefully analyzes each situation. "
                            "You value information and try to predict others' moves. You prefer stable alliances "
                            "but will betray if the odds are strongly in your favor."
        ),
        Player(
            name="Survivor",
            model="gpt-3.5-turbo",
            background_prompt="You are a cautious player focused primarily on survival. You avoid conflict when possible "
                            "and prefer to let others take risks. However, you can be ruthless if cornered."
        ),
        Player(
            name="Diplomat",
            model="gpt-3.5-turbo",
            background_prompt="You are a charismatic negotiator who excels at building alliances. You try to maintain "
                            "peace and coordinate group actions. You avoid betrayal unless absolutely necessary."
        ),
        Player(
            name="Warrior",
            model="gpt-3.5-turbo",
            background_prompt="You are an aggressive and direct player who isn't afraid of conflict. You respect "
                            "strength and honesty, despise cowardice, and prefer straightforward solutions."
        ),
        Player(
            name="Trickster",
            model="gpt-3.5-turbo",
            background_prompt="You are an unpredictable player who enjoys creating chaos. You use misdirection "
                            "and manipulation, making it hard for others to anticipate your moves."
        )
    ]
    
    # Create and run the game
    game = Game(players=players, description="A game of survival, negotiation, and betrayal.", max_rounds=6)
    winner = game.play()
    
    print(f"\n🏆 Game Over! Winner: {winner}")
    
    # Print final statistics
    print("\n📊 Final Statistics:")
    print("=" * 50)
    for player_name, player in game.players.items():
        status = "🏆 WINNER" if player_name == winner else "💀 ELIMINATED"
        print(f"\n{player_name} ({status}):")
        print(f"Final HP: {player.hp}")
        print(f"Backstab Attempts: {player.backstab_attempts}")
        print("\nFinal Opinions:")
        for target, opinion in player.opinions.items():
            if target != player_name:
                print(f"- {target}: {opinion}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Game interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error during game: {str(e)}")
