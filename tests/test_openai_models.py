import os
import sys
import json
import yaml
import pytest
from pathlib import Path
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from llm_client import LLMClient, LLMResponse, LLMError

def display_response(response: LLMResponse, prompt_type: str):
    """Display the response in a formatted way."""
    print(f"\nTesting {prompt_type} prompt...")
    print("\n🤔 Thinking Process:")
    print(response.thinking)
    print("\n💡 Response Content:")
    print(response.content)

def save_test_results(results: list, output_file: Path):
    """Save test results to a file with detailed formatting."""
    with open(output_file, 'w') as f:
        f.write("AI Saw - OpenAI Models Test Results\n")
        f.write("=" * 50 + "\n")
        f.write(f"Test Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for model_result in results:
            f.write(f"\nModel: {model_result['model']}\n")
            f.write("-" * 30 + "\n")
            
            for test in model_result['tests']:
                f.write(f"\nTest Case: {test['prompt_type']}\n")
                f.write("~" * 20 + "\n")
                
                # Write prompt
                f.write("\nPrompt:\n")
                f.write(test['prompt'] + "\n")
                
                # Write results
                f.write("\nResult: " + ("✅ Passed" if test['success'] else "❌ Failed") + "\n")
                
                if test['success']:
                    f.write("\nResponse:\n")
                    f.write(json.dumps(test['response'], indent=2) + "\n")
                else:
                    f.write("\nError: " + test.get('error', 'Unknown error') + "\n")
                    if 'raw_response' in test:
                        f.write("\nRaw Response:\n")
                        f.write(test['raw_response'] + "\n")
                
                f.write("\n" + "=" * 50 + "\n")
            
            # Write summary for this model
            successful_tests = sum(1 for test in model_result["tests"] if test["success"])
            total_tests = len(model_result["tests"])
            f.write(f"\nSuccess Rate: {successful_tests}/{total_tests}\n")
            f.write("=" * 50 + "\n")

def test_openai_models():
    """Test different OpenAI models with JSON response format."""
    
    # Try to load API key from config file first
    config_path = project_root / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                os.environ["OPENAI_API_KEY"] = config['openai']['api_key']
        except Exception as e:
            print(f"Failed to load API key from config: {e}")
    
    if "OPENAI_API_KEY" not in os.environ:
        pytest.skip("No OpenAI API key available")
    
    models = [
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4-turbo-preview"
    ]
    
    test_prompts = [
        # Test negotiation response
        {
            "prompt": """You are Player1 in the AI Saw game. You are a strategic player who values survival.
            Make a decision for the negotiation phase. Other players have 5 HP each.
            The total required damage is 3.
            
            Your response must be in JSON format with the following structure:
            {
                "thinking": "your thought process",
                "content": {
                    "action": "Offer/Refuse/Kill",
                    "damage": number,
                    "target": "player name",
                    "speech": "what you say"
                }
            }""",
            "expected_fields": ["thinking", "content"],
            "expected_content_fields": ["action", "damage", "target", "speech"]
        },
        # Test opinion update response
        {
            "prompt": """You are Player1 in the AI Saw game. Player2 just offered to take 2 damage to help the group.
            Update your opinion about Player2.
            
            Your response must be in JSON format with the following structure:
            {
                "thinking": "your thought process",
                "content": {
                    "opinion": "your detailed opinion"
                }
            }""",
            "expected_fields": ["thinking", "content"],
            "expected_content_fields": ["opinion"]
        },
        # Test backstab decision response
        {
            "prompt": """You are Player1 in the AI Saw game. You have 5 HP and agreed to take 2 damage.
            Your backstab success chance is 30%. Decide whether to attempt a backstab.
            
            Your response must be in JSON format with the following structure:
            {
                "thinking": "your thought process",
                "content": {
                    "decision": boolean
                }
            }""",
            "expected_fields": ["thinking", "content"],
            "expected_content_fields": ["decision"]
        }
    ]
    
    results = []
    
    for model in models:
        print(f"\n🔍 Testing model: {model}")
        client = LLMClient(model=model)
        
        model_results = {
            "model": model,
            "tests": []
        }
        
        for test_case in test_prompts:
            print(f"\n📝 Testing prompt type: {test_case['expected_content_fields']}")
            try:
                response = client.get_response(test_case["prompt"])
                
                # Try to parse JSON response
                try:
                    resp_json = json.loads(response.content)
                    
                    # Verify required fields
                    has_required_fields = all(field in resp_json for field in test_case["expected_fields"])
                    has_required_content_fields = all(
                        field in resp_json.get("content", {}) 
                        for field in test_case["expected_content_fields"]
                    )
                    
                    test_result = {
                        "prompt_type": str(test_case["expected_content_fields"]),
                        "prompt": test_case["prompt"],
                        "success": has_required_fields and has_required_content_fields,
                        "response": resp_json
                    }
                    
                except json.JSONDecodeError:
                    test_result = {
                        "prompt_type": str(test_case["expected_content_fields"]),
                        "prompt": test_case["prompt"],
                        "success": False,
                        "error": "Invalid JSON format",
                        "raw_response": response.content
                    }
                    
            except Exception as e:
                test_result = {
                    "prompt_type": str(test_case["expected_content_fields"]),
                    "prompt": test_case["prompt"],
                    "success": False,
                    "error": str(e)
                }
            
            model_results["tests"].append(test_result)
            
            # Print results
            if test_result["success"]:
                print("✅ Test passed")
                print("\nResponse:")
                print(json.dumps(test_result["response"], indent=2))
            else:
                print("❌ Test failed")
                if "error" in test_result:
                    print(f"Error: {test_result['error']}")
                if "raw_response" in test_result:
                    print("\nRaw response:")
                    print(test_result["raw_response"])
        
        results.append(model_results)
    
    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = project_root / "tests" / f"test_results_{timestamp}.txt"
    save_test_results(results, output_file)
    print(f"\n📝 Test results saved to: {output_file}")
    
    # Print summary
    print("\n📊 Test Summary:")
    print("=" * 50)
    for model_result in results:
        print(f"\nModel: {model_result['model']}")
        successful_tests = sum(1 for test in model_result["tests"] if test["success"])
        total_tests = len(model_result["tests"])
        print(f"Success rate: {successful_tests}/{total_tests}")
        
        if successful_tests < total_tests:
            print("\nFailed tests:")
            for test in model_result["tests"]:
                if not test["success"]:
                    print(f"- {test['prompt_type']}: {test.get('error', 'Unknown error')}")
    
    # Assert all tests passed
    assert all(
        all(test["success"] for test in model_result["tests"])
        for model_result in results
    ), "Some tests failed"

if __name__ == "__main__":
    test_openai_models() 