import re
import json
import discord
import pywikibot
from sys import stderr
from random import shuffle
from datetime import datetime, timedelta
from pywikibot.data.api import Request

class InputError(RuntimeError):
    pass

def detalkify(pagename):
    if ':' not in pagename:
        return pagename
    prefix, rest = pagename.split(':', maxsplit=1)
    if prefix == 'Обсуждение':
        return rest
    elif prefix == 'Обсуждение файла':
        return 'Файл:' + rest
    elif prefix == 'Обсуждение шаблона':
        return 'Шаблон:' + rest
    elif prefix == 'Обсуждение категории':
        return 'Категория:' + rest
    elif prefix == 'Обсуждение портала':
        return 'Портал:' + rest
    elif prefix == 'Обсуждение модуля':
        return 'Модуль:' + rest
    else:
        return pagename

def unique(items):
    return list(set(items))

def stringify_date(date):
    return f'{date.year}-{date.month:02d}-{date.day:02d}T{date.hour:02d}:{date.minute:02d}:{date.second:02d}Z'

class MyClient(discord.Client):
    chunk_size = 500
    color = 3447003
    max_oldreviewed_results = 20
    max_unreviewed_results = 5

    def get_category_members(self, source):
        if 'type' not in source or source['type'] != 'category':
            raise InputError(f"Wrong type (expected `category`, got `{source.get('type', '???')}`), source: `{json.dumps(source)}`")
        if 'title' not in source:
            raise InputError(f'No title specified, source: `{json.dumps(source)}`')
        if not re.match(r'^\s*([кК]атегория|[cC]ategory|[кК])\s*:', source['title']):
            title = 'Category:' + source['title']
        else:
            title = source['title']

        parameters = {
            'action': 'query',
            'format': 'json',
            'list': 'categorymembers',
            'cmtitle': title,
            'cmlimit': 'max',
            'cmprop': 'title',
            'cmnamespace': source.get('namespaces', '0'),
            'assert': 'bot'
        }

        request = Request(self.site, parameters=parameters)
        result = []
        while True:
            reply = request.submit()
            if 'categorymembers' in reply['query']:
                if source.get('detalkify', False):
                    result.extend([detalkify(pageinfo['title']) for pageinfo in reply['query']['categorymembers']])
                else:
                    result.extend([pageinfo['title'] for pageinfo in reply['query']['categorymembers']])
            if 'query-continue' in reply:
                for key, value in reply['query-continue']['categorymembers'].items():
                    request[key] = value
            elif 'continue' in reply:
                for key, value in reply['continue'].items():
                    request[key] = value
            else:
                break

        return result

    source_handlers = {
        'category': get_category_members
        # TODO: implement 'template'
    }

    def form_pending_changes_report(self, sources):
        pagelist = []
        for source in sources:
            try:
                if 'type' not in source or source['type'] not in self.source_handlers:
                    raise InputError(f"Unknown type `{source.get('type', '???')}`, source: `{json.dumps(source)}`")
                pagelist += self.source_handlers[source['type']](self, source)
            except InputError as error:
                print(f'Input ignored. {error}', file=stderr)
        pagelist = unique(pagelist)

        total_count = len(pagelist)
        reviewed_count = 0
        unreviewed_count = 0
        oldreviewed_count = 0

        unreviewed = []
        oldreviewed = []
        for i in range(0, len(pagelist), self.chunk_size):
            print(len('|'.join(pagelist[i:i+self.chunk_size])))
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
                    if flaggedinfo['pending_since'] < self.day_ago_timestamp:
                        continue
                    oldreviewed.append((
                        flaggedinfo['pending_since'],
                        f"\n- [{pagename}](https://ru.wikipedia.org/w/index.php?diff=curr&oldid={flaggedinfo['stable_revid']})"
                    ))
                else:
                    reviewed_count += 1

        content = f'Проанализировано {total_count} страниц, из них неотпатрулировано {unreviewed_count} ({100 * unreviewed_count / total_count:.2n} %), устарело {oldreviewed_count} ({100 * oldreviewed_count / total_count:.2n} %).'

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
            self.day_ago_timestamp = stringify_date(date - timedelta(days=1))
            self.week_ago_timestamp = stringify_date(date - timedelta(days=7))

            with open('config.json', encoding='utf-8') as config:
                for command in json.load(config):
                    channel = self.get_channel(command['channel'])                
                    async with channel.typing():
                        await channel.send(**self.form_pending_changes_report(command.get('sources', [])))
        except Exception as error:
            print(f'ERROR: {error}', file=stderr)
        finally:
            await self.close()

if __name__ == '__main__':
    MyClient(intents=discord.Intents.default()).run(open("./keys/discord.token").read())
