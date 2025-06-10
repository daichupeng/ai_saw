import os
import sys
import yaml
import json
from pathlib import Path
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from player import Player

def save_test_log(log_entries: list, output_file: Path):
    """Save test log entries to a file with detailed formatting."""
    with open(output_file, 'w') as f:
        f.write("AI Saw - Player Test Log\n")
        f.write("=" * 50 + "\n")
        f.write(f"Test Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for entry in log_entries:
            f.write(f"\n{entry['stage']}\n")
            f.write("-" * len(entry['stage']) + "\n")
            
            if 'description' in entry:
                f.write(f"\nDescription: {entry['description']}\n")
            
            if 'prompt' in entry:
                f.write("\nPrompt:\n")
                f.write("-" * 20 + "\n")
                f.write(entry['prompt'] + "\n")
            
            if 'raw_response' in entry:
                f.write("\nRaw Response:\n")
                f.write("-" * 20 + "\n")
                if isinstance(entry['raw_response'], dict):
                    f.write(json.dumps(entry['raw_response'], indent=2) + "\n")
                else:
                    f.write(str(entry['raw_response']) + "\n")
            
            if 'parsed_response' in entry:
                f.write("\nParsed Response:\n")
                f.write("-" * 20 + "\n")
                f.write(json.dumps(entry['parsed_response'], indent=2) + "\n")
            
            if 'error' in entry:
                f.write("\nError:\n")
                f.write("-" * 20 + "\n")
                f.write(entry['error'] + "\n")
            
            f.write("\n" + "=" * 50 + "\n")

def create_test_player():
    """Create a test player with configuration loaded from config file."""
    
    log_entries = []
    
    # Load API key from config
    config_path = project_root / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                os.environ["OPENAI_API_KEY"] = config['openai']['api_key']
                
            log_entries.append({
                "stage": "Configuration Loading",
                "description": "Successfully loaded API key from config file"
            })
        except Exception as e:
            log_entries.append({
                "stage": "Configuration Loading",
                "description": "Failed to load API key from config file",
                "error": str(e)
            })
            return None, log_entries
    else:
        log_entries.append({
            "stage": "Configuration Loading",
            "description": "Config file not found",
            "error": "Missing config.yaml file"
        })
        return None, log_entries
    
    # Create player
    try:
        player = Player(
            name="TestPlayer",
            model="gpt-3.5-turbo",
            background_prompt="You are a strategic and cautious player who values survival above all else. "
                            "You prefer to build alliances but will not hesitate to take decisive action when necessary."
        )
        
        log_entries.append({
            "stage": "Player Creation",
            "description": "Successfully created player instance",
            "parsed_response": {
                "name": player.name,
                "model": player.model,
                "hp": player.hp,
                "backstab_success_rate": player.backstab_success_rate,
                "prompts_loaded": list(player._prompt_templates.keys())
            }
        })
        
        return player, log_entries
        
    except Exception as e:
        log_entries.append({
            "stage": "Player Creation",
            "description": "Failed to create player instance",
            "error": str(e)
        })
        return None, log_entries

def test_negotiate(player: Player, log_entries: list):
    """Test the player's negotiate function with a mock game state."""
    
    # Create a mock game state
    game_state = {
        "round_number": 2,
        "damage_required": 4,
        "negotiation_attempt": 1,
        "player_states": {
            "Player2": {"hp": 6},
            "Player3": {"hp": 4},
            "Player4": {"hp": 5}
        },
        "previous_actions": [
            {
                "player": "Player2",
                "action_type": "Offer",
                "damage_amount": 1,
                "speech": "I'll take one damage to show my commitment to the group."
            },
            {
                "player": "Player3",
                "action_type": "Refuse",
                "speech": "I'm too low on health to take any damage this round."
            }
        ]
    }
    
    log_entries.append({
        "stage": "Game State Setup",
        "description": "Created mock game state for negotiation test",
        "parsed_response": game_state
    })
    
    # Get the raw prompt that will be sent to the LLM
    raw_prompt = player._prompt_templates["negotiation"].format(
        name=player.name,
        background_prompt=player.background_prompt,
        hp=player.hp,
        round_number=game_state['round_number'],
        damage_required=game_state['damage_required'],
        negotiation_attempt=game_state['negotiation_attempt'],
        player_states=player._format_player_states(game_state['player_states']),
        previous_actions=player._format_previous_actions(game_state['previous_actions']),
        opinions=player._format_opinions()
    )
    
    log_entries.append({
        "stage": "Prompt Generation",
        "description": "Generated negotiation prompt",
        "prompt": raw_prompt
    })
    
    try:
        print("\n🤔 Making decision...")
        action = player.negotiate(game_state)
        
        log_entries.append({
            "stage": "Negotiation Decision",
            "description": "Successfully received and parsed response",
            "parsed_response": {
                "action_type": action.action_type,
                "damage_amount": action.damage_amount,
                "target_player": action.target_player,
                "speech": action.speech,
                "thinking": action.thinking
            }
        })
        
        print("\n✅ Decision made:")
        print(f"Action Type: {action.action_type}")
        if action.damage_amount is not None:
            print(f"Damage Amount: {action.damage_amount}")
        if action.target_player is not None:
            print(f"Target Player: {action.target_player}")
        print(f"Speech: {action.speech}")
        print("\nThinking Process:")
        print(action.thinking)
        
        return action
        
    except Exception as e:
        log_entries.append({
            "stage": "Negotiation Decision",
            "description": "Failed to get or parse response",
            "error": str(e)
        })
        print(f"\n❌ Error during negotiation: {str(e)}")
        return None

def test_opinion_update(player: Player, log_entries: list) -> None:
    """Test the opinion update functionality."""
    print("\n🔄 Testing Opinion Update...")
    
    # Add test entry
    log_entries.append({
        "stage": "Opinion Update Test",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "Testing opinion update after a player's action"
    })
    
    try:
        # Test scenario: Player2 takes a protective action
        context = {
            "round": 2,
            "previous_hp": 6,
            "current_hp": 5,
            "voluntary": True,
            "protected_player": "Player3",
            "reason": "To save Player3 from elimination"
        }
        
        print("\n📊 Testing opinion update for protective action:")
        print(f"Context: {json.dumps(context, indent=2)}")
        
        # Get the raw prompt that will be sent to the LLM
        raw_prompt = player._prompt_templates["opinion_update"].format(
            name=player.name,
            background_prompt=player.background_prompt,
            target_player="Player2",
            action_type="protect",
            context=context,
            current_opinion=player.opinions.get("Player2", "No previous opinion")
        )
        
        # Log the prompt
        log_entries.append({
            "stage": "Opinion Update Prompt",
            "description": "Generated opinion update prompt",
            "prompt": raw_prompt
        })
        
        # Temporarily attach the log entries to the player for response logging
        player._current_test_log = log_entries
        
        # Update opinion about Player2's protective action
        player.update_opinion("Player2", "protect", context)
        
        # Remove the temporary log entries reference
        delattr(player, '_current_test_log')
        
        # Log the updated opinion and response
        updated_opinion = player.opinions.get("Player2", "No opinion formed")
        print(f"\n✨ Updated opinion about Player2: {updated_opinion}")
        
        # Add final results to log
        log_entries.append({
            "stage": "Opinion Update Results",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": "Opinion update completed",
            "parsed_response": {
                "context": context,
                "updated_opinion": updated_opinion,
                "all_opinions": player.opinions
            }
        })
        
    except Exception as e:
        error_msg = f"Error in opinion update test: {str(e)}"
        print(f"\n❌ {error_msg}")
        log_entries.append({
            "stage": "Opinion Update Error",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": error_msg,
            "error": str(e)
        })
        # Clean up temporary log entries reference if error occurs
        if hasattr(player, '_current_test_log'):
            delattr(player, '_current_test_log')
        raise

def test_backstab(player: Player, log_entries: list) -> None:
    """Test the backstab decision functionality."""
    print("\n🗡️ Testing Backstab Decision...")
    
    # Add test entry
    log_entries.append({
        "stage": "Backstab Test",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "Testing backstab decision during execution phase"
    })
    
    try:
        # Test scenario: Player is considering backstabbing during execution
        game_state = {
            "round": 2,
            "your_damage": 1,  # You agreed to take 1 damage
            "player_damages": {
                "Player2": 2,  # Player2 agreed to take more damage
                "Player3": 0,  # Player3 refused any damage
                "Player4": 1   # Player4 agreed to take some damage
            }
        }
        
        print("\n📊 Testing backstab decision with game state:")
        print(f"Game State: {json.dumps(game_state, indent=2)}")
        
        # Get the raw prompt that will be sent to the LLM
        raw_prompt = player._prompt_templates["backstab"].format(
            name=player.name,
            background_prompt=player.background_prompt,
            hp=player.hp,
            backstab_chance=player.get_current_backstab_chance() * 100,
            your_damage=game_state['your_damage'],
            player_damages=player._format_player_damages(game_state['player_damages']),
            opinions=player._format_opinions()
        )
        
        # Log the prompt
        log_entries.append({
            "stage": "Backstab Prompt",
            "description": "Generated backstab decision prompt",
            "prompt": raw_prompt
        })
        
        # Temporarily attach the log entries to the player for response logging
        player._current_test_log = log_entries
        
        # Make backstab decision
        decision, thinking = player.decide_backstab(game_state)
        
        # Remove the temporary log entries reference
        delattr(player, '_current_test_log')
        
        # Print the decision
        print(f"\n🤔 Backstab Decision: {'Yes' if decision else 'No'}")
        print(f"Thinking Process: {thinking}")
        
        # Add results to log
        log_entries.append({
            "stage": "Backstab Results",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": "Backstab decision completed",
            "parsed_response": {
                "decision": decision,
                "thinking": thinking,
                "game_state": game_state,
                "backstab_chance": player.get_current_backstab_chance() * 100
            }
        })
        
    except Exception as e:
        error_msg = f"Error in backstab test: {str(e)}"
        print(f"\n❌ {error_msg}")
        log_entries.append({
            "stage": "Backstab Error",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": error_msg,
            "error": str(e)
        })
        # Clean up temporary log entries reference if error occurs
        if hasattr(player, '_current_test_log'):
            delattr(player, '_current_test_log')
        raise

if __name__ == "__main__":
    # Initialize log entries list
    log_entries = []
    
    # Create player
    player, creation_logs = create_test_player()
    log_entries.extend(creation_logs)
    
    if player:
        # Test negotiation
        # test_negotiate(player, log_entries)
        test_opinion_update(player, log_entries)
        test_backstab(player, log_entries)
        
        # Save test results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = project_root / "tests" / f"player_test_log_{timestamp}.txt"
        save_test_log(log_entries, output_file)
        print(f"\n📝 Test log saved to: {output_file}")
    else:
        print("\n❌ Tests aborted due to player creation failure") 