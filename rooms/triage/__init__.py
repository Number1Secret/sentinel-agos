"""
Room 1: Triage Engine

Mass URL scanning with fast-pass qualification.
Extracts high-intent signals and scores leads for the Architect room.

Signals detected:
- PageSpeed score
- SSL certificate status
- Mobile responsiveness
- Copyright year (outdated = opportunity)
"""
from rooms.triage.agent import TriageAgent
from rooms.triage.room import TriageRoom

__all__ = ["TriageAgent", "TriageRoom"]
