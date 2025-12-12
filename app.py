
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, flash
from db import init_db, get_conn

PT = ZoneInfo('America/Los_Angeles')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')


# Initialize the database when the app is created (Flask 3.x safe)
with app.app_context():
    init_db()


# Helpers

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id=?', (uid,))
    user = cur.fetchone()
    conn.close()
    return user

def require_manager():
    user = current_user()
    if not user or user['role'] != 'manager':
        flash('Manager access required.', 'error')
        return False
    return True

# Routes
@app.get("/")
def landing():
    # Flask auto-adds HEAD when GET is present, but being explicit and tolerant helps.
    # If you want to skip template rendering on HEAD:
    if request.method == "HEAD":
        # return headers only; Flask/Werkzeug will drop the body for HEAD anyway.
        return "", 200
    # Normal GET flow:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM contests ORDER BY created_at DESC")
    contests = cur.fetchall()
    conn.close()
    return render_template("landing.html", contests=contests)


@app.get('/contest/create')
def create_contest_form():
    return render_template('create_contest.html')

@app.post('/contest/create')
def create_contest():
    name = request.form.get('name')
    access_code = request.form.get('access_code')
    admin_code = request.form.get('admin_code')
    if not all([name, access_code, admin_code]):
        flash('All fields are required.', 'error')
        return redirect(url_for('create_contest_form'))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO contests (name, access_code, admin_code) VALUES (?, ?, ?)', (name, access_code, admin_code))
    conn.commit()
    conn.close()
    flash(f'Contest "{name}" created. Share the access code with players.')
    return redirect(url_for('landing'))

@app.get('/admin')
def admin_login_form():
    return render_template('admin_login.html')

@app.post('/admin')
def admin_login():
    contest_id = request.form.get('contest_id')
    admin_code = request.form.get('admin_code')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM contests WHERE id=? AND admin_code=?', (contest_id, admin_code))
    contest = cur.fetchone()
    if not contest:
        flash('Invalid admin code or contest.', 'error')
        return redirect(url_for('admin_login_form'))
    cur.execute('INSERT INTO users (contest_id, display_name, role) VALUES (?, ?, ?)', (contest['id'], 'Manager', 'manager'))
    conn.commit()
    session['user_id'] = cur.lastrowid
    session['contest_id'] = contest['id']
    session['role'] = 'manager'
    conn.close()
    return redirect(url_for('manage_games'))

@app.get('/join')
def join_form():
    return render_template('join.html')

@app.post('/join')
def join():
    display_name = request.form.get('display_name')
    access_code = request.form.get('access_code')
    contest_id = request.form.get('contest_id')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM contests WHERE id=? AND access_code=?', (contest_id, access_code))
    contest = cur.fetchone()
    if not contest:
        flash('Invalid access code or contest.', 'error')
        return redirect(url_for('join_form'))
    cur.execute('INSERT INTO users (contest_id, display_name, role) VALUES (?, ?, ?)', (contest['id'], display_name, 'player'))
    conn.commit()
    session['user_id'] = cur.lastrowid
    session['contest_id'] = contest['id']
    session['role'] = 'player'
    conn.close()
    return redirect(url_for('picks'))

# Picks page
@app.get('/picks')
def picks():
    user = current_user()
    if not user:
        return redirect(url_for('join_form'))
    contest_id = user['contest_id']
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM games WHERE contest_id=? ORDER BY is_cfp ASC, game_date, id', (contest_id,))
    games = cur.fetchall()
    cur.execute('SELECT game_id, pick FROM picks WHERE user_id=?', (user['id'],))
    picks_map = {row['game_id']: row['pick'] for row in cur.fetchall()}

    cur.execute('SELECT game_id, slot, depends_on_game_id FROM cfp_links WHERE game_id IN (SELECT id FROM games WHERE contest_id=?)', (contest_id,))
    links = cur.fetchall()
    link_map = {}
    for l in links:
        link_map.setdefault(l['game_id'], []).append({'slot': l['slot'], 'depends_on': l['depends_on_game_id']})

    def resolved_team_name(dep_game_id):
        earlier_pick = picks_map.get(dep_game_id)
        if not earlier_pick:
            return None
        for g in games:
            if g['id'] == dep_game_id:
                return g['team1'] if earlier_pick == 'team1' else g['team2']
        return None

    display_games = []
    for g in games:
        t1, t2 = g['team1'], g['team2']
        if g['is_cfp'] == 1:
            for l in link_map.get(g['id'], []):
                if l['slot'] == 'team1':
                    rt = resolved_team_name(l['depends_on'])
                    if rt:
                        t1 = rt
                elif l['slot'] == 'team2':
                    rt = resolved_team_name(l['depends_on'])
                    if rt:
                        t2 = rt
        display_games.append({**dict(g), 'disp_team1': t1, 'disp_team2': t2})

    conn.close()
    return render_template('picks.html', games=display_games, picks_map=picks_map)

@app.post('/picks')
def save_picks():
    user = current_user()
    if not user:
        return redirect(url_for('join_form'))
    now_pt = datetime.now(PT)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute('SELECT * FROM games WHERE contest_id=?', (user['contest_id'],))
    all_games = cur.fetchall()

    cur.execute('SELECT game_id, slot, depends_on_game_id FROM cfp_links WHERE game_id IN (SELECT id FROM games WHERE contest_id=?)', (user['contest_id'],))
    links = cur.fetchall()
    dep_map = {}
    for l in links:
        dep_map.setdefault(l['game_id'], []).append({'slot': l['slot'], 'depends_on': l['depends_on_game_id']})

    for g in all_games:
        pid = f"pick_{g['id']}"
        pick = request.form.get(pid)
        if pick not in ('team1','team2'):
            continue
        lock_pt = g['lock_pt']
        if lock_pt:
            try:
                lock_dt = datetime.fromisoformat(lock_pt)
                if now_pt >= lock_dt:
                    continue
            except Exception:
                pass
        if g['is_cfp'] == 1:
            deps = dep_map.get(g['id'], [])
            for d in deps:
                if d['slot'] == pick:
                    cur.execute('SELECT pick FROM picks WHERE user_id=? AND game_id=?', (user['id'], d['depends_on']))
                    if not cur.fetchone():
                        pick = None
                        break
            if pick is None:
                continue
        try:
            cur.execute('INSERT INTO picks (user_id, game_id, pick) VALUES (?, ?, ?)', (user['id'], g['id'], pick))
        except Exception:
            cur.execute('UPDATE picks SET pick=? WHERE user_id=? AND game_id=?', (pick, user['id'], g['id']))

    conn.commit()
    conn.close()
    flash('Picks saved!', 'success')
    return redirect(url_for('picks'))

@app.get('/manage/games')
def manage_games():
    if not require_manager():
        return redirect(url_for('admin_login_form'))
    contest_id = session.get('contest_id')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM games WHERE contest_id=? ORDER BY game_date, id', (contest_id,))
    games = cur.fetchall()
    conn.close()
    return render_template('manage_games.html', games=games)

@app.post('/manage/games')
def update_winners():
    if not require_manager():
        return redirect(url_for('admin_login_form'))
    contest_id = session.get('contest_id')
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, points_per_win FROM games WHERE contest_id=?', (contest_id,))

    for row in cur.fetchall():
        gid = str(row['id'])
        winner = request.form.get(f'winner_{gid}')
        if winner in ('team1', 'team2'):
            cur.execute('UPDATE games SET winner=? WHERE id=?', (winner, gid))
            cur.execute('UPDATE picks SET points_awarded=CASE WHEN pick=? THEN ? ELSE 0 END WHERE game_id=?', (winner, row['points_per_win'], gid))
    conn.commit()
    conn.close()
    flash('Winners updated and points awarded.', 'success')
    return redirect(url_for('manage_games'))

@app.get('/scoreboard')
def scoreboard():
    contest_id = session.get('contest_id')
    conn = get_conn()
    cur = conn.cursor()
    if not contest_id:
        cur.execute('SELECT id FROM contests ORDER BY created_at DESC LIMIT 1')
        row = cur.fetchone()
        contest_id = row['id'] if row else None
    rows = []
    if contest_id:
        cur.execute(
            'SELECT u.display_name, COALESCE(SUM(p.points_awarded),0) AS points FROM users u LEFT JOIN picks p ON p.user_id=u.id WHERE u.contest_id=? GROUP BY u.id ORDER BY points DESC, u.display_name',
            (contest_id,)
        )
        rows = cur.fetchall()
    conn.close()
    return render_template('scoreboard.html', rows=rows)

@app.post('/admin/scrape')
def admin_scrape():
    if not require_manager():
        return redirect(url_for('admin_login_form'))
    from scrape import scrape_ncaa, NCAA_URL, load_into_db, build_cfp_links
    contest_id = session.get('contest_id')
    df = scrape_ncaa(NCAA_URL)
    load_into_db(contest_id, df)
    build_cfp_links(contest_id)
    flash(f'Loaded {len(df)} games from NCAA and rebuilt CFP links.', 'success')
    return redirect(url_for('manage_games'))

if __name__ == '__main__':
    app.run(debug=True)
