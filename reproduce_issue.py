
from fastapi.testclient import TestClient
from main import app
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

client = TestClient(app)

def test_websocket_route():
    print("Testing WebSocket route /ws/auth/user/status...")
    try:
        with client.websocket_connect("/ws/auth/user/status") as websocket:
            print("Connection successful!")
            websocket.close()
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_websocket_route()
