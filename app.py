"""
Simple Business Ledger App
Tracks customer names and money owed, supports add/edit/delete,
and shows total amount.

Run:
    python app.py
"""

from flask import Flask, request, g, redirect, url_for, render_template_string, Response
import sqlite3
from pathlib import Path
import csv
from io import StringIO

# ----------------------------------------------------
# CONFIG & DATABASE
# ----------------------------------------------------

DB_PATH = Path(__file__).parent / "customers.db"

app = Flask(__name__)
app.config['DATABASE'] = str(DB_PATH)

# ----------------------------------------------------
# HTML TEMPLATE (Bootstrap UI)
# ----------------------------------------------------

TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Customer Ledger</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body class="bg-light">
    <div class="container py-5">
      <h1 class="mb-4">Customer Ledger</h1>

      <div class="card mb-4">
        <div class="card-body">
          <form method="post" action="/add" class="row g-2 align-items-end">
            <div class="col-sm-6">
              <label class="form-label">Customer name</label>
              <input name="name" required class="form-control" placeholder="e.g. John Doe">
            </div>
            <div class="col-sm-4">
              <label class="form-label">Amount owed (₹)</label>
              <input name="amount" required type="number" step="0.01" class="form-control" placeholder="e.g. 500.00">
            </div>
            <div class="col-sm-2">
              <button class="btn btn-primary w-100">Add</button>
            </div>
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
                <tr>
                  <th>#</th>
                  <th>Name</th>
                  <th class="text-end">Amount (₹)</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {% for c in customers %}
                <tr>
                  <td>{{ loop.index }}</td>
                  <td>{{ c['name'] }}</td>
                  <td class="text-end">{{ '%.2f'|format(c['amount']) }}</td>
                  <td>
                    <form method="post" action="/delete/{{ c['id'] }}" style="display:inline-block;">
                      <button class="btn btn-sm btn-danger" onclick="return confirm('Delete this customer?')">Delete</button>
                    </form>
                    <button class="btn btn-sm btn-outline-secondary" data-bs-toggle="modal" data-bs-target="#editModal{{ c['id'] }}">Edit</button>

                    <!-- Edit modal -->
                    <div class="modal fade" id="editModal{{ c['id'] }}" tabindex="-1" aria-hidden="true">
                      <div class="modal-dialog">
                        <div class="modal-content">
                          <form method="post" action="/update/{{ c['id'] }}">
                            <div class="modal-header">
                              <h5 class="modal-title">Edit Customer</h5>
                              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                              <div class="mb-3">
                                <label class="form-label">Name</label>
                                <input name="name" required class="form-control" value="{{ c['name'] }}">
                              </div>
                              <div class="mb-3">
                                <label class="form-label">Amount (₹)</label>
                                <input name="amount" required type="number" step="0.01" class="form-control" value="{{ '%.2f'|format(c['amount']) }}">
                              </div>
                            </div>
                            <div class="modal-footer">
                              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                              <button class="btn btn-primary">Save</button>
                            </div>
                          </form>
                        </div>
                      </div>
                    </div>

                  </td>
                </tr>
                {% endfor %}
              </tbody>
              <tfoot>
                <tr>
                  <th colspan="2">Total</th>
                  <th class="text-end">{{ '%.2f'|format(total) }}</th>
                  <th></th>
                </tr>
              </tfoot>
            </table>
          </div>
          {% else %}
            <p class="text-muted">No customers yet — add someone above.</p>
          {% endif %}

          <a href="/export.csv" class="btn btn-success mt-3">Download CSV</a>

        </div>
      </div>

    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

# ----------------------------------------------------
# DATABASE FUNCTIONS
# ----------------------------------------------------

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
    db = sqlite3.connect(app.config["DATABASE"])
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0
        )
    """)
    db.commit()
    db.close()

# ----------------------------------------------------
# ROUTES
# ----------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    cur = db.execute("SELECT * FROM customers ORDER BY id DESC")
    customers = [dict(row) for row in cur.fetchall()]
    total = sum(c["amount"] for c in customers)
    return render_template_string(TEMPLATE, customers=customers, total=total)

@app.route("/add", methods=["POST"])
def add_customer():
    name = request.form["name"].strip()
    amount = float(request.form["amount"])
    db = get_db()
    db.execute("INSERT INTO customers (name, amount) VALUES (?, ?)", (name, amount))
    db.commit()
    return redirect(url_for("index"))

@app.route("/update/<int:id>", methods=["POST"])
def update_customer(id):
    name = request.form["name"].strip()
    amount = float(request.form["amount"])
    db = get_db()
    db.execute("UPDATE customers SET name=?, amount=? WHERE id=?", (name, amount, id))
    db.commit()
    return redirect(url_for("index"))

@app.route("/delete/<int:id>", methods=["POST"])
def delete_customer(id):
    db = get_db()
    db.execute("DELETE FROM customers WHERE id=?", (id,))
    db.commit()
    return redirect(url_for("index"))

@app.route("/export.csv")
def export_csv():
    db = get_db()
    cur = db.execute("SELECT * FROM customers ORDER BY id DESC")
    rows = cur.fetchall()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "name", "amount"])
    for r in rows:
        writer.writerow([r["id"], r["name"], "%.2f" % r["amount"]])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=customers.csv"},
    )

# ----------------------------------------------------
# START APP
# ----------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=8000)
