# -*- coding: utf-8 -*-
"""
Theo dõi dung lượng dữ liệu chấm công từng máy ZK — với GUI
─────────────────────────────────────────────────────────────
• Lấy dữ liệu tự động lúc 08:00 và 16:00 hàng ngày
• Lưu lịch sử vào data_history.json, hiển thị trực tiếp trên GUI
• Gửi email cảnh báo KHI SỐ BẢN GHI > 70.000
• Có thể kiểm tra thủ công ngay từ GUI

Yêu cầu: pip install zk schedule
Cấu hình: config.json
"""

import json
import logging
import os
import smtplib
import threading
import time
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from tkinter import (
    Tk, Frame, Label, Button, Entry, Text, StringVar,
    Scrollbar, Canvas, END, BOTH, X, Y, LEFT, RIGHT,
    TOP, BOTTOM, W, E, N, S, FLAT, DISABLED, NORMAL,
    Toplevel, IntVar, BooleanVar
)
from tkinter import messagebox
from tkinter.ttk import Treeview, Style, Separator, Notebook
from typing import Optional

try:
    import schedule as _schedule
except ImportError:
    _schedule = None

try:
    from zk import ZK
except ImportError:
    ZK = None


# ══════════════════════════════════════════════════════════
#  CẤU HÌNH
# ══════════════════════════════════════════════════════════
CONFIG_FILE  = "config.json"
HISTORY_FILE_DEFAULT = "data_history.json"
LOG_FILE_DEFAULT     = "monitor.log"
ALERT_THRESHOLD = 70_000          # gửi mail khi count > ngưỡng này


def load_config(path: str = CONFIG_FILE) -> dict:
    if not os.path.exists(path):
        # Tạo config mẫu nếu chưa có
        default = {
            "devices": [
                {"ip": "10.0.0.221", "name": "Máy 1"},
                {"ip": "10.0.0.222", "name": "Máy 2"},
                {"ip": "10.0.0.223", "name": "Máy 3"},
                {"ip": "10.0.0.224", "name": "Máy 4"},
                {"ip": "10.0.0.225", "name": "Máy 5"},
                {"ip": "10.0.0.226", "name": "Máy 6"},
                {"ip": "10.0.0.227", "name": "Máy 7"},
                {"ip": "10.0.0.238", "name": "Máy 8"},
            ],
            "device_port": 4370,
            "device_timeout": 10,
            "device_password": 0,
            "schedule_times": ["08:00", "16:00"],
            "alert_threshold": 70000,
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_use_tls": True,
                "sender": "",
                "password": "",
                "recipients": []
            },
            "log_file": LOG_FILE_DEFAULT,
            "history_file": HISTORY_FILE_DEFAULT
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
HISTORY_FILE = CFG.get("history_file", HISTORY_FILE_DEFAULT)

# ── Logger ──
_log_file = CFG.get("log_file", LOG_FILE_DEFAULT)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ══════════════════════════════════════════════════════════
CLR = {
    "bg":          "#F0F2F5",
    "surface":     "#FFFFFF",
    "sidebar":     "#1E2A3A",
    "sidebar_hdr": "#141E2B",
    "primary":     "#2563EB",
    "primary_dk":  "#1D4ED8",
    "danger":      "#DC2626",
    "danger_dk":   "#B91C1C",
    "success":     "#16A34A",
    "warning":     "#D97706",
    "muted":       "#6B7280",
    "border":      "#E5E7EB",
    "row_alt":     "#F8FAFC",
    "row_sel":     "#DBEAFE",
    "text":        "#111827",
    "text_muted":  "#6B7280",
    "header_bg":   "#1E40AF",
    "header_fg":   "#FFFFFF",
    "log_bg":      "#0F172A",
    "log_fg":      "#94A3B8",
    "ok":          "#D1FAE5",
    "warn":        "#FEF3C7",
    "crit":        "#FEE2E2",
}
FONT        = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SM     = ("Segoe UI", 9)
FONT_LG     = ("Segoe UI", 13, "bold")
FONT_MONO   = ("Consolas", 10)
FONT_MONO_SM= ("Consolas", 9)


# ══════════════════════════════════════════════════════════
#  LỊCH SỬ DỮ LIỆU
# ══════════════════════════════════════════════════════════
def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(history: dict):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi lưu lịch sử: {e}")


def update_history(ip: str, count: int, status: str, history: dict) -> dict:
    if ip not in history:
        history[ip] = []
    history[ip].append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date":      date.today().strftime("%Y-%m-%d"),
        "count":     count,
        "status":    status,
    })
    history[ip] = history[ip][-200:]   # giữ 200 điểm gần nhất / máy
    return history


def get_last_ok_count(ip: str, history: dict) -> Optional[int]:
    """Số bản ghi lần OK trước (bỏ bản vừa thêm)."""
    records = history.get(ip, [])
    for rec in reversed(records[:-1]):
        if rec["status"] == "OK":
            return rec["count"]
    return None


# ══════════════════════════════════════════════════════════
#  KẾT NỐI MÁY ZK
# ══════════════════════════════════════════════════════════
def get_attendance_count(ip: str) -> tuple[int, str]:
    if ZK is None:
        return -1, "ERR: chưa cài zk"
    port     = CFG.get("device_port", 4370)
    timeout  = CFG.get("device_timeout", 10)
    password = CFG.get("device_password", 0)
    zk   = ZK(ip, port=port, timeout=timeout, password=password,
              force_udp=False, ommit_ping=False)
    conn = None
    try:
        conn = zk.connect()
        conn.disable_device()
        att   = conn.get_attendance()
        count = len(att) if att else 0
        return count, "OK"
    except Exception as e:
        return -1, f"Lỗi: {e}"
    finally:
        try:
            if conn:
                conn.enable_device()
                conn.disconnect()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
#  PHÂN TÍCH & GỬI EMAIL
# ══════════════════════════════════════════════════════════
def should_alert(count: int) -> bool:
    """Cảnh báo khi số bản ghi VƯỢT ngưỡng 70.000."""
    threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
    return count > threshold


def send_alert_email(alerts: list[dict], snapshot: list[dict]):
    ec  = CFG.get("email", {})
    smtp_host  = ec.get("smtp_host",  "smtp.gmail.com")
    smtp_port  = ec.get("smtp_port",  587)
    use_tls    = ec.get("smtp_use_tls", True)
    sender     = ec.get("sender",    "")
    password   = ec.get("password",  "")
    recipients = ec.get("recipients", [])

    if not recipients or not sender or not password:
        logger.warning("Email chưa cấu hình đầy đủ — bỏ qua gửi.")
        return

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
    subject = (f"[Chấm công] 🔴 CẢNH BÁO — Số bản ghi vượt {threshold:,} — {now_str}")

    # ── Alert rows ──
    alert_rows = ""
    for a in alerts:
        alert_rows += (
            f"<tr>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;"
            f"color:#dc2626;font-weight:bold;'>CRITICAL</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;'>"
            f"{a['name']} ({a['ip']})</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;'>{a['msg']}</td>"
            f"</tr>"
        )

    # ── Snapshot rows ──
    snap_rows = ""
    for s in snapshot:
        cnt_str  = f"{s['count']:,}" if s['count'] >= 0 else "N/A"
        chg      = s.get("change_str", "—")
        st_color = "#16a34a" if s["status"] == "OK" else "#dc2626"
        row_bg   = "#FEE2E2" if should_alert(s["count"]) else "#ffffff"
        snap_rows += (
            f"<tr style='background:{row_bg};'>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;'>{s['name']}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;"
            f"font-family:monospace;'>{s['ip']}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;"
            f"text-align:right;font-family:monospace;'>{cnt_str}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;"
            f"text-align:right;'>{chg}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;"
            f"color:{st_color};'>{s['status']}</td>"
            f"</tr>"
        )

    html = f"""<html><body style="font-family:Segoe UI,Arial,sans-serif;
color:#111827;background:#f9fafb;">
<div style="max-width:740px;margin:24px auto;background:#fff;border-radius:8px;
box-shadow:0 2px 8px rgba(0,0,0,.08);padding:28px;">
<h2 style="margin-top:0;color:#1e40af;">🖥️ Báo cáo theo dõi dữ liệu chấm công</h2>
<p style="color:#6b7280;">Thời điểm: <strong>{now_str}</strong>
 &nbsp;|&nbsp; Ngưỡng cảnh báo: <strong>{threshold:,} bản ghi</strong></p>

<h3 style="color:#dc2626;">⚠️ Máy vượt ngưỡng ({len(alerts)} máy)</h3>
<table style="border-collapse:collapse;width:100%;font-size:14px;">
<thead><tr style="background:#1e40af;color:#fff;">
<th style="padding:8px 10px;text-align:left;">Mức</th>
<th style="padding:8px 10px;text-align:left;">Máy</th>
<th style="padding:8px 10px;text-align:left;">Chi tiết</th>
</tr></thead><tbody>{alert_rows}</tbody></table>

<h3 style="color:#1e40af;margin-top:24px;">📊 Trạng thái toàn bộ máy</h3>
<table style="border-collapse:collapse;width:100%;font-size:14px;">
<thead><tr style="background:#1e40af;color:#fff;">
<th style="padding:8px 10px;text-align:left;">Tên máy</th>
<th style="padding:8px 10px;text-align:left;">IP</th>
<th style="padding:8px 10px;text-align:right;">Bản ghi</th>
<th style="padding:8px 10px;text-align:right;">Thay đổi</th>
<th style="padding:8px 10px;text-align:left;">Trạng thái</th>
</tr></thead><tbody>{snap_rows}</tbody></table>

<p style="margin-top:24px;font-size:12px;color:#9ca3af;">
Email tự động — vui lòng không trả lời.</p>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        if use_tls:
            srv = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
            srv.ehlo(); srv.starttls()
        else:
            srv = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
        srv.login(sender, password)
        srv.sendmail(sender, recipients, msg.as_bytes())
        srv.quit()
        logger.info(f"✅ Đã gửi email → {', '.join(recipients)}")
    except Exception as e:
        logger.error(f"❌ Gửi email thất bại: {e}")


# ══════════════════════════════════════════════════════════
#  TÁC VỤ KIỂM TRA CHÍNH  (gọi từ scheduler hoặc GUI)
# ══════════════════════════════════════════════════════════
def run_check(callback_log=None) -> list[dict]:
    """
    Kiểm tra tất cả máy.
    Trả về danh sách snapshot để GUI cập nhật.
    callback_log(str): hàm ghi log ra GUI (tuỳ chọn).
    """
    def _log(msg: str):
        logger.info(msg)
        if callback_log:
            callback_log(msg)

    _log("=" * 55)
    _log("BẮT ĐẦU KIỂM TRA DỮ LIỆU CHẤM CÔNG")
    _log("=" * 55)

    devices    = CFG.get("devices", [])
    history    = load_history()
    snapshot   = []
    all_alerts = []
    threshold  = CFG.get("alert_threshold", ALERT_THRESHOLD)

    for dev in devices:
        ip   = dev.get("ip", "")
        name = dev.get("name", ip)

        _log(f"[{name}] ({ip}) Đang kết nối ...")
        count, status = get_attendance_count(ip)

        if status == "OK":
            _log(f"  ✓ {count:,} bản ghi")
        else:
            _log(f"  ✗ {status}")

        prev = get_last_ok_count(ip, history)
        history = update_history(ip, count, status, history)

        # Tính thay đổi
        change_str = "—"
        if prev is not None and count >= 0:
            delta = count - prev
            sign  = "+" if delta >= 0 else ""
            pct   = (delta / prev * 100) if prev else 0
            change_str = f"{sign}{delta:,} ({sign}{pct:.1f}%)"

        snap = {
            "ip":         ip,
            "name":       name,
            "count":      count,
            "status":     status,
            "prev_count": prev,
            "change_str": change_str,
            "timestamp":  datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
        }
        snapshot.append(snap)

        # Kiểm tra ngưỡng
        if status == "OK" and should_alert(count):
            msg = (f"Số bản ghi {count:,} VƯỢT ngưỡng {threshold:,}")
            _log(f"  ⚠ {msg}")
            all_alerts.append({"ip": ip, "name": name, "msg": msg,
                                "count": count})

    save_history(history)

    # Log bảng tóm tắt
    _log("-" * 55)
    for s in snapshot:
        cnt = f"{s['count']:,}" if s["count"] >= 0 else "N/A"
        _log(f"  {s['name']:<10} {s['ip']:<16} {cnt:>10}  {s['change_str']:>18}  {s['status']}")
    _log("-" * 55)

    if all_alerts:
        _log(f"⚠ {len(all_alerts)} máy vượt ngưỡng — Đang gửi email ...")
        send_alert_email(all_alerts, snapshot)
    else:
        _log("✅ Không có máy nào vượt ngưỡng — không gửi email.")

    _log("HOÀN THÀNH KIỂM TRA")
    _log("=" * 55)
    return snapshot


# ══════════════════════════════════════════════════════════
#  SCHEDULER (chạy nền)
# ══════════════════════════════════════════════════════════
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop   = threading.Event()


def start_scheduler(callback_log=None, callback_refresh=None):
    global _scheduler_thread, _scheduler_stop

    if _schedule is None:
        if callback_log:
            callback_log("❌ Chưa cài 'schedule' — pip install schedule")
        return

    _scheduler_stop.clear()
    times = CFG.get("schedule_times", ["08:00", "16:00"])

    import schedule as sch
    sch.clear()
    for t in times:
        def _job(t=t):
            snap = run_check(callback_log)
            if callback_refresh:
                callback_refresh(snap)
        sch.every().day.at(t).do(_job)
        logger.info(f"Đã lên lịch lúc {t}")

    def _loop():
        while not _scheduler_stop.is_set():
            sch.run_pending()
            time.sleep(30)

    _scheduler_thread = threading.Thread(target=_loop, daemon=True)
    _scheduler_thread.start()
    logger.info("Scheduler đang chạy.")


def stop_scheduler():
    _scheduler_stop.set()


# ══════════════════════════════════════════════════════════
#  WIDGET — MINI SPARKLINE (canvas thuần)
# ══════════════════════════════════════════════════════════
class Sparkline(Canvas):
    """Mini line-chart vẽ lịch sử count của một máy."""
    W, H = 160, 40

    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=CLR["surface"], highlightthickness=0, **kw)
        self._points: list[int] = []

    def set_data(self, points: list[int]):
        self._points = [p for p in points if p >= 0]
        self._draw()

    def _draw(self):
        self.delete("all")
        pts = self._points
        if len(pts) < 2:
            return
        mn, mx = min(pts), max(pts)
        rng    = mx - mn if mx != mn else 1
        threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)

        # Ngưỡng gạch đỏ
        if mn <= threshold <= mx:
            ty = self.H - int((threshold - mn) / rng * (self.H - 6)) - 3
            self.create_line(0, ty, self.W, ty,
                             fill="#fca5a5", dash=(3, 3), width=1)

        # Đường dữ liệu
        xs = [int(i / (len(pts) - 1) * (self.W - 4)) + 2
              for i in range(len(pts))]
        ys = [self.H - int((p - mn) / rng * (self.H - 8)) - 4
              for p in pts]
        coords = []
        for x, y in zip(xs, ys):
            coords += [x, y]
        self.create_line(*coords, fill=CLR["primary"], width=2,
                         smooth=True, joinstyle="round")

        # Điểm cuối
        last_x, last_y = xs[-1], ys[-1]
        color = CLR["danger"] if should_alert(pts[-1]) else CLR["success"]
        self.create_oval(last_x-3, last_y-3, last_x+3, last_y+3,
                         fill=color, outline="")


# ══════════════════════════════════════════════════════════
#  WIDGET — BẢNG CHÍNH (TreeView)
# ══════════════════════════════════════════════════════════
class DeviceTable(Frame):
    COLS = ("name", "ip", "count", "change", "status", "last_check")
    HEADS= ("Tên máy", "IP", "Bản ghi", "Thay đổi", "Trạng thái", "Lần kiểm tra")
    WIDTHS = (90, 130, 100, 150, 90, 160)

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=CLR["surface"], **kw)
        style = Style()
        style.configure("Mon.Treeview",
                        font=FONT, rowheight=30,
                        background=CLR["surface"],
                        fieldbackground=CLR["surface"],
                        foreground=CLR["text"])
        style.configure("Mon.Treeview.Heading",
                        font=FONT_BOLD,
                        background=CLR["header_bg"],
                        foreground=CLR["header_fg"])
        style.map("Mon.Treeview",
                  background=[("selected", CLR["row_sel"])])

        self.tree = Treeview(self, columns=self.COLS, show="headings",
                             style="Mon.Treeview", selectmode="browse")
        for col, head, w in zip(self.COLS, self.HEADS, self.WIDTHS):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=w, anchor=W if col in
                             ("name","ip","status","last_check") else "center")

        self.tree.tag_configure("ok",   background=CLR["ok"])
        self.tree.tag_configure("warn", background=CLR["warn"])
        self.tree.tag_configure("err",  background=CLR["crit"])
        self.tree.tag_configure("alt",  background=CLR["row_alt"])

        vsb = Scrollbar(self, orient="vertical",   command=self.tree.yview)
        hsb = Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def load(self, snapshot: list[dict]):
        self.tree.delete(*self.tree.get_children())
        threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
        for i, s in enumerate(snapshot):
            cnt = f"{s['count']:,}" if s["count"] >= 0 else "N/A"
            if s["status"] != "OK":
                tag = "err"
            elif should_alert(s["count"]):
                tag = "warn"
            elif i % 2 == 0:
                tag = "ok"
            else:
                tag = "alt"
            self.tree.insert("", END, values=(
                s["name"], s["ip"], cnt,
                s.get("change_str", "—"),
                s["status"],
                s.get("timestamp", ""),
            ), tags=(tag,))


# ══════════════════════════════════════════════════════════
#  WIDGET — PANEL LỊCH SỬ TỪNG MÁY
# ══════════════════════════════════════════════════════════
class HistoryPanel(Frame):
    """Hiển thị 10 bản ghi gần nhất + sparkline cho từng máy."""

    COLS  = ("ts", "count", "change", "status")
    HEADS = ("Thời điểm", "Bản ghi", "Thay đổi", "TT")
    WIDTHS= (155, 90, 110, 70)

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=CLR["bg"], **kw)

        # Selector
        top = Frame(self, bg=CLR["bg"])
        top.pack(fill=X, padx=10, pady=(8, 4))
        Label(top, text="Máy:", font=FONT_BOLD, bg=CLR["bg"],
              fg=CLR["text"]).pack(side=LEFT)
        self._var_device = StringVar()
        from tkinter.ttk import Combobox
        self.cbo = Combobox(top, textvariable=self._var_device,
                            state="readonly", font=FONT, width=22)
        self.cbo.pack(side=LEFT, padx=(6, 0))
        self.cbo.bind("<<ComboboxSelected>>", lambda _: self._refresh())

        # Sparkline + label
        spark_frame = Frame(self, bg=CLR["surface"],
                            relief=FLAT, bd=0)
        spark_frame.pack(fill=X, padx=10, pady=4)
        Label(spark_frame, text="Biểu đồ gần nhất:",
              font=FONT_SM, bg=CLR["surface"],
              fg=CLR["muted"]).pack(side=LEFT, padx=(6, 4))
        self.spark = Sparkline(spark_frame)
        self.spark.pack(side=LEFT, pady=4)
        self._lbl_latest = Label(spark_frame, text="", font=FONT_BOLD,
                                  bg=CLR["surface"], fg=CLR["text"])
        self._lbl_latest.pack(side=LEFT, padx=14)

        # Treeview lịch sử
        style = Style()
        style.configure("Hist.Treeview", font=FONT_MONO_SM, rowheight=26)
        style.configure("Hist.Treeview.Heading", font=FONT_BOLD)
        style.map("Hist.Treeview",
                  background=[("selected", CLR["row_sel"])])

        tf = Frame(self, bg=CLR["bg"])
        tf.pack(fill=BOTH, expand=True, padx=10, pady=(0, 8))

        self.tree = Treeview(tf, columns=self.COLS, show="headings",
                             style="Hist.Treeview", height=12)
        for col, head, w in zip(self.COLS, self.HEADS, self.WIDTHS):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=w,
                             anchor=W if col in ("ts","status") else "e")
        self.tree.tag_configure("warn", background=CLR["warn"])
        self.tree.tag_configure("err",  background=CLR["crit"])
        self.tree.tag_configure("alt",  background=CLR["row_alt"])

        vsb = Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)

        self._history: dict = {}
        self._ip_map:  dict = {}   # name → ip

    # ── public API ──────────────────────────────────────
    def set_devices(self, devices: list[dict]):
        self._ip_map = {d.get("name", d["ip"]): d["ip"] for d in devices}
        names = list(self._ip_map.keys())
        self.cbo["values"] = names
        if names:
            self.cbo.current(0)

    def refresh(self, history: dict):
        self._history = history
        self._refresh()

    # ── internal ────────────────────────────────────────
    def _refresh(self):
        name = self._var_device.get()
        ip   = self._ip_map.get(name, "")
        records = self._history.get(ip, [])

        # Sparkline: tất cả điểm ok
        counts = [r["count"] for r in records if r["status"] == "OK"]
        self.spark.set_data(counts)

        # Label bản ghi mới nhất
        last_ok = next((r for r in reversed(records)
                        if r["status"] == "OK"), None)
        if last_ok:
            cnt = last_ok["count"]
            threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
            color = CLR["danger"] if cnt > threshold else CLR["success"]
            self._lbl_latest.config(
                text=f"Mới nhất: {cnt:,}  |  {last_ok['timestamp']}",
                fg=color)
        else:
            self._lbl_latest.config(text="Chưa có dữ liệu", fg=CLR["muted"])

        # Bảng: 50 bản ghi gần nhất, mới nhất lên trên
        self.tree.delete(*self.tree.get_children())
        for i, rec in enumerate(reversed(records[-50:])):
            cnt   = f"{rec['count']:,}" if rec["count"] >= 0 else "N/A"
            # tính thay đổi
            idx = records.index(rec)   # O(n) nhưng tập nhỏ nên ok
            prev_rec = next(
                (r for r in reversed(records[:idx]) if r["status"] == "OK"),
                None)
            if prev_rec and rec["status"] == "OK" and rec["count"] >= 0:
                d = rec["count"] - prev_rec["count"]
                s = "+" if d >= 0 else ""
                chg = f"{s}{d:,}"
            else:
                chg = "—"

            if rec["status"] != "OK":
                tag = "err"
            elif should_alert(rec["count"]):
                tag = "warn"
            elif i % 2:
                tag = "alt"
            else:
                tag = ""
            self.tree.insert("", END,
                             values=(rec["timestamp"], cnt, chg, rec["status"]),
                             tags=(tag,))


# ══════════════════════════════════════════════════════════
#  WIDGET — LOG BOX
# ══════════════════════════════════════════════════════════
class LogBox(Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=CLR["log_bg"], **kw)
        self.txt = Text(self, font=FONT_MONO_SM, bg=CLR["log_bg"],
                        fg=CLR["log_fg"], wrap="word",
                        state=DISABLED, relief=FLAT, bd=0, height=10)
        sb = Scrollbar(self, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side=LEFT, fill=BOTH, expand=True, padx=4, pady=4)
        sb.pack(side=RIGHT, fill=Y)

        self.txt.tag_config("ok",  foreground="#4ade80")
        self.txt.tag_config("err", foreground="#f87171")
        self.txt.tag_config("wrn", foreground="#fbbf24")
        self.txt.tag_config("sep", foreground="#475569")

    def append(self, msg: str):
        self.txt.configure(state=NORMAL)
        tag = ("ok"  if "✅" in msg or "✓" in msg
               else "err" if "❌" in msg or "✗" in msg or "Lỗi" in msg
               else "wrn" if "⚠" in msg
               else "sep" if msg.startswith("=") or msg.startswith("-")
               else "")
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt.insert(END, f"[{ts}] {msg}\n", tag)
        self.txt.see(END)
        self.txt.configure(state=DISABLED)

    def clear(self):
        self.txt.configure(state=NORMAL)
        self.txt.delete("1.0", END)
        self.txt.configure(state=DISABLED)


# ══════════════════════════════════════════════════════════
#  CỬA SỔ CẤU HÌNH
# ══════════════════════════════════════════════════════════
class ConfigDialog(Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Cấu hình hệ thống")
        self.resizable(False, False)
        self.configure(bg=CLR["bg"])
        self.grab_set()
        self._build()

    def _row(self, parent, label: str, row: int, default="", width=30):
        Label(parent, text=label, font=FONT, bg=CLR["bg"],
              fg=CLR["text"], anchor=W).grid(
            row=row, column=0, sticky=W, padx=(0, 8), pady=3)
        var = StringVar(value=str(default))
        ent = Entry(parent, textvariable=var, font=FONT_MONO,
                    width=width, relief="solid", bd=1)
        ent.grid(row=row, column=1, sticky=EW, pady=3)
        return var

    def _build(self):
        nb = Notebook(self)
        nb.pack(fill=BOTH, expand=True, padx=12, pady=8)

        ec   = CFG.get("email", {})
        al   = CFG.get("alert", {})
        thr  = CFG.get("alert_threshold", ALERT_THRESHOLD)
        sched= CFG.get("schedule_times", ["08:00", "16:00"])

        # ── Tab Email ──
        f_email = Frame(nb, bg=CLR["bg"], padx=12, pady=8)
        nb.add(f_email, text="  Email  ")
        f_email.columnconfigure(1, weight=1)

        self._smtp_host = self._row(f_email, "SMTP Host:",  0, ec.get("smtp_host","smtp.gmail.com"))
        self._smtp_port = self._row(f_email, "SMTP Port:",  1, ec.get("smtp_port",587), 10)
        self._sender    = self._row(f_email, "Tài khoản gửi:", 2, ec.get("sender",""))
        self._password  = self._row(f_email, "Mật khẩu App:", 3, ec.get("password",""))
        Label(f_email, text="Emails nhận (mỗi dòng 1 email):",
              font=FONT, bg=CLR["bg"], fg=CLR["text"]).grid(
            row=4, column=0, columnspan=2, sticky=W, pady=(8,2))
        self._recipients_box = Text(f_email, font=FONT_MONO, height=4,
                                     width=38, relief="solid", bd=1)
        self._recipients_box.grid(row=5, column=0, columnspan=2, sticky="ew")
        self._recipients_box.insert(END, "\n".join(ec.get("recipients", [])))

        # ── Tab Lịch & Ngưỡng ──
        f_sched = Frame(nb, bg=CLR["bg"], padx=12, pady=8)
        nb.add(f_sched, text="  Lịch & Ngưỡng  ")
        f_sched.columnconfigure(1, weight=1)

        self._threshold = self._row(f_sched, "Ngưỡng cảnh báo (bản ghi):", 0, thr, 15)
        Label(f_sched, text="(Email được gửi khi số bản ghi VƯỢT ngưỡng này)",
              font=FONT_SM, bg=CLR["bg"], fg=CLR["muted"]).grid(
            row=1, column=0, columnspan=2, sticky=W)

        Label(f_sched, text="Giờ lấy dữ liệu (mỗi dòng 1 giờ HH:MM):",
              font=FONT, bg=CLR["bg"], fg=CLR["text"]).grid(
            row=2, column=0, columnspan=2, sticky=W, pady=(12,2))
        self._sched_box = Text(f_sched, font=FONT_MONO, height=4,
                                width=20, relief="solid", bd=1)
        self._sched_box.grid(row=3, column=0, columnspan=2, sticky=W)
        self._sched_box.insert(END, "\n".join(sched))

        # ── Buttons ──
        btn_frame = Frame(self, bg=CLR["bg"])
        btn_frame.pack(fill=X, padx=12, pady=(0, 12))
        Button(btn_frame, text="Lưu & Áp dụng",
               command=self._save, font=FONT_BOLD,
               bg=CLR["primary"], fg="white",
               activebackground=CLR["primary_dk"],
               relief=FLAT, cursor="hand2",
               padx=14, pady=5).pack(side=RIGHT, padx=(6, 0))
        Button(btn_frame, text="Huỷ",
               command=self.destroy, font=FONT,
               bg="#F3F4F6", fg=CLR["text"],
               relief=FLAT, cursor="hand2",
               padx=14, pady=5).pack(side=RIGHT)

    def _save(self):
        global CFG
        try:
            thr = int(self._threshold.get().replace(",", "").strip())
        except ValueError:
            messagebox.showerror("Lỗi", "Ngưỡng phải là số nguyên.", parent=self)
            return

        sched = [t.strip() for t in
                 self._sched_box.get("1.0", END).splitlines()
                 if t.strip()]
        recipients = [e.strip() for e in
                      self._recipients_box.get("1.0", END).splitlines()
                      if e.strip()]

        CFG["alert_threshold"]  = thr
        CFG["schedule_times"]   = sched
        CFG["email"]["smtp_host"]   = self._smtp_host.get().strip()
        CFG["email"]["smtp_port"]   = int(self._smtp_port.get().strip())
        CFG["email"]["sender"]      = self._sender.get().strip()
        CFG["email"]["password"]    = self._password.get().strip()
        CFG["email"]["recipients"]  = recipients

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(CFG, f, ensure_ascii=False, indent=2)

        messagebox.showinfo("Đã lưu",
                            "Cấu hình đã được lưu.\n"
                            "Scheduler sẽ áp dụng ở lần khởi động tiếp theo.",
                            parent=self)
        self.destroy()


# ══════════════════════════════════════════════════════════
#  CỬA SỔ CHÍNH
# ══════════════════════════════════════════════════════════
class MonitorApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Giám sát Dữ liệu Chấm công — ZK Monitor")
        self.root.geometry("1050x700")
        self.root.configure(bg=CLR["bg"])
        self.root.minsize(820, 580)

        self._snapshot: list[dict] = []
        self._build_ui()
        self._load_initial_history()
        self._start_scheduler()

    # ── Build UI ──────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = Frame(self.root, bg=CLR["sidebar_hdr"], height=52)
        hdr.pack(fill=X)
        hdr.pack_propagate(False)
        Label(hdr, text="🖥  ZK Attendance Monitor",
              font=FONT_LG, bg=CLR["sidebar_hdr"],
              fg="white").pack(side=LEFT, padx=16, pady=10)
        threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
        self._lbl_threshold = Label(
            hdr,
            text=f"Ngưỡng cảnh báo: {threshold:,} bản ghi",
            font=FONT_SM, bg=CLR["sidebar_hdr"], fg="#94A3B8")
        self._lbl_threshold.pack(side=LEFT, padx=8)

        # Toolbar
        tb = Frame(self.root, bg=CLR["bg"], pady=6)
        tb.pack(fill=X, padx=12)

        def btn(text, cmd, style="primary"):
            colors = {
                "primary": (CLR["primary"], CLR["primary_dk"], "white"),
                "success": (CLR["success"], "#15803D", "white"),
                "muted":   ("#F3F4F6", "#E5E7EB", CLR["text"]),
            }
            bg, abg, fg = colors[style]
            b = Button(tb, text=text, command=cmd, font=FONT_BOLD,
                       bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                       relief=FLAT, cursor="hand2", padx=12, pady=4)
            b.pack(side=LEFT, padx=(0, 6))
            return b

        self._btn_check = btn("▶  Kiểm tra ngay", self._on_check_now, "success")
        btn("⚙  Cấu hình",    self._on_config, "muted")
        btn("🗑  Xóa log",     self._on_clear_log, "muted")

        self._lbl_status = Label(tb, text="Chờ lịch...",
                                  font=FONT_SM, bg=CLR["bg"],
                                  fg=CLR["muted"])
        self._lbl_status.pack(side=LEFT, padx=12)

        self._lbl_next = Label(tb, text="", font=FONT_SM,
                                bg=CLR["bg"], fg=CLR["muted"])
        self._lbl_next.pack(side=RIGHT)

        # Notebook
        nb = Notebook(self.root)
        nb.pack(fill=BOTH, expand=True, padx=8, pady=(0, 4))

        # Tab 1 — Tổng quan
        f1 = Frame(nb, bg=CLR["bg"])
        nb.add(f1, text="  Tổng quan  ")

        self._tbl = DeviceTable(f1)
        self._tbl.pack(fill=BOTH, expand=True, padx=8, pady=8)

        sep = Separator(f1); sep.pack(fill=X, padx=8)
        Label(f1, text="Log hoạt động",
              font=FONT_BOLD, bg=CLR["bg"],
              fg=CLR["muted"]).pack(anchor=W, padx=12, pady=(4, 0))
        self._log = LogBox(f1)
        self._log.pack(fill=X, padx=8, pady=(0, 8))

        # Tab 2 — Lịch sử
        f2 = Frame(nb, bg=CLR["bg"])
        nb.add(f2, text="  Lịch sử từng máy  ")

        self._hist = HistoryPanel(f2)
        self._hist.pack(fill=BOTH, expand=True)
        devices = CFG.get("devices", [])
        self._hist.set_devices(devices)

        # Tick đếm ngược
        self._tick()

    # ── Initial load ─────────────────────────────────────
    def _load_initial_history(self):
        hist = load_history()
        self._hist.refresh(hist)
        # Hiển thị snapshot từ lịch sử (dữ liệu lần cuối)
        devices = CFG.get("devices", [])
        snap = []
        for dev in devices:
            ip   = dev.get("ip", "")
            name = dev.get("name", ip)
            records = hist.get(ip, [])
            last = next((r for r in reversed(records)
                         if r["status"] == "OK"), None)
            if last:
                snap.append({
                    "ip": ip, "name": name,
                    "count":      last["count"],
                    "status":     last["status"],
                    "change_str": "—",
                    "timestamp":  last["timestamp"],
                })
        if snap:
            self._tbl.load(snap)
            self._log.append(f"Đã tải dữ liệu lịch sử: {len(snap)} máy.")

    # ── Scheduler ────────────────────────────────────────
    def _start_scheduler(self):
        start_scheduler(
            callback_log     = self._safe_log,
            callback_refresh = self._safe_refresh,
        )
        sched_times = CFG.get("schedule_times", ["08:00", "16:00"])
        self._log.append(
            f"Scheduler đang chạy. Lịch: {', '.join(sched_times)}")

    # ── Thread-safe callbacks ─────────────────────────────
    def _safe_log(self, msg: str):
        self.root.after(0, lambda: self._log.append(msg))

    def _safe_refresh(self, snapshot: list[dict]):
        def _do():
            self._tbl.load(snapshot)
            hist = load_history()
            self._hist.refresh(hist)
            self._lbl_status.config(
                text=f"Cập nhật lúc {datetime.now():%H:%M:%S}",
                fg=CLR["success"])
        self.root.after(0, _do)

    # ── Kiểm tra thủ công ────────────────────────────────
    def _on_check_now(self):
        self._btn_check.config(state=DISABLED)
        self._lbl_status.config(text="Đang kiểm tra ...", fg=CLR["warning"])

        def worker():
            snap = run_check(self._safe_log)
            self._safe_refresh(snap)
            self.root.after(0, lambda: self._btn_check.config(state=NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    # ── Config dialog ─────────────────────────────────────
    def _on_config(self):
        dlg = ConfigDialog(self.root)
        self.root.wait_window(dlg)
        # Cập nhật label ngưỡng
        threshold = CFG.get("alert_threshold", ALERT_THRESHOLD)
        self._lbl_threshold.config(
            text=f"Ngưỡng cảnh báo: {threshold:,} bản ghi")

    def _on_clear_log(self):
        self._log.clear()

    # ── Tick đếm ngược ───────────────────────────────────
    def _tick(self):
        if _schedule is not None:
            try:
                import schedule as sch
                nxt = sch.next_run()
                if nxt:
                    delta = nxt - datetime.now()
                    total = int(delta.total_seconds())
                    if total > 0:
                        h, rem = divmod(total, 3600)
                        m, s   = divmod(rem, 60)
                        self._lbl_next.config(
                            text=f"⏱ Lần tới: {h:02d}:{m:02d}:{s:02d}",
                            fg=CLR["muted"])
                    else:
                        self._lbl_next.config(text="⏱ Sắp chạy...",
                                              fg=CLR["warning"])
            except Exception:
                pass
        self.root.after(1000, self._tick)


# ══════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════
def main():
    root = Tk()
    app = MonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_scheduler(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()