"""
Discovery Room - Room 3: Autonomous Closing Engine.

Room 3 in the AgOS Factory:
- Receives mockup_ready leads from Architect (Room 2)
- Generates proposals with dynamic pricing
- Manages multi-channel follow-up (email/SMS) via SDR loop
- Handles negotiation and objection resolution with VLM analysis
- Creates Stripe checkout sessions for payment
- Generates PDF contracts upon acceptance
- Hands off closed_won leads to Room 4 (Guardian)
"""
from rooms.discovery.room import DiscoveryRoom, create_discovery_room, DISCOVERY_ROOM_CONFIG
from rooms.discovery.agent import DiscoveryAgent, create_discovery_agent

__all__ = [
    "DiscoveryRoom",
    "create_discovery_room",
    "DISCOVERY_ROOM_CONFIG",
    "DiscoveryAgent",
    "create_discovery_agent",
]
