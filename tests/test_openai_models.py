from llm_client import LLMClient, LLMResponse, UnsupportedModelError, ConfigurationError

def display_response(response: LLMResponse, prompt_type: str):
    """Display the response in a formatted way."""
    print(f"\nTesting {prompt_type} prompt...")
    print("\n🤔 Thinking Process:")
    print(response.thinking)
    print("\n💡 Response Content:")
    print(response.content)
    print(f"\nTokens used: {response.tokens_used}")

def test_openai_models():
    """Test all OpenAI models supported by our LLMClient."""
    
    print("\n🔍 Testing OpenAI Models")
    print("=" * 50)
    
    # Test prompts for different scenarios
    prompts = {
        "basic": "Say 'Hello, World!' briefly.",
        "coding": "Write a simple Python function to add two numbers.",
        "creative": "Write a short haiku about programming."
    }
    
    # Test each OpenAI model
    models = ["gpt-o3", "gpt-o1", "gpt-o4-mini"]
    
    for model in models:
        print(f"\n📝 Testing model: {model}")
        print("-" * 30)
        
        try:
            # Initialize client with specific model
            client = LLMClient(provider="openai", model=model)
            print(f"✅ Successfully initialized client with {model}")
            
            # Test each prompt type
            for prompt_type, prompt in prompts.items():
                response = client.get_response(prompt)
                display_response(response, prompt_type)
            
        except UnsupportedModelError as e:
            print(f"❌ Model Error: {str(e)}")
        except ConfigurationError as e:
            print(f"❌ Configuration Error: {str(e)}")
        except Exception as e:
            print(f"❌ Unexpected Error: {str(e)}")
            
    print("\n✨ OpenAI models testing completed!")

if __name__ == "__main__":
    test_openai_models() 