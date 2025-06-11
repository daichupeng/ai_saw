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
            player_id="test_player_1",
            name="TestPlayer",
            model="gpt-3.5-turbo",
            background_prompt="You are a strategic and cautious player who values survival above all else. "
                            "You prefer to build alliances but will not hesitate to take decisive action when necessary."
        )
        
        log_entries.append({
            "stage": "Player Creation",
            "description": "Successfully created player instance",
            "parsed_response": {
                "player_id": player.player_id,
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
    
    # Create a mock game state with player IDs
    game_state = {
        "round_number": 2,
        "damage_required": 4,
        "negotiation_attempt": 1,
        "player_states": {
            "player_2": {"hp": 6},
            "player_3": {"hp": 4},
            "player_4": {"hp": 5}
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
        ],
        "player_name_to_id": {
            "Player2": "player_2",
            "Player3": "player_3",
            "Player4": "player_4"
        }
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
                "target_player_id": action.target_player_id,
                "speech": action.speech,
                "thinking": action.thinking
            }
        })
        
        print("\n✅ Decision made:")
        print(f"Action Type: {action.action_type}")
        if action.damage_amount is not None:
            print(f"Damage Amount: {action.damage_amount}")
        if action.target_player_id is not None:
            print(f"Target Player ID: {action.target_player_id}")
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
            current_opinion=player.opinions.get("player_2", "No previous opinion")
        )
        
        # Log the prompt
        log_entries.append({
            "stage": "Opinion Update Prompt",
            "description": "Generated opinion update prompt",
            "prompt": raw_prompt
        })
        
        # Update opinion using player ID
        observer, subject, opinion, request_id = player.update_opinion(
            target_player_id="player_2",
            target_player_name="Player2",
            action_type="protect",
            context=context
        )
        
        # Log the results
        log_entries.append({
            "stage": "Opinion Update Result",
            "description": "Successfully updated opinion",
            "parsed_response": {
                "observer": observer,
                "subject": subject,
                "opinion": opinion,
                "request_id": request_id
            }
        })
        
        print("\n✅ Opinion updated:")
        print(f"Observer: {observer}")
        print(f"Subject: {subject}")
        print(f"Opinion: {opinion}")
        print(f"Request ID: {request_id}")
        
    except Exception as e:
        log_entries.append({
            "stage": "Opinion Update",
            "description": "Failed to update opinion",
            "error": str(e)
        })
        print(f"\n❌ Error during opinion update: {str(e)}")

def test_backstab(player: Player, log_entries: list) -> None:
    """Test the backstab decision functionality."""
    print("\n🗡️ Testing Backstab Decision...")
    
    # Create mock game state for backstab
    game_state = {
        "round": 3,
        "your_damage": 2,
        "player_damages": {
            "player_2": 1,
            "player_3": 2,
            "player_4": 1
        }
    }
    
    log_entries.append({
        "stage": "Backstab Test Setup",
        "description": "Created mock game state for backstab decision",
        "parsed_response": game_state
    })
    
    try:
        print("\n🤔 Making backstab decision...")
        will_backstab, thinking, request_id = player.decide_backstab(game_state)
        
        log_entries.append({
            "stage": "Backstab Decision",
            "description": "Successfully made backstab decision",
            "parsed_response": {
                "will_backstab": will_backstab,
                "thinking": thinking,
                "request_id": request_id
            }
        })
        
        print("\n✅ Decision made:")
        print(f"Will Backstab: {will_backstab}")
        print("\nThinking Process:")
        print(thinking)
        print(f"\nRequest ID: {request_id}")
        
    except Exception as e:
        log_entries.append({
            "stage": "Backstab Decision",
            "description": "Failed to make backstab decision",
            "error": str(e)
        })
        print(f"\n❌ Error during backstab decision: {str(e)}")

def main():
    """Run all player tests."""
    print("\n🎮 Starting Player Tests")
    
    # Create output directory if it doesn't exist
    output_dir = project_root / "test_output"
    output_dir.mkdir(exist_ok=True)
    
    # Create test player
    player, log_entries = create_test_player()
    if not player:
        print("\n❌ Failed to create test player")
        save_test_log(log_entries, output_dir / "test_log.txt")
        return
    
    print("\n✅ Test player created successfully")
    
    # Run negotiation test
    test_negotiate(player, log_entries)
    
    # Run opinion update test
    test_opinion_update(player, log_entries)
    
    # Run backstab test
    test_backstab(player, log_entries)
    
    # Save test log
    save_test_log(log_entries, output_dir / "test_log.txt")
    print("\n📝 Test log saved to test_output/test_log.txt")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error during tests: {str(e)}") 