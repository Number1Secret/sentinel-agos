"""
Sentinel AgOS Rooms - The 4-Room Factory Pattern

Each room represents a stage in the lead processing pipeline:
- Room 1 (Triage): Fast-pass URL scanning and qualification
- Room 2 (Architect): Deep audit and mockup generation
- Room 3 (Discovery): Interactive closing (Future)
- Room 4 (Guardian): Autonomous maintenance (Future)
"""
from rooms.base import BaseRoom, RoomConfig

__all__ = ["BaseRoom", "RoomConfig"]
