#!/usr/bin/env python3
import collections
import gzip
import json
import math
import os
from urllib.request import urlopen

model = {
    'mean': 1500,

    # Elo K factor
    'K': 10,

    # Revert to mean factor between seasons
    'seasonRevertFactor': 0.2,

    # Pitcher's game score multipliers
    'gamescore': {
        'base': 47.4,
        'strikeouts': 1,
        'outs': 1.5,
        'walks': -2,
        'hits': -2,
        'runs': -3,
        'homeruns': -3,
    },

    # Number of past games to count toward pitcher's rolling game score
    'playerRgs': 5,
    # Number of past games to count toward team's rolling game score
    'teamRgs': 25,

    # Game score multiplier (to be added to Elo)
    'gsMult': 5.9,
}

ratings = collections.defaultdict(lambda: model['mean'])
rgs = collections.defaultdict(lambda: [])


def expected(rating_away, rating_home):
    q_away = math.pow(10, rating_away / 400)
    q_home = math.pow(10, rating_home / 400)
    return (q_away / (q_away + q_home), q_home / (q_away + q_home))


def observed(game):
    observed_away = int(game['awayScore'] > game['homeScore'])
    return (observed_away, 1 - observed_away)


def calculate_elo(game):
    """
    Calculates and stores the new Elo for the two teams in a game, then returns
    the old Elo for testing the model.
    """
    rating_away = ratings[game['awayTeam']]
    rating_home = ratings[game['homeTeam']]

    expected_away, expected_home = expected(rating_away, rating_home)
    observed_away, observed_home = observed(game)

    ratings[game['awayTeam']] += model['K'] * (observed_away - expected_away)
    ratings[game['homeTeam']] += model['K'] * (observed_home - expected_home)

    return (rating_away, rating_home)


def cache_request(key, url, transform):
    try:
        os.makedirs('cache')
    except FileExistsError:
        pass

    path = os.path.join('cache', f'{key}.json.gz')

    try:
        f = gzip.open(path, 'rt')
    except FileNotFoundError:
        with urlopen(url) as request:
            data = transform(json.load(request))
            with gzip.open(path, 'wt') as f:
                json.dump(data, f)
    else:
        data = json.load(f)
        f.close()

    return data


def game_score(game):
    """
    Calculates and stores the game scores for both starting pitchers of a game.
    Returns the rating adjustments.
    """
    # start-of-game events prior to season 2 day 39 are unavailable
    if (game['season'], game['day']) < (1, 38):
        return (0, 0)

    events = cache_request(game['id'],
                           'https://api.blaseball-reference.com/v1/events?gameId=' + game['id'],
                           lambda data: sorted(data['results'], key=lambda x: x['event_index']))

    adj = {}
    for which in ['away', 'home']:
        team = game[f'{which}Team']
        pitcher = next(event['pitcher_id'] for event in events if event['pitcher_team_id'] == team)
        events = list(filter(lambda event: event['pitcher_id'], events))

        score = model['gamescore']['base']
        opponent = {'away': 'home', 'home': 'away'}[which]
        # this is not quite perfect if the pitcher is replaced mid-game, but so
        # far when that happened they're never to be seen again...
        score += game[f'{opponent}Score'] * model['gamescore']['runs']

        for event in (e['event_type'] for e in events):
            if event == 'STRIKEOUT':
                score += model['gamescore']['strikeouts'] + model['gamescore']['outs']
            elif event in ['CAUGHT_STEALING', 'OUT']:
                score += model['gamescore']['outs']
            elif event == 'WALK':
                score += model['gamescore']['walks'] + model['gamescore']['hits']
            elif event in ['SINGLE', 'DOUBLE', 'TRIPLE']:
                score += model['gamescore']['hits']
            elif event in ['FIELDERS_CHOICE']:
                score += model['gamescore']['outs'] + model['gamescore']['hits']
            elif event == 'HOME_RUN':
                score += model['gamescore']['homeruns']
            elif event in ['STOLEN_BASE', 'UNKNOWN']:
                pass
            else:
                raise ValueError(f'unknown event type "{event}"')

        rgs[pitcher].append(score)
        rgs[pitcher] = rgs[pitcher][-model['playerRgs']:]
        rgs[team].append(score)
        rgs[team] = rgs[team][-model['teamRgs']:]

        adj[which] = model['gsMult'] * (sum(rgs[pitcher]) / len(rgs[pitcher])
                                      - sum(rgs[team]) / len(rgs[team]))

    return (adj['away'], adj['home'])


def error(expected, observed):
    return math.pow(expected - observed, 2)


def revert_to_mean():
    for team, rating in ratings.items():
        ratings[team] = (model['seasonRevertFactor'] * model['mean'] +
                         (1 - model['seasonRevertFactor']) * rating)


if __name__ == '__main__':
    seasons = collections.defaultdict(dict)
    for root, dirs, files in os.walk('game-data'):
        for filename in files:
            with open(os.path.join(root, filename)) as f:
                data = json.load(f)
            seasons[data[0]['season']][data[0]['day']] = data

    analysis = collections.defaultdict(lambda: {'sibr': {'count': 0, 'correct': 0, 'error': 0},
                                                'official': {'count': 0, 'correct': 0, 'error': 0}})

    for season, days in sorted(seasons.items()):
        for day, games in sorted(days.items()):
            for game in games:
                rating_away, rating_home = calculate_elo(game)
                adj_away, adj_home = game_score(game)
                expected_away, expected_home = expected(rating_away + adj_away, rating_home + adj_home)
                observed_away, observed_home = observed(game)

                analysis[season]['sibr']['count'] += 1
                analysis[season]['sibr']['correct'] += int(abs(expected_away - observed_away) < 0.5)
                analysis[season]['sibr']['error'] += error(expected_away, observed_away) + error(expected_home, observed_home)

                if game['awayOdds'] != game['homeOdds']:
                    analysis[season]['official']['count'] += 1
                    analysis[season]['official']['correct'] += int(abs(game['awayOdds'] - observed_away) < 0.5)
                    analysis[season]['official']['error'] += error(game['awayOdds'], observed_away) + error(game['homeOdds'], observed_home)

        revert_to_mean()

    for season, data in analysis.items():
        print(f'=== SEASON {season + 1} ===')
        print(f"official correct: {data['official']['correct'] / data['official']['count']}")
        print(f"    SIBR correct: {data['sibr']['correct'] / data['sibr']['count']}")
        print()
        print(f"  official error: {data['official']['error'] / data['official']['count']}")
        print(f"      SIBR error: {data['sibr']['error'] / data['sibr']['count']}")
        print()
