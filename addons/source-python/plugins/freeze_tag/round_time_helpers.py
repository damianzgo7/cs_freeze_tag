# ../freeze_tag/round_time_helpers.py

# =============================================================================
# >> IMPORTS
# =============================================================================   
from events import Event

from cvars import ConVar

from listeners.tick import Repeat

# =============================================================================
# >> ALL DECLARATION
# =============================================================================   
__all__ = ["get_round_timestamp",
    "get_round_timestamp_from_end",
    "stop_round_time_counter"]

# =============================================================================
# >> GLOBAL VARIABLES
# =============================================================================   
timestamp = 0
timestamp_from_end = 0
count_task = None

# =============================================================================
# >> EVENTS
# =============================================================================   
@Event("round_freeze_end")
def on_round_freeze_end(game_event):
    timestamp = 0
    timestamp_from_end = _calculate_round_end_timestamp()
    count_task.start(1.0)

@Event("round_end")
def on_round_end(game_event):
    timestamp = 0
    timestamp_from_end = 0
    stop_round_time_counter()
    
# =============================================================================
# >> CALLBACKS
# =============================================================================       
def _count_task_callback():
    global timestamp
    global timestamp_from_end
    timestamp += 1
    timestamp_from_end -= 1

count_task = Repeat(_count_task_callback)
    
# =============================================================================
# >> FUNCTIONS
# =============================================================================      
def get_round_timestamp():
    return timestamp

def get_round_timestamp_from_end():
    return timestamp_from_end

def stop_round_time_counter():
    count_task.stop()
      
def _calculate_round_end_timestamp():
    global timestamp_from_end
    round_end_time = ConVar("mp_roundtime").get_float()
    seconds = int(60*(round_end_time % 1))
    minutes = round_end_time - seconds
    timestamp_from_end = int(60*minutes + seconds)