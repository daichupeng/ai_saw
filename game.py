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
    acting_player: str  # This will be the player's name for display
    target_player: Optional[str] = None  # This will be the player's name for display
    damage_amount: Optional[float] = None
    speech: Optional[str] = None
    outcome: Optional[str] = None  # Describes the result of the action
    successful_backstabbers: Set[str] = field(default_factory=set)  # These will be player names
    failed_backstabbers: Set[str] = field(default_factory=set)  # These will be player names
    loyal_players: Set[str] = field(default_factory=set)  # These will be player names
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
        if self.outcome:
            context_dict["outcome"] = self.outcome
            
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
    player_sequence: List[str] = field(default_factory=list)  # List of player IDs
    active_players: List[str] = field(default_factory=list)  # List of player IDs
    player_actions: Dict[str, PlayerAction] = field(default_factory=dict)  # player_id -> action
    damage_taken: Dict[str, int] = field(default_factory=dict)  # player_id -> damage

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
        """Get the player_id and action if there was a kill action."""
        for player_id, action in self.player_actions.items():
            if action.action_type == "Kill":
                return player_id, action
        return None

class Game:
    """Main game class that manages the game flow."""
    def __init__(self, players: List[Player], description: str = "", max_rounds: int = 10):
        self.description = description
        self.players = {player.player_id: player for player in players}  # Use player_id as key
        self.player_id_to_name = {player.player_id: player.name for player in players}  # Mapping for display
        self.player_name_to_id = {player.name: player.player_id for player in players}  # Reverse mapping
        self.rounds: List[Round] = []
        self.current_round: Optional[Round] = None
        self.phase = GamePhase.NEGOTIATION
        self.active_players = list(self.players.keys())  # List of player IDs
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
        for player_id in self.current_round.player_sequence:
            player = self.players[player_id]
            
            # Create game state for player decision
            game_state = {
                "round_number": self.current_round.number,
                "damage_required": self.current_round.damage_required,
                "negotiation_attempt": self.current_round.negotiation_attempts,
                "player_states": {
                    pid: {"hp": self.players[pid].hp}
                    for pid in self.active_players
                },
                "previous_actions": [
                    {
                        "player": self.player_id_to_name[pid],  # Use name for display
                        "action_type": action.action_type,
                        "damage_amount": action.damage_amount,
                        "target": self.player_id_to_name[action.target_player_id] if action.target_player_id else None,
                        "speech": action.speech
                    }
                    for pid, action in self.current_round.player_actions.items()
                ],
                "player_name_to_id": self.player_name_to_id  # Add mapping for player to convert names to IDs
            }
            
            # Get player's action
            action = player.negotiate(game_state)
            self.current_round.player_actions[player_id] = action
            
            # Log negotiation action with request ID
            log(f"Negotiation Action - Player: {player.name}")
            log(f"Thinking: {action.thinking}", 3, action.request_id)
            log(f"Speech: {action.speech}", 3, action.request_id)
            log(f"Action: {action.action_type}", 2, action.request_id)
            if action.damage_amount:
                log(f"Damage Amount: {action.damage_amount}", 3, action.request_id)
            if action.target_player_id:
                target_name = self.player_id_to_name[action.target_player_id]
                log(f"Target: {target_name}", 3, action.request_id)

            
            # Handle kill action
            if action.action_type == "Kill":
                kill_success = self.handle_kill_action(player_id, action)
                if kill_success:
                    return True  # End negotiation if kill was successful
                # If kill failed, continue with next player
                continue
        
            # Create context and update opinions based on action
            context = Context(
                event=EventType.OFFER if action.action_type == "Offer" else EventType.REFUSE,
                round_number=self.current_round.number,
                acting_player=player.name,
                damage_amount=action.damage_amount,
                speech=action.speech,
                total_damage_required=self.current_round.damage_required,
                total_damage_offered=self.current_round.total_damage_offered(),
                negotiation_attempt=self.current_round.negotiation_attempts,
                outcome="决定献祭自己" if action.action_type == "Offer" else "拒绝献祭自己"
            )
            self.update_all_opinions(player_id, context.event.value, context.to_dict())

        # Check if enough damage was offered
        if self.current_round.total_damage_offered() >= self.current_round.damage_required:
            self.phase = GamePhase.EXECUTION
            return True
        
        # Handle failed negotiation
        if self.current_round.negotiation_attempts % 3 == 1 and self.current_round.negotiation_attempts != 1:
            self.apply_negotiation_failure_damage()
            # self.current_round.negotiation_attempts = 0
            
        return False

    def handle_kill_action(self, killer_id: str, action: PlayerAction) -> bool:
        """Handle a kill action during negotiation."""
        if not action.target_player_id:
            raise ValueError("Kill action must have a target")
            
        killer = self.players[killer_id]
        target = self.players[action.target_player_id]
        
        # Check if target is still alive
        if action.target_player_id not in self.active_players:
            log(f"❌ Kill action failed: {killer.name} cannot kill {target.name} (target already eliminated)")
            
            # Create context for failed kill attempt
            context = Context(
                event=EventType.KILL,
                round_number=self.current_round.number,
                acting_player=killer.name,
                target_player=target.name,
                speech=action.speech,
                outcome="因为目标已经死亡，所以无法杀死目标"
            )
            # Update opinions about the failed kill attempt
            self.update_all_opinions(killer_id, context.event.value, context.to_dict())
            return False
        
        # Validate kill conditions
        if killer.hp <= target.hp:
            log(f"❌ Kill action failed: {killer.name} cannot kill {target.name} (invalid HP condition)")
            
            # Create context for failed kill attempt
            context = Context(
                event=EventType.KILL,
                round_number=self.current_round.number,
                acting_player=killer.name,
                target_player=target.name,
                speech=action.speech,
                outcome="因为自己太血量低于对方，无法杀死目标"
            )
            # Update opinions about the failed kill attempt
            self.update_all_opinions(killer_id, context.event.value, context.to_dict())
            return False
            
        # Apply damage
        killer.hp -= 1
        target.hp = 0
        
        # Create context and update opinions for successful kill
        context = Context(
            event=EventType.KILL,
            round_number=self.current_round.number,
            acting_player=killer.name,
            target_player=target.name,
            speech=action.speech,
            outcome="成功杀死目标"
        )
        self.update_all_opinions(killer_id, context.event.value, context.to_dict())
        self.eliminate_player(action.target_player_id)
        
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
            player_id for player_id in self.current_round.player_sequence
            if self.current_round.player_actions[player_id].action_type == "Offer"
        ])
        
        successful_backstabbers = set()
        failed_backstabbers = set()
        loyal_players = set()
        
        # Handle backstab attempts
        for player_id in self.current_round.player_sequence:
            player = self.players[player_id]
            action = self.current_round.player_actions[player_id]
            
            # Create game state for backstab decision
            game_state = {
                "round": self.current_round.number,
                "your_damage": action.damage_amount,
                "player_damages": {
                    pid: self.current_round.player_actions[pid].damage_amount or 0
                    for pid in self.active_players
                    if self.current_round.player_actions[pid].action_type == "Offer"
                }
            }
            
            # Get backstab decision
            will_backstab, thinking, request_id = player.decide_backstab(game_state)
            
            # Log backstab decision with request ID
            log(f"Backstab Decision - Player: {player.name}", 2, request_id)
            log(f"Thinking: {thinking}", 3, request_id)
            log(f"Decision: {'Will Backstab' if will_backstab else 'Will Not Backstab'}", 3, request_id)
            
            if will_backstab:
                success = random.random() < player.get_current_backstab_chance()
                if success:
                    successful_backstabbers.add(player.name)  # Use name for display
                    player.backstab_attempts += 1
                    print(f"🗡️ {player.name}'s backstab succeeded!")
                    log(f"{player.name}'s backstab succeeded!", 2, request_id)
                    
                    # Update opinions about successful backstab
                    context = Context(
                        event=EventType.BACKSTAB_SUCCESS,
                        round_number=self.current_round.number,
                        acting_player=player.name,
                        speech=thinking,
                        outcome="成功背刺其他人，逃脱了自己承诺好的献祭"
                    )
                    self.update_all_opinions(player_id, context.event.value, context.to_dict())
                else:
                    failed_backstabbers.add(player.name)  # Use name for display
                    print(f"❌ {player.name}'s backstab failed!")
                    log(f"{player.name}'s backstab failed!", 2, request_id)
                    self.apply_damage(player_id, action.damage_amount or 0)
                    
                    # Update opinions about failed backstab
                    context = Context(
                        event=EventType.BACKSTAB_FAIL,
                        round_number=self.current_round.number,
                        acting_player=player.name,
                        speech=thinking,
                        outcome="想逃脱自己承诺的献祭，但失败了"
                    )
                    self.update_all_opinions(player_id, context.event.value, context.to_dict())
            else:
                loyal_players.add(player.name)  # Use name for display
                print(f"✋ {player.name} chose not to backstab")
                # log(f"{player.name} chose not to backstab", 2, request_id)
                self.apply_damage(player_id, action.damage_amount or 0)
                
                # Update opinions about choosing not to backstab
                # context = Context(
                #     event=EventType.NO_BACKSTAB,
                #     round_number=self.current_round.number,
                #     acting_player=player.name,
                #     speech=thinking,
                #     outcome="chose_loyalty"
                # )
                # self.update_all_opinions(player_id, context.event.value, context.to_dict())
        
        # Handle successful backstabs
        if successful_backstabbers:
            remaining_players = [
                player_id for player_id in self.active_players
                if self.player_id_to_name[player_id] not in successful_backstabbers and 
                self.current_round.player_actions[player_id].action_type == "Offer"
            ]
            
            if remaining_players:
                # Distribute damage from successful backstabbers
                total_damage = sum(
                    self.current_round.player_actions[player_id].damage_amount or 0
                    for player_id in self.active_players
                    if self.player_id_to_name[player_id] in successful_backstabbers
                )
                damage_per_player = total_damage / len(remaining_players)
                
                for player_id in remaining_players:
                    self.apply_damage(player_id, damage_per_player)
            else:
                # If everyone backstabbed successfully, last player takes all damage
                last_player_id = self.player_name_to_id[list(successful_backstabbers)[-1]]
                total_damage = sum(
                    self.current_round.player_actions[player_id].damage_amount or 0
                    for player_id in self.active_players
                    if self.player_id_to_name[player_id] in successful_backstabbers
                )
                self.apply_damage(last_player_id, total_damage)
        
        # Complete round
        self.current_round.status = RoundStatus.COMPLETED

    def apply_damage(self, player_id: str, damage: float) -> None:
        """Apply damage to a player."""
        player = self.players[player_id]
        player.hp -= damage
        self.current_round.damage_taken[player_id] = damage
        
        if player.hp <= 0:
            player.hp = 0
            self.eliminate_player(player_id)

    def apply_negotiation_failure_damage(self) -> None:
        """Apply damage to all players after 3 failed negotiations."""
        print("\n⚡ Three failed negotiations - applying 1 damage to all players")
        for player_id in self.active_players:
            self.apply_damage(player_id, 1)

    def eliminate_player(self, player_id: str) -> None:
        """Handle player elimination."""
        if player_id in self.active_players:
            self.active_players.remove(player_id)
            player_name = self.player_id_to_name[player_id]
            print(f"\n💀 {player_name} has been eliminated!")

    def update_all_opinions(self, target_player_id: str, action_type: str, context: Dict) -> None:
        """Update all players' opinions about an action."""
        target_name = self.player_id_to_name[target_player_id]
        for observer_id in self.active_players:
            if observer_id != target_player_id:
                observer, subject, opinion, request_id = self.players[observer_id].update_opinion(
                    target_player_id=target_player_id,
                    target_player_name=target_name,
                    action_type=action_type,
                    context=context
                )
                log(f"{observer}对{subject}的印象更新了：{opinion}, Request ID: {request_id}, ")

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return len(self.active_players) <= 1 or len(self.rounds) > self.max_rounds

    def get_winner(self) -> Optional[str]:
        """Get the winner's name if there is one."""
        if len(self.active_players) == 1:
            return self.player_id_to_name[self.active_players[0]]
        return None

    def play(self) -> str:
        """
        Play the game until completion.
        Returns the name of the winner.
        """
        # Initialize log file with game setup
        log("=== AI SAW GAME RECORD ===")
        log(f"Game Description: {self.description}")
        log("\nInitial Players:")
        for player_id, player in self.players.items():
            log(f"- {player.name}:", 1)
            log(f"HP: {player.hp}", 2)
            log(f"Background: {player.background_prompt}", 2)
            log(f"Backstab Success Rate: {player.backstab_success_rate * 100}%", 2)
        log("\n" + "=" * 50 + "\n")

        while not self.is_game_over():
            self.start_new_round()
            log(f"\n🎲 ROUND {len(self.rounds)}")
            log("Active Players:", 1)
            for player_id in self.active_players:
                player = self.players[player_id]
                log(f"- {player.name} (HP: {player.hp})", 2)
            
            # Negotiation phase
            while self.phase == GamePhase.NEGOTIATION:
                log(f"\n💬 NEGOTIATION ATTEMPT {self.current_round.negotiation_attempts + 1}")
                log(f"Damage Required: {self.current_round.damage_required}", 1)
                
                success = self.handle_negotiation_phase()
                
                # Log negotiation results
                total_damage = self.current_round.total_damage_offered()
                log(f"\nNegotiation Results:", 1)
                log(f"Total Damage Offered: {total_damage}/{self.current_round.damage_required}", 2)
                
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
                    killer_id, action = kill_action
                    killer_name = self.player_id_to_name[killer_id]
                    target_name = self.player_id_to_name[action.target_player_id] if action.target_player_id else "Unknown"
                    log("\n💀 KILL ACTION", 1)
                    log(f"Killer: {killer_name}", 2)
                    log(f"Target: {target_name}", 2)
                    log(f"Reason: {action.speech}", 2)
                continue
                
            # Execution phase
            if self.phase == GamePhase.EXECUTION:
                log("\n⚔️ EXECUTION PHASE")
                
                # Record initial state
                log("Initial State:", 1)
                for player_id in self.active_players:
                    player = self.players[player_id]
                    damage = self.current_round.player_actions[player_id].damage_amount
                    log(f"- {player.name}: HP={player.hp}, Promised Damage={damage}", 2)
                
                self.handle_execution_phase()
                
                # Record results
                log("\nExecution Results:", 1)
                for player_id in self.current_round.player_sequence:
                    player = self.players[player_id]
                    damage_taken = self.current_round.damage_taken.get(player_id, 0)
                    log(f"- {player.name}:", 2)
                    log(f"Final HP: {player.hp}", 3)
                    log(f"Damage Taken: {damage_taken}", 3)
                    if player_id in self.active_players:
                        log("Status: Survived", 3)
                    else:
                        log("Status: Eliminated", 3)
            
            # End of round summary
            log("\n📊 END OF ROUND SUMMARY")
            log("Player Status:", 1)
            for player_id, player in self.players.items():
                status = "Active" if player_id in self.active_players else "Eliminated"
                log(f"- {player.name}:", 2)
                log(f"HP: {player.hp}", 3)
                log(f"Status: {status}", 3)
                log(f"Backstab Attempts: {player.backstab_attempts}", 3)
            log("\n" + "=" * 50 + "\n")
        
        # Game over
        winner = self.get_winner()
        if winner:
            log(f"\n👑 GAME OVER - {winner} WINS!")
            log("\nWinner Details:", 1)
            winner_id = self.player_name_to_id[winner]
            winner_player = self.players[winner_id]
            log(f"Final HP: {winner_player.hp}", 2)
            log(f"Total Backstab Attempts: {winner_player.backstab_attempts}", 2)
            log("\nFinal Opinions:", 2)
            for target_id, opinion in winner_player.opinions.items():
                if target_id != winner_id:
                    target_name = self.player_id_to_name[target_id]
                    log(f"- {target_name}: {opinion}", 3)
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
            player_id="chenzhihua",
            name="chenzhihua",
            model="gpt-3.5-turbo",
            background_prompt="你是45岁的房地产开发商陈志华。你极度理性冷酷，将一切视为可计算的商业交易，善于操控他人情绪但从不暴露真实感受。你靠强拆养老院发家致富，为了项目利润导致多名老人无家可归后病死，连亲兄弟都被你算计破产。你在生活中习惯成为主导者，会冷静分析每个人的价值并优先牺牲'无用'的人。"
        ),
        Player(
            player_id="linxiaoyu",
            name="linxiaoyu",
            model="gpt-3.5-turbo",
            background_prompt="你是32岁的失业小学教师林小雨。为了给患白血病的7岁儿子筹治疗费，你挪用了学校救灾款被发现后失业，丈夫因无法承受压力自杀，留下你独自面对巨额债务。曾经温柔的你变得歇斯底里，情绪极度不稳定。你有强烈的求生欲望，认为为了孩子可以做任何事，道德观念已经彻底扭曲。你容易情绪失控，会反复提及自己的孩子试图获得同情。"
        ),
        Player(
            player_id="wangdawei",
            name="wangdawei",
            model="gpt-3.5-turbo",
            background_prompt="你是28岁的网约车司机王大伟。你沉迷网络赌博输光了所有积蓄和父母养老钱，为了还债偷取乘客遗失物品，甚至曾企图绑架富家女勒索但最终胆怯放弃。你极度胆小优柔寡断，总是寻求他人保护，善于察言观色投靠强者但关键时刻总会背叛。自卑感强烈却渴望被认可，容易被威胁而改变立场。"
        ),
        Player(
            player_id="sumengqi",
            name="sumengqi",
            model="gpt-3.5-turbo",
            background_prompt="你是26岁的前护士苏梦琪。你曾是优秀的ICU护士，目睹太多因医疗腐败死去的病人后开始对收红包的医生进行'制裁'——在药物中添加有害物质，被发现后杀死了举报你的同事。你外表柔弱但内心极度坚韧狠毒，有强烈但扭曲的正义感，善于伪装无害实际城府极深。你对背叛和欺骗零容忍，报复心极强，会在对你认为'邪恶'的人毫不留情。"
        ),
        Player(
            player_id="zhangjianwen",
            name="zhangjianwen",
            model="gpt-3.5-turbo",
            background_prompt="你是58岁的退休保安张建文。作为退伍军人，你在维和任务中失去战友患上PTSD，退休后做保安时因过度使用武力导致年轻窃贼重伤致残，但你认为自己在'维护正义'。你意志坚定但偏执狂躁，有强烈但扭曲的荣誉感和规则意识，容易被激怒且一旦愤怒就失去理智。你特别严厉，可能在情绪失控时做出冲动的致命决定。"
        )
    ]
    
    # Create and run the game
    game = Game(players=players, description="A game of survival, negotiation, and betrayal.", max_rounds=6)
    winner = game.play()
    
    print(f"\n🏆 Game Over! Winner: {winner}")
    
    # Print final statistics
    print("\n📊 Final Statistics:")
    print("=" * 50)
    for player_id, player in game.players.items():
        status = "🏆 WINNER" if player_id in game.active_players else "💀 ELIMINATED"
        print(f"\n{player.name} ({status}):")
        print(f"Final HP: {player.hp}")
        print(f"Backstab Attempts: {player.backstab_attempts}")
        print("\nFinal Opinions:")
        for target_id, opinion in player.opinions.items():
            if target_id != player_id:
                target_name = game.player_id_to_name[target_id]
                print(f"- {target_name}: {opinion}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Game interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error during game: {str(e)}")
