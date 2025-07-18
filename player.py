from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple, List
from pathlib import Path
import json
from llm_client import LLMClient, LLMResponse

# Type definitions
ActionType = Literal["Offer", "Refuse", "Kill", "Lynch"]
PhaseType = Literal["negotiation", "execution"]

@dataclass
class PlayerAction:
    """Class to represent a player's action during negotiation."""
    action_type: ActionType
    damage_amount: Optional[int] = None  # For Offer action
    target_player_id: Optional[str] = None  # For Kill action, using player_id instead of name
    thinking: str = ""
    speech: str = ""
    request_id: Optional[str] = None  # Request ID from LLM response

@dataclass
class Player:
    """Class representing a player in the AI Saw game."""
    
    # Required initialization attributes
    player_id: str  # Unique identifier for the player
    name: str
    model: str
    background_prompt: str
    
    # Optional initialization attributes with defaults
    hp: int = 10
    backstab_success_rate: float = 0.30
    opinions: Dict[str, str] = field(default_factory=dict)  # player_id -> opinion (descriptive string)
    backstab_attempts: int = 0
    mindset: str = ""  # Current psychological state of the player
    
    # LLM client for decision making
    _llm_client: Optional[LLMClient] = None
    
    # Prompt templates
    _prompt_templates: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize the LLM client and load prompt templates."""
        if not self._llm_client:
            self._llm_client = LLMClient(model=self.model)
        
        # Load prompt templates
        prompts_dir = Path(__file__).parent / "prompts"
        self._load_prompt_templates(prompts_dir)
    
    def _load_prompt_templates(self, prompts_dir: Path) -> None:
        """Load all prompt templates from the prompts directory."""
        template_files = {
            "negotiation": "negotiation.txt",
            "backstab": "backstab.txt",
            "opinion_update": "opinion_update.txt",
            "mindset": "mindset.txt",
            "intro": "intro.txt"
        }
        
        for key, filename in template_files.items():
            try:
                with open(prompts_dir / filename, 'r') as f:
                    self._prompt_templates[key] = f.read()
            except FileNotFoundError:
                raise RuntimeError(f"Could not find prompt template: {filename}")
    
    def is_alive(self) -> bool:
        """Check if the player is still alive."""
        return self.hp > 0
    
    def get_current_backstab_chance(self) -> float:
        """Calculate current backstab success chance."""
        return max(0, self.backstab_success_rate - (0.05 * self.backstab_attempts))
    
    def take_damage(self, amount: int) -> bool:
        """
        Apply damage to the player.
        
        Args:
            amount: Amount of damage to take
            
        Returns:
            bool: True if player died from this damage
        """
        self.hp = max(0, self.hp - amount)
        return self.hp == 0
    
    def update_opinion(self, target_player_id: str, target_player_name: str, action_type: str, context: Dict) -> Tuple[str, str, str, str]:
        """
        Update opinion about another player based on their actions.
        
        Args:
            target_player_id: ID of the player to update opinion about
            target_player_name: Name of the player to update opinion about (for display)
            action_type: Type of action they took
            context: Additional context about the action
            
        Returns:
            Tuple[str, str, str, str]: (observer_name, subject_name, opinion, request_id)
        """
        prompt = self._prompt_templates["opinion_update"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            target_player=target_player_name,  # Use name for display in prompts
            action_type=action_type,
            context=json.dumps(context, ensure_ascii=False),  # Convert context to string
            current_opinion=self.opinions.get(target_player_id, "No previous opinion")
        )
        
        response = self._llm_client.get_response(prompt)
        
        try:
            # Handle nested content structure
            content = response.content.get("content", {})
            if not content:
                content = response.content  # If not nested, use the content directly
            
            opinion = content.get("opinion", "")
            print(f"opinion: {opinion}")
            self.opinions[target_player_id] = opinion  # Store opinion using player_id
            
            return self.name, target_player_name, opinion, response.request_id
            
        except Exception as e:
            print(f"\n⚠️ Error updating opinion: {str(e)}")
            return self.name, target_player_name, "", response.request_id
    
    def negotiate(self, game_state: Dict) -> PlayerAction:
        """
        Make a decision during the negotiation phase.
        
        Args:
            game_state: Current state of the game including:
                - round_number: Current round number
                - damage_required: Total damage to be distributed
                - player_states: Dict of player states (hp, etc.)
                - negotiation_attempt: Which attempt this is at negotiating
                - previous_actions: List of previous actions in this negotiation
                - current_mindset: Player's current psychological state
                
        Returns:
            PlayerAction containing the decision, speech, and thinking process
        """
        prompt = self._prompt_templates["negotiation"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            hp=self.hp,
            round_number=game_state['round_number'],
            damage_required=game_state['damage_required'],
            negotiation_attempt=game_state['negotiation_attempt'],
            scenario=game_state.get('scenario', ''),
            current_mindset=game_state.get('current_mindset', self.mindset or '尚未形成明确的心理状态'),
            player_states=self._format_player_states(game_state['player_states']),
            previous_actions=self._format_previous_actions(game_state['previous_actions']),
            opinions=self._format_opinions(),
            backstab_numbers=self.backstab_attempts
        )
        
        # Print raw prompt
        print("\n📤 Sending Negotiation Prompt:")
        print("=" * 50)
        print("=" * 50)
        
        # Get response from LLM
        response = self._llm_client.get_response(prompt)
        
        # Print raw response with request ID
        print("\n📥 Received Negotiation Response:")
        print(f"Request ID: {response.request_id}")
        
        # Parse the response into a PlayerAction
        action = self._parse_negotiation_response(response, game_state)
        action.request_id = response.request_id
        return action
    
    def decide_backstab(self, game_state: Dict) -> Tuple[bool, str, str]:
        """
        Decide whether to attempt a backstab during execution phase.
        
        Args:
            game_state: Current state of the game including:
                - round: Current round number
                - your_damage: Amount of damage you promised
                - player_damages: Dict of player damages
                - current_mindset: Player's current psychological state
        
        Returns:
            Tuple[bool, str, str]: (backstab decision, thinking process, request_id)
        """
        prompt = self._prompt_templates["backstab"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            hp=self.hp,
            backstab_chance=self.get_current_backstab_chance() * 100,
            your_damage=game_state.get('your_damage', 0),
            current_mindset=game_state.get('current_mindset', self.mindset or '尚未形成明确的心理状态'),
            player_damages=self._format_player_damages(game_state['player_damages']),
            opinions=self._format_opinions()
        )
        
        # Print raw prompt
        print("\n📤 Sending Backstab Decision Prompt:")
        print("=" * 50)
        print("=" * 50)
        
        response = self._llm_client.get_response(prompt)
        
        # Print raw response with request ID
        print("\n📥 Received Backstab Decision Response:")
        print(f"Request ID: {response.request_id}")
        
        try:
            # Handle nested content structure
            content = response.content.get("content", {})
            if not content:
                content = response.content  # If not nested, use the content directly
            
            decision = content.get("decision", False)
            thinking = response.content.get("thinking", "")
            
            return decision, thinking, response.request_id
            
        except Exception as e:
            print(f"Error parsing backstab decision: {e}")
            return False, "Error in decision making, choosing not to backstab.", response.request_id
    
    def _parse_negotiation_response(self, response: LLMResponse, game_state: Dict) -> PlayerAction:
        """
        Parse the LLM response into a PlayerAction.
        Expects response.content to be a dictionary with action details.
        """
        try:
            # Create PlayerAction with default Refuse
            action = PlayerAction(
                action_type="Refuse",
                speech="我需要更多时间思考。"
            )
            
            # Parse the response content
            content = response.content
            if isinstance(content, str):
                import json
                try:
                    content = json.loads(content)
                except json.JSONDecodeError as e:
                    print(f"\n⚠️ Failed to parse response as JSON: {str(e)}")
                    print("Raw response:", content)
                    # Try to clean the response string
                    cleaned_content = content.strip().replace('\n', '')
                    print("Cleaned response:", cleaned_content)
                    try:
                        content = json.loads(cleaned_content)
                        print("Successfully parsed cleaned response")
                    except json.JSONDecodeError:
                        print("⚠️ Failed to parse cleaned response")
                        return action

            # Get the actual content from nested structure if needed
            if isinstance(content, dict):
                content = content.get('content', content)
            
            # Parse action details
            if content and isinstance(content, dict):
                if "action" in content and content["action"] in ["Offer", "Refuse", "Kill", "Lynch"]:
                    action.action_type = content["action"]
                    action.damage_amount = content.get("damage")
                    
                    # Handle Kill or Lynch action target
                    if action.action_type in ["Kill", "Lynch"] and "target" in content:
                        target_name = content["target"]
                        # Game state should include a name to id mapping
                        if "player_name_to_id" in game_state:
                            action.target_player_id = game_state["player_name_to_id"].get(target_name)
                        else:
                            print("\n⚠️ Missing player_name_to_id mapping in game state")
                    action.speech = content.get("speech", "")
                    action.thinking = response.content.get("thinking", "")
                    
                    # Update mindset based on thinking
                    self.mindset = response.content.get("mindset", self.mindset)
                else:
                    print(f"\n⚠️ Invalid or missing action in content: {content}")
            else:
                print(f"\n⚠️ Invalid content structure: {content}")
            
            return action
            
        except Exception as e:
            print(f"\n❌ Error parsing negotiation response: {str(e)}")
            print("Response:", response.content)
            return PlayerAction(
                action_type="Refuse",
                thinking=f"Error parsing response: {str(e)}",
                speech="我需要更多时间思考。"
            )
    
    def _format_player_states(self, player_states: Dict) -> str:
        """Format player states for prompt."""
        return "\n".join([
            f"- {name}: HP={state['hp']}" for name, state in player_states.items()
            if name != self.name
        ])
    
    def _format_previous_actions(self, previous_actions: list) -> str:
        """
        Format previous actions for prompt.
        Each action contains:
        - player: Name of the player
        - action_type: "Offer", "Refuse", "Kill", or "Lynch"
        - damage_amount: (Optional) Amount of damage offered
        - target: (Optional) Target player for Kill/Lynch action
        - supporters: (Optional) List of supporting players for Lynch action
        - speech: What the player said during their action
        """
        formatted_actions = []
        for action in previous_actions:
            # Format the action part
            action_str = f"- {action['player']}: {action['action_type']}"
            if 'damage_amount' in action:
                action_str += f" ({action['damage_amount']} damage)"
            if 'target' in action:
                action_str += f" -> {action['target']}"
            
            # Add the speech if present
            if 'speech' in action and action['speech']:
                action_str += f"\n  Speech: \"{action['speech']}\""
            
            formatted_actions.append(action_str)
        
        return "\n".join(formatted_actions)
    
    def _format_player_damages(self, player_damages: Dict) -> str:
        """Format player damages for prompt."""
        return "\n".join([
            f"- {name}: {damage} damage" for name, damage in player_damages.items()
            if name != self.name
        ])
    
    def _format_opinions(self) -> str:
        """Format opinions for prompt."""
        return "\n".join([
            f"- {name}: {opinion}" for name, opinion in self.opinions.items()
        ])

    def update_mindset(self, round_number: int, context: Dict) -> Tuple[str, str]:
        """
        Update the player's mindset based on recent events.
        
        Args:
            round_number: Current round number
            context: Dictionary containing details about the recent event
            
        Returns:
            Tuple[str, str]: (new mindset, request_id)
        """
        print("\n📤 Sending mindset update prompt...")
        prompt = self._prompt_templates["mindset"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            hp=self.hp,
            round_number=round_number,
            current_mindset=self.mindset or "尚未形成明确的心理状态",
            context=json.dumps(context, ensure_ascii=False)
        )
        
        
        response = self._llm_client.get_response(prompt)

        try:
            # Parse the response content
            content = response.content
            if isinstance(content, str):
                content = json.loads(content)
            
            # Get the mindset from the parsed content
            new_mindset = content.get("mindset", self.mindset)
            
            # Update the player's mindset
            self.mindset = new_mindset
            
            return new_mindset, response.request_id
            
        except Exception as e:
            print(f"\n⚠️ Error updating mindset: {str(e)}")
            return self.mindset, response.request_id

    def introduce_self(self) -> Tuple[str, str]:
        """
        Generate a self introduction for the player.
        
        Returns:
            Tuple[str, str]: (introduction text, request_id)
        """
        prompt = self._prompt_templates["intro"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            current_mindset=self.mindset,
            opinions=self._format_opinions()
        )
        
        response = self._llm_client.get_response(prompt)
        
        try:
            # Parse the response content
            content = response.content
            if isinstance(content, str):
                import json
                content = json.loads(content)
            
            # Get the thinking and introduction from the parsed content
            thinking = content.get("thinking", "")
            content_obj = content.get("content", {})
            introduction = content_obj.get("intro", "")
            
            return thinking, introduction, response.request_id
            
        except Exception as e:
            print(f"\n⚠️ Error parsing introduction: {str(e)}")
            return "", "我需要一点时间思考...", response.request_id
