import asyncio
import os
import sys
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from axtrade.common import AlpacaConfig, SymbolConfig, get_logger
from axtrade.gateway.alpaca import AlpacaAdapter

# Configure logging
logger = get_logger("test_alpaca")

async def test_alpaca_connection():
    """Test Alpaca connection and data streaming."""
    
    # Get credentials from env or use the ones provided by user (for testing only)
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    
    if not api_key or not secret_key:
        print("Error: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set.")
        return

    print(f"Testing with API Key: {api_key[:5]}...")

    config = AlpacaConfig(
        api_key=api_key,
        secret_key=secret_key,
        feed="iex",  # Free feed
        paper=True
    )

    adapter = AlpacaAdapter(config)

    try:
        print("Connecting to Alpaca...")
        await adapter.connect()
        print("Connected!")

        symbols = [SymbolConfig(symbol="AAPL", base_price=150.0)]
        print(f"Subscribing to {symbols[0].symbol}...")
        await adapter.subscribe(symbols)

        print("Waiting for ticks (timeout 10s)...")
        
        # Create a task to stream ticks
        stream_task = asyncio.create_task(stream_ticks(adapter))
        
        # Wait a bit to receive some data
        await asyncio.sleep(10)
        
        print("Disconnecting...")
        await adapter.disconnect()
        await stream_task

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

async def stream_ticks(adapter):
    try:
        async for tick in adapter.stream_ticks():
            print(f"Received tick: {tick}")
    except Exception as e:
        print(f"Stream error: {e}")

if __name__ == "__main__":
    asyncio.run(test_alpaca_connection())
