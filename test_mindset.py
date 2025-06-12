import os
import yaml
from pathlib import Path
from player import Player

# Load API key from config
config_path = Path("config.yaml")
try:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        os.environ["OPENAI_API_KEY"] = config['openai']['api_key']
except FileNotFoundError:
    print("❌ config.yaml not found. Please create it with your OpenAI API key.")
    exit(1)
except Exception as e:
    print(f"❌ Error loading config: {str(e)}")
    exit(1)

# Create a test player
player = Player(
    player_id="test_player",
    name="Test Player",
    model="o4-mini-2025-04-16",
    background_prompt="你是一个测试角色，正在经历一个生死游戏。",
    mindset="初始的心理状态：紧张且充满警惕。"
)

# Test context
test_context = {
    "event": "new_round",
    "round": 1,
    "scenario": "玩家们被困在一个危险的房间里",
    "active_players": ["Player1", "Player2", "Player3"],
    "total_players": 3
}

print("\n🔄 Calling update_mindset...")
try:
    # Call update_mindset
    new_mindset, request_id = player.update_mindset(1, test_context)
    
    print(f"\n✅ Success!")
    print(f"New mindset: {new_mindset}")
    print(f"Request ID: {request_id}")
except Exception as e:
    print(f"\n❌ Error: {str(e)}")
    import traceback
    print("\nTraceback:")
    print(traceback.format_exc()) 