from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, uuid
from functools import wraps

app = Flask(__name__)
app.secret_key = 'notes_platform_super_secret_2024'
UPLOAD_FOLDER = 'uploads'
MAX_MB = 10
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_MB * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DB = 'notes.db'


# ─── DB Helpers ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            title             TEXT NOT NULL,
            description       TEXT,
            subject_id        INTEGER,
            filename          TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            user_id           INTEGER,
            downloads         INTEGER DEFAULT 0,
            likes             INTEGER DEFAULT 0,
            created_at        TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (user_id)    REFERENCES users(id)
        );
        INSERT OR IGNORE INTO subjects (name) VALUES
            ('Mathematics'),('Physics'),('Chemistry'),('Biology'),
            ('Computer Science'),('English'),('History'),('Economics'),
            ('Data Structures'),('Algorithms'),('Operating Systems'),
            ('Database Management'),('Computer Networks'),('Machine Learning'),('Other');
    ''')
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    subjects    = conn.execute('SELECT s.*, COUNT(n.id) as note_count FROM subjects s LEFT JOIN notes n ON s.id=n.subject_id GROUP BY s.id').fetchall()
    top_notes   = conn.execute('''
        SELECT n.*, s.name as subject_name, u.username
        FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
        ORDER BY n.downloads DESC LIMIT 6''').fetchall()
    recent_notes = conn.execute('''
        SELECT n.*, s.name as subject_name, u.username
        FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
        ORDER BY n.created_at DESC LIMIT 6''').fetchall()
    total_notes = conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]
    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    return render_template('index.html', subjects=subjects, top_notes=top_notes,
                           recent_notes=recent_notes, total_notes=total_notes, total_users=total_users)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email    = request.form['email'].strip()
        password = request.form['password']
        if not username or not email or not password:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        conn = get_db()
        if conn.execute('SELECT id FROM users WHERE username=? OR email=?', (username, email)).fetchone():
            flash('Username or email already exists.', 'error')
            conn.close()
            return render_template('register.html')
        conn.execute('INSERT INTO users (username, email, password) VALUES (?,?,?)',
                     (username, email, generate_password_hash(password)))
        conn.commit()
        conn.close()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip()
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    conn     = get_db()
    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    if request.method == 'POST':
        title       = request.form['title'].strip()
        description = request.form.get('description', '').strip()
        subject_id  = request.form.get('subject_id')
        file        = request.files.get('file')

        if not title:
            flash('Title is required.', 'error')
            return render_template('upload.html', subjects=subjects)
        if not subject_id:
            flash('Please select a subject.', 'error')
            return render_template('upload.html', subjects=subjects)
        if not file or file.filename == '':
            flash('Please select a PDF file.', 'error')
            return render_template('upload.html', subjects=subjects)
        if not allowed_file(file.filename):
            flash('Only PDF files are allowed.', 'error')
            return render_template('upload.html', subjects=subjects)

        # Duplicate check
        if conn.execute('SELECT id FROM notes WHERE title=? AND subject_id=? AND user_id=?',
                        (title, subject_id, session['user_id'])).fetchone():
            flash('You already uploaded a note with this title in this subject.', 'warning')
            conn.close()
            return render_template('upload.html', subjects=subjects)

        original_filename = secure_filename(file.filename)
        unique_filename   = f"{uuid.uuid4().hex}_{original_filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))

        conn.execute('''INSERT INTO notes (title, description, subject_id, filename, original_filename, user_id)
                        VALUES (?,?,?,?,?,?)''',
                     (title, description, subject_id, unique_filename, original_filename, session['user_id']))
        conn.commit()
        conn.close()
        flash('Notes uploaded successfully! 🎉', 'success')
        return redirect(url_for('browse'))

    conn.close()
    return render_template('upload.html', subjects=subjects)


@app.route('/browse')
def browse():
    conn       = get_db()
    subject_id = request.args.get('subject_id', '')
    subjects   = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    if subject_id:
        notes = conn.execute('''
            SELECT n.*, s.name as subject_name, u.username
            FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
            WHERE n.subject_id=? ORDER BY n.created_at DESC''', (subject_id,)).fetchall()
    else:
        notes = conn.execute('''
            SELECT n.*, s.name as subject_name, u.username
            FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
            ORDER BY n.created_at DESC''').fetchall()
    conn.close()
    return render_template('browse.html', notes=notes, subjects=subjects, selected=subject_id)


@app.route('/search')
def search():
    query    = request.args.get('q', '').strip()
    conn     = get_db()
    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    notes    = []
    if query:
        notes = conn.execute('''
            SELECT n.*, s.name as subject_name, u.username
            FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
            WHERE n.title LIKE ? OR n.description LIKE ? OR s.name LIKE ?
            ORDER BY n.downloads DESC''',
            (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    return render_template('search.html', notes=notes, query=query, subjects=subjects)


@app.route('/note/<int:note_id>')
def note_detail(note_id):
    conn = get_db()
    note = conn.execute('''
        SELECT n.*, s.name as subject_name, u.username
        FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
        WHERE n.id=?''', (note_id,)).fetchone()
    if not note:
        flash('Note not found.', 'error')
        return redirect(url_for('browse'))

    # ── AI Recommendation: TF-IDF cosine similarity ──
    all_notes = conn.execute('''
        SELECT n.*, s.name as subject_name, u.username
        FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
    ''').fetchall()
    recommendations = []
    if len(all_notes) > 1:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            texts    = [f"{n['title']} {n['description'] or ''} {n['subject_name']}" for n in all_notes]
            note_ids = [n['id'] for n in all_notes]
            tfidf    = TfidfVectorizer(stop_words='english', min_df=1)
            matrix   = tfidf.fit_transform(texts)
            idx      = note_ids.index(note_id)
            scores   = cosine_similarity(matrix[idx], matrix).flatten()
            scores[idx] = 0
            top      = scores.argsort()[-4:][::-1]
            recommendations = [all_notes[i] for i in top if scores[i] > 0]
        except Exception:
            recommendations = conn.execute('''
                SELECT n.*, s.name as subject_name, u.username
                FROM notes n JOIN subjects s ON n.subject_id=s.id JOIN users u ON n.user_id=u.id
                WHERE n.subject_id=? AND n.id!=? LIMIT 4''',
                (note['subject_id'], note_id)).fetchall()

    conn.close()
    return render_template('note_detail.html', note=note, recommendations=recommendations)


@app.route('/download/<int:note_id>')
def download(note_id):
    conn = get_db()
    note = conn.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
    if not note:
        flash('Note not found.', 'error')
        return redirect(url_for('browse'))
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], note['filename'])
    if not os.path.exists(filepath):
        flash('File no longer exists on server.', 'error')
        return redirect(url_for('browse'))
    conn.execute('UPDATE notes SET downloads=downloads+1 WHERE id=?', (note_id,))
    conn.commit()
    conn.close()
    return send_file(filepath, as_attachment=True, download_name=note['original_filename'])


@app.route('/like/<int:note_id>', methods=['POST'])
@login_required
def like(note_id):
    conn = get_db()
    conn.execute('UPDATE notes SET likes=likes+1 WHERE id=?', (note_id,))
    conn.commit()
    likes = conn.execute('SELECT likes FROM notes WHERE id=?', (note_id,)).fetchone()[0]
    conn.close()
    return jsonify({'likes': likes})


@app.route('/my-notes')
@login_required
def my_notes():
    conn  = get_db()
    notes = conn.execute('''
        SELECT n.*, s.name as subject_name
        FROM notes n JOIN subjects s ON n.subject_id=s.id
        WHERE n.user_id=? ORDER BY n.created_at DESC''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('my_notes.html', notes=notes)


@app.route('/delete/<int:note_id>', methods=['POST'])
@login_required
def delete_note(note_id):
    conn = get_db()
    note = conn.execute('SELECT * FROM notes WHERE id=? AND user_id=?',
                        (note_id, session['user_id'])).fetchone()
    if note:
        fp = os.path.join(app.config['UPLOAD_FOLDER'], note['filename'])
        if os.path.exists(fp):
            os.remove(fp)
        conn.execute('DELETE FROM notes WHERE id=?', (note_id,))
        conn.commit()
        flash('Note deleted.', 'success')
    else:
        flash('Unauthorized.', 'error')
    conn.close()
    return redirect(url_for('my_notes'))


@app.errorhandler(413)
def too_large(e):
    flash(f'File too large! Maximum size is {MAX_MB}MB.', 'error')
    return redirect(url_for('upload'))


if __name__ == '__main__':
    init_db()
    print("\n🚀  NoteShare Platform running at http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
