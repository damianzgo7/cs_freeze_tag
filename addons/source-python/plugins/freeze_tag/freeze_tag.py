# ../freeze_tag/freeze_tag.py

# =============================================================================
# >> IMPORTS
# =============================================================================
# Source.Python
from entities.entity import Entity, BaseEntity
from entities.constants import CollisionGroup, RenderMode, SolidFlags, SolidType
from entities.hooks import EntityPostHook, EntityPreHook, EntityCondition
from entities.helpers import baseentity_from_inthandle, index_from_pointer
from entities.helpers import index_from_inthandle

from players.entity import Player
from players.helpers import index_from_userid
from players.constants import PlayerButtons

from listeners import OnClientActive, OnClientDisconnect, OnLevelInit
from listeners import OnClientConnect
from listeners import OnButtonStateChanged, get_button_combination_status
from listeners import ButtonStatus
from listeners import OnServerActivate
from listeners.tick import Delay, Repeat
from events import Event

from menus.radio import PagedRadioMenu, PagedRadioOption
from messages.base import SayText2, HudMsg

from commands.typed import TypedClientCommand, TypedSayCommand
from commands import CommandReturn

from filters.players import PlayerIter

from colors import Color

from memory import DataType
from memory import make_object

from config.manager import ConfigManager
from cvars import ConVar
from cvars.flags import ConVarFlags

from stringtables import string_tables

# Module plugins
from . import round_time_helpers as rth

# =============================================================================
# >> CONSTANTS
# =============================================================================
MELT_END_POINT = 100


# =============================================================================
# >> GLOBAL VARIABLES
# =============================================================================
sudden_death = False
sd_time = None
round_time = None

# =============================================================================
# >> CONFIG MANAGEMENT
# =============================================================================
ft_config = ConfigManager("ft_config")
ft_config.header = "Freeze Tag mod configuration file"
ft_sudden_death_time = ft_config.cvar("ft_sudden_death_time",
        30, "Time (in seconds) when sudden death begins. If this value is greater \
        than round time, sudden death will not trigger.", 
        ConVarFlags.PROTECTED|ConVarFlags.HIDDEN|ConVarFlags.PRINTABLEONLY
)
ft_config.write()

# =============================================================================
# >> MANAGERS
# =============================================================================
class _PlayersManager(dict):
    def __delitem__(self, index):
        super().__delitem__(index)
        
players = _PlayersManager()        

class _FrozenEntsManager(dict):
    def __delitem__(self, index):
        self[index].remove()
        super().__delitem__(index)

    def ft_remove(self, index):
        self.__delitem__(index)
        
        if sudden_death is False:
            players[index].spawn()        
        
f_players = _FrozenEntsManager()        
        
        
# =============================================================================
# >> INITIALIZATION
# =============================================================================
def load():
    global sd_time
    global round_time
    
    for player in PlayerIter('all'):
        if player.index not in players.keys():
            players[player.index] = FtPlayer(player.index)

    ft_config.execute() 
    sd_time = ConVar("ft_sudden_death_time").get_int()  
    ft_hud_send(round_start=True)

def unload():
    players.clear()
    f_players.clear()
    rth.stop_round_time_counter()
            
# =============================================================================
# >> CLASSES
# =============================================================================
class FtPlayer(Player):
    """Extended Player class with mod-related methods and attributes"""
    
    def __init__(self, index):
        super().__init__(index)
        self.ft_menu_el = PagedRadioOption(f"{self.name}", self.index)
        self.is_crouching = False
    
    def create_frozen_ent(self):
        origin = self.playerinfo.origin
        
        if not self.is_crouching:
            origin[2] -= 65
        else:
            origin[2] -= 50
            
        model = self.get_model()    

        f_players[self.index] = FtFrozen.create("prop_dynamic")
        f_players[self.index].spawn_ent(model, origin, self.index, self.team_index)
        
class FtFrozen(Entity): 
    
    def __init__(self, index):
        super().__init__(index)
        self.player_index = None
        self._lock_melt = False
        self._melting = False
        self._melt_points = 0
        self.colors = []
        self.melters = []
        
    @property
    def melt_points(self):
        return self._melt_points
    @melt_points.setter
    def melt_points(self, value):
        self._melt_points = value
        
        if self._melting is True and self._lock_melt is False and self._melt_points >= MELT_END_POINT:
            if len(self.melters) == 1:
                SayText2(f"{players[self.player_index].name} melted by {self.melters[0]}.").send()
            elif len(self.melters) >= 2:
                SayText2(f"{players[self.player_index].name} melted " +
                         f"by {self.melters[0]} and {self.melters[1]}.").send()
            self.melt_player()
            
    @property
    def lock_melt(self):
        return self._lock_melt
    @lock_melt.setter
    def lock_melt(self, value):
        self._lock_melt = value
        
        if self._melting is True:
            return
            
        if self._lock_melt is True:
            self.render_color = self.colors[2] 
            Delay(0.1, reset_melt_progress, (self.player_index,))
        else:
            self.render_color = self.colors[0] 
    
    @property
    def melting(self):
        return self._melting
    @melting.setter
    def melting(self, value):
        self._melting = value
        
        if self.lock_melt is True:
            return
            
        if self._melting is True:
            self.render_color = self.colors[1]
            self.emit_sound("freeze_tag/ft_melting.wav", origin=self.origin,
                attenuation=0.7, download=True) 
        else:
            self.render_color = self.colors[0]
            self.stop_sound("freeze_tag/ft_melting.wav")
            Delay(0.5, reset_melt_progress, (self.player_index,))
        
    def set_colors(self):
        if self.team_index == 2:
            self.colors = [Color(255,0,0), # frozen model color
                              Color(255,255,0), # melting model color
                              Color(255,102,102) # melting locked model color
                              ]
        elif self.team_index == 3:
            self.colors = [Color(0,0,255), # frozen model color
                              Color(0,200,255), # melting model color
                              Color(255,102,102) # melting locked model color
                              ]                            
        
    def spawn_ent(self, model, origin, index, team_index):
        self.create("prop_dynamic")
        self.player_index = index
        self.team_index = team_index
        self.set_colors()
        self.model = model  
        self.origin = origin
        self.target_name = f"Frozen_{index}"
        self.collision_group = CollisionGroup.DEBRIS
        self.solid_flags = SolidFlags.TRIGGER
        self.solid_type = SolidType.VPHYSICS
        self.render_mode = RenderMode.TRANS_COLOR
        self.render_color = self.colors[0]
        self.spawn()
    
    def remove(self):
        self.stop_sound("freeze_tag/ft_melting.wav")
        self.emit_sound("freeze_tag/ft_melted.mp3", origin=self.origin,
                attenuation=0.7, download=True)
        Entity.remove(self)
    
    def melt_player(self):
        f_players.ft_remove(self.player_index) 
        
# =============================================================================
# >> SAY COMMANDS
# =============================================================================
@TypedSayCommand("/ftlist")
def show_list(command_info):
    ft_list.send(command_info.index)         

# =============================================================================
# >> HOOKS
# =============================================================================        
@EntityPostHook(EntityCondition.is_player, 'start_touch')    
def ent_start_touch(args, ret):
    if sudden_death is True:
        return
    
    touched = get_frozen_ent(index_from_pointer(args[0]))
    touching = get_player(index_from_pointer(args[1]))
    
    if touched is None or touching is None:
        return    
        
    if touched.team_index != touching.team_index:
        touched.lock_melt = True
        return
    
    touched.melting = True   
    touched.melters.append(touching.name) 
    touched.melt_points += 50
    Delay(0.5, melting_func, (touching.index, touched.player_index, 50))
    
 
@EntityPreHook(EntityCondition.is_player, 'end_touch')    
def pre_ent_end_touch(args):
    # this pre-hook code prevents crashing when some entities are touched
    # changing this code is not recommended
    
    handle = make_object(BaseEntity, args[0]).parent_inthandle
    other = make_object(BaseEntity, args[1])

    if handle != -1:
        parent = Entity(index_from_inthandle(handle))
        parent.end_touch.call_trampoline(other)
        
    return DataType.VOID    
 
@EntityPostHook(EntityCondition.is_player, 'end_touch')    
def ent_end_touch(args, ret):
    if sudden_death is True:
        return
    
    touched = get_frozen_ent(index_from_pointer(args[0]))
    touching = get_player(index_from_pointer(args[1]))
    
    if touched is None or touching is None:
        return
    
    if touched.team_index != touching.team_index:
        touched.lock_melt = False
        return    
    
    touched.melters.remove(touching.name) 
    touched.melting = False   
    
      
# =============================================================================
# >> EVENTS
# =============================================================================
@Event("player_death")    
def on_player_death(game_event):
    ft_hud_update(players_update=True)
    
    if sudden_death is True:
        return
    
    index = index_from_userid(game_event['userid'])
    
    # Removing dead body
    try:
        rag = baseentity_from_inthandle(players[index].get_property_int('m_hRagdoll'))
        rag.remove()
    except RuntimeError:    
        pass
         
    if players[index].team_index == 2:
        ft_list_t.append(players[index].ft_menu_el)
    elif players[index].team_index == 3:
        ft_list_ct.append(players[index].ft_menu_el)  
        
    players[index].create_frozen_ent()  
    
    
@Event("player_spawn")
def on_player_spawn(game_event):
    ft_hud_update(players_update=True)
    
    if sudden_death is True:
        return
    
    index = index_from_userid(game_event['userid'])  
    
    if players[index].team_index == 2:
        del_from_list_t(index)
    elif players[index].team_index == 3:
        del_from_list_ct(index)  
        
    if index in f_players.keys():
        f_players.ft_remove(index) 
     
@Event("player_team")
def on_changing_team(game_event):
    oldteam = game_event['oldteam']
    index = index_from_userid(game_event['userid'])
    
    if oldteam == 2:
        del_from_list_t(index)
    elif oldteam == 3:
        del_from_list_ct(index)  

    ft_hud_update(players_update=True)
             
@Event("round_freeze_end")
def on_round_freeze_end(game_event):
    global sudden_death; global sd_notice_task; global sd_switch_task
    sudden_death = False
    round_time = rth.get_round_timestamp_from_end()    
    
    if round_time > sd_time:
        sd_notice_task = Delay(round_time - sd_time - 20.0, _sd_info_callback)
        sd_switch_task = Delay(round_time - sd_time, _sd_switch_callback)
        
    ft_hud_update(players_update=True)

def _sd_info_callback():
    SayText2("20 seconds to sudden death").send()
    
def _sd_switch_callback():
    global sudden_death
    sudden_death = True
    
    for index in f_players.keys():
        f_players[index].remove()
    f_players.clear() 
    ft_hud_update() 
    SayText2("Sudden death activated").send()  
        
@Event("round_end")
def on_round_end(game_event):
    for index in f_players.keys():
        f_players[index].remove()
    f_players.clear()
    ft_list_t.clear()
    ft_list_ct.clear()
    sd_notice_task.cancel()
    sd_switch_task.cancel()

sd_notice_task = None
sd_switch_task = None    
   
     
@Event("round_freeze_end")
def on_round_freeze_end(game_event):
    global sudden_death; global sd_notice_task; global sd_switch_task
    sudden_death = False
    round_time = rth.get_round_timestamp_from_end()    
    
    if round_time > sd_time:
        sd_notice_task = Delay(round_time - sd_time - 20.0, _sd_info_callback)
        sd_switch_task = Delay(round_time - sd_time, _sd_switch_callback)
        
    ft_hud_update(players_update=True)

def _sd_info_callback():
    SayText2("20 seconds to sudden death").send()
    
def _sd_switch_callback():
    global sudden_death
    sudden_death = True
    
    for index in f_players.keys():
        f_players[index].remove()
    f_players.clear() 
    ft_hud_update()              
    SayText2("Sudden death activated").send()  
       
        
# =============================================================================
# >> LISTENERS
# =============================================================================      
@OnClientConnect
def on_client_connect(allow_connect_ptr, edict, name, address, reject_msg_ptr, reject_msg_len):
    string_tables.soundprecache.add_string("freeze_tag/ft_melting.wav") 
    string_tables.soundprecache.add_string("freeze_tag/ft_melted.mp3") 

@OnClientActive
def on_client_active(index):
    if index not in players.keys():
        players[index] = FtPlayer(index)
    
@OnClientDisconnect
def on_client_disconnect(index):
    if index in players.keys():
        del players[index]
    
    if index in f_players.keys():
        del f_players[index]  
    
@OnButtonStateChanged
def on_button_state_changed(player, old_buttons, new_buttons):    
    status = get_button_combination_status(old_buttons, new_buttons,
        PlayerButtons.DUCK)

    if status == ButtonStatus.PRESSED:
        players[player.index].is_crouching = True

    elif status == ButtonStatus.RELEASED:
        players[player.index].is_crouching = False

        
# =============================================================================
# >> FUNCTIONS
# =============================================================================        
def melting_func(melter_index, melted_index, points):
    if melted_index not in f_players.keys():
        return
        
    f_players[melted_index].melt_points += points
  
def reset_melt_progress(index):
    if index not in f_players.keys():
        return
    
    f_players[index].melt_points = 0
    f_players[index].melters = []

def get_player(index):
    for el in players.values():
        if el.index == index:
            return el
            
    return None   
            
def get_frozen_ent(index):
    for el in f_players.values():
        if el.index == index:
            return el
            
    return None   

def count_players_in_team(team_shortcut):
    count = 0
    for player in PlayerIter(team_shortcut):
        count += 1
            
    return count   
    
def count_alive_in_team(team_shortcut):
    team = {'t': 2, 'ct': 3}
    count = 0
    for el in PlayerIter('alive'):
        if el.team_index == team[team_shortcut]:
            count += 1
            
    return count       
    
# =============================================================================
# >> MENUS
# =============================================================================   
ft_list_main = [PagedRadioOption('TT Menu',1), PagedRadioOption('CT Menu',2)]

def _ft_list_callback(menu, index, option):
    if option.value == 1:
        ft_list_t.send(index)
    elif option.value == 2:
        ft_list_ct.send(index)    
    
def _ft_list_data_callback(menu, index, option):
    SayText2(f"Name: {players[option.value].name}").send()
    if menu.title == "Frozen players (TT)":
        ft_list_t.send(index)
    elif menu.title == "Frozen players (CT)":
        ft_list_ct.send(index)       

def del_from_list_t(index):
     for i in range(0, len(ft_list_t)):
        if ft_list_t[i].value == index:
            del ft_list_t[i]
            break

def del_from_list_ct(index):
     for i in range(0, len(ft_list_ct)):
        if ft_list_ct[i].value == index:
            del ft_list_ct[i]
            break    
        
ft_list = PagedRadioMenu(data=ft_list_main, select_callback=_ft_list_callback, 
                        title="Frozen players", top_separator=" ", 
                        bottom_separator=" ") 
ft_list_t = PagedRadioMenu(select_callback=_ft_list_data_callback, 
                           title="Frozen players (TT)", parent_menu=ft_list) 
ft_list_ct = PagedRadioMenu(select_callback=_ft_list_data_callback, 
                            title="Frozen players (CT)", parent_menu=ft_list)
                            
                            
# =============================================================================
# >> HUD DISPLAY
# =============================================================================     
hud_data = {
    "status": "[Freeze Tag]",
    "t_players": f"T: {count_alive_in_team('t')} / {count_players_in_team('t')}",
    "ct_players": f"CT: {count_alive_in_team('ct')} / {count_players_in_team('ct')}"
}

hud_data_round_start = hud_data

hud = HudMsg(f"{hud_data['status']}\n" +
        f"    {hud_data['t_players']}\n" +
        f"    {hud_data['ct_players']}", x=0.9, y=0.4, hold_time=0.6)

def ft_hud_send(round_start=False):
    global refesh_task

    if round_start:
        hud_data = hud_data_round_start
        refresh_hud_task.start(0.5)
    
    hud.send()
    
refresh_hud_task = Repeat(ft_hud_send)  

def ft_hud_clear():
    global refesh_hud_task  
    
    refresh_hud_task.cancel()
    hud.clear()

def ft_hud_update(players_update=False):
    global refesh_hud_task   

    if sudden_death:
        hud_data['status'] = f"[No Respawn]"
    else:
        hud_data['status'] = f"[Freeze Tag]"
    
    if players_update:
        hud_data['t_players'] = f"T: {count_alive_in_team('t')} / {count_players_in_team('t')}"
        hud_data['ct_players'] = f"CT: {count_alive_in_team('ct')} / {count_players_in_team('ct')}"
        
    hud['message'] = f"{hud_data['status']}\n    {hud_data['t_players']}\n    {hud_data['ct_players']}"   