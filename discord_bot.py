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
conn = sqlite3.connect(config["DB_name"])
cursor = conn.cursor()


def main():
    initSQLiteDB()
    client = MyClient()
    client.run(config["token"])


class sourceChannel():
    """ get and cleanse messages from source channel"""

    def __init__(self):
        self.content = None

    def getNewMessages(self):
        headers = {
            'authorization': config["auth"]
        }
        r = requests.get('https://discord.com/api/v9/channels/{}/messages'.format(config["source_channel_id"]),
                         headers=headers)
        self.content = json.loads(r.text)

    def insert_messages(self):
        for message in self.content:
            if 'Now tracking' not in message["content"]:
                cnt = re.sub(r'<.+>', '', message["content"])
                try:
                    cursor.execute("""
                    INSERT INTO messages(msg_id,msg_content, tstamp, json_object, sent)
                    VALUES (:msgid, :content, :tstamp, :json_obj, :sent)
    
                    """, {'msgid': message["id"], 'content': cnt, 'tstamp': message["timestamp"],
                          'json_obj': json.dumps(message), 'sent': False})
                except Exception as e:
                    pass
                    # print("tried to add already existing message to DB, message: "+cnt)
                else:
                    conn.commit()

    def getMessagesFromDB(self):
        self.getNewMessages()
        self.insert_messages()

        query = """
        SELECT msg_id, msg_content
        FROM messages
        where sent = 0
        ORDER BY tstamp DESC;
        """
        cursor.execute(query)
        cleansed_messages = cursor.fetchall()
        conn.commit()
        return cleansed_messages


class MyClient(discord.Client):
    """the discord bot to send sourced messages"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # an attribute we can access from our task
        self.source_channel = sourceChannel()
        self.messages = self.source_channel.getMessagesFromDB()
        self.counter = len(self.messages)

        # start the task to run in the background
        self.my_background_task.start()

    async def on_ready(self):
        print('Logged on as', self.user)
        print(f'{self.user} has connected to Discord!')
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    @tasks.loop(seconds=60)  # task runs every 60 seconds
    async def my_background_task(self):
        channel = self.get_channel(int(config["destination_channel_id"]))  # channel ID goes here
        if self.counter > 0:
            self.counter -= 1
            cursor.execute('''
            UPDATE messages
            SET sent = 1
            where msg_id = ?
            ''', (self.messages[self.counter][0],))
            conn.commit()
            await channel.send(self.messages[self.counter][1] + '\n'+config["role_tag"])
        else:
            self.messages = self.source_channel.getMessagesFromDB()
            self.counter = len(self.messages)

    @my_background_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()  # wait until the bot logs in


def initSQLiteDB():
    table = """
    CREATE TABLE IF NOT EXISTS `messages`
    (msg_id TEXT,
    msg_content TEXT,
    tstamp TIMESTAMP,
    json_object TEXT,
    sent BOOLEAN,
    PRIMARY KEY ('msg_id')
    )
    """
    cursor.execute(table)
    conn.commit()


if __name__ == '__main__':
    main()
