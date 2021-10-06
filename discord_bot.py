import json
import os
import re
import sqlite3
import sys

import discord
import requests
from discord.ext import tasks

if not os.path.isfile("config.json"):
    sys.exit("'config.json' not found! Please add it and try again.")
else:
    with open("config.json") as file:
        config = json.load(file)

source_channels = config["source_channel_id"]
dest_channels = config["destination_channel_id"]

string_to_delete = ["some strings"]


def main():
    # initialize database
    db = Database()
    db.initSQLiteDB()

    # start discord bot
    client = MyClient()
    client.run(config["token"])


class SourceChannel:
    """get and cleanse messages from source channel"""

    def __init__(self, channelName, channelID):
        self.channelName = channelName
        self.channelID = channelID
        self.content = None
        self.db = Database()

    def getNewMessages(self):
        headers = {
            'authorization': config["auth"]
        }

        r = requests.get('https://discord.com/api/v9/channels/{}/messages'.format(self.channelID), headers=headers)
        self.content = json.loads(r.text)

    def insert_messages(self):
        for message in self.content:
            if 'Now tracking' not in message["content"]:
                try:
                    query, values = self.db.build_query(message, self.channelName)
                    self.db.execute(query, values)

                except Exception as e:
                    pass
                    # print("tried to add already existing message to DB, message: "+cnt)
                else:
                    self.db.commit()

    def getMessagesFromDB(self):
        self.getNewMessages()
        self.insert_messages()

        query = "SELECT msg_id, msg_content, image_url, reference FROM " + "`" + self.channelName + "`" + "where sent " \
                                                                                                          "= 0 " \
                                                                                                          "ORDER BY " \
                                                                                                          "tstamp " \
                                                                                                          "DESC; "
        self.db.execute(query)
        clean_messages = self.db.cursor.fetchall()
        self.db.commit()
        return clean_messages


class MyClient(discord.Client):
    """
    the discord bot to send sourced messages
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # start the task to run in the background
        self.my_background_task.start()

        self.db = Database()

    async def on_ready(self):
        # login
        print('Logged on as', self.user)
        print(f'{self.user} has connected to Discord!')
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    @tasks.loop(seconds=config["polling_interval"])  # task runs every 60 seconds
    async def my_background_task(self):
        # an attribute we can access from our task
        for channel in source_channels:
            # initialize subclass
            source_channel = SourceChannel(channelName=channel, channelID=source_channels[channel])
            # get messages from DB
            messages = source_channel.getMessagesFromDB()
            counter = len(messages) - 1

            # get the destination channel to send message to
            dest_channel = self.get_channel(int(dest_channels[channel]))  # channel ID goes here

            if counter > 0:
                # update database
                query = "UPDATE " + "`" + channel + "`" + '''
                SET sent = 1
                where msg_id = ?
                ''', (messages[counter][0],)
                self.db.execute(query)
                self.db.commit()

                # print logs
                print(channel + ": ")
                print('\n' + config["role_tag"] + messages[counter][1])

                # send the message to discord channel
                await dest_channel.send('\n' + config["role_tag"] + '\n' + messages[counter][1])
            else:
                messages = source_channel.getMessagesFromDB()
                counter = len(messages)

    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()  # wait until the bot logs in


class Database:
    def __init__(self):
        self.source_channel = source_channels
        self.conn = sqlite3.connect(config["DB_name"])
        self.cursor = self.conn.cursor()

    def initSQLiteDB(self):
        for chName in self.source_channel:
            x = 'CREATE TABLE IF NOT EXISTS ' + '`' + chName + '`'
            table = x + """
            (msg_id TEXT,
            msg_content TEXT,
            tstamp TIMESTAMP,
            json_object TEXT,
            image_url TEXT DEFAULT null,
            reference TEXT DEFAULT null,
            sent BOOLEAN DEFAULT 0,
            PRIMARY KEY ('msg_id')
            )
            """
            self.execute(table)
            self.commit()

    def build_query(self, message, channelName):
        # remove role tags
        cnt = re.sub(r'<.+>', '', message["content"])

        # remove extra sub strings
        for string in string_to_delete:
            cnt = cnt.replace(string, "")

        # build query
        first_line = "INSERT INTO " + "`" + channelName + "`" + "(msg_id, msg_content, tstamp, " \
                                                                "json_object"

        second_line = "\nVALUES (:msg_id, :msg_content, :tstamp, :json_obj"

        values = {"msg_id": message["id"],
                  "msg_content": cnt,
                  "tstamp": message["timestamp"],
                  "json_obj": json.dumps(message)}

        if "message_reference" in message:
            first_line += ", reference"
            second_line += ", :reference"
            values["reference"] = json.dumps(message["message_reference"])

        if message["attachments"]:
            first_line += ", image_url"
            second_line += ", :url"
            values["url"] = json.dumps(message["attachments"])

        first_line += ") "
        second_line += ")"
        query = first_line + second_line

        return query, values

    def execute(self, query, *args):
        self.cursor.execute(query, *args)

    def commit(self):
        self.conn.commit()


if __name__ == '__main__':
    main()
