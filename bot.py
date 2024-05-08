import discord
import pywikibot
import json
from pywikibot.data.api import Request
from datetime import datetime, timedelta
from random import shuffle

def remove_prefix(pagename, prefix):
    if pagename.startswith(prefix):
        return pagename[len(prefix):]
    else:
        return pagename

def stringify_date(date):
    return f'{date.year}-{date.month:02d}-{date.day:02d}T{date.hour:02d}:{date.minute:02d}:{date.second:02d}Z'

class MyClient(discord.Client):
    chunk_size = 500
    color = 3447003
    max_oldreviewed_results = 20
    max_unreviewed_results = 5

    def get_category_members(self, catname, prefix):
        parameters = {
            'action': 'query',
            'format': 'json',
            'list': 'categorymembers',
            'cmtitle': catname,
            'cmlimit': 'max',
            'cmprop': 'title',
            'cmnamespace': 1,
            'assert': 'bot'
        }
        request = Request(self.site, parameters=parameters)
        result = []
        while True:
            reply = request.submit()
            if 'categorymembers' in reply['query']:
                result.extend([remove_prefix(pageinfo['title'], prefix) for pageinfo in reply['query']['categorymembers']])
            if 'query-continue' in reply:
                for key, value in reply['query-continue']['categorymembers'].items():
                    request[key] = value
            elif 'continue' in reply:
                for key, value in reply['continue'].items():
                    request[key] = value
            else:
                break
        return result

    def form_pending_changes_report(self, catname, timestamp):
        pagelist = self.get_category_members(catname, 'Обсуждение:')

        total_count = len(pagelist)
        reviewed_count = 0
        unreviewed_count = 0
        oldreviewed_count = 0

        unreviewed = []
        oldreviewed = []
        for i in range(0, len(pagelist), self.chunk_size):
            parameters = {
                'action': 'query',
                'format': 'json',
                'prop': 'flagged',
                'titles': '|'.join(pagelist[i:i+self.chunk_size]),
                'assert': 'bot',
            }
            request = Request(self.site, parameters=parameters, use_get=False)
            reply = request.submit()
            for pageinfo in reply['query']['pages'].values():
                pagename = pageinfo['title']
                if 'flagged' not in pageinfo:
                    unreviewed_count += 1
                    unreviewed.append(f"\n- [{pagename}](https://ru.wikipedia.org/wiki/{pagename.replace(' ', '_')})")
                elif 'pending_since' in pageinfo['flagged']:
                    oldreviewed_count += 1
                    flaggedinfo = pageinfo['flagged']
                    if timestamp and flaggedinfo['pending_since'] < timestamp:
                        continue
                    oldreviewed.append((
                        flaggedinfo['pending_since'],
                        f"\n- [{pagename}](https://ru.wikipedia.org/w/index.php?diff=curr&oldid={flaggedinfo['stable_revid']})"
                    ))
                else:
                    reviewed_count += 1

        content = f'Проанализировано {total_count} статей, из них неотпатрулировано {unreviewed_count} ({100 * unreviewed_count / total_count:.2n} %), устарело {oldreviewed_count} ({100 * oldreviewed_count / total_count:.2n} %).'

        if oldreviewed:
            description = f'**Распатрулировали за сегодня ({len(oldreviewed)}):**'
            oldreviewed.sort()
            if len(oldreviewed) > self.max_oldreviewed_results:
                description += '\n- …'
                oldreviewed = oldreviewed[-self.max_oldreviewed_results+1:]
            description += ''.join(line for _, line in oldreviewed)
        else:
            description = '**Сегодня ничего не распатрулировали!**'
            if unreviewed:
                shuffle(unreviewed)
                if len(unreviewed) > self.max_unreviewed_results:
                    unreviewed = unreviewed[:self.max_unreviewed_results]
                description += '\n\nОтличная возможность заняться старыми завалами:'
                description += ''.join(unreviewed)

        return { 'content': content, 'embed': discord.Embed(colour=self.color, description=description) }

    async def on_ready(self):
        try:
            self.site = pywikibot.Site()
            self.site.login()

            date = datetime.utcnow()
            day_ago_timestamp = stringify_date(date - timedelta(days=1))

            with open('config.json', encoding='utf-8') as config:
                for command in json.load(config):
                    channel = self.get_channel(command['channel'])                
                    async with channel.typing():
                        await channel.send(**self.form_pending_changes_report(command['category'], day_ago_timestamp))
        finally:
            await self.close()

MyClient(intents=discord.Intents.default()).run(open("./keys/discord.token").read())
