"""
Advanced Customer Ledger App (with automatic migrations)

This version includes an automatic migration that will:
- Detect old 'customers' table and move older 'amount' values into 'transactions' when present.
- Ensure the 'phone' column exists on the customers table (adds it if missing).

Run:
    export LEDGER_PASS=yourpassword   # Linux / macOS
    set LEDGER_PASS=yourpassword      # Windows cmd
    $env:LEDGER_PASS="yourpassword" # PowerShell
    python app.py

The app listens on 0.0.0.0:8000 by default.
"""
from flask import (
    Flask,
    request,
    g,
    redirect,
    url_for,
    render_template_string,
    Response,
    session,
    flash,
)
import sqlite3
from pathlib import Path
import csv
from io import StringIO
from datetime import datetime
import os

# ---------------- CONFIG ----------------
DB_PATH = Path(__file__).parent / "customers.db"
app = Flask(__name__)
app.config["DATABASE"] = str(DB_PATH)
app.secret_key = os.environ.get("LEDGER_SECRET", "change_this_secret")
ADMIN_PASSWORD = os.environ.get("LEDGER_PASS", "changeme")

# ----------------- TEMPLATE -----------------
TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Advanced Customer Ledger</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style> .mono {font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;} </style>
  </head>
  <body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">Ledger</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav ms-auto">
            {% if session.get('logged_in') %}
            <li class="nav-item"><a class="nav-link" href="/">Dashboard</a></li>
            <li class="nav-item"><a class="nav-link" href="/logout">Logout</a></li>
            {% else %}
            <li class="nav-item"><a class="nav-link" href="/login">Login</a></li>
            {% endif %}
          </ul>
        </div>
      </div>
    </nav>

    <div class="container py-4">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          {% for m in messages %}
            <div class="alert alert-info">{{ m }}</div>
          {% endfor %}
        {% endif %}
      {% endwith %}

      {% if page == 'login' %}
        <div class="row justify-content-center">
          <div class="col-md-6">
            <div class="card">
              <div class="card-body">
                <h4 class="card-title mb-3">Admin Login</h4>
                <form method="post" action="/login">
                  <div class="mb-3">
                    <label class="form-label">Password</label>
                    <input type="password" name="password" class="form-control" required>
                  </div>
                  <button class="btn btn-primary">Login</button>
                </form>
                <p class="mt-3 text-muted small">Password is stored in environment variable <code class="mono">LEDGER_PASS</code>.</p>
              </div>
            </div>
          </div>
        </div>

      {% elif page == 'dashboard' %}

        <div class="row mb-4">
          <div class="col-md-6">
            <form method="get" action="/">
              <div class="input-group">
                <input name="q" value="{{ q }}" placeholder="Search name or phone" class="form-control">
                <button class="btn btn-outline-secondary">Search</button>
              </div>
            </form>
          </div>
          <div class="col-md-6 text-end">
            <a href="/export/customers.csv" class="btn btn-success">Export Customers CSV</a>
            <a href="/export/transactions.csv" class="btn btn-secondary">Export Transactions CSV</a>
            <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#importModal">Import CSV</button>
          </div>
        </div>

        <div class="card mb-4">
          <div class="card-body">
            <h5 class="card-title">Add Customer</h5>
            <form method="post" action="/add_customer" class="row g-2 align-items-end">
              <div class="col-sm-5"><input name="name" required class="form-control" placeholder="Name"></div>
              <div class="col-sm-4"><input name="phone" class="form-control" placeholder="Phone (optional)"></div>
              <div class="col-sm-3"><button class="btn btn-primary w-100">Add Customer</button></div>
            </form>
          </div>
        </div>

        <div class="card">
          <div class="card-body">
            <h5 class="card-title">Customers</h5>
            {% if customers %}
            <div class="table-responsive">
              <table class="table table-striped">
                <thead>
                  <tr><th>#</th><th>Name</th><th>Phone</th><th class="text-end">Balance</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {% for c in customers %}
                    <tr>
                      <td>{{ loop.index }}</td>
                      <td>{{ c['name'] }}</td>
                      <td>{{ c['phone'] or '-' }}</td>
                      <td class="text-end">{{ '%.2f'|format(c['balance']) }}</td>
                      <td>
                        <a class="btn btn-sm btn-outline-primary" href="/customer/{{ c['id'] }}">View</a>
                        <form method="post" action="/delete_customer/{{ c['id'] }}" style="display:inline-block;">
                          <button class="btn btn-sm btn-danger" onclick="return confirm('Delete customer and transactions?')">Delete</button>
                        </form>
                      </td>
                    </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
            {% else %}
              <p class="text-muted">No customers yet.</p>
            {% endif %}
          </div>
        </div>

        <!-- Import Modal -->
        <div class="modal fade" id="importModal" tabindex="-1" aria-hidden="true">
          <div class="modal-dialog">
            <div class="modal-content">
              <form method="post" action="/import" enctype="multipart/form-data">
                <div class="modal-header"><h5 class="modal-title">Import CSV</h5></div>
                <div class="modal-body">
                  <p>CSV should have headers: <code>name,phone</code> for customers OR <code>customer_id,amount,type,note,date</code> for transactions.</p>
                  <div class="mb-3"><input type="file" name="file" class="form-control" required></div>
                </div>
                <div class="modal-footer">
                  <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                  <button class="btn btn-primary">Import</button>
                </div>
              </form>
            </div>
          </div>
        </div>

      {% elif page == 'customer' %}
        <div class="row">
          <div class="col-md-6">
            <div class="card mb-3">
              <div class="card-body">
                <h4>{{ customer['name'] }}</h4>
                <p class="mb-1"><strong>Phone:</strong> {{ customer['phone'] or '-' }}</p>
                <p class="mb-1"><strong>Balance:</strong> {{ '%.2f'|format(customer['balance']) }}</p>
              </div>
            </div>

            <div class="card mb-3">
              <div class="card-body">
                <h5 class="card-title">Add Transaction</h5>
                <form method="post" action="/customer/{{ customer['id'] }}/add_txn">
                  <div class="mb-2"><label class="form-label">Amount</label><input name="amount" required type="number" step="0.01" class="form-control"></div>
                  <div class="mb-2"><label class="form-label">Type</label><select name="type" class="form-select"><option value="debit">Debit (customer owes)</option><option value="credit">Credit (customer paid)</option></select></div>
                  <div class="mb-2"><label class="form-label">Note</label><input name="note" class="form-control"></div>
                  <button class="btn btn-primary">Add Transaction</button>
                </form>
              </div>
            </div>

            <a href="/export/transactions.csv?customer_id={{ customer['id'] }}" class="btn btn-sm btn-success mb-3">Export transactions CSV</a>

          </div>

          <div class="col-md-6">
            <div class="card">
              <div class="card-body">
                <h5 class="card-title">Transactions</h5>
                {% if txns %}
                <div class="table-responsive">
                  <table class="table table-sm">
                    <thead><tr><th>#</th><th>Date</th><th>Type</th><th class="text-end">Amount</th><th>Note</th></tr></thead>
                    <tbody>
                      {% for t in txns %}
                        <tr>
                          <td>{{ loop.index }}</td>
                          <td>{{ t['created_at'] }}</td>
                          <td>{{ t['type'] }}</td>
                          <td class="text-end">{{ '%.2f'|format(t['amount']) }}</td>
                          <td>{{ t['note'] or '' }}</td>
                        </tr>
                      {% endfor %}
                    </tbody>
                  </table>
                </div>
                {% else %}
                  <p class="text-muted">No transactions yet.</p>
                {% endif %}
              </div>
            </div>
          </div>
        </div>

      {% endif %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

# ----------------- DB UTILITIES -----------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables and perform safe automatic migrations if needed."""
    db = sqlite3.connect(app.config["DATABASE"])
    cur = db.cursor()

    # If customers table exists, check for missing 'phone' and existing 'amount' column to migrate
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
    exists = cur.fetchone()

    if exists:
        # inspect columns
        cur.execute("PRAGMA table_info(customers)")
        cols = [r[1] for r in cur.fetchall()]
        # add phone column if missing
        if 'phone' not in cols:
            print("Adding missing 'phone' column to customers table...")
            cur.execute("ALTER TABLE customers ADD COLUMN phone TEXT")
            db.commit()
        # if old schema had 'amount' column, migrate values into transactions
        if 'amount' in cols:
            print("Old 'amount' column detected — migrating to transactions...")
            # ensure transactions table exists
            cur.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
            # move positive amounts -> debit, negative -> credit
            cur.execute('SELECT id, amount FROM customers')
            rows = cur.fetchall()
            for r in rows:
                cid, amt = r
                if amt is None:
                    continue
                if amt == 0:
                    continue
                ttype = 'debit' if amt > 0 else 'credit'
                now = datetime.utcnow().isoformat()
                cur.execute('INSERT INTO transactions (customer_id, amount, type, note, created_at) VALUES (?,?,?,?,?)', (cid, abs(amt), ttype, 'migrated', now))
            # Note: removing a column in SQLite is complex — we leave the column but future code ignores it
            db.commit()
            db.close()
            return
    # If customers table does not exist, create fresh schema
    cur.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    db.commit()
    db.close()

# ----------------- AUTH -----------------

def require_login():
    if not session.get('logged_in'):
        return False
    return True

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string(TEMPLATE, page='login')
    pw = request.form.get('password', '')
    if pw == ADMIN_PASSWORD:
        session['logged_in'] = True
        flash('Logged in')
        return redirect(url_for('index'))
    else:
        flash('Wrong password')
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out')
    return redirect(url_for('index'))

# ----------------- HELPERS -----------------

def compute_balance(db, customer_id):
    cur = db.execute('SELECT amount, type FROM transactions WHERE customer_id = ?', (customer_id,))
    total = 0.0
    for r in cur.fetchall():
        amt = r['amount']
        if r['type'] == 'debit':
            total += amt
        else:
            total -= amt
    return total

# ----------------- ROUTES -----------------

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    db = get_db()
    if q:
        cur = db.execute("SELECT id, name, phone FROM customers WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC", (f"%{q}%", f"%{q}%"))
    else:
        cur = db.execute('SELECT id, name, phone FROM customers ORDER BY id DESC')
    rows = [dict(r) for r in cur.fetchall()]
    customers = []
    for r in rows:
        r['balance'] = compute_balance(db, r['id'])
        customers.append(r)

    return render_template_string(TEMPLATE, page='dashboard', customers=customers, q=q)

@app.route('/add_customer', methods=['POST'])
def add_customer():
    if not require_login():
        return "Forbidden", 403
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    if not name:
        flash('Name required')
        return redirect(url_for('index'))
    db = get_db()
    db.execute('INSERT INTO customers (name, phone) VALUES (?, ?)', (name, phone or None))
    db.commit()
    flash('Customer added')
    return redirect(url_for('index'))

@app.route('/delete_customer/<int:cust_id>', methods=['POST'])
def delete_customer(cust_id):
    if not require_login():
        return "Forbidden", 403
    db = get_db()
    db.execute('DELETE FROM transactions WHERE customer_id = ?', (cust_id,))
    db.execute('DELETE FROM customers WHERE id = ?', (cust_id,))
    db.commit()
    flash('Customer and transactions deleted')
    return redirect(url_for('index'))

@app.route('/customer/<int:cust_id>')
def customer_detail(cust_id):
    db = get_db()
    cur = db.execute('SELECT id, name, phone FROM customers WHERE id = ?', (cust_id,))
    r = cur.fetchone()
    if not r:
        return 'Not found', 404
    customer = dict(r)
    customer['balance'] = compute_balance(db, cust_id)
    tx = db.execute('SELECT id, amount, type, note, created_at FROM transactions WHERE customer_id = ? ORDER BY created_at DESC', (cust_id,))
    txns = [dict(t) for t in tx.fetchall()]
    return render_template_string(TEMPLATE, page='customer', customer=customer, txns=txns)

@app.route('/customer/<int:cust_id>/add_txn', methods=['POST'])
def add_transaction(cust_id):
    if not require_login():
        return "Forbidden", 403
    try:
        amount = float(request.form.get('amount', '0'))
    except ValueError:
        flash('Invalid amount')
        return redirect(url_for('customer_detail', cust_id=cust_id))
    ttype = request.form.get('type', 'debit')
    if ttype not in ('debit', 'credit'):
        ttype = 'debit'
    note = request.form.get('note', '').strip()
    now = datetime.utcnow().isoformat()
    db = get_db()
    db.execute('INSERT INTO transactions (customer_id, amount, type, note, created_at) VALUES (?,?,?,?,?)', (cust_id, abs(amount), ttype, note or None, now))
    db.commit()
    flash('Transaction added')
    return redirect(url_for('customer_detail', cust_id=cust_id))

@app.route('/export/<what>.csv')
def export_csv(what):
    db = get_db()
    si = StringIO()
    writer = csv.writer(si)
    if what == 'customers':
        cur = db.execute('SELECT id, name, phone FROM customers ORDER BY id DESC')
        writer.writerow(['id', 'name', 'phone', 'balance'])
        for r in cur.fetchall():
            bal = compute_balance(db, r['id'])
            writer.writerow([r['id'], r['name'], r['phone'] or '', '%.2f' % bal])
    elif what == 'transactions':
        customer_id = request.args.get('customer_id')
        if customer_id:
            cur = db.execute('SELECT id, customer_id, amount, type, note, created_at FROM transactions WHERE customer_id = ? ORDER BY created_at DESC', (customer_id,))
        else:
            cur = db.execute('SELECT id, customer_id, amount, type, note, created_at FROM transactions ORDER BY created_at DESC')
        writer.writerow(['id', 'customer_id', 'amount', 'type', 'note', 'created_at'])
        for r in cur.fetchall():
            writer.writerow([r['id'], r['customer_id'], '%.2f' % r['amount'], r['type'], r['note'] or '', r['created_at']])
    else:
        return 'Not found', 404
    return Response(si.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename={what}.csv"})

@app.route('/import', methods=['POST'])
def import_csv():
    if not require_login():
        return "Forbidden", 403
    f = request.files.get('file')
    if not f:
        flash('No file uploaded')
        return redirect(url_for('index'))
    stream = StringIO(f.stream.read().decode('utf-8'))
    reader = csv.DictReader(stream)
    db = get_db()
    added = 0
    for row in reader:
        if 'name' in row:
            name = (row.get('name') or '').strip()
            phone = (row.get('phone') or '').strip()
            if name:
                db.execute('INSERT INTO customers (name, phone) VALUES (?, ?)', (name, phone or None))
                added += 1
        elif 'customer_id' in row and 'amount' in row:
            try:
                cid = int(row.get('customer_id'))
                amt = float(row.get('amount') or 0)
                ttype = (row.get('type') or 'debit')
                note = (row.get('note') or '')
                created_at = row.get('created_at') or datetime.utcnow().isoformat()
                db.execute('INSERT INTO transactions (customer_id, amount, type, note, created_at) VALUES (?,?,?,?,?)', (cid, abs(amt), ttype, note or None, created_at))
                added += 1
            except Exception:
                continue
    db.commit()
    flash(f'Imported {added} rows')
    return redirect(url_for('index'))

# ----------------- START -----------------

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8000)
