import asyncio
import json
import logging
import websockets
import traceback

from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from app.config import VENDOR_WS_URL, API_KEY, USE_AZURE_OPENAI

realtime_router = APIRouter()

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Determine appropriate headers
extra_headers = (
    {
        "Authorization": f"Bearer {API_KEY}",
        "openai-beta": "realtime=v1",
    }
    if USE_AZURE_OPENAI
    else {"api-key": API_KEY}
)


async def relay_messages(client_ws: WebSocket, vendor_ws):
    """Relay messages between client and vendor WebSockets."""

    async def client_to_vendor():
        try:
            while True:
                data = await client_ws.receive_json()
                if data and json_validator(data):
                    await vendor_ws.send(json.dumps(data))
                else:
                    warning_msg = "Invalid data: payload should be JSON."
                    logging.warning(warning_msg)
                    await send_text_safe(client_ws, warning_msg)
        except WebSocketDisconnect:
            logging.info("Client WebSocket disconnected.")
        except Exception as e:
            print(traceback.format_exc())

            logging.error(f"Error in client_to_vendor: {e}")

    async def vendor_to_client():
        try:
            while True:
                data = await vendor_ws.recv()
                await client_ws.send_text(data)
        except websockets.exceptions.ConnectionClosed as e:
            logging.info(f"Vendor WebSocket disconnected: {e}")
        except Exception as e:
            print(traceback.format_exc())

            logging.error(f"Error in vendor_to_client: {e}")

    tasks = [
        asyncio.create_task(client_to_vendor()),
        asyncio.create_task(vendor_to_client()),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@realtime_router.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections from clients."""
    client_ip = websocket.client.host
    logging.info(f"Client connected: {client_ip}")
    await websocket.accept()

    try:
        async with websockets.connect(
            VENDOR_WS_URL, extra_headers=extra_headers
        ) as vendor_ws:
            logging.info("Connected to vendor WebSocket.")
            await relay_messages(websocket, vendor_ws)
    except websockets.exceptions.InvalidHandshake as e:
        error_msg = f"Vendor WebSocket handshake failed: {e}"
        logging.error(error_msg)
        await send_text_safe(websocket, error_msg)
    except WebSocketDisconnect:
        logging.info(f"Client disconnected: {client_ip}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        await send_text_safe(websocket, f"Unexpected error: {e}")


async def send_text_safe(ws: WebSocket, message: str):
    """Safely send messages to the client WebSocket."""
    try:
        await ws.send_text(message)
    except Exception as e:
        logging.error(f"Error sending message to client: {e}")


def json_validator(data) -> bool:
    """Validate if the input data is JSON."""
    try:
        print(f"data: {data}")
        # Check if data is already a dict, which is valid JSON in Python
        if isinstance(data, dict):
            return True
        # Check if the input is a non-empty string
        if isinstance(data, str) and data.strip() == "":
            return False
        # If data is a string, try to load it as JSON
        json.loads(data)
        return True
    except (json.JSONDecodeError, TypeError):
        return False
