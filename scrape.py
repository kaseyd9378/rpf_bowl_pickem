
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from db import get_conn

NCAA_URL = 'https://www.ncaa.com/news/football/article/2025-12-07/2025-26-college-football-bowl-game-schedule-scores-tv-channels-times'

DATE_RE = re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+)\s+(\d{1,2})')
LINE_RE = re.compile(
    r'^(?P<bowl>[^\n]+?)\s+'
    r'(?P<team1>[^\n]+?)\s+vs\.\s+(?P<team2>[^\n]+?)\s+'
    r'(?P<time>[0-9:.]+\s*(?:a|p)\.m\.)\s*\|\s*(?P<network>[^\n|]+)\s*(?P<location>.*)$'
)
TIME_RE = re.compile(r'^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ap>[ap])\.m\.$', re.IGNORECASE)

ET = ZoneInfo('America/New_York')
PT = ZoneInfo('America/Los_Angeles')

CFP_POINTS = {'first': 1, 'quarter': 2, 'semi': 3, 'final': 4}

def scrape_ncaa(url: str = NCAA_URL) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    container = soup.select_one('article') or soup.select_one('.field--name-body') or soup.select_one('main') or soup
    lines = []
    for el in container.find_all(['h2','h3','li','p']):
        txt = ' '.join(el.get_text(' ', strip=True).split())
        if txt:
            lines.append(txt)

    current_month = None
    current_day = None
    records = []

    for line in lines:
        dm = DATE_RE.match(line)
        if dm:
            current_month = dm.group(2)
            current_day = dm.group(3)
            continue
        if 'vs.' in line:
            m = LINE_RE.match(line)
            if not m:
                m2 = re.search(r'(?P<team1>[^|]+?)\s+vs\.\s+(?P<team2>[^|]+?)\s+(?P<time>[0-9:.]+\s*(?:a|p)\.m\.)\s*\|\s*(?P<network>[^\n|]+)', line)
                bowl_name = line.split(' vs. ')[0].strip()
                if m2:
                    team1 = m2.group('team1').strip()
                    team2 = m2.group('team2').strip()
                    time_et = m2.group('time').strip()
                    network = m2.group('network').strip()
                    location = None
                else:
                    continue
            else:
                bowl_name = m.group('bowl').strip()
                team1 = m.group('team1').strip()
                team2 = m.group('team2').strip()
                time_et = m.group('time').strip()
                network = m.group('network').strip()
                location = (m.group('location') or '').strip() or None

            # Date
            game_date = None
            if current_month and current_day:
                for fmt in ('%b','%B'):
                    try:
                        dt = datetime.strptime(f"{current_month} {current_day} 2025", f"{fmt} %d %Y")
                        game_date = dt.strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        pass

            # CFP round + points
            is_cfp = 0
            cfp_round = None
            bl = bowl_name.lower()
            if 'college football playoff' in bl:
                is_cfp = 1
                if 'first round' in bl:
                    cfp_round = 'first'
                elif 'quarterfinal' in bl:
                    cfp_round = 'quarter'
                elif 'semifinal' in bl:
                    cfp_round = 'semi'
                elif 'national championship' in bl:
                    cfp_round = 'final'
            points_per_win = CFP_POINTS.get(cfp_round, 1)

            # ET -> PT
            kickoff_et = kickoff_pt = lock_pt = None
            if game_date and time_et:
                tm = TIME_RE.match(time_et)
                if tm:
                    hour = int(tm.group('hour'))
                    minute = int(tm.group('minute') or 0)
                    ap = tm.group('ap').lower()
                    if ap == 'p' and hour != 12:
                        hour += 12
                    if ap == 'a' and hour == 12:
                        hour = 0
                    dt_et = datetime.fromisoformat(game_date).replace(hour=hour, minute=minute, tzinfo=ET)
                    kickoff_et = dt_et.isoformat()
                    dt_pt = dt_et.astimezone(PT)
                    kickoff_pt = dt_pt.isoformat()
                    lock_pt = kickoff_pt

            records.append({
                'bowl_name': bowl_name,
                'team1': team1,
                'team2': team2,
                'game_date': game_date,
                'game_time_et': time_et,
                'network': network,
                'location': location,
                'is_cfp': is_cfp,
                'cfp_round': cfp_round,
                'points_per_win': points_per_win,
                'kickoff_et': kickoff_et,
                'kickoff_pt': kickoff_pt,
                'lock_pt': lock_pt,
            })

    return pd.DataFrame(records)


def load_into_db(contest_id: int, df: pd.DataFrame):
    conn = get_conn()
    cur = conn.cursor()
    for _, r in df.iterrows():
        cur.execute(
            'INSERT INTO games (contest_id,bowl_name,team1,team2,game_date,game_time_et,network,location,is_cfp,cfp_round,points_per_win,kickoff_et,kickoff_pt,lock_pt,winner) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
            (
                contest_id,
                r.get('bowl_name'), r.get('team1'), r.get('team2'),
                r.get('game_date'), r.get('game_time_et'),
                r.get('network'),   r.get('location'),
                int(r.get('is_cfp') or 0), r.get('cfp_round'),
                int(r.get('points_per_win') or 1),
                r.get('kickoff_et'), r.get('kickoff_pt'), r.get('lock_pt')
            )
        )
    conn.commit()
    conn.close()


def build_cfp_links(contest_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id,bowl_name,team1,team2,cfp_round FROM games WHERE contest_id=?', (contest_id,))
    rows = cur.fetchall()

    def find(pred):
        for r in rows:
            if pred(r):
                return r
        return None

    # Identify First Round games by teams
    fr_ou_ala = find(lambda r: r['cfp_round']=='first' and ('Oklahoma' in r['team1'] or 'Oklahoma' in r['team2']) and ('Alabama' in r['team1'] or 'Alabama' in r['team2']))
    fr_tamu_mia = find(lambda r: r['cfp_round']=='first' and ('Texas A&M' in r['team1'] or 'Texas A&M' in r['team2']) and ('Miami' in r['team1'] or 'Miami' in r['team2']))
    fr_om_tul  = find(lambda r: r['cfp_round']=='first' and ('Ole Miss' in r['team1'] or 'Ole Miss' in r['team2']) and ('Tulane' in r['team1'] or 'Tulane' in r['team2']))
    fr_ore_jmu = find(lambda r: r['cfp_round']=='first' and ('Oregon' in r['team1'] or 'Oregon' in r['team2']) and ('James Madison' in r['team1'] or 'James Madison' in r['team2']))

    # Quarterfinals by bowl name
    qf_orange = find(lambda r: r['cfp_round']=='quarter' and 'Orange Bowl' in r['bowl_name'])
    qf_rose   = find(lambda r: r['cfp_round']=='quarter' and 'Rose Bowl'   in r['bowl_name'])
    qf_sugar  = find(lambda r: r['cfp_round']=='quarter' and 'Sugar Bowl'  in r['bowl_name'])
    qf_cotton = find(lambda r: r['cfp_round']=='quarter' and 'Cotton Bowl' in r['bowl_name'])

    # Semifinals
    sf_fiesta = find(lambda r: r['cfp_round']=='semi' and 'Fiesta Bowl' in r['bowl_name'])
    sf_peach  = find(lambda r: r['cfp_round']=='semi' and 'Peach Bowl'  in r['bowl_name'])

    # Final
    final     = find(lambda r: r['cfp_round']=='final')

    def link(game, slot, dep):
        if game and dep:
            cur.execute('INSERT INTO cfp_links (game_id,slot,depends_on_game_id) VALUES (?,?,?)', (game['id'], slot, dep['id']))

    # Quarterfinal dependencies: team2 depends on First Round winners
    link(qf_orange, 'team2', fr_ore_jmu)
    link(qf_rose,   'team2', fr_ou_ala)
    link(qf_sugar,  'team2', fr_om_tul)
    link(qf_cotton, 'team2', fr_tamu_mia)

    # Semifinal dependencies (crossing assumption)
    link(sf_fiesta, 'team1', qf_orange)
    link(sf_fiesta, 'team2', qf_cotton)
    link(sf_peach,  'team1', qf_rose)
    link(sf_peach,  'team2', qf_sugar)

    # Final dependencies
    link(final, 'team1', sf_fiesta)
    link(final, 'team2', sf_peach)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    from db import init_db
    init_db()
    df = scrape_ncaa(NCAA_URL)
    print(f'Scraped {len(df)} games')

    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id FROM contests WHERE name=?', ("Bowl Pick'em 2025-26",))
    row = cur.fetchone()
    if row:
        contest_id = row['id']
    else:
        cur.execute('INSERT INTO contests (name,access_code,admin_code) VALUES (?,?,?)', ("Bowl Pick'em 2025-26","JOIN2025","ADMIN2025"))
        conn.commit()
        contest_id = cur.lastrowid
        print(f'Created contest id={contest_id} (access_code=JOIN2025, admin_code=ADMIN2025)')

    load_into_db(contest_id, df)
    build_cfp_links(contest_id)
    df.to_csv('games.csv', index=False)
    print('Loaded games, built CFP links, wrote games.csv')
