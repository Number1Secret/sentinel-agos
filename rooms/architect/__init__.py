"""
Architect Room - Deep audit and mockup generation.

Room 2 in the AgOS Factory:
- Receives qualified leads from Triage
- Performs deep brand audit
- Extracts brand DNA (colors, fonts, voice)
- Generates production-ready mockups via E2B sandbox
"""

from rooms.architect.agent import ArchitectAgent, create_architect_agent
from rooms.architect.room import ArchitectRoom, create_architect_room

__all__ = [
    "ArchitectAgent",
    "create_architect_agent",
    "ArchitectRoom",
    "create_architect_room",
]
