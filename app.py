"""
바나프레소 커피 주문 취합 시스템
- 직원: 메뉴 선택 후 주문
- 담당자: /admin 에서 집계 확인 + 카카오톡 나에게보내기
"""

from flask import Flask, render_template_string, request, jsonify, redirect, url_for
import os
import sqlite3
from datetime import datetime, date

app = Flask(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL")

DB_PATH = os.path.join(os.path.dirname(__file__), "coffee_orders.db")


def get_db():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def _pg_execute(conn, sql, params=()):
    sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _pg_to_dict(cursor):
    if cursor.description is None:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def db_execute(conn, sql, params=()):
    if DATABASE_URL:
        return _pg_execute(conn, sql, params)
    else:
        return conn.execute(sql, params)


def db_fetchone(conn, sql, params=()):
    if DATABASE_URL:
        cur = _pg_execute(conn, sql, params)
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None
    else:
        return conn.execute(sql, params).fetchone()


def db_fetchall(conn, sql, params=()):
    if DATABASE_URL:
        cur = _pg_execute(conn, sql, params)
        return _pg_to_dict(cur)
    else:
        return conn.execute(sql, params).fetchall()

# ── 바나프레소 메뉴 ──
MENU = {
    "커피": [
        ("아메리카노", 2500),
        ("디카페인 아메리카노", 2800),
        ("시그니처 아메리카노", 2700),
        ("바나리카노 (32oz)", 4000),
        ("클래식 밀크커피", 2500),
        ("화이트 아메리카노", 3000),
        ("제로슈가 스위트 아메리카노", 3000),
        ("허니아메리카노", 2800),
        ("카페라떼", 3300),
        ("크리미라떼", 3800),
        ("바닐라라떼", 3800),
        ("연유라떼", 4000),
        ("카페모카", 4300),
        ("밀크카라멜마키아또", 4300),
        ("시나몬라떼", 4300),
        ("피스타치오 카페라떼", 4300),
        ("에스프레소", 2500),
        ("콜드브루", 3300),
    ],
    "밀크티/라떼": [
        ("얼그레이밀크티", 3800),
        ("흑당밀크티", 3800),
        ("피스타치오라떼", 3800),
        ("딸기라떼", 4000),
        ("딸기퐁당밀크티", 4800),
        ("딸기퐁당말차라떼", 4500),
    ],
    "주스/드링크": [
        ("딸기쥬스", 4000),
        ("망고쥬스", 4000),
        ("요거트드링크", 3500),
    ],
    "스무디/바나치노": [
        ("자바칩바나치노", 4500),
        ("딸기스무디", 4000),
        ("망고스무디", 4000),
        ("바닐라쉐이크", 4500),
    ],
    "티/에이드": [
        ("자몽허니블랙티", 3800),
        ("제주청귤에이드", 3800),
        ("레몬에이드", 3800),
        ("캐모마일", 2800),
    ],
}

CUTOFF_HOUR = 8   # 표시용 (참고 시간)
CUTOFF_MINUTE = 20


# ── DB ──
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    if DATABASE_URL:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                order_date TEXT NOT NULL,
                name TEXT NOT NULL,
                menu TEXT NOT NULL,
                temperature TEXT NOT NULL DEFAULT 'ICE',
                price INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_date TEXT NOT NULL,
                name TEXT NOT NULL,
                menu TEXT NOT NULL,
                temperature TEXT NOT NULL DEFAULT 'ICE',
                price INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
    conn.close()


init_db()


def today_str():
    return date.today().isoformat()


def is_closed():
    conn = get_db()
    row = db_fetchone(conn, "SELECT value FROM settings WHERE key = %s" if DATABASE_URL else "SELECT value FROM settings WHERE key = ?", ("closed_date",))
    conn.close()
    return row is not None and row["value"] == today_str()


def set_closed(closed):
    conn = get_db()
    if closed:
        # 마감 시 주문 초기화
        db_execute(conn, "DELETE FROM orders WHERE order_date = ?", (today_str(),))
        if DATABASE_URL:
            cur = conn.cursor()
            cur.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("closed_date", today_str()))
        else:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("closed_date", today_str()))
    else:
        db_execute(conn, "DELETE FROM settings WHERE key = ?", ("closed_date",))
    conn.commit()
    conn.close()






# ── 주문 페이지 (직원용) ──
ORDER_PAGE = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>☕ 인트리홀딩스 모닝커피타임</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    background: #FFF5F5;
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, #E91E63, #FF5722);
    color: white;
    padding: 24px 20px;
    text-align: center;
  }
  .header h1 { font-size: 24px; margin-bottom: 4px; }
  .header p { font-size: 14px; opacity: 0.9; }
  .closed-banner {
    background: #F44336;
    color: white;
    text-align: center;
    padding: 16px;
    font-size: 16px;
    font-weight: bold;
  }
  .container { max-width: 500px; margin: 0 auto; padding: 20px; padding-bottom: 100px; }
  .form-group { margin-bottom: 20px; }
  .form-group label {
    display: block;
    font-weight: bold;
    margin-bottom: 8px;
    font-size: 15px;
    color: #333;
  }
  .form-group input[type="text"] {
    width: 100%;
    padding: 12px 16px;
    border: 2px solid #E0E0E0;
    border-radius: 12px;
    font-size: 16px;
    transition: border-color 0.2s;
  }
  .form-group input[type="text"]:focus {
    outline: none;
    border-color: #E91E63;
  }
  .category-title {
    font-size: 16px;
    font-weight: bold;
    color: #E91E63;
    margin: 20px 0 10px;
    padding-bottom: 6px;
    border-bottom: 2px solid #E91E63;
  }
  .menu-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .menu-item {
    background: white;
    border: 2px solid #E0E0E0;
    border-radius: 12px;
    padding: 12px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    user-select: none;
  }
  .menu-item:hover { border-color: #E91E63; transform: translateY(-1px); }
  .menu-item.selected {
    border-color: #E91E63;
    background: #FCE4EC;
    box-shadow: 0 2px 8px rgba(233,30,99,0.2);
  }
  .menu-item .name { font-size: 14px; font-weight: 600; color: #333; }
  .menu-item .price { font-size: 13px; color: #888; margin-top: 4px; }
  .temp-toggle {
    display: flex;
    gap: 8px;
    margin-top: 16px;
  }
  .temp-btn {
    flex: 1;
    padding: 12px;
    border: 2px solid #E0E0E0;
    border-radius: 12px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    text-align: center;
    background: white;
    transition: all 0.2s;
  }
  .temp-btn.ice.selected { background: #E3F2FD; border-color: #2196F3; color: #1565C0; }
  .temp-btn.hot.selected { background: #FBE9E7; border-color: #FF5722; color: #D84315; }
  .submit-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: white;
    padding: 12px 20px;
    padding-bottom: max(12px, env(safe-area-inset-bottom));
    box-shadow: 0 -2px 12px rgba(0,0,0,0.1);
    z-index: 100;
  }
  .submit-btn {
    width: 100%;
    max-width: 500px;
    margin: 0 auto;
    display: block;
    padding: 16px;
    background: linear-gradient(135deg, #E91E63, #FF5722);
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 18px;
    font-weight: bold;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .submit-btn:hover { opacity: 0.9; }
  .submit-btn:disabled { background: #CCC; cursor: not-allowed; }
  .bottom-spacer { height: 20px; }
  .toast {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    background: #333;
    color: white;
    padding: 14px 28px;
    border-radius: 30px;
    font-size: 15px;
    display: none;
    z-index: 999;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  }
  .today-orders {
    background: white;
    border-radius: 12px;
    padding: 16px;
    margin-top: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .today-orders h3 { font-size: 15px; color: #333; margin-bottom: 10px; }
  .order-list { list-style: none; }
  .order-list li {
    padding: 8px 0;
    border-bottom: 1px solid #F0F0F0;
    font-size: 14px;
    color: #555;
    display: flex;
    justify-content: space-between;
  }
  .order-list li:last-child { border-bottom: none; }
</style>
</head>
<body>
  <div class="header">
    <h1>☕ 인트리홀딩스 모닝커피타임</h1>
    <p>{{ today }}{% if closed %} | 주문 마감됨{% endif %}</p>
  </div>

  {% if closed %}
  <div class="closed-banner">☕ 내일 드실 음료를 미리 적어주세요</div>
  {% endif %}

  <div class="container">
    {% if not closed %}
    <form id="orderForm">
      <div class="form-group">
        <label>👤 이름</label>
        <input type="text" id="nameInput" placeholder="이름을 입력하세요" required>
      </div>

      <div class="form-group">
        <label>🌡️ ICE / HOT</label>
        <div class="temp-toggle">
          <div class="temp-btn ice selected" onclick="selectTemp(this, 'ICE')">🧊 ICE</div>
          <div class="temp-btn hot" onclick="selectTemp(this, 'HOT')">🔥 HOT</div>
        </div>
      </div>

      <div class="form-group">
        <label>☕ 메뉴 선택</label>
        {% for category, items in menu.items() %}
        <div class="category-title">{{ category }}</div>
        <div class="menu-grid">
          {% for name, price in items %}
          <div class="menu-item" data-menu="{{ name }}" data-price="{{ price }}" onclick="selectMenu(this)">
            <div class="name">{{ name }}</div>
            <!-- <div class="price">{{ "{:,}".format(price) }}원</div> -->
          </div>
          {% endfor %}
        </div>
        {% endfor %}
      </div>

      <div class="bottom-spacer"></div>
    </form>
    <div class="submit-bar">
      <button type="submit" form="orderForm" class="submit-btn" id="submitBtn" disabled>주문하기</button>
    </div>
    {% endif %}

    <div class="today-orders">
      <h3>📋 오늘 주문 현황 ({{ orders|length }}건)</h3>
      <ul class="order-list">
        {% for o in orders %}
        <li>
          <span>{{ o.name }} — {{ o.menu }} ({{ o.temperature }})</span>
          <!-- <span>{{ "{:,}".format(o.price) }}원</span> -->
        </li>
        {% else %}
        <li>아직 주문이 없습니다</li>
        {% endfor %}
      </ul>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    let selectedMenu = null;
    let selectedPrice = 0;
    let selectedTemp = 'ICE';

    // 로컬스토리지에서 이름 복원
    const savedName = localStorage.getItem('coffee_order_name');
    if (savedName) document.getElementById('nameInput') && (document.getElementById('nameInput').value = savedName);

    function selectMenu(el) {
      document.querySelectorAll('.menu-item').forEach(e => e.classList.remove('selected'));
      el.classList.add('selected');
      selectedMenu = el.dataset.menu;
      selectedPrice = parseInt(el.dataset.price);
      document.getElementById('submitBtn').disabled = false;
    }

    function selectTemp(el, temp) {
      document.querySelectorAll('.temp-btn').forEach(e => e.classList.remove('selected'));
      el.classList.add('selected');
      selectedTemp = temp;
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 2500);
    }

    const form = document.getElementById('orderForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('nameInput').value.trim();
        if (!name || !selectedMenu) return;

        localStorage.setItem('coffee_order_name', name);

        const res = await fetch('/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name, menu: selectedMenu, temperature: selectedTemp, price: selectedPrice
          })
        });
        const data = await res.json();
        if (data.ok) {
          showToast('✅ 주문 완료! ' + selectedMenu + ' (' + selectedTemp + ')');
          setTimeout(() => location.reload(), 1500);
        } else {
          showToast('❌ ' + (data.error || '주문 실패'));
        }
      });
    }
  </script>
</body>
</html>
"""

# ── 관리자 집계 페이지 ──
ADMIN_PAGE = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📊 인트리홀딩스 모닝커피타임 - 관리자</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    background: #F5F5F5;
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, #7B1FA2, #E91E63);
    color: white;
    padding: 24px 20px;
    text-align: center;
  }
  .header h1 { font-size: 22px; }
  .header p { font-size: 14px; opacity: 0.9; margin-top: 4px; }
  .container { max-width: 600px; margin: 0 auto; padding: 20px; }
  .card {
    background: white;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .card h2 { font-size: 17px; color: #333; margin-bottom: 14px; }
  .summary-row {
    display: flex;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid #F0F0F0;
    font-size: 15px;
  }
  .summary-row:last-child { border-bottom: none; }
  .summary-row .count {
    background: #E91E63;
    color: white;
    border-radius: 20px;
    padding: 2px 12px;
    font-weight: bold;
    font-size: 14px;
  }
  .total-bar {
    background: linear-gradient(135deg, #E91E63, #FF5722);
    color: white;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    margin-bottom: 16px;
  }
  .total-bar .num { font-size: 36px; font-weight: bold; }
  .total-bar .label { font-size: 14px; opacity: 0.9; }
  .order-detail {
    font-size: 14px;
    color: #555;
    padding: 8px 0;
    border-bottom: 1px solid #F0F0F0;
    display: flex;
    justify-content: space-between;
  }
  .copy-btn {
    width: 100%;
    padding: 16px;
    background: #FFD600;
    color: #3C1E1E;
    border: none;
    border-radius: 12px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    margin-top: 8px;
  }
  .copy-btn:hover { opacity: 0.9; }
  .reset-btn {
    width: 100%;
    padding: 14px;
    background: #F44336;
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: bold;
    cursor: pointer;
    margin-top: 8px;
  }
  .toast {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    background: #333;
    color: white;
    padding: 14px 28px;
    border-radius: 30px;
    font-size: 15px;
    display: none;
    z-index: 999;
  }
</style>
</head>
<body>
  <div class="header">
    <h1>📊 인트리홀딩스 모닝커피타임</h1>
    <p>{{ today }} | 총 {{ orders|length }}건</p>
  </div>

  <div class="container">
    <div class="total-bar">
      <div class="num">{{ orders|length }}잔</div>
      <div class="label">총 주문 | {{ "{:,}".format(total_price) }}원</div>
    </div>

    <div class="card">
      <h2>📋 메뉴별 집계</h2>
      {% for item in summary %}
      <div class="summary-row">
        <span>{{ item.menu }} ({{ item.temperature }})</span>
        <span class="count">{{ item.count }}잔</span>
      </div>
      {% endfor %}
      {% if not summary %}
      <p style="color:#999; text-align:center; padding:20px;">주문이 없습니다</p>
      {% endif %}
    </div>

    <div class="card">
      <h2>👥 개인별 주문</h2>
      {% for o in orders %}
      <div class="order-detail">
        <span>{{ o.name }}</span>
        <span>{{ o.menu }} ({{ o.temperature }}) — {{ "{:,}".format(o.price) }}원</span>
      </div>
      {% endfor %}
    </div>

    {% if not closed %}
    <button class="close-btn" onclick="toggleClose(true)" style="width:100%;padding:16px;background:#FF9800;color:white;border:none;border-radius:12px;font-size:16px;font-weight:bold;cursor:pointer;margin-bottom:8px;">🔒 주문 마감하기</button>
    {% else %}
    <button class="close-btn" onclick="toggleClose(false)" style="width:100%;padding:16px;background:#4CAF50;color:white;border:none;border-radius:12px;font-size:16px;font-weight:bold;cursor:pointer;margin-bottom:8px;">🔓 주문 마감 해제</button>
    {% endif %}
    <button class="copy-btn" onclick="copyToClipboard()">📋 카카오톡 전송용 텍스트 복사</button>
    <button class="reset-btn" onclick="resetOrders()">🗑️ 오늘 주문 초기화</button>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 2500);
    }

    function copyToClipboard() {
      const text = `{{ copy_text|safe }}`;
      navigator.clipboard.writeText(text).then(() => {
        showToast('✅ 복사 완료! 카카오톡에 붙여넣기 하세요');
      }).catch(() => {
        // fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('✅ 복사 완료!');
      });
    }

    function toggleClose(close) {
      const msg = close ? '주문을 마감할까요?' : '마감을 해제할까요?';
      if (!confirm(msg)) return;
      fetch('/admin/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ closed: close })
      }).then(() => location.reload());
    }

    function resetOrders() {
      if (!confirm('오늘 주문을 모두 초기화할까요?')) return;
      fetch('/admin/reset', { method: 'POST' }).then(() => location.reload());
    }
  </script>
</body>
</html>
"""


# ── Routes ──
@app.route("/")
def index():
    conn = get_db()
    rows = db_fetchall(conn, "SELECT * FROM orders WHERE order_date = ? ORDER BY created_at", (today_str(),))
    conn.close()

    return render_template_string(
        ORDER_PAGE,
        menu=MENU,
        orders=rows,
        today=today_str(),
        closed=is_closed(),
    )


@app.route("/order", methods=["POST"])
def place_order():
    if is_closed():
        return jsonify({"ok": False, "error": "주문이 마감되었습니다"})

    data = request.get_json()
    name = data.get("name", "").strip()
    menu = data.get("menu", "").strip()
    temperature = data.get("temperature", "ICE")
    price = data.get("price", 0)

    if not name or not menu:
        return jsonify({"ok": False, "error": "이름과 메뉴를 입력하세요"})

    conn = get_db()
    existing = db_fetchone(conn, "SELECT id FROM orders WHERE order_date = ? AND name = ?", (today_str(), name))

    if existing:
        db_execute(conn, "UPDATE orders SET menu = ?, temperature = ?, price = ?, created_at = ? WHERE id = ?",
            (menu, temperature, price, datetime.now().isoformat(), existing["id"]))
    else:
        db_execute(conn, "INSERT INTO orders (order_date, name, menu, temperature, price, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (today_str(), name, menu, temperature, price, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/admin")
def admin():
    conn = get_db()
    orders = db_fetchall(conn, "SELECT * FROM orders WHERE order_date = ? ORDER BY created_at", (today_str(),))

    # 메뉴별 집계
    summary_dict = {}
    total_price = 0
    for o in orders:
        key = (o["menu"], o["temperature"])
        if key not in summary_dict:
            summary_dict[key] = {"menu": o["menu"], "temperature": o["temperature"], "count": 0}
        summary_dict[key]["count"] += 1
        total_price += o["price"]

    summary = sorted(summary_dict.values(), key=lambda x: x["count"], reverse=True)
    conn.close()

    # 카카오톡 복사용 텍스트
    lines = [f"☕ 바나프레소 주문 집계 ({today_str()})", f"총 {len(orders)}잔 | {total_price:,}원", ""]
    lines.append("[ 메뉴별 ]")
    for s in summary:
        lines.append(f"  • {s['menu']} ({s['temperature']}) × {s['count']}잔")
    lines.append("")
    lines.append("[ 개인별 ]")
    for o in orders:
        lines.append(f"  • {o['name']}: {o['menu']} ({o['temperature']})")

    copy_text = "\\n".join(lines)

    return render_template_string(
        ADMIN_PAGE,
        orders=orders,
        summary=summary,
        total_price=total_price,
        today=today_str(),
        copy_text=copy_text,
        closed=is_closed(),
    )


@app.route("/admin/close", methods=["POST"])
def close_orders():
    data = request.get_json()
    set_closed(data.get("closed", True))
    return jsonify({"ok": True})


@app.route("/admin/reset", methods=["POST"])
def reset_today():
    conn = get_db()
    db_execute(conn, "DELETE FROM orders WHERE order_date = ?", (today_str(),))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/summary")
def api_summary():
    conn = get_db()
    orders = db_fetchall(conn, "SELECT * FROM orders WHERE order_date = ? ORDER BY created_at", (today_str(),))
    conn.close()
    return jsonify({
        "date": today_str(),
        "count": len(orders),
        "orders": [dict(o) for o in orders],
    })


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("=" * 50)
    print("  바나프레소 커피 주문 시스템")
    print(f"  주문 페이지: http://localhost:5000")
    print(f"  관리자 집계: http://localhost:5000/admin")
    print(f"  마감 시간: {CUTOFF_HOUR:02d}:{CUTOFF_MINUTE:02d}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
