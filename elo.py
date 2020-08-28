#!/usr/bin/python3
import collections
import json
import math
import os

from pprint import pprint

model = {
    'initial': 1500,
    'K': 5,
}

days = {}
for root, dirs, files in os.walk('game-data'):
    for filename in files:
        with open(os.path.join(root, filename)) as f:
            data= json.load(f)
        days[(data[0]['season'], data[0]['day'])] = data

ratings = collections.defaultdict(lambda: 1500)
day_ratings = collections.defaultdict(dict)
correct = 0
official_correct = 0
total = 0
for (season, day), data in sorted(days.items()):
    for game in data:
        away = game['awayTeamNickname']
        home = game['homeTeamNickname']
        r_a = ratings[away]
        r_h = ratings[home]
        q_a = math.pow(10, r_a / 400)
        q_h = math.pow(10, r_h / 400)
        e_a = q_a / (q_a + q_h)
        e_h = q_h / (q_a + q_h)
        s_a = int(game['awayScore'] > game['homeScore'])
        s_h = int(game['awayScore'] < game['homeScore'])
        r_a_new = r_a + model['K'] * (s_a - e_a)
        r_h_new = r_h + model['K'] * (s_h - e_h)

        total += 1
        if abs(e_a - s_a) <= 0.5:
            correct += 1
        if abs(game['awayOdds'] - s_a) <= 0.5:
            official_correct += 1

        day_ratings[(season, day)][away] = r_a_new
        day_ratings[(season, day)][home] = r_h_new
        ratings[away] = r_a_new
        ratings[home] = r_h_new

pprint(sorted(ratings.items(), key=lambda x: x[1], reverse=True))
print(f'our model accuracy:      {correct / total}')
print(f'official model accuracy: {official_correct / total}')
