import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import uuid
from flask import session
from datetime import datetime
import os
import json
from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'


# Init DB (run once or with check)
def create_tables():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # tabel users jika belum ada
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        tanggal_lahir TEXT NOT NULL,
        jenis_kelamin TEXT NOT NULL
    );
    ''')

    # tabel hasil_cek jika belum ada
    c.execute('''
    CREATE TABLE IF NOT EXISTS hasil_cek (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        diagnosis TEXT NOT NULL,
        persentase TEXT NOT NULL,
        tanggal_cek TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    ''')

    # Tabel admin
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Tabel gejala
    c.execute('''
        CREATE TABLE IF NOT EXISTS gejala (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            deskripsi TEXT
        )
    ''')

    # Tabel aturan fuzzy
    c.execute('''
        CREATE TABLE IF NOT EXISTS aturan_fuzzy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gejala TEXT NOT NULL,
            kondisi TEXT NOT NULL,
            diagnosis text NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


    # Tambah admin default (jika belum ada)
def buat_admin_default():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute('SELECT * FROM admin WHERE username = ?', ('admin',))
    if c.fetchone() is None:
        password_hash = generate_password_hash('admin123')
        c.execute('INSERT INTO admin (username, password) VALUES (?, ?)', ('admin', password_hash))
        conn.commit()

    conn.close()

def setup_gejala_vars():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT gejala FROM aturan_fuzzy")
    gejala_names = [row[0] for row in c.fetchall()]
    conn.close()

    input_vars = {}
    for nama in gejala_names:
        var = ctrl.Antecedent(np.arange(0, 11, 1), nama)
        var['low'] = fuzz.trimf(var.universe, [0, 0, 5])
        var['medium'] = fuzz.trimf(var.universe, [3, 5, 7])
        var['high'] = fuzz.trimf(var.universe, [5, 10, 10])
        input_vars[nama] = var
    return input_vars

def setup_output_var():
    tuberkulosis = ctrl.Consequent(np.arange(0, 101, 1), 'tuberkulosis')
    tuberkulosis['paru'] = fuzz.trimf(tuberkulosis.universe, [0, 10, 20])
    tuberkulosis['otak'] = fuzz.trimf(tuberkulosis.universe, [20, 30, 40])
    tuberkulosis['tulang punggung'] = fuzz.trimf(tuberkulosis.universe, [40, 50, 60])
    tuberkulosis['kulit'] = fuzz.trimf(tuberkulosis.universe, [60, 70, 80])
    tuberkulosis['hati'] = fuzz.trimf(tuberkulosis.universe, [80, 90, 100])
    return tuberkulosis

def setup_rules_from_db_logic(input_vars, output_var):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Ambil semua gejala dengan kondisi 'high' untuk setiap diagnosis
    c.execute("SELECT diagnosis, gejala FROM aturan_fuzzy WHERE kondisi='high'")
    rows = c.fetchall()
    conn.close()

    # Susun dict: {'paru': [gejala1, gejala2, ...], ...}
    aturan_gejala = {}
    for diagnosis, gejala in rows:
        aturan_gejala.setdefault(diagnosis, []).append(gejala)

    rules = []

    for diagnosis, gejala_list in aturan_gejala.items():
        terms = []

        for gejala in gejala_list:
            if gejala not in input_vars:
                print(f"⚠️ Gejala '{gejala}' tidak ditemukan di input_vars. Lewati.")
                continue
            terms.append(input_vars[gejala]['high'])  # Hanya ambil 'high'

        if diagnosis not in output_var.terms:
            print(f"⚠️ Diagnosis '{diagnosis}' tidak ditemukan di output_var. Lewati.")
            continue

        if len(terms) >= 2:
            kondisi_rule = terms[0]
            for t in terms[1:]:
                kondisi_rule = kondisi_rule & t
        elif len(terms) == 1:
            kondisi_rule = terms[0]
        else:
            print(f"❌ Tidak ada gejala valid untuk diagnosis '{diagnosis}'")
            continue

        rule = ctrl.Rule(kondisi_rule, output_var[diagnosis])
        rules.append(rule)

    return rules



# Plot fungsi keanggotaan
def plot_output_membership(output_var):
    plt.figure(figsize=(8, 4))
    
    for label in output_var.terms:
        mf = output_var[label].mf
        plt.plot(output_var.universe, mf, label=label.capitalize())

    plt.title('Fungsi Keanggotaan Output - Jenis Tuberkulosis')
    plt.xlabel('Crisp Output')
    plt.ylabel('Derajat Keanggotaan')
    plt.legend(loc='upper right')
    plt.tight_layout()

    # Simpan gambar ke folder static
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join('static', filename)
    plt.savefig(filepath)
    plt.close()
    
    return filename

# Routes
@app.route('/')
def index():
    return render_template('index.html')



@app.route("/index")
def home():
    if 'user_id' not in session:
        flash('Silakan login terlebih dahulu.')
        return redirect(url_for('login'))
    return render_template('home.html', username=session.get('username'))

@app.route("/blog.html")
def blog():
    return render_template("blog.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        tanggal_lahir = request.form['tanggal_lahir']
        jenis_kelamin = request.form['jenis_kelamin']

        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute('''INSERT INTO users (username, password, tanggal_lahir, jenis_kelamin)
                         VALUES (?, ?, ?, ?)''', (username, password, tanggal_lahir, jenis_kelamin))
            conn.commit()
            conn.close()
            flash('Akun berhasil dibuat. Silakan login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username sudah digunakan. Coba yang lain.')
    return render_template('register.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = username  # Tambahkan baris ini
            return redirect(url_for('home'))
        else:
            flash('Username atau password salah.')
    return render_template('login.html')

@app.route('/profil')
def profil():
    if 'user_id' not in session:
        flash('Anda harus login terlebih dahulu.')
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Ambil data pengguna
    c.execute('SELECT username, tanggal_lahir, jenis_kelamin FROM users WHERE id = ?', (session['user_id'],))
    user = c.fetchone()

    # Ambil riwayat hasil pengecekan
    c.execute('SELECT diagnosis, persentase, tanggal_cek FROM hasil_cek WHERE user_id = ? ORDER BY tanggal_cek DESC', (session['user_id'],))
    hasil_cek = c.fetchall()

    conn.close()

    if user is None:
        flash('Data user tidak ditemukan.')
        return redirect(url_for('login'))

    # ✅ Di sinilah kamu melakukan konversi JSON string ke dict agar bisa digunakan di template
    hasil_cek_list = []
    for row in hasil_cek:
        hasil_dict = dict(row)
        hasil_dict['persentase'] = json.loads(hasil_dict['persentase'])  # ✅ DI SINI
        hasil_cek_list.append(hasil_dict)

    return render_template('profil.html', user=user, hasil_cek=hasil_cek_list)

@app.route('/logout')
def logout():
    session.clear()
    flash('Anda berhasil logout.')
    return redirect(url_for('login'))


# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        print(f"Login attempt username: {username}")

        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM admin WHERE username = ?', (username,))
        admin = c.fetchone()
        conn.close()

        print("Admin record:", admin)
        if admin and check_password_hash(admin['password'], password):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            print("Login successful")
            return redirect(url_for('admin_dashboard'))
        else:
            print("Login failed")
            flash('Username atau password salah.')
    return render_template('admin/admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    return render_template('admin/admin_dashboard.html', admin=session['admin_username'])

#gejala
@app.route('/admin/gejala/add', methods=['GET', 'POST'])
def admin_add_gejala():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        nama = request.form['nama']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT INTO gejala (nama) VALUES (?)", (nama,))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_list_gejala'))

    return render_template('admin/gejala_form.html', title='Tambah Gejala', gejala=None)

@app.route('/admin/gejala')
def admin_list_gejala():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    keyword = request.args.get('keyword', '')  # Ambil keyword dari parameter URL
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if keyword:
        c.execute("SELECT id, nama FROM gejala WHERE nama LIKE ?", ('%' + keyword + '%',))
    else:
        c.execute("SELECT id, nama FROM gejala")

    gejalas = [{'id': row[0], 'nama': row[1]} for row in c.fetchall()]
    conn.close()

    return render_template('admin/admin_list_gejala.html', gejalas=gejalas)


@app.route('/admin/gejala/edit/<int:id>', methods=['GET', 'POST'])
def admin_edit_gejala(id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'POST':
        nama = request.form['nama']
        c.execute("UPDATE gejala SET nama=? WHERE id=?", (nama, id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_list_gejala'))

    c.execute("SELECT * FROM gejala WHERE id=?", (id,))
    gejala = c.fetchone()
    conn.close()
    return render_template('admin/gejala_form.html', title='Edit Gejala', gejala=gejala)

@app.route('/admin/gejala/delete/<int:id>')
def admin_delete_gejala(id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM gejala WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_list_gejala'))

#aturan
@app.route('/admin/rules')
def admin_list_rules():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM aturan_fuzzy')
    rules = c.fetchall()
    conn.close()
    
    return render_template('admin/admin_list_rules.html', rules=rules)

@app.route('/admin/rules/add', methods=['GET', 'POST'])
def admin_add_rule():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        gejala = request.form['gejala']
        diagnosis = request.form['diagnosis']
        bobot = int(request.form['bobot'])

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('INSERT INTO aturan (gejala, diagnosis, bobot) VALUES (?, ?, ?)',
                  (gejala, diagnosis, bobot))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_list_rules'))

    return render_template('admin/rule_add.html')

@app.route('/admin/rules/edit/<int:id>', methods=['GET', 'POST'])
def admin_edit_rule(id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        gejala = request.form['gejala']
        kondisi = request.form['kondisi']
        diagnosis = request.form['diagnosis']

        c.execute("UPDATE aturan_fuzzy SET gejala=?, kondisi=?, diagnosis=? WHERE id=?",
                  (gejala, kondisi, diagnosis, id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_list_rules'))

    # GET request – tampilkan data yang sudah ada
    c.execute("SELECT * FROM aturan_fuzzy WHERE id=?", (id,))
    rule = c.fetchone()
    conn.close()

    if not rule:
        return "Aturan tidak ditemukan", 404

    return render_template('admin/rule_edit.html', rule=rule)

@app.route('/admin/rules/delete/<int:id>')
def admin_delete_rule(id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('DELETE FROM aturan_fuzzy WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_list_rules'))




@app.route('/cek', methods=['GET', 'POST'])
def cek():
    if request.method == 'GET':
        # Ambil daftar gejala dari database untuk ditampilkan di form
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT DISTINCT nama FROM gejala")
        gejala_list = [row[0] for row in c.fetchall()]
        conn.close()
        return render_template('cek.html', gejala_list=gejala_list)

    # POST: Lakukan proses diagnosis
    input_vars = setup_gejala_vars()
    output_var = setup_output_var()
    rules = setup_rules_from_db_logic(input_vars, output_var)

    system_ctrl = ctrl.ControlSystem(rules)
    sim = ctrl.ControlSystemSimulation(system_ctrl)

    # Ambil nilai dari form
    for nama_gejala in input_vars.keys():
        nilai = float(request.form.get(nama_gejala, 0))
        sim.input[nama_gejala] = nilai

    try:
        sim.compute()
        hasil_crisp = sim.output['tuberkulosis']
    except Exception as e:
        return f"❌ Error saat komputasi fuzzy: {e}"

    tb_output = {
        'paru': fuzz.interp_membership(output_var.universe, output_var['paru'].mf, hasil_crisp),
        'otak': fuzz.interp_membership(output_var.universe, output_var['otak'].mf, hasil_crisp),
        'tulang punggung': fuzz.interp_membership(output_var.universe, output_var['tulang punggung'].mf, hasil_crisp),
        'kulit': fuzz.interp_membership(output_var.universe, output_var['kulit'].mf, hasil_crisp),
        'hati': fuzz.interp_membership(output_var.universe, output_var['hati'].mf, hasil_crisp)
    }

    hasil_diagnosis = max(tb_output, key=tb_output.get)
    
    # 📝 Simpan hasil ke database
    if 'user_id' in session:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO hasil_cek (user_id, diagnosis, persentase, tanggal_cek)
            VALUES (?, ?, ?, ?)
        ''', (
            session['user_id'],
            hasil_diagnosis,
            json.dumps(tb_output),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        conn.commit()
        conn.close()

    # Buat grafik fungsi keanggotaan output
    grafik_filename = plot_output_membership(output_var)

    return render_template('hasil.html',
                            hasil=hasil_diagnosis,
                            crisp=hasil_crisp,
                            persentase=tb_output,
                            grafik=grafik_filename)
# Jalankan server Flask
if __name__ == '__main__':
    create_tables()
    buat_admin_default()# <--- tambahkan ini
    app.run(debug=True)
