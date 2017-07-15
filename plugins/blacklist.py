""" Plugin for blacklisting words. 

    See config/blacklist.json for customization.
"""


import logging
import re
from collections import namedtuple

import discord

import plugins
from pcbot import Config

client = plugins.client  # type: discord.Client


blacklist = Config("blacklist", data={"enabled": False, "global": {}, "server": [], "channel": []}, pretty=True)

# Field names only needed for parsing: id, override
blacklist_config_fieldnames = "match_patterns regex_patterns case_sensitive response bots exclude words".split(" ")

BlacklistConfig = namedtuple("BlacklistConfig", " ".join(blacklist_config_fieldnames))
blacklist_cache = {}


def make_config_object(data: dict):
    """ Return a BlacklistConfig from the given dict. 
    
    :param data: dict with blacklist config data.
    :return: BlacklistConfig
    """
    # If there are invalid keys, remove these with a warning
    for key in data:
        if key not in blacklist_config_fieldnames:
            logging.warning("Invalid key name in blacklist.json: " + key)
            del data[key]

    # When a key in not found, default to None
    for key in blacklist_config_fieldnames:
        if key not in data:
            data[key] = None

    # The previous steps are necessary since namedtuples require all fields to be filled
    return BlacklistConfig(**data)


def update_data(data: dict, section: str, object_id: str=None):
    """ Overrides any valid keys with the keys in data.
    
    Data is modified in place and is not returned.
    
    :param data: The eventual BlacklistConfig data object.
    :param section: channel, server or global
    :param object_id: The id of the channel or server the message was sent from.
    """

    for server_data in ([blacklist.data["global"]] if section == "global" else blacklist.data[section]):
        # Since this could also be the global config, only check for id when it's not
        if object_id:
            # The server id is required, skip if not found and issue an error
            if "id" not in server_data:
                logging.error("Missing id key under the \"{}\" section of blacklist.json".format(section))
                continue

            # If the server is found, append all valid keys
            if not server_data["id"] == object_id:
                continue

        override = server_data.get("override", False)
        case_sensitive = server_data.get("case_sensitive", False)

        for key in blacklist_config_fieldnames:
            if key not in server_data:
                continue

            local_data = server_data[key]

            # Manually parse match patterns and regex match patterns
            if key == "match_patterns":
                if not case_sensitive:
                    local_data = [s.lower() for s in local_data]
            elif key == "regex_patterns":
                local_data = [re.compile(s, flags=0 if case_sensitive else re.IGNORECASE) for s in local_data]
            else:
                # The override keyword is only used for determining patterns
                override = True

            if override or key not in data:
                data[key] = local_data
            else:
                data[key].extend(local_data)


def complete_config(message: discord.Message):
    """ Return the correct config info using the given message object. 
    
    :param message: discord.Message to determine complete config data.
    :return: BlacklistConfig
    """
    if message.channel.id in blacklist_cache:
        return blacklist_cache[message.channel.id]

    # Start with global, overwrite with server, overwrite with channel
    data = {}
    update_data(data, "global")
    update_data(data, "server", message.server.id)
    update_data(data, "channel", message.channel.id)
    valid_config = make_config_object(data)

    # Add the found config to the channel cache, considering this will always be the channel override
    blacklist_cache[message.channel.id] = valid_config

    return valid_config


async def delete_message(message: discord.Message, response: str, pattern: str):
    """ Remove the message and send a response if there is one. 
    
    :param message: The discord message to delete.
    :param response: The optional response to send, found in a BlacklistConfig.
    :param pattern: The match pattern found in the deleted message, optional for the response. 
    """
    await client.delete_message(message)

    if response:
        # Parse the response message by replacing keywords
        response = response \
                   .replace("{user}", message.author.display_name) \
                   .replace("{mention}", message.author.mention) \
                   .replace("{channel}", message.channel.mention) \
                   .replace("{server}", message.server.name) \
                   .replace("{pattern}", pattern)

        await client.send_message(message.channel, response)


async def on_message(message: discord.Message):
    """ Handle any message accordingly to the data in the blacklist config. """
    channel_config = complete_config(message)

    # We don't care about private channels and we might not care about bots
    if message.channel.is_private or (message.author.bot and channel_config.bots is False):
        return

    # Exclude any members in the exclude list
    if channel_config.exclude and message.author.id in channel_config.exclude:
        return

    # Check for matching patterns
    if channel_config.match_patterns:
        for pattern in channel_config.match_patterns:
            content = message.content if channel_config.case_sensitive else message.content.lower()
            invalid = False

            # Look for whole words if the words field is set to True
            # This is ignored if the pattern has any spaces
            if channel_config.words and " " not in pattern:
                for word in content.split(" "):
                    if word == pattern:
                        invalid = True
                        break
            else:
                invalid = pattern in content

            if invalid:
                await delete_message(message, channel_config.response, pattern)
                return

    # Check for matching regex patterns
    if channel_config.regex_patterns:
        for pattern in channel_config.regex_patterns:
            if pattern.search(message.content):
                await delete_message(message, channel_config.response, pattern)
                return


# Manually add the event if blacklists are enabled
if blacklist.data["enabled"]:
    plugins.event(bot=True)(on_message)
