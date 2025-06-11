import os
import sys
import json
import yaml
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from player import Player, PlayerAction
from llm_client import LLMClient, LLMResponse

def save_test_results(results: list, output_file: Path):
    """Save test results to a file with detailed formatting."""
    with open(output_file, 'w') as f:
        f.write("AI Saw - Player Class Test Results\n")
        f.write("=" * 50 + "\n")
        f.write(f"Test Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for test_result in results:
            f.write(f"\nTest Case: {test_result['name']}\n")
            f.write("-" * 30 + "\n")
            f.write(f"Description: {test_result['description']}\n\n")
            
            if 'prompt' in test_result:
                f.write("Prompt:\n")
                f.write(test_result['prompt'] + "\n\n")
            
            f.write("Result: " + ("✅ Passed" if test_result['success'] else "❌ Failed") + "\n")
            
            if 'response' in test_result:
                f.write("\nResponse:\n")
                f.write(json.dumps(test_result['response'], indent=2) + "\n")
            
            if 'error' in test_result:
                f.write("\nError:\n")
                f.write(test_result['error'] + "\n")
            
            f.write("\n" + "=" * 50 + "\n")

@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for testing."""
    mock_client = Mock(spec=LLMClient)
    
    def mock_get_response(prompt: str) -> LLMResponse:
        if "opinion_update" in prompt:
            return LLMResponse(
                content={"opinion": "This player seems trustworthy"},
                request_id="test-123"
            )
        elif "negotiation" in prompt:
            return LLMResponse(
                content={
                    "action": "Offer",
                    "damage": 2,
                    "speech": "I'll help with the damage.",
                    "thinking": "Strategic cooperation is important"
                },
                request_id="test-456"
            )
        else:  # backstab
            return LLMResponse(
                content={
                    "decision": False,
                    "thinking": "It's too risky to backstab now"
                },
                request_id="test-789"
            )
    
    mock_client.get_response.side_effect = mock_get_response
    return mock_client

def test_player(mock_llm_client):
    """Test all functions of the Player class."""
    results = []
    
    # Create a test player with mock LLM client
    player = Player(
        player_id="test_player",
        name="TestPlayer",
        model="gpt-3.5-turbo",
        background_prompt="You are a strategic and cautious player who values survival above all else."
    )
    player._llm_client = mock_llm_client
    
    # Test 1: Basic player initialization
    results.append({
        "name": "Player Initialization",
        "description": "Test basic player attributes after initialization",
        "success": all([
            player.name == "TestPlayer",
            player.model == "gpt-3.5-turbo",
            player.hp == 7,
            player.backstab_success_rate == 0.30,
            isinstance(player.opinions, dict),
            player.backstab_attempts == 0
        ])
    })
    
    # Test 2: HP and damage mechanics
    player.take_damage(3)
    results.append({
        "name": "HP and Damage Mechanics",
        "description": "Test HP reduction and damage application",
        "success": player.hp == 4 and player.is_alive()
    })
    
    # Test 3: Backstab chance calculation
    player.backstab_attempts = 2
    results.append({
        "name": "Backstab Chance Calculation",
        "description": "Test backstab success rate reduction with attempts",
        "success": player.get_current_backstab_chance() == 0.20
    })
    
    # Test 4: Opinion update
    test_case = {
        "name": "Opinion Update",
        "description": "Test updating opinion about another player"
    }
    
    try:
        observer, subject, opinion, request_id = player.update_opinion(
            target_player_id="player2",
            target_player_name="Player2",
            action_type="Offer",
            context={"damage": 2}
        )
        test_case["success"] = all([
            observer == "TestPlayer",
            subject == "Player2",
            opinion == "This player seems trustworthy",
            request_id == "test-123"
        ])
        test_case["response"] = {"opinion": opinion}
    except Exception as e:
        test_case["success"] = False
        test_case["error"] = str(e)
    
    results.append(test_case)
    
    # Test 5: Negotiation
    game_state = {
        "round_number": 1,
        "damage_required": 3,
        "negotiation_attempt": 1,
        "player_states": {
            "Player2": {"hp": 5},
            "Player3": {"hp": 5}
        },
        "previous_actions": [
            {
                "player": "Player2",
                "action_type": "Offer",
                "damage_amount": 1,
                "speech": "I'll take some damage to help."
            }
        ],
        "player_name_to_id": {
            "Player2": "player2",
            "Player3": "player3"
        }
    }
    
    test_case = {
        "name": "Negotiation Decision",
        "description": "Test negotiation phase decision making"
    }
    
    try:
        action = player.negotiate(game_state)
        test_case["success"] = all([
            isinstance(action, PlayerAction),
            action.action_type == "Offer",
            action.damage_amount == 2,
            action.speech == "I'll help with the damage.",
            action.thinking == "Strategic cooperation is important",
            action.request_id == "test-456"
        ])
        test_case["response"] = {
            "action_type": action.action_type,
            "damage_amount": action.damage_amount,
            "speech": action.speech,
            "thinking": action.thinking
        }
    except Exception as e:
        test_case["success"] = False
        test_case["error"] = str(e)
    
    results.append(test_case)
    
    # Test 6: Backstab decision
    game_state = {
        "your_damage": 2,
        "player_damages": {
            "Player2": 1,
            "Player3": 0
        }
    }
    
    test_case = {
        "name": "Backstab Decision",
        "description": "Test backstab decision making"
    }
    
    try:
        decision, thinking, request_id = player.decide_backstab(game_state)
        test_case["success"] = all([
            decision is False,
            thinking == "It's too risky to backstab now",
            request_id == "test-789"
        ])
        test_case["response"] = {
            "decision": decision,
            "thinking": thinking
        }
    except Exception as e:
        test_case["success"] = False
        test_case["error"] = str(e)
    
    results.append(test_case)
    
    # Test 7: Formatting functions
    results.append({
        "name": "Formatting Functions",
        "description": "Test various formatting helper functions",
        "success": all([
            isinstance(player._format_player_states({"Player2": {"hp": 5}}), str),
            isinstance(player._format_previous_actions([{"player": "Player2", "action_type": "Offer"}]), str),
            isinstance(player._format_player_damages({"Player2": 2}), str),
            isinstance(player._format_opinions(), str)
        ])
    })
    
    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = project_root / "tests" / f"player_test_results_{timestamp}.txt"
    save_test_results(results, output_file)
    print(f"\n📝 Test results saved to: {output_file}")
    
    # Print summary
    print("\n📊 Test Summary:")
    print("=" * 50)
    successful_tests = sum(1 for test in results if test["success"])
    total_tests = len(results)
    print(f"Success rate: {successful_tests}/{total_tests}")
    
    if successful_tests < total_tests:
        print("\nFailed tests:")
        for test in results:
            if not test["success"]:
                print(f"- {test['name']}: {test.get('error', 'Unknown error')}")
    
    # Assert all tests passed
    assert all(test["success"] for test in results), "Some tests failed"

if __name__ == "__main__":
    pytest.main([__file__]) 