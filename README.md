# CSS/CSGO Freeze Tag mod

Mod is based on [Mefy's MOHAA Freeze Tag mod](http://www.mohaaaa.co.uk/AAAAMOHAA/content/extended-gametypes-122-mefy-freeze-tag-ect). 
At this moment mod is in alpha version. It means the mod is playable, but unstable (needs further testing).

## Introduction

This mod provides Freeze Tag gamemode for CS Source/CS Global Offensive. It uses [Source.Python](https://github.com/Source-Python-Dev-Team/Source.Python), so you need to install it on your game server, before installing this mod.

In this gamemode killed player is frozen. Teammate can melt this player by standing next to him for 2 seconds (duration not changeable at this moment).  
This mod have a mechanic called "Sudden Death". When sudden death begins, players can't be melted for the rest of the round.  
Round ends when all players from one of teams are killed or round win condition is met (ex. hostages are rescued).

## Installation

To install this mod, download current release and copy the contents into the main directory of your server (ex. "cstrike").

After install, you can load this mod by:
* Entering ```sp plugin load freeze_tag``` in server console (after loading, restarting round is recommended)
* Adding ```sp plugin load freeze_tag``` to autoexec.cfg

## Configuration

You can config this mod by editing __../cfg/source_python/ft_config.cfg__.

Available cvars:
* __ft_sudden_death_time__ (def. 30) - Time (in seconds) when sudden death begins. If this value is greater than round time, sudden death will not trigger.

## Say commands

* __/ftlist__ - list of frozen players from both teams

## Used resources
### Sounds
* Melting - [Ice Melting Sound Effect by SoundEffects](https://audiograb.com/czRP1wxsTz)
* Melted - [Single Water Droplet by Mike Koenig](http://soundbible.com/384-Single-Water-Droplet.html)



