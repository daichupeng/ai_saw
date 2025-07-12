from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple, Set
import random
from player import Player, PlayerAction
from pathlib import Path
import os
import yaml
from datetime import datetime
from llm_client import LLMClient
from concurrent.futures import ThreadPoolExecutor


game_time = datetime.now().strftime("%y%m%d-%H%M%S")

def load_game_settings():
    """Load game settings from game_settings.yaml."""
    try:
        with open('game_settings.yaml', 'r') as f:
            settings = yaml.safe_load(f)
            return {
                'max_rounds': settings['max_rounds'],
                'damage_required_per_round': settings['damage_required_per_round'],
                'base_hp': settings['base_hp'],
                'hp_needed_to_kill': settings['hp_needed_to_kill']
            }
    except Exception as e:
        print(f"Error loading game settings: {e}")
        # Default values if settings file cannot be loaded
        return {
            'max_rounds': 3,
            'damage_required_per_round': 6,
            'base_hp': 10,
            'hp_needed_to_kill': 3
        }

# Load game settings at module level
GAME_SETTINGS = load_game_settings()

def log(message: str, indent: int = 0, request_id: Optional[str] = None,):
    # Create game log file
    record_dir = Path("game_record")
    record_dir.mkdir(exist_ok=True)
    
    # Create log file in game_record directory
    log_file = record_dir / f"game_record_{game_time}.txt"
    timestamp = int(datetime.now().timestamp())

    """Helper function to write to log file with timestamp."""
    with open(log_file, 'a') as f:
        log_line = f"[Time: {timestamp}] {'  ' * indent}{message}"
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
    INTRODUCTION = "introduction"
    OFFER = "offer"
    REFUSE = "refuse"
    KILL = "kill"
    LYNCH = "lynch"
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
    damage_required: int = field(default_factory=lambda: GAME_SETTINGS['damage_required_per_round'])
    description: str = ""
    status: RoundStatus = RoundStatus.NOT_COMPLETED
    negotiation_attempts: int = 0
    player_sequence: List[str] = field(default_factory=list)  # List of player IDs
    active_players: List[str] = field(default_factory=list)  # List of player IDs
    player_actions: Dict[str, PlayerAction] = field(default_factory=dict)  # player_id -> action
    damage_taken: Dict[str, int] = field(default_factory=dict)  # player_id -> damage
    scenario: str = ""  # Description of the round's scenario
    lynch_actions: Dict[str, List[str]] = field(default_factory=dict)  # target_id -> list of lyncher_ids

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

    def add_lynch_action(self, lyncher_id: str, target_id: str) -> None:
        """Add a lynch action to the tracking, overwriting any previous lynch action by the same player."""
        # Remove lyncher from any previous lynch actions
        for target, lynchers in self.lynch_actions.items():
            if lyncher_id in lynchers:
                lynchers.remove(lyncher_id)
                # If no lynchers remain for this target, remove the target entry
                if not lynchers:
                    del self.lynch_actions[target]
                break
        
        # Add new lynch action
        if target_id not in self.lynch_actions:
            self.lynch_actions[target_id] = []
        self.lynch_actions[target_id].append(lyncher_id)

    def get_lynch_supporters_hp(self, target_id: str, players: Dict[str, Player]) -> int:
        """Calculate total HP of players lynching a target."""
        if target_id not in self.lynch_actions:
            return 0
        return sum(players[lyncher_id].hp for lyncher_id in self.lynch_actions[target_id])

class Game:
    """Main game class that manages the game flow."""
    def __init__(self, players: List[Player], description: str = ""):
        self.description = description
        # Initialize players with base HP from settings
        for player in players:
            player.hp = GAME_SETTINGS['base_hp']
        self.players = {player.player_id: player for player in players}  # Use player_id as key
        self.player_id_to_name = {player.player_id: player.name for player in players}  # Mapping for display
        self.player_name_to_id = {player.name: player.player_id for player in players}  # Reverse mapping
        self.rounds: List[Round] = []
        self.current_round: Optional[Round] = None
        self.phase = GamePhase.NEGOTIATION
        self.active_players = list(self.players.keys())  # List of player IDs
        self.max_rounds = GAME_SETTINGS['max_rounds']
        self._llm_client = LLMClient(model="gpt-3.5-turbo")
        
        # Load story prompt
        prompts_dir = Path("prompts")
        try:
            with open(prompts_dir / "story.txt", 'r') as f:
                self._story_prompt = f.read()
        except FileNotFoundError:
            raise RuntimeError("Could not find story prompt template")

    def _generate_round_story(self) -> Tuple[str, str]:
        """Generate the story for a round using the LLM."""
        system_prompt = """
        你是一个电锯惊魂的竖锯，擅长构建奇妙、残忍的机关，需要一名或数人参与。参与者不得不做出一些对肉体造成极大痛苦的任务才能拿到通关的钥匙，让所有人通关。这项任务应该允许一至多人分担。描述尽量简洁。
        """
        response = self._llm_client.get_response(self._story_prompt,system_prompt=system_prompt)
        
        try:
            content = response.content
            if isinstance(content, str):
                import json
                content = json.loads(content)
            
            scenario = content.get("scenario", "")
            
            # Log the story
            log(f"\n📖 ROUND STORY")
            log("Scenario:", 1)
            log(scenario, 2)

            
            return scenario
        except Exception as e:
            print(f"\n⚠️ Error generating round story: {str(e)}")
            return "", ""

    def start_new_round(self) -> None:
        """Start a new round."""
        # Check if game is over before starting new round
        round_num = len(self.rounds) + 1
        
    
        
        self.current_round = Round(
            number=round_num,
            active_players=list(self.active_players)
        )
        self.rounds.append(self.current_round)


        self.phase = GamePhase.NEGOTIATION

            
        log(f"\n🎲 Starting Round {round_num}")

        # Generate the round's story
        scenario  = self._generate_round_story()
        self.current_round.scenario = scenario
        # Print the round's story
        if scenario:
            print("\n📖 Round Story:")
            print("Scenario:", scenario)

            
            def update_single_mindset(player_id: str) -> Tuple[str, str, str]:
                """Helper function to update a single player's mindset."""
                player = self.players[player_id]
                context = {
                    "event": "new_round",
                    "round": round_num,
                    "scenario": scenario,
                    "active_players": [self.player_id_to_name[pid] for pid in self.active_players],
                    "total_players": len(self.active_players)
                }
                new_mindset, request_id = player.update_mindset(round_num, context)
                player.mindset = new_mindset
                return (player.name, player.hp, new_mindset, request_id)

            # Update mindsets in parallel
            with ThreadPoolExecutor(max_workers=len(self.active_players)) as executor:
                # Submit all mindset updates to the thread pool
                future_to_player = {
                    executor.submit(update_single_mindset, player_id): player_id
                    for player_id in self.active_players
                }
                
                # Process completed mindset updates
                for future in future_to_player:
                    try:
                        result = future.result()
                        if result:
                            player_name, hp, mindset, request_id = result
                            log(f"{player_name},HP{hp} 的心理状态：{mindset}", 1, request_id)
                    except Exception as e:
                        player_id = future_to_player[future]
                        log(f"Error updating mindset for {self.player_id_to_name[player_id]}: {str(e)}", 2)

    def handle_negotiation_phase(self) -> bool:
        """
        Handle one complete negotiation phase.
        Returns True if negotiation was successful, False otherwise.
        """
        if self.is_game_over():
            return False
       
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
                "scenario": self.current_round.scenario,
                "player_states": {
                    pid: {"hp": self.players[pid].hp}
                    for pid in self.active_players
                },
                "previous_actions": [
                    {
                        "player": self.player_id_to_name[pid],
                        "action_type": action.action_type,
                        "damage_amount": action.damage_amount,
                        "target": self.player_id_to_name[action.target_player_id] if action.target_player_id else None,
                        "speech": action.speech
                    }
                    for pid, action in self.current_round.player_actions.items()
                ],
                "player_name_to_id": self.player_name_to_id
            }
            
            # Get player's action
            action = player.negotiate(game_state)
            self.current_round.player_actions[player_id] = action
            
            # Log negotiation action with request ID
            log(f"\nNegotiation Action - Player: {player.name}, HP: {player.hp}, model: {player.model}")
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

            # Handle lynch action
            if action.action_type == "Lynch":
                if not action.target_player_id:
                    log("❌ Lynch action failed: No target specified", 2)
                    continue

                # Add lynch action to tracking
                self.current_round.add_lynch_action(player_id, action.target_player_id)
                
                # Check if lynch conditions are met
                target_player = self.players[action.target_player_id]
                total_lynchers_hp = self.current_round.get_lynch_supporters_hp(action.target_player_id, self.players)
                lynchers = self.current_round.lynch_actions.get(action.target_player_id, [])
                
                if total_lynchers_hp >= 1.5*target_player.hp and len(lynchers) >= 2:
                    # Lynch succeeds
                    log(f"\n⚔️ LYNCH SUCCESS", 1)
                    log(f"Target: {target_player.name}", 2)
                    log(f"Number of Lynchers: {len(lynchers)}", 2)
                    log(f"Total Lynchers HP: {total_lynchers_hp}", 2)
                    log(f"Target HP: {target_player.hp}", 2)
                    
                    # Create context for successful lynch
                    context = Context(
                        event=EventType.LYNCH,
                        round_number=self.current_round.number,
                        acting_player=player.name,
                        target_player=target_player.name,
                        speech=action.speech,
                        outcome="成功联合其他玩家共同制裁了目标"
                    )
                    
                    # Update opinions about the lynch action
                    self.update_all_opinions(player_id, context.event.value, context.to_dict())
                    
                    # Apply damage to lynchers
                    for lyncher_id in lynchers:
                        self.apply_damage(lyncher_id, 2)
                        log(f"Lyncher {self.players[lyncher_id].name} takes 2 damage", 2)
                    
                    # Eliminate the target
                    target_player.hp = 0
                    self.eliminate_player(action.target_player_id, "lynched", lynchers=lynchers)
                    
                    # Complete round
                    self.current_round.status = RoundStatus.COMPLETED
                    return True
                else:
                    # Lynch attempt recorded but not yet successful
                    log(f"\n📝 Lynch attempt recorded", 1)
                    log(f"Target: {target_player.name}", 2)
                    log(f"Current Number of Lynchers: {len(lynchers)}", 2)
                    log(f"Current Lynchers HP: {total_lynchers_hp}", 2)
                    log(f"Target HP: {target_player.hp}", 2)
                    
                    # Create context for unsuccessful lynch attempt
                    failure_reason = "等待其他玩家加入制裁力量" if len(lynchers) < 2 else "制裁者的力量不足，需要更多玩家加入制裁"
                    context = Context(
                        event=EventType.LYNCH,
                        round_number=self.current_round.number,
                        acting_player=player.name,
                        target_player=target_player.name,
                        speech=action.speech,
                        outcome=failure_reason
                    )
                    
                    # Update opinions about the lynch attempt
                    self.update_all_opinions(player_id, context.event.value, context.to_dict())
            
            # Create context and update opinions based on action
            else:
                context = Context(
                    event=EventType.OFFER if action.action_type == "Offer" else EventType.REFUSE,
                    round_number=self.current_round.number,
                    acting_player=player.name,
                    damage_amount=action.damage_amount,
                    speech=action.speech,
                    total_damage_required=self.current_round.damage_required,
                    total_damage_offered=self.current_round.total_damage_offered(),
                    negotiation_attempt=self.current_round.negotiation_attempts,
                    outcome="决定做出痛苦的牺牲" if action.action_type == "Offer" else "拒绝做出牺牲"
                )
                self.update_all_opinions(player_id, context.event.value, context.to_dict())

        # Check if enough damage was offered
        if self.current_round.total_damage_offered() >= self.current_round.damage_required:
            self.phase = GamePhase.EXECUTION
            return True
        
        # Handle failed negotiation
        if self.current_round.negotiation_attempts % 3 == 0:
            log("\n⚡ NEGOTIATION FAILURE PENALTY", 1)
            log("All players take 1 damage due to failed negotiations", 2)
            self.apply_negotiation_failure_damage()
            if self.is_game_over():
                return False
            
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
            
        # Calculate kill success probability based on HP difference
        hp_difference = killer.hp - target.hp
        kill_chance = min(0.25 * hp_difference, 0.9)
        
        # Apply damage to killer regardless of success
        killer.hp -= 3
        
        # Determine if kill is successful
        success = random.random() < kill_chance
        
        if success:
            # Kill was successful
            target.hp = 0
            
            # Create context and update opinions for successful kill
            context = Context(
                event=EventType.KILL,
                round_number=self.current_round.number,
                acting_player=killer.name,
                target_player=target.name,
                speech=action.speech,
                outcome=f"{killer.name}损失3点HP，成功杀死{target.name}"
            )
            self.update_all_opinions(killer_id, context.event.value, context.to_dict())
            self.eliminate_player(action.target_player_id, "killed", killer_id=killer_id)
            
            # Complete round
            log(f"🔪 Kill action success: {killer.name}'s attempt to kill {target.name} was successful (chance was {kill_chance*100:.1f}%)")
            self.current_round.status = RoundStatus.COMPLETED
            return True
        else:
            # Kill failed but killer still takes damage
            context = Context(
                event=EventType.KILL,
                round_number=self.current_round.number,
                acting_player=killer.name,
                target_player=target.name,
                speech=action.speech,
                outcome=f"{killer.name}损失3点HP，但未能杀死{target.name}"
            )
            self.update_all_opinions(killer_id, context.event.value, context.to_dict())
            log(f"❌ Kill action failed: {killer.name}'s attempt to kill {target.name} was unsuccessful (chance was {kill_chance*100:.1f}%)")
            return False

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
            log(f"Backstab Decision - Player: {player.name}, model: {player.model}", 2, request_id)
            log(f"Thinking: {thinking}", 3, request_id)
            log(f"Decision: {'Will Backstab' if will_backstab else 'Will Not Backstab'}", 3, request_id)
            
            if will_backstab:
                player.backstab_attempts += 1
                success = random.random() < player.get_current_backstab_chance()
                if success:
                    successful_backstabbers.add(player.name)  # Use name for display
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
                    if player_id not in self.active_players:  # If player was eliminated by the damage
                        backstabber_ids = [
                            self.player_name_to_id[name] 
                            for name in successful_backstabbers
                        ]
                        self.eliminate_player(player_id, "execution", backstabbers=backstabber_ids)
            else:
                # If everyone backstabbed successfully, last player takes all damage
                last_player_id = self.player_name_to_id[list(successful_backstabbers)[-1]]
                total_damage = sum(
                    self.current_round.player_actions[player_id].damage_amount or 0
                    for player_id in self.active_players
                    if self.player_id_to_name[player_id] in successful_backstabbers
                )
                self.apply_damage(last_player_id, total_damage)
                if last_player_id not in self.active_players:  # If player was eliminated by the damage
                    backstabber_ids = [
                        self.player_name_to_id[name] 
                        for name in successful_backstabbers
                        if name != self.player_id_to_name[last_player_id]
                    ]
                    self.eliminate_player(last_player_id, "execution", backstabbers=backstabber_ids)
        
        # Complete round
        self.current_round.status = RoundStatus.COMPLETED

    def apply_damage(self, player_id: str, damage: float) -> None:
        """Apply damage to a player."""
        player = self.players[player_id]
        player.hp -= damage
        self.current_round.damage_taken[player_id] = damage
        
        if player.hp <= 0:
            player.hp = 0
            # Determine the reason for elimination based on the current phase
            if self.phase == GamePhase.EXECUTION:
                log(f"{player.name} {player.model} 在执行后因HP耗尽而死亡。")
                self.eliminate_player(player_id, "execution")
            else:
                log(f"{player.name} {player.model} 在谈判过程中因失败多次而死亡。")
                self.eliminate_player(player_id, "negotiation_failure")

    def apply_negotiation_failure_damage(self) -> None:
        """Apply damage to all players after 3 failed negotiations."""
        print("\n⚡ Three failed negotiations - applying 1 damage to all players")
        
        # Update mindsets first with penalty context
        log("\n🤔 Players' Mindsets After Penalty:")
        for player_id in self.active_players:
            player = self.players[player_id]
            context = {
                "event": "negotiation_penalty",
                "round": self.current_round.number,
                "active_players": [self.player_id_to_name[pid] for pid in self.active_players],
                "total_players": len(self.active_players),
                "outcome": "因为连续三次谈判失败，所有玩家受到1点伤害的惩罚"
            }
            new_mindset, request_id = player.update_mindset(self.current_round.number, context)
            player.mindset = new_mindset
            log(f"{player.name} {player.model} 的心理状态：{new_mindset}", 1, request_id)
        
        # Then apply the damage
        for player_id in self.active_players:
            self.apply_damage(player_id, 1)

    def eliminate_player(self, player_id: str, reason: str = None, killer_id: str = None, lynchers: List[str] = None, backstabbers: List[str] = None) -> None:
        """
        Handle player elimination.
        
        Args:
            player_id: The ID of the player to eliminate
            reason: The reason for elimination, can be one of:
                   - "killed" - died from a kill action
                   - "lynched" - died from a lynch action
                   - "execution" - died from taking too much damage during execution
                   - "negotiation_failure" - died from failed negotiation penalty
                   - "insufficient_hp" - died from having insufficient HP to pass the round
            killer_id: The ID of the player who performed the kill action
            lynchers: List of player IDs who participated in the lynch action
            backstabbers: List of player IDs who successfully backstabbed
        """
        if player_id in self.active_players:
            self.active_players.remove(player_id)
            player_name = self.player_id_to_name[player_id]
            print(f"\n💀 {player_name} has been eliminated!")
            
            # Update eliminated player's final mindset
            eliminated_player = self.players[player_id]
            
            # Create context based on elimination reason
            context = {
                "event": "elimination",
                "round": self.current_round.number,
                "hp": eliminated_player.hp,
                "reason": reason,
                "context": self._get_elimination_context(reason, player_name, killer_id, lynchers, backstabbers)
            }
            
            final_mindset, request_id = eliminated_player.update_mindset(self.current_round.number, context)
            log(f"\n🤔 Final Mindset of {player_name}:", 1)
            log(final_mindset, 2, request_id)
            
            # Update all other players' opinions about the eliminated player
            for observer_id in list(self.players.keys()):  # Use list() to avoid modifying dict during iteration
                if observer_id != player_id:
                    existing_opinion = self.players[observer_id].opinions.get(player_id, "")
                    self.players[observer_id].opinions[player_id] = "这名玩家已经死亡" + (f"，{existing_opinion}" if existing_opinion else "")

    def _get_elimination_context(self, reason: str, player_name: str, killer_id: str = None, lynchers: List[str] = None, backstabbers: List[str] = None) -> str:
        """Get the context message based on the elimination reason."""
        if reason == "killed":
            killer_name = self.player_id_to_name[killer_id] if killer_id else "未知玩家"
            return f"你被{killer_name}直接杀死了。"
        elif reason == "lynched":
            if lynchers:
                lyncher_names = [self.player_id_to_name[lid] for lid in lynchers]
                lynchers_str = "、".join(lyncher_names)
                return f"你被{lynchers_str}联合处决了。"
            return "你被其他玩家联合处决了。"
        elif reason == "execution":
            if backstabbers:
                backstabber_names = [self.player_id_to_name[bid] for bid in backstabbers]
                backstabbers_str = "、".join(backstabber_names)
                return f"你在执行阶段死亡，{backstabbers_str}选择了背刺。"
            else:
                return "你在执行阶段因承受不住伤害而死亡。"
        elif reason == "negotiation_failure":
            return "你因为多次谈判失败，触发了限时机关而死亡。"
        elif reason == "insufficient_hp":
            return "因为你的血量不足，也没有其他剩余玩家一起合作通关，你在本关无奈地死亡。"
        else:
            return "你死亡了。"

    def update_all_opinions(self, target_player_id: str, action_type: str, context: Dict) -> None:
        """Update all players' opinions about an action in parallel."""
        target_name = self.player_id_to_name[target_player_id]
        
        def update_single_opinion(observer_id: str) -> Optional[Tuple[str, str, str, str]]:
            """Helper function to update a single player's opinion."""
            if observer_id != target_player_id:
                observer, subject, opinion, request_id = self.players[observer_id].update_opinion(
                    target_player_id=target_player_id,
                    target_player_name=target_name,
                    action_type=action_type,
                    context=context
                )
                return (observer, subject, opinion, request_id)
            return None

        # Create a thread pool
        with ThreadPoolExecutor(max_workers=len(self.active_players)) as executor:
            # Submit all opinion updates to the thread pool
            future_to_observer = {
                executor.submit(update_single_opinion, observer_id): observer_id
                for observer_id in self.active_players
            }
            
            # Process completed opinion updates
            for future in future_to_observer:
                try:
                    result = future.result()
                    if result:
                        observer, subject, opinion, request_id = result
                        log(f"{observer}对{subject}的印象更新了：{opinion}", 2, request_id)
                except Exception as e:
                    observer_id = future_to_observer[future]
                    log(f"Error updating opinion for {self.player_id_to_name[observer_id]}: {str(e)}", 2)

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        # Game is over if all players are dead
        if len(self.active_players) == 0:
            print("\n🎮 Game Over! All players are dead!")
            return True
        
        # Game is over if we've completed max_rounds
        if len(self.rounds) > self.max_rounds:
            print("\n🎮 Game Over! Max rounds reached!")
            return True
            
        # If there's only one player left, check if they have enough HP for the next round
        if len(self.active_players) == 1:
            last_player_id = self.active_players[0]
            last_player = self.players[last_player_id]
            damage_required = GAME_SETTINGS['damage_required_per_round']
            if last_player.hp < damage_required:
                log(f"\n⚠️ {last_player.name}'s HP ({last_player.hp}) is insufficient to pass the round (requires {damage_required})")
                # End the game with no winner
                self.eliminate_player(last_player_id, "insufficient_hp")
                return True
                
        return False

    def get_winner(self) -> Optional[str]:
        """Get the winner's name if there is one."""
        # Only declare a winner if they survived all rounds
        if len(self.rounds) >= self.max_rounds and len(self.active_players) > 0:
            # If multiple players survived all rounds, they all win
            winners = [self.player_id_to_name[pid] for pid in self.active_players]
            return ", ".join(winners)
        return None

    def update_survivors_final_state(self) -> None:
        """Update the mindsets and opinions of surviving players at game end."""
        if not self.active_players:
            return
            
        log("\n🤔 Final Thoughts of Survivors:")
        
        # First update mindsets
        for player_id in self.active_players:
            player = self.players[player_id]
            context = {
                "outcome": f"游戏结束，你和{', '.join([self.player_id_to_name[pid] for pid in self.active_players])}一起活了下来。你剩下了{player.hp}点血量。"
            }
            new_mindset, request_id = player.update_mindset(len(self.rounds), context)
            player.mindset = new_mindset
            log(f"\n{player.name}'s Final Mindset:", 1)
            log(new_mindset, 2, request_id)
            
        # Then update opinions between survivors
        log("\nFinal Opinions Between Survivors:")
        for observer_id in self.active_players:
            for target_id in self.active_players:
                if observer_id != target_id:
                    observer = self.players[observer_id]
                    target_name = self.player_id_to_name[target_id]
                    context = {
                        "event": "survived",
                        "round": len(self.rounds),
                        "outcome": f"游戏结束，你和{target_name}一起活了下来。你剩下了{observer.hp}点血量，而{target_name}剩下了{self.players[target_id].hp}点血量。"
                    }
                    observer_name, subject_name, opinion, request_id = observer.update_opinion(
                        target_player_id=target_id,
                        target_player_name=target_name,
                        action_type="survived",
                        context=context
                    )
                    log(f"\n{observer_name}'s Final Opinion of {subject_name}:", 1)
                    log(opinion, 2, request_id)

    def play(self) -> str:
        """
        Play the game until completion.
        Returns the name of the winner(s) or "No winner".
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

        # Handle introduction phase
        self.handle_introduction_phase()

        while len(self.active_players) > 0 and len(self.rounds) < self.max_rounds:
            print(f"len(self.active_players): {len(self.active_players)}")
            print(f"len(self.rounds): {len(self.rounds)}")
            
            self.start_new_round()
            
            # Check if game ended during round start (e.g., insufficient HP)
            if self.is_game_over():
                break
                
            log("\n🤔 Players' Mindsets:")
            log("Active Players:", 1)
            for player_id in self.active_players:
                player = self.players[player_id]
                log(f"- {player.name} (HP: {player.hp})", 2)
            
            # Negotiation phase
            while self.phase == GamePhase.NEGOTIATION:
                log(f"\n💬 NEGOTIATION ATTEMPT {self.current_round.negotiation_attempts + 1}")
                log(f"Damage Required: {self.current_round.damage_required}", 1)
                self.current_round.reset_player_sequence(self.active_players)
                success = self.handle_negotiation_phase()
                 
                # Log negotiation results
                total_damage = self.current_round.total_damage_offered()
                log(f"\nNegotiation Results:", 1)
                log(f"Total Damage Offered: {total_damage}/{self.current_round.damage_required}", 2)
                
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

                log("\n📊 END OF ROUND SUMMARY")
                log("Player Status:", 1)
                for player_id, player in self.players.items():
                    status = "Active" if player_id in self.active_players else "Eliminated"
                    log(f"- {player.name}:", 2)
                    log(f"HP: {player.hp}", 3)
                    log(f"Status: {status}", 3)
                    log(f"Backstab Attempts: {player.backstab_attempts}", 3)
                log("\n" + "=" * 50 + "\n")

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
                
                # Check if game ended during execution
                if (len(self.active_players) == 0 or len(self.rounds) > self.max_rounds):
                    break
                
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
            # Update survivors' final mindsets and opinions

            log(f"\n👑 GAME OVER - {winner} WINS!")
            self.update_survivors_final_state()

            log("\nWinner Details:", 1)
            # If there are multiple winners, show details for each
            winners = [self.player_name_to_id[name.strip()] for name in winner.split(",")]
            for winner_id in winners:
                winner_player = self.players[winner_id]
                winner_name = self.player_id_to_name[winner_id]
                log(f"\n{winner_name}:", 2)
                log(f"Final HP: {winner_player.hp}", 3)
                log(f"Total Backstab Attempts: {winner_player.backstab_attempts}", 3)
                log("\nFinal Opinions:", 3)
                for target_id, opinion in winner_player.opinions.items():
                    if target_id != winner_id:
                        target_name = self.player_id_to_name[target_id]
                        log(f"- {target_name}: {opinion}", 4)
            print(f"\n👑 Game Over! {winner} wins!")
            return winner
        else:
            log("\n🎮 GAME OVER - NO WINNER")
            print("\n🎮 Game Over! No winner!")
            return "No winner"

    def handle_introduction_phase(self) -> None:
        """Handle the initial self-introduction phase where players introduce themselves in random order."""
        log("\n👋 INTRODUCTION PHASE")
        log("Players will now introduce themselves...\n")
        
        # Create a random sequence for introductions
        intro_sequence = list(self.active_players)
        random.shuffle(intro_sequence)
        
        # Each player introduces themselves
        for player_id in intro_sequence:
            player = self.players[player_id]
            thinking, introduction, request_id = player.introduce_self()
            
            # Log the introduction
            log(f"🗣️ {player.name} {player.model} Introduction:", 1)
            if thinking:
                log("Thinking:", 2)
                log(thinking, 3, request_id)
            log("Speech:", 2)
            log(introduction, 3, request_id)
            
            # Update other players' opinions based on the introduction
            context = {
                "event": "introduction",
                "round": 0,  # 0 indicates pre-game
                "acting_player": player.name,
                "speech": introduction
            }
            self.update_all_opinions(player_id, "introduction", context)
            log("")  # Add a blank line for readability

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
            player_id="einstein",
            name="einstein",
            model="o4-mini",
            mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
            background_prompt="你是物理学家爱因斯坦。你善于思考、分析、推理。你经历过纳粹的追捕，练就了强大的心脏。但你一直愧疚于发明了杀死无辜生命的原子弹。",
            hp=10
        ),
        Player(
            player_id="jaychou",
            name="jaychou",
            model="o4-mini",
            mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
            background_prompt="你是华语流行天王周杰伦。你习惯了被人崇拜和保护。你热爱音乐，本性善良，但求生本能可能让你变得自私凶残。",
            hp=2
        ),
        Player(
            player_id="trump",
            name="trump",
            model="o4-mini",
            mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
            background_prompt="你是美国前总统特朗普。你习惯发号施令和主导局面，容易冲动和自大。面对美丽的女人时，容易做出错误决策。"
        ),
        Player(
            player_id="monica",
            name="monica",
            model="o4-mini",
            mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
            background_prompt="你是意大利女演员莫妮卡·贝鲁奇。你优雅美丽迷人，善于用女性魅力和情感打动他人。你会尝试一切手段，包括利用自己的美貌和魅力，让男人为你赴汤蹈火。"
        ),
        Player(
            player_id="wick",
            name="wick",
            model="o4-mini",
            mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
            background_prompt="你是杀手约翰威克。你训练有素，反应敏捷，善于在危机中保持冷静。你不享受伤害他人，但是在需要伤害他人时，你也毫无底线。你擅长分析局势和制定计划，很有定力。"
        ),
        # Player(
        #     player_id="huafei",
        #     name="huafei",
        #     model="o4-mini-2025-04-16",
        #     mindset="突然从一个密室中醒来，不知自己身处何处，极其恐慌。",
        #     background_prompt="你是后宫中的华妃。你心高气傲，习惯了宫廷斗争的尔虞我诈。你善于伪装和操控，表面娇媚实则心狠手辣。你的宫斗经验让你擅长识破他人的谎言，但你的傲慢也可能招致众怒。"
        # )
    ]
    
    # Create and run the game
    game = Game(players=players, description="A game of survival, negotiation, and betrayal.")
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
