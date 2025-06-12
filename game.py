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


game_time = datetime.now().strftime("%y%m%d-%H%M%S")

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
    damage_required: int = 6
    description: str = ""
    status: RoundStatus = RoundStatus.NOT_COMPLETED
    negotiation_attempts: int = 0
    player_sequence: List[str] = field(default_factory=list)  # List of player IDs
    active_players: List[str] = field(default_factory=list)  # List of player IDs
    player_actions: Dict[str, PlayerAction] = field(default_factory=dict)  # player_id -> action
    damage_taken: Dict[str, int] = field(default_factory=dict)  # player_id -> damage
    scenario: str = ""  # Description of the round's scenario
    process: str = ""  # Description of how the scenario plays out
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
        """Add a lynch action to the tracking."""
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
        response = self._llm_client.get_response(self._story_prompt)
        
        try:
            content = response.content
            if isinstance(content, str):
                import json
                content = json.loads(content)
            
            scenario = content.get("scenario", "")
            process = content.get("process", "")
            
            # Log the story
            log(f"\n📖 ROUND STORY")
            log("Scenario:", 1)
            log(scenario, 2)
            log("Process:", 1)
            log(process, 2)
            
            return scenario, process
        except Exception as e:
            print(f"\n⚠️ Error generating round story: {str(e)}")
            return "", ""

    def start_new_round(self) -> None:
        """Start a new round."""
        round_num = len(self.rounds) + 1
        log(f"\n🎲 Starting Round {round_num}")

        # Generate the round's story
        scenario, process = self._generate_round_story()
        
        self.current_round = Round(
            number=round_num,
            active_players=list(self.active_players),
            scenario=scenario,
            process=process
        )
        self.current_round.reset_player_sequence(self.active_players)
        self.rounds.append(self.current_round)
        self.phase = GamePhase.NEGOTIATION
        
        # Check if there's only one player left with insufficient HP
        if len(self.active_players) == 1:
            last_player_id = self.active_players[0]
            last_player = self.players[last_player_id]
            if last_player.hp < self.current_round.damage_required:
                log("\n⚠️ Last player has insufficient HP to pass the round")
                # Update the player's mindset with the special context
                context = {
                    "event": "insufficient_hp",
                    "round": round_num,
                    "hp": last_player.hp,
                    "damage_required": self.current_round.damage_required,
                    "context": "因为你的血量不足，也没有其他剩余玩家一起合作通关，你在本关无奈地死亡。"
                }
                final_mindset, request_id = last_player.update_mindset(round_num, context)
                log(f"\n🤔 Final Mindset of {last_player.name}:", 1)
                log(final_mindset, 2, request_id)
                # End the game with no winner
                self.eliminate_player(last_player_id, "insufficient_hp")
                self.current_round.status = RoundStatus.COMPLETED
                print("\n🎮 Game Over! No winner!")
                return
        
        # Print the round's story
        if scenario and process:
            print("\n📖 Round Story:")
            print("Scenario:", scenario)
            print("Process:", process)
            
            # Update all alive players' mindsets based on the new scenario
            log("\n🤔 Players'  Mindsets:")
            for player_id in self.active_players:
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
                log(f"{player.name},HP{player.hp} 的心理状态：{new_mindset}", 1, request_id)

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
            log(f"Negotiation Action - Player: {player.name}, HP: {player.hp}")
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
                
                if len(lynchers) >= 2 and total_lynchers_hp >= target_player.hp:
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
                        self.apply_damage(lyncher_id, 1)
                        log(f"Lyncher {self.players[lyncher_id].name} takes 1 damage", 2)
                    
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
        if killer.hp < target.hp:
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
        killer.hp -= 2
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
        self.eliminate_player(action.target_player_id, "killed", killer_id=killer_id)
        
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
                self.eliminate_player(player_id, "execution")
            else:
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
            log(f"{player.name}的心理状态：{new_mindset}", 1, request_id)
        
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
        """Update all players' opinions about an action."""
        target_name = self.player_id_to_name[target_player_id]
        
        # First update the acting player's mindset
        acting_player = self.players[target_player_id]

    
        # Then update other players' opinions and mindsets
        for observer_id in self.active_players:
            if observer_id != target_player_id:
                # Update opinion
                observer, subject, opinion, request_id = self.players[observer_id].update_opinion(
                    target_player_id=target_player_id,
                    target_player_name=target_name,
                    action_type=action_type,
                    context=context
                )
                log(f"{observer}对{subject}的印象更新了：{opinion}", 2, request_id)
                

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        # Game is over if all players are dead or we've completed max_rounds
        return len(self.active_players) == 0 or len(self.rounds) >= self.max_rounds

    def get_winner(self) -> Optional[str]:
        """Get the winner's name if there is one."""
        # Only declare a winner if they survived all rounds
        if len(self.rounds) >= self.max_rounds and len(self.active_players) > 0:
            # If multiple players survived all rounds, they all win
            winners = [self.player_id_to_name[pid] for pid in self.active_players]
            return ", ".join(winners)
        return None

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
            # If there are multiple winners, show details for each
            winner_ids = [self.player_name_to_id[name.strip()] for name in winner.split(",")]
            for winner_id in winner_ids:
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
            model="o4-mini-2025-04-16",
            mindset="突然从一个密室中醒来，不知自己身处何处，周围有恐怖的刀、钻头、电锯等工具，极其恐慌。",
            background_prompt="你是45岁的房地产开发商陈志华。你极度理性冷酷，将一切视为可计算的商业交易，善于操控他人情绪但从不暴露真实感受。你靠强拆养老院发家致富，为了项目利润导致多名老人无家可归后病死，连亲兄弟都被你算计破产。你在生活中习惯成为主导者，会冷静分析每个人的价值并优先牺牲'无用'的人。"
        ),
        Player(
            player_id="linxiaoyu",
            name="linxiaoyu",
            model="o4-mini-2025-04-16",
            mindset="突然从一个密室中醒来，不知自己身处何处，周围有恐怖的刀、钻头、电锯等工具，极其恐慌。",
            background_prompt="你是32岁的失业小学教师林小雨。为了给患白血病的7岁儿子筹治疗费，你挪用了学校救灾款被发现后失业，丈夫因无法承受压力自杀，留下你独自面对巨额债务。曾经温柔的你变得歇斯底里，情绪极度不稳定。你有强烈的求生欲望，认为为了孩子可以做任何事，道德观念已经彻底扭曲。你容易情绪失控，会反复提及自己的孩子试图获得同情。"
        ),
        Player(
            player_id="wangdawei",
            name="wangdawei",
            model="o4-mini-2025-04-16",
            mindset="突然从一个密室中醒来，不知自己身处何处，周围有恐怖的刀、钻头、电锯等工具，极其恐慌。",
            background_prompt="你是28岁的网约车司机王大伟。你沉迷网络赌博输光了所有积蓄和父母养老钱，为了还债偷取乘客遗失物品，甚至曾企图绑架富家女勒索但最终胆怯放弃。你极度胆小优柔寡断，总是寻求他人保护，善于察言观色投靠强者但关键时刻总会背叛。自卑感强烈却渴望被认可，容易被威胁而改变立场。"
        ),
        Player(
            player_id="sumengqi",
            name="sumengqi",
            model="o4-mini-2025-04-16",
            mindset="突然从一个密室中醒来，不知自己身处何处，周围有恐怖的刀、钻头、电锯等工具，极其恐慌。",
            background_prompt="你是26岁的前护士苏梦琪。你曾是优秀的ICU护士，目睹太多因医疗腐败死去的病人后开始对收红包的医生进行'制裁'——在药物中添加有害物质，被发现后杀死了举报你的同事。你外表柔弱但内心极度坚韧狠毒，有强烈但扭曲的正义感，善于伪装无害实际城府极深。你对背叛和欺骗零容忍，报复心极强，会在对你认为'邪恶'的人毫不留情。"
        ),
        Player(
            player_id="yingzheng",
            name="yingzheng",
            model="o4-mini-2025-04-16",
            mindset="突然从一个密室中醒来，不知自己身处何处，周围有恐怖的刀、钻头、电锯等工具，极其恐慌。",
            background_prompt="你是50岁的秦王嬴政穿越到此。你的出生只是一场政治阴谋的副产品，你就是踏着阴谋的隐忍与凶杀降临到这个世界，你的出生本来就是一场笑话，你很透了这个世界。你克制隐忍，可以在没有尊严的猪圈般的生活下存活。你嗜血疯狂，你逼迫生父自杀，只因外面的传言，虽然你并不在乎传言。你杀死了同父异母的两个弟弟，只因他抢夺了，那世上唯一的眷恋，那一点可怜的母爱。"
        )
    ]
    
    # Create and run the game
    game = Game(players=players, description="A game of survival, negotiation, and betrayal.", max_rounds=5)
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
