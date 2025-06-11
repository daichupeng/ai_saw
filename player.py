from dataclasses import dataclass, field
from typing import Dict, Optional, Literal, Tuple
from pathlib import Path
import json
from llm_client import LLMClient, LLMResponse

# Type definitions
ActionType = Literal["Offer", "Refuse", "Kill"]
PhaseType = Literal["negotiation", "execution"]

@dataclass
class PlayerAction:
    """Class to represent a player's action during negotiation."""
    action_type: ActionType
    damage_amount: Optional[int] = None  # For Offer action
    target_player: Optional[str] = None  # For Kill action
    thinking: str = ""
    speech: str = ""
    request_id: Optional[str] = None  # Request ID from LLM response

@dataclass
class Player:
    """Class representing a player in the AI Saw game."""
    
    # Required initialization attributes
    name: str
    model: str
    background_prompt: str
    
    # Optional initialization attributes with defaults
    hp: int = 7
    backstab_success_rate: float = 0.30
    opinions: Dict[str, str] = field(default_factory=dict)  # player_name -> opinion (descriptive string)
    backstab_attempts: int = 0
    
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
            "opinion_update": "opinion_update.txt"
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
    
    def update_opinion(self, player_name: str, action_type: str, context: Dict) -> Tuple[str, str, str, str]:
        """
        Update opinion about another player based on their actions.
        
        Args:
            player_name: Name of the player to update opinion about
            action_type: Type of action they took
            context: Additional context about the action
            
        Returns:
            Tuple[str, str, str, str]: (observer_name, subject_name, opinion, request_id)
            - observer_name: Name of the player making the observation
            - subject_name: Name of the player being observed
            - opinion: The updated opinion content
            - request_id: The unique identifier for this opinion update request
        """
        prompt = self._prompt_templates["opinion_update"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            target_player=player_name,
            action_type=action_type,
            context=context,
            current_opinion=self.opinions.get(player_name, "No previous opinion")
        )
        
        response = self._llm_client.get_response(prompt)
        
        opinion = ""
        try:
            # First try to parse the content as JSON
            if isinstance(response.content, str):
                content = json.loads(response.content)
            else:
                content = response.content
                
            # Extract the opinion from the content
            opinion = content.get("opinion", "")
                
            # Update the opinion if we found one
            if opinion:
                self.opinions[player_name] = opinion
                print(f"\n💭 Successfully parsed and stored opinion: {opinion}")
                
                # Log the successful update for test log
                if hasattr(self, '_current_test_log'):
                    self._current_test_log.append({
                        "stage": "Opinion Update Response",
                        "description": "Successfully parsed and stored opinion",
                        "raw_response": response.content,
                        "parsed_opinion": opinion
                    })
            else:
                print("\n⚠️ No opinion found in parsed content")
                
        except json.JSONDecodeError as e:
            print(f"\n⚠️ Failed to parse JSON response: {str(e)}")
            # Fallback to using the entire content as the opinion
            if response.content:
                opinion = response.content.strip()
                self.opinions[player_name] = opinion
                print(f"\n💭 Stored raw content as opinion: {opinion}")
        except Exception as e:
            print(f"\n❌ Error updating opinion: {str(e)}")
            # Store the raw content as opinion in case of other errors
            if response.content:
                opinion = response.content.strip()
                self.opinions[player_name] = opinion
                print(f"\n💭 Stored raw content as opinion due to error: {opinion}")
            else:
                opinion = "Error forming opinion"
        
        return self.name, player_name, opinion, response.request_id
    
    def negotiate(self, game_state: Dict) -> PlayerAction:
        """
        Make a decision during the negotiation phase.
        
        Args:
            game_state: Current state of the game including:
                - round_number: Current round number
                - damage_required: Total damage to be distributed
                - player_states: Dict of player states (hp, etc.)
                - negotiation_attempt: Which attempt this is at negotiating
                - previous_actions: List of previous actions in this negotiation, including:
                    - player: Name of the player
                    - action_type: "Offer", "Refuse", or "Kill"
                    - damage_amount: (Optional) Amount of damage offered
                    - target: (Optional) Target player for Kill action
                    - speech: What the player said during their action
                
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
            player_states=self._format_player_states(game_state['player_states']),
            previous_actions=self._format_previous_actions(game_state['previous_actions']),
            opinions=self._format_opinions()
        )
        
        # Print raw prompt
        print("\n📤 Sending Negotiation Prompt:")
        print("=" * 50)
        # print(prompt)
        print("=" * 50)
        
        # Get response from LLM
        response = self._llm_client.get_response(prompt)
        
        # Print raw response with request ID
        print("\n📥 Received Negotiation Response:")
        print(f"Request ID: {response.request_id}")
        # print(f"Response: {response}")
        
        # Parse the response into a PlayerAction
        action = self._parse_negotiation_response(response, game_state)
        action.request_id = response.request_id
        return action
    
    def decide_backstab(self, game_state: Dict) -> Tuple[bool, str, str]:
        """
        Decide whether to attempt a backstab during execution phase.
        
        Returns:
            Tuple[bool, str, str]: (backstab decision, thinking process, request_id)
        """
        prompt = self._prompt_templates["backstab"].format(
            name=self.name,
            background_prompt=self.background_prompt,
            hp=self.hp,
            backstab_chance=self.get_current_backstab_chance() * 100,
            your_damage=game_state.get('your_damage', 0),
            player_damages=self._format_player_damages(game_state['player_damages']),
            opinions=self._format_opinions()
        )
        
        # Print raw prompt
        print("\n📤 Sending Backstab Decision Prompt:")
        print("=" * 50)
        # print(prompt)
        print("=" * 50)
        
        response = self._llm_client.get_response(prompt)
        
        # Print raw response with request ID
        print("\n📥 Received Backstab Decision Response:")
        print(f"Request ID: {response.request_id}")
        # print(f"Response: {response}")
        
        try:
            # Handle both string and dictionary content
            content = response.content
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    # Fallback to simple text parsing
                    decision = content.strip().lower() == "true"
                    return decision, response.thinking, response.request_id
            
            # At this point content should be a dictionary
            decision = content.get("content", {}).get("decision", False)
            thinking = content.get("thinking", response.thinking)
            
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
                thinking=response.thinking,
                speech="I need more time to think about this."
            )
            
            # Get content as dictionary
            content = response.content
            if not isinstance(content, dict):
                print(f"\n⚠️ Response content is not a dictionary: {content}")
                return action
                
            # Parse action details
            if "action" in content and content["action"] in ["Offer", "Refuse", "Kill"]:
                action.action_type = content["action"]
                action.damage_amount = content.get("damage")
                action.target_player = content.get("target")
                action.speech = content.get("speech", "")
                action.thinking = response.thinking
            else:
                print(f"\n⚠️ Invalid or missing action in content: {content}")
            
            return action
            
        except Exception as e:
            print(f"\n❌ Error parsing negotiation response: {str(e)}")
            print("Response:", response)
            return PlayerAction(
                action_type="Refuse",
                thinking=f"Error parsing response: {str(e)}",
                speech="I need more time to think about this."
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
        - action_type: "Offer", "Refuse", or "Kill"
        - damage_amount: (Optional) Amount of damage offered
        - target: (Optional) Target player for Kill action
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
