import os
import sys
from pathlib import Path
import pytest
from unittest.mock import Mock, patch
import json
from player import Player, PlayerAction
from llm_client import LLMClient, LLMResponse, LLMError

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def print_response(response: str, parsed_thinking: str, parsed_content: str):
    """Helper function to print original response and parsed components."""
    print("\nOriginal response:")
    print("=" * 50)
    print(response)
    print("=" * 50)
    print("\nParsed components:")
    print("THINKING:")
    print("-" * 20)
    print(parsed_thinking or "(empty)")
    print("\nCONTENT:")
    print("-" * 20)
    print(parsed_content or "(empty)")
    print("-" * 50)

def test_llm_client():
    print("\n🔍 Testing LLMClient functionality...")
    
    # Test initialization
    print("\n1️⃣ Testing initialization...")
    try:
        # Test with environment variable
        os.environ["OPENAI_API_KEY"] = "test_key"
        client = LLMClient()
        assert client.model == "gpt-3.5-turbo", "Incorrect default model"
        assert client._api_key == "test_key", "API key not set correctly"
        print("✅ Basic initialization successful")
        
        # Test system prompt loading
        assert hasattr(client, '_system_prompt'), "System prompt not loaded"
        assert len(client._system_prompt) > 0, "System prompt is empty"
        assert "AI Saw game" in client._system_prompt, "System prompt content incorrect"
        print("✅ System prompt loaded successfully")
        print("\nSystem Prompt:")
        print("=" * 50)
        print(client._system_prompt)
        print("=" * 50)
        
    except AssertionError as e:
        print(f"❌ Initialization test failed: {str(e)}")
        return
    except Exception as e:
        print(f"❌ Unexpected error during initialization: {str(e)}")
        return

    # Test response parsing
    print("\n2️⃣ Testing response parsing...")
    try:
        # Test well-formatted response
        print("\nTesting well-formatted response:")
        response = """[THINKING]
This is my thought process
[CONTENT]
This is the actual content"""
        thinking, content = client._parse_response(response)
        assert thinking == "This is my thought process", "Thinking section not parsed correctly"
        assert content == "This is the actual content", "Content section not parsed correctly"
        print_response(response, thinking, content)
        print("✅ Well-formatted response parsed correctly")
        
        # Test response with only thinking
        print("\nTesting thinking-only response:")
        response = "[THINKING]\nJust thinking"
        thinking, content = client._parse_response(response)
        assert thinking == "Just thinking", "Thinking-only response not parsed correctly"
        assert content == "", "Content should be empty for thinking-only response"
        print_response(response, thinking, content)
        print("✅ Thinking-only response handled correctly")
        
        # Test response with no markers
        print("\nTesting unmarked response:")
        response = "Plain response"
        thinking, content = client._parse_response(response)
        assert thinking == "", "Thinking should be empty for unmarked response"
        assert content == "Plain response", "Unmarked response not handled correctly"
        print_response(response, thinking, content)
        print("✅ Unmarked response handled correctly")
        
    except AssertionError as e:
        print(f"❌ Response parsing test failed: {str(e)}")
        return
    except Exception as e:
        print(f"❌ Unexpected error during response parsing: {str(e)}")
        return

    # Test API interaction
    print("\n3️⃣ Testing API interaction...")
    if "OPENAI_API_KEY" in os.environ and os.environ["OPENAI_API_KEY"] != "test_key":
        try:
            client = LLMClient()
            prompt = "What is 2+2? Explain your thinking."
            print("📤 Sending test prompt to API...")
            print("\nPrompt:")
            print("=" * 50)
            print(prompt)
            print("=" * 50)
            
            response = client.get_response(prompt)
            assert isinstance(response, LLMResponse), "Response not in correct format"
            assert len(response.thinking) > 0, "Response missing thinking section"
            assert len(response.content) > 0, "Response missing content section"
            print("✅ Successfully received and parsed API response")
            
            print("\nAPI Response:")
            print("=" * 50)
            print("THINKING:")
            print(response.thinking)
            print("\nCONTENT:")
            print(response.content)
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ API interaction test failed: {str(e)}")
    else:
        print("⏭️ Skipping API test (no valid API key available)")

    # Test error handling
    print("\n4️⃣ Testing error handling...")
    try:
        client = LLMClient(api_key="invalid_key")
        try:
            print("\nTesting with invalid API key...")
            client.get_response("Test prompt")
            print("❌ Error handling test failed: Should have raised an error")
        except LLMError as e:
            print("✅ Invalid API key handled correctly")
            print(f"Error message: {str(e)}")
    except Exception as e:
        print(f"❌ Error handling test failed unexpectedly: {str(e)}")

    print("\n✨ All tests completed!")

@pytest.fixture
def mock_llm_client():
    client = Mock(spec=LLMClient)
    return client

@pytest.fixture
def test_player(mock_llm_client):
    player = Player("TestPlayer", "A test player", mock_llm_client)
    return player

def test_parse_negotiation_json_response(test_player):
    # Test JSON response parsing
    json_response = {
        "thinking": "I should make a strategic offer",
        "content": {
            "action": "Offer",
            "damage": 30,
            "target": "Player2",
            "speech": "Let's work together"
        }
    }
    
    response = LLMResponse(
        content=json.dumps(json_response),
        thinking="Raw thinking"
    )
    
    action = test_player._parse_negotiation_response(response, {})
    
    assert action.action_type == "Offer"
    assert action.damage_amount == 30
    assert action.target_player == "Player2"
    assert action.speech == "Let's work together"
    assert action.thinking == "I should make a strategic offer"

def test_parse_negotiation_fallback_response(test_player):
    # Test fallback to text parsing
    response = LLMResponse(
        content="ACTION: Kill\nDAMAGE: 50\nTARGET: Player3\nSPEECH: You're going down!",
        thinking="Fallback thinking"
    )
    
    action = test_player._parse_negotiation_response(response, {})
    
    assert action.action_type == "Kill"
    assert action.damage_amount == 50
    assert action.target_player == "Player3"
    assert action.speech == "You're going down!"
    assert action.thinking == "Fallback thinking"

def test_update_opinion_json(test_player):
    json_response = {
        "thinking": "Evaluating player's actions",
        "content": {
            "opinion": "This player seems trustworthy and strategic"
        }
    }
    
    test_player._llm_client.get_response.return_value = LLMResponse(
        content=json.dumps(json_response),
        thinking="Raw thinking"
    )
    
    test_player.update_opinion("Player2", "Offer", {})
    assert test_player.opinions["Player2"] == "This player seems trustworthy and strategic"

def test_update_opinion_fallback(test_player):
    test_player._llm_client.get_response.return_value = LLMResponse(
        content="This player is untrustworthy",
        thinking="Fallback thinking"
    )
    
    test_player.update_opinion("Player3", "Kill", {})
    assert test_player.opinions["Player3"] == "This player is untrustworthy"

def test_decide_backstab_json(test_player):
    json_response = {
        "thinking": "Analyzing the situation",
        "content": {
            "decision": True
        }
    }
    
    test_player._llm_client.get_response.return_value = LLMResponse(
        content=json.dumps(json_response),
        thinking="Raw thinking"
    )
    
    decision, thinking = test_player.decide_backstab({})
    assert decision is True
    assert thinking == "Analyzing the situation"

def test_decide_backstab_fallback(test_player):
    test_player._llm_client.get_response.return_value = LLMResponse(
        content="true",
        thinking="Should definitely backstab"
    )
    
    decision, thinking = test_player.decide_backstab({})
    assert decision is True
    assert thinking == "Should definitely backstab"

if __name__ == "__main__":
    test_llm_client() 