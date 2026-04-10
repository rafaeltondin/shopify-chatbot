# -*- coding: utf-8 -*-
import logging
import json
import asyncio
from typing import List, Dict, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connection established: {websocket.client}")

    def disconnect(self, websocket: WebSocket):
        """
        Safely disconnects a WebSocket, handling the case where it may not be in the list.
        """
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                logger.info(f"WebSocket connection closed: {websocket.client}")
            else:
                logger.warning(f"WebSocket disconnect called but connection not in list: {websocket.client}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnect: {e}", exc_info=True)

    def _remove_dead_connections(self, dead_connections: List[WebSocket]):
        """
        Removes dead connections from the active list.
        """
        for conn in dead_connections:
            try:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
                    logger.info(f"Removed dead WebSocket connection: {conn.client}")
            except Exception as e:
                logger.error(f"Error removing dead connection: {e}", exc_info=True)

    async def broadcast(self, event: str, data: Dict[str, Any]):
        """
        Broadcasts a message to all connected clients.
        Automatically removes dead connections that fail to receive messages.
        """
        if not self.active_connections:
            logger.debug(f"No active connections to broadcast event '{event}'")
            return

        message = {"event": event, "data": data}
        message_json = json.dumps(message)
        logger.info(f"Broadcasting event '{event}' to {len(self.active_connections)} clients.")
        logger.debug(f"Broadcast message: {message_json}")

        # Create a copy of connections to avoid modification during iteration
        connections_snapshot = list(self.active_connections)
        dead_connections = []

        # Create a list of tasks to send messages concurrently
        tasks = [connection.send_text(message_json) for connection in connections_snapshot]

        # Run all send tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that occurred during sending
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                conn = connections_snapshot[i]
                logger.error(f"Error sending message to {conn.client}: {result}")
                dead_connections.append(conn)

        # Remove dead connections
        if dead_connections:
            self._remove_dead_connections(dead_connections)
            logger.info(f"Removed {len(dead_connections)} dead connections after broadcast.")

    async def send_to_one(self, websocket: WebSocket, event: str, data: Dict[str, Any]):
        """
        Sends a message to a specific WebSocket connection.
        """
        if websocket not in self.active_connections:
            logger.warning(f"Cannot send to WebSocket not in active connections: {websocket.client}")
            return False

        message = {"event": event, "data": data}
        message_json = json.dumps(message)

        try:
            await websocket.send_text(message_json)
            logger.debug(f"Sent event '{event}' to {websocket.client}")
            return True
        except Exception as e:
            logger.error(f"Error sending to {websocket.client}: {e}")
            self.disconnect(websocket)
            return False

    def get_connection_count(self) -> int:
        """Returns the number of active connections."""
        return len(self.active_connections)

manager = ConnectionManager()
