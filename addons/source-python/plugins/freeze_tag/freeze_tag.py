# ../freeze_tag/freeze_tag.py

# =============================================================================
# >> IMPORTS
# =============================================================================
# Source.Python
from entities.entity import Entity, BaseEntity
from entities.constants import CollisionGroup, RenderMode, SolidFlags
from entities.constants import SolidType, MoveType, EntityEffects
from entities.hooks import EntityPostHook, EntityPreHook, EntityCondition
from entities.helpers import baseentity_from_inthandle, index_from_pointer
from entities.helpers import index_from_inthandle

from players.entity import Player
from players.helpers import index_from_userid
from players.constants import PlayerButtons

from listeners import OnClientActive, OnClientDisconnect
from listeners import OnButtonStateChanged, get_button_combination_status
from listeners import ButtonStatus
from listeners.tick import Delay, Repeat
from events import Event

from menus.radio import PagedRadioMenu, PagedRadioOption
from messages.base import SayText2, HudMsg

from commands.typed import TypedSayCommand

from filters.players import PlayerIter

from colors import Color

from memory import DataType
from memory import make_object

from config.manager import ConfigManager
from cvars import ConVar
from cvars.flags import ConVarFlags

from stringtables import string_tables
from stringtables.downloads import Downloadables

from engines.precache import Model
from engines.sound import Sound

from mathlib import Vector

from core import GAME_NAME

# Module plugins
from . import round_time_helpers as rth

# =============================================================================
# >> CONSTANTS
# =============================================================================
MELT_END_POINT = 100.0

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
ft_touch_melt_time = ft_config.cvar("ft_touch_melt_time",
        1.0, "Time (in seconds) needed to melt player by touching him.", 
        ConVarFlags.PROTECTED|ConVarFlags.HIDDEN|ConVarFlags.PRINTABLEONLY
)
ft_laser_melt_time = ft_config.cvar("ft_laser_melt_time",
        3.0, "Time (in seconds) needed to melt player with laser.", 
        ConVarFlags.PROTECTED|ConVarFlags.HIDDEN|ConVarFlags.PRINTABLEONLY
)
ft_config.write()  
    
def calc_melt_point(melt_time):
    return round(MELT_END_POINT/melt_time*melt_frequency, 2)
       
# =============================================================================
# >> GLOBAL VARIABLES
# =============================================================================
sudden_death = False
round_time = None
ft_config.execute() 
sd_time = ConVar("ft_sudden_death_time").get_int()  
melt_frequency = 0.1
touch_melt_time = ConVar("ft_touch_melt_time").get_float()
touch_melt_point = calc_melt_point(touch_melt_time)
laser_melt_time = ConVar("ft_laser_melt_time").get_float()
laser_melt_point = calc_melt_point(laser_melt_time)


# =============================================================================
# >> DOWNLOADABLES
# =============================================================================
downloadables = Downloadables()
downloadables.add("sound/freeze_tag/ft_melting.wav")
downloadables.add("sound/freeze_tag/ft_melted.mp3")
downloadables.add("materials/sprites/bluelaser1.vmt")
downloadables.add("materials/sprites/bluelaser1.vtf")


# =============================================================================
# >> SOUND PRECACHING
# =============================================================================       
if GAME_NAME == "csgo":
    string_tables.soundprecache.add_string("freeze_tag/ft_melting.wav") 
    string_tables.soundprecache.add_string("freeze_tag/ft_melted.mp3") 
elif GAME_NAME == "cstrike":
    Sound("freeze_tag/ft_melting.wav").precache()
    Sound("freeze_tag/ft_melted.mp3").precache()
    
    
# =============================================================================
# >> MANAGERS
# =============================================================================
# TODO: change to PlayerDictionary and EntityDictionary

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
    for player in PlayerIter('all'):
        if player.index not in players.keys():
            players[player.index] = FtPlayer(player.index)

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
        self.laser = FtLaser(self.name, self.index, self.team_index)
        self.laser.set_color(self.team_index)
        self.is_crouching = False    
        self.melting_task = None
        self.melting_by_laser = False
    
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
                attenuation=0.7) 
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
        self.collision_group = CollisionGroup.DEBRIS_TRIGGER
        self.solid_flags = SolidFlags.TRIGGER
        self.solid_type = SolidType.BBOX
        self.render_mode = RenderMode.TRANS_COLOR
        self.render_color = self.colors[0]
        self.spawn()
    
    def remove(self):
        self.stop_sound("freeze_tag/ft_melting.wav")
        self.emit_sound("freeze_tag/ft_melted.mp3", origin=self.origin,
                attenuation=0.7)
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
@EntityPostHook(EntityCondition.equals_entity_classname('prop_dynamic'), 'start_touch')    
def ent_start_touch(args, ret):  
    if sudden_death is True:
        return
    
    melter = get_melter(index_from_pointer(args[1]))
    melted = get_frozen_ent(index_from_pointer(args[0]))
    
    if melted is None or melter is None:
        return    
        
    if melted.team_index != melter.team_index:
        if not melter.melting_by_laser:
            melted.lock_melt = True
        
        return    
    
    if not melter.melting_by_laser:
        start_melting(melter, melted, touch_melt_point) 
    else:
        start_melting(melter, melted, laser_melt_point)     
 
@EntityPreHook(EntityCondition.equals_entity_classname('prop_dynamic'), 'end_touch')    
def pre_ent_end_touch(args):
    _ent_touch_inform_parent(args[0], args[1])
    
    return DataType.VOID   
 
@EntityPostHook(EntityCondition.equals_entity_classname('prop_dynamic'), 'end_touch')    
def ent_end_touch(args, ret):
    if sudden_death is True:
        return
    
    melted = get_frozen_ent(index_from_pointer(args[0]))
    melter = get_melter(index_from_pointer(args[1]))
    
    if melted is None or melter is None:
        return
    
    if melted.team_index != melter.team_index:
        if not melter.melting_by_laser:
            melted.lock_melt = False
        
        return          
    
    stop_melting(melter, melted)
    
    
def _ent_touch_inform_parent(ptr0, ptr1):
    handle = make_object(BaseEntity, ptr0).parent_inthandle
    other = make_object(BaseEntity, ptr1)

    if handle != -1:
        parent = Entity(index_from_inthandle(handle))
        parent.end_touch.call_trampoline(other)    
      
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
        
    players[index].laser.set_color(game_event['team'])
    players[index].laser.team_index = game_event['team']
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
    if players[player.index].playerinfo.is_dead():
        return
    
    use_button = get_button_combination_status(old_buttons, new_buttons,
        PlayerButtons.USE)
    duck_button = get_button_combination_status(old_buttons, new_buttons,
        PlayerButtons.DUCK)   
   
    if use_button == ButtonStatus.PRESSED:
        players[player.index].laser.activate()
    elif use_button == ButtonStatus.RELEASED:
        players[player.index].laser.disable()
        
    if duck_button == ButtonStatus.PRESSED:
        players[player.index].is_crouching = True
    elif duck_button == ButtonStatus.RELEASED:
        players[player.index].is_crouching = False
        
# =============================================================================
# >> FUNCTIONS
# =============================================================================        
def melting_func(melter, melted, points):
    melted.melt_points += points
    
def start_melting(melter, melted, points):     
    melted.melting = True   
    melted.melters.append(melter.name) 
    melted.melt_points += points
    melter.melting_task = Repeat(continue_melting, (melter, melted, points))
    melter.melting_task.start(melt_frequency)
    
def continue_melting(melter, melted, points): 
    try:
        melted.melt_points += points      
    except:
        melter.melting_task.stop()

def stop_melting(melter, melted):
    try:
        melted.melters.remove(melter.name) 
    except:
        pass  
    
    melter.melting_task.stop()    
    melted.melting = False  
  
def reset_melt_progress(index):
    if index not in f_players.keys():
        return
    
    f_players[index].melt_points = 0
    f_players[index].melters = []

def get_melter(index):
    for el in players.values():
        if el.index == index:
            el.melting_by_laser = False
            return el
            
        try:
            if el.laser.laser_trigger.index == index:
                el.melting_by_laser = True
                return el
        except:
            pass
            
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

# =============================================================================
# >> LASER MELTING
# =============================================================================   
laser_model = Model("materials/sprites/bluelaser1.vmt")                   

class FtLaser(object):
    def __init__(self, player_name, player_index, team_index):
        self.laser = None
        self.laser_trigger = None
        self.laser_trigger_spawned = False
        self.classname = "laser"
        self.name = player_name
        self.index = player_index
        self.team_index = team_index      
        self.melting_task = None
        self.update_task = Repeat(self.update_laser)    
        
    def set_color(self, team_index):
        if team_index == 2:
            self.color = Color(255,0,0)
        elif team_index == 3:
            self.color = Color(0,0,255)
    
    def activate(self):           
        self.end_vec = players[self.index].view_coordinates
        self.start_vec = _calc_start_vec(players[self.index].eye_location, 
            self.end_vec)
            
        self.laser = Entity.create("env_beam")
        self.laser.model = laser_model
        self.laser.spawn_flags = 1
        self.laser.origin = self.start_vec
        self.laser.target_name = f"Laser_{self.index}"
        self.laser.set_key_value_float('BoltWidth', 15.0)
        self.laser.set_key_value_int('damage', 0)
        self.laser.set_key_value_int('life', 0)
        self.laser.set_key_value_string(
            'LightningStart', self.laser.target_name) 
        self.laser.set_key_value_int('renderamt', 255)
        self.laser.set_key_value_color('rendercolor', self.color)
        self.laser.set_key_value_string('texture', "materials/sprites/physbeam.vmt")
        self.laser.set_key_value_int('TextureScroll', 1)
        self.laser.set_property_vector('m_vecEndPos', self.end_vec)

        self.laser.spawn()

        self.laser.call_input('TurnOff')
        self.laser.call_input('TurnOn')
        
        self.laser.emit_sound("ambient/machines/power_transformer_loop_2.wav", 
            origin=self.laser.origin, attenuation=0.27, volume=0.5) 
        
        if "Frozen" in players[self.index].view_entity.target_name:
            if not self.laser_trigger_spawned:
                self.create_trigger()
        else:
            if self.laser_trigger_spawned:
                self.laser_trigger.remove()
                self.laser_trigger_spawned = False

        self.update_task.start(0.01)    
        
    def create_trigger(self):
        self.trig_vec = players[self.index].view_entity.origin
        self.trig_vec.z += 50
        
        self.laser_trigger = Entity.create("smokegrenade_projectile")
        self.laser_trigger.origin = self.trig_vec
        self.laser_trigger.spawn_flags = 1
        #self.laser_trigger.target_name = f"laser_trig_{self.index}"
        self.laser_trigger.spawn()
        self.laser_trigger.effects |= EntityEffects.NODRAW
        self.laser_trigger.collision_group = CollisionGroup.DEBRIS_TRIGGER
        self.laser_trigger.solid_type = SolidType.BSP
        self.laser_trigger.solid_flags = SolidFlags.TRIGGER_TOUCH_DEBRIS
        self.laser_trigger.move_type = MoveType.FLY
        self.laser_trigger_spawned = True
        
    def update_laser(self):
        self.end_vec = players[self.index].view_coordinates
        self.start_vec = _calc_start_vec(players[self.index].eye_location, 
            self.end_vec)
        self.laser.origin = self.start_vec
        self.laser.set_property_vector('m_vecEndPos', self.end_vec)
        
        if "Frozen" in players[self.index].view_entity.target_name:
            if not self.laser_trigger_spawned:
                self.create_trigger()
        else:
            if self.laser_trigger_spawned:
                self.laser_trigger.remove()
                self.laser_trigger_spawned = False
        
        
    def disable(self):
        self.update_task.stop()
        self.laser.call_input('TurnOff')   
        self.laser.stop_sound("ambient/machines/power_transformer_loop_2.wav") 
        self.laser.remove() 
        self.laser = None 
        if self.laser_trigger_spawned:   
            self.laser_trigger.remove()
            self.laser_trigger_spawned = False
             
def _calc_start_vec(start_vec, end_vec): 
    try:
        vec = start_vec
        dist = start_vec.get_distance(end_vec)
        percentage = 0.4/(dist/100)
        aux_vec = Vector((end_vec.x-start_vec.x)*percentage, 
            (end_vec.y-start_vec.y)*percentage-0.5, 
            (end_vec.z-start_vec.z)*percentage)
        vec = Vector(vec.x+aux_vec.x, 
            vec.y+aux_vec.y, 
            vec.z+aux_vec.z)    
        return vec
    except:
        return start_vec   