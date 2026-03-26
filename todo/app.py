from flask import Flask, render_template, request, redirect, url_for, send_file, session
from fpdf import FPDF
import mysql.connector
import math
import hashlib
import uuid
import smtplib
from functools import wraps

app = Flask(__name__)
app.secret_key = 'una_stringa_casuale_molto_difficile'

DB_CONFIG = {
    "user": "",
    "password": "",
    "host": "10.25.0.14",
    "database": "",
}

# ── EMAIL CONFIG ─────────────────────────────────────────────────────────────
SMTP_SERVER    = "smtp.gmail.com"
SMTP_PORT      = 587
EMAIL_USER     = ""
EMAIL_PASSWORD = ""

def send_verification_email(to_email, username, uuid_user):
    """Invia la mail con il link di verifica contenente l'UUID."""
    verify_url = url_for('verify_email', uuid_user=uuid_user, _external=True)

    subject = "Verifica il tuo account Todo Project"
    body = (
        f"Subject: {subject}\n"
        f"Content-Type: text/plain; charset=utf-8\n\n"
        f"Ciao {username},\n\n"
        f"Clicca il link qui sotto per attivare il tuo account:\n\n"
        f"{verify_url}\n\n"
        f"Se non hai richiesto la registrazione, ignora questa email."
    )

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, to_email, body.encode('utf-8'))
        print(f"Email inviata a {to_email}")
        server.quit()
    except Exception as e:
        print(f"Errore invio email: {e}")

# ── DB ───────────────────────────────────────────────────────────────────────

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# ── DECORATORE LOGIN ─────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── HOME ─────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html")

# ── AUTH ─────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    username  = request.form['username']
    password  = request.form['password']
    email     = request.form['email']
    pw_hash   = hashlib.sha256(password.encode()).hexdigest()
    uuid_user = str(uuid.uuid4())

    cnx = get_db()
    try:
        cursor = cnx.cursor(dictionary=True)

        cursor.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cursor.fetchone():
            return render_template('register.html', error="Username già esistente")

        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            return render_template('register.html', error="Email già registrata")

        cursor.execute(
            """INSERT INTO users (username, password, email, attivo, uuid_user)
               VALUES (%s, %s, %s, 0, %s)""",
            (username, pw_hash, email, uuid_user)
        )
        cnx.commit()
    finally:
        cursor.close()
        cnx.close()

    send_verification_email(email, username, uuid_user)

    return render_template('register.html',
                           success="Registrazione completata! Controlla la tua email e clicca il link per attivare l'account.")


@app.route('/verify/<uuid_user>')
def verify_email(uuid_user):
    """Attiva l'account quando l'utente clicca il link nella email."""
    cnx = get_db()
    try:
        cursor = cnx.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE uuid_user=%s AND attivo=0", (uuid_user,))
        user = cursor.fetchone()

        if not user:
            return render_template('loginForm.html',
                                   error="Link di verifica non valido o account già attivato.")

        cursor.execute(
            "UPDATE users SET attivo=1, uuid_user=NULL WHERE id=%s",
            (user['id'],)
        )
        cnx.commit()
    finally:
        cursor.close()
        cnx.close()

    return render_template('loginForm.html',
                           success="✅ Account attivato! Ora puoi fare il login.")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('loginForm.html')

    username = request.form['username']
    password = request.form['password']
    pw_hash  = hashlib.sha256(password.encode()).hexdigest()

    cnx = get_db()
    try:
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, pw_hash)
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        cnx.close()

    if not user:
        return render_template('loginForm.html', error="Credenziali errate")

    if not user['attivo']:
        return render_template('loginForm.html',
                               error="Account non ancora attivato. Controlla la tua email.")

    session['user_id']  = user['id']
    session['username'] = user['username']
    session['super']    = user['super_utente']
    return redirect(url_for('todo_list'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── TODO ─────────────────────────────────────────────────────────────────────

@app.route("/todo")
@login_required
def todo_list():
    page     = request.args.get("page", 1, type=int)
    offset   = (page - 1) * 3
    uid      = session['user_id']
    is_super = session.get('super', 0)

    cnx = get_db()
    try:
        cursor = cnx.cursor(dictionary=True)

        if is_super:
            cursor.execute("SELECT COUNT(*) AS num FROM todo")
        else:
            cursor.execute("SELECT COUNT(*) AS num FROM todo WHERE id_user=%s", (uid,))
        num_pages = math.ceil(cursor.fetchone()['num'] / 3) or 1

        if is_super:
            cursor.execute("""
                SELECT id, description, priority, before_at, executed_at
                FROM todo
                ORDER BY executed_at IS NULL DESC, priority ASC, id DESC
                LIMIT %s OFFSET %s
            """, (3, offset))
        else:
            cursor.execute("""
                SELECT id, description, priority, before_at, executed_at
                FROM todo
                WHERE id_user=%s
                ORDER BY executed_at IS NULL DESC, priority ASC, id DESC
                LIMIT %s OFFSET %s
            """, (uid, 3, offset))

        todos = cursor.fetchall()
    finally:
        cursor.close()
        cnx.close()

    return render_template("todo.html", todos=todos, num_pages=num_pages)


@app.get("/newTask")
@login_required
def showTask():
    return render_template("showForm.html")


@app.post("/newTask")
@login_required
def newTask():
    description = request.form["description"]
    priority    = request.form["priority"]
    before_at   = request.form["before_at"]
    uid         = session['user_id']

    cnx = get_db()
    try:
        cursor = cnx.cursor()
        cursor.execute(
            "INSERT INTO todo (description, priority, before_at, id_user) VALUES (%s, %s, %s, %s)",
            (description, priority, before_at, uid)
        )
        cnx.commit()
    finally:
        cursor.close()
        cnx.close()

    return redirect(url_for("todo_list"))


@app.post("/esegui/<int:id>")
@login_required
def esegui(id):
    cnx = get_db()
    try:
        cursor = cnx.cursor()
        cursor.execute("UPDATE todo SET executed_at = CURDATE() WHERE id=%s", (id,))
        cnx.commit()
    finally:
        cursor.close()
        cnx.close()
    return redirect(url_for("todo_list"))


@app.post("/eliminaTask/<int:id>")
@login_required
def eliminaTask(id):
    cnx = get_db()
    try:
        cursor = cnx.cursor()
        cursor.execute("DELETE FROM todo WHERE id=%s", (id,))
        cnx.commit()
    finally:
        cursor.close()
        cnx.close()
    return redirect(url_for("todo_list"))

# ── STAMPA PDF ───────────────────────────────────────────────────────────────

@app.route("/stampa")
@login_required
def stampa():
    uid      = session['user_id']
    is_super = session.get('super', 0)

    cnx = get_db()
    try:
        cursor = cnx.cursor()
        if is_super:
            cursor.execute("SELECT COUNT(*) FROM todo")
        else:
            cursor.execute("SELECT COUNT(*) FROM todo WHERE id_user=%s", (uid,))
        num_todos = cursor.fetchone()[0]
    finally:
        cursor.close()
        cnx.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Numero totale di TODO: {num_todos}", ln=True)

    pdf_file = "todo1.pdf"
    pdf.output(pdf_file)
    return send_file(pdf_file, mimetype="application/pdf", as_attachment=False)

# ── ABOUT ────────────────────────────────────────────────────────────────────

@app.route("/about")
def about():
    return render_template("about.html")

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)