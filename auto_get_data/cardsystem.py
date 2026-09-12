# -*- coding: utf-8 -*-
"""
GUI Quản lý thẻ RFID tương tự Mitapro
- Cập nhật danh sách nhân viên từ nhiều máy (zk TCP/IP) -> all_rfid.txt
- Hiển thị bảng "Danh sách nhân viên" với ô lọc theo MST
- Mỗi dòng có nút [+] để thêm MST đó vào danh sách xóa
- Nhập RFID -> Enter -> Tự động tìm MST -> Thêm vào danh sách xóa
- Xóa tất cả MST trong danh sách trên toàn bộ máy
- Lấy dữ liệu chấm công từ ngày đến ngày từ tất cả máy -> xuất CSV
- Tự động lấy chấm công hôm qua + hôm nay lúc 07:31 mỗi ngày
- Lưu dữ liệu chấm công vào SQL Server (pyodbc)

Yêu cầu: pip install zk pyodbc
"""

import os
import csv
import glob
import threading
import json
from datetime import datetime, date, timedelta
from tkinter import (
    Tk, Frame, Label, Button, Entry, Text, StringVar,
    Scrollbar, Canvas, END, BOTH, X, Y, LEFT, RIGHT,
    TOP, BOTTOM, DISABLED, NORMAL, W, NW, WORD, FLAT, RIDGE,
    Toplevel, Listbox
)
from tkinter import messagebox, filedialog, font as tkfont
from tkinter.ttk import Treeview, Style, Separator, Notebook, Combobox

# ====== KẾT NỐI THIẾT BỊ (ZK) ======
try:
    from zk import ZK
except ImportError:
    ZK = None

# ====== KẾT NỐI SQL SERVER ======
try:
    import pyodbc
except ImportError:
    pyodbc = None

# ====== CẤU HÌNH ======
LISTS_DEVICE_IP = [
    "172.17.60.221", "172.17.60.22", "172.17.60.23", "172.17.60.24",
    "172.17.60.25", "172.17.60.26", "172.17.60.27", "172.17.60.28"
]
DEVICE_PORT = 4370
TIMEOUT = 10
PASSWORD = 0

HEADER = "MST|RFID"
MERGED_FILE = "all_rfid.txt"
DEDUPLICATE = True
SORT_BY_MST = True

ADD_ICON = "＋"

# ====== TỰ ĐỘNG LẤY CHẤM CÔNG ======
# Danh sách các mốc giờ chạy tự động (có thể cấu hình nhiều mốc)
AUTO_FETCH_TIMES = ["07:31", "12:00", "17:30"]
CONFIG_AUTO_FILE = "config_auto.json"

def load_auto_fetch_times():
    global AUTO_FETCH_TIMES
    try:
        if os.path.exists(CONFIG_AUTO_FILE):
            with open(CONFIG_AUTO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    AUTO_FETCH_TIMES = data
    except Exception:
        pass

def save_auto_fetch_times():
    try:
        with open(CONFIG_AUTO_FILE, "w", encoding="utf-8") as f:
            json.dump(AUTO_FETCH_TIMES, f)
    except Exception:
        pass

load_auto_fetch_times()

# ====== CẤU HÌNH SQL SERVER ======
DB_CONFIG = {
    "server":   "172.16.60.100",
    "database": "MITACOSQL",
    "username": "IT",
    "password": ".<>N@mthu4n@123#",
    "table":    "Checkinout",
    "driver":   "ODBC Driver 17 for SQL Server",
}

DB_DEFAULT_KIEU_CHAM  = 255
DB_DEFAULT_NGUON_CHAM = 4
DB_DEFAULT_MA_SO_MAY  = 1

def _ip_to_ten_may(ip: str) -> tuple[int, str]:
    try:
        last = int(ip.split(".")[-1])
        so   = last - 220
        if so < 1:
            so = last
        return so, f"Máy {so}"
    except Exception:
        return DB_DEFAULT_MA_SO_MAY, ip

# ====== DESIGN TOKENS ======
CLR = {
    "bg":           "#F0F2F5",
    "surface":      "#FFFFFF",
    "sidebar":      "#1E2A3A",
    "sidebar_hdr":  "#141E2B",
    "primary":      "#2563EB",
    "primary_dk":   "#1D4ED8",
    "danger":       "#DC2626",
    "danger_dk":    "#B91C1C",
    "success":      "#16A34A",
    "warning":      "#D97706",
    "muted":        "#6B7280",
    "border":       "#E5E7EB",
    "row_alt":      "#F8FAFC",
    "row_sel":      "#DBEAFE",
    "row_dim":      "#CBD5E1",
    "text":         "#111827",
    "text_muted":   "#6B7280",
    "header_bg":    "#1E40AF",
    "header_fg":    "#FFFFFF",
    "log_bg":       "#0F172A",
    "log_fg":       "#94A3B8",
    "tag_added":    "#FEF3C7",
    "in_list_fg":   "#94A3B8",
    "attend_hdr":   "#064E3B",
    "attend_fg":    "#FFFFFF",
    "attend_sel":   "#D1FAE5",
}

FONT_FAMILY = "Segoe UI"
FONT = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SM = (FONT_FAMILY, 9)
FONT_LG = (FONT_FAMILY, 12, "bold")
FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)


# ──────────────────────────────────────────────────────────
#  TIỆN ÍCH SẮP XẾP
# ──────────────────────────────────────────────────────────
def _int_key(s):
    try:
        return (0, int(s))
    except (ValueError, TypeError):
        return (1, str(s))


# ──────────────────────────────────────────────────────────
#  TIỆN ÍCH TỆP
# ──────────────────────────────────────────────────────────
def read_all_rfid_file(path=MERGED_FILE):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.upper() == HEADER.upper():
                continue
            parts = ln.split("|")
            if len(parts) != 2:
                continue
            mst, rfid = parts[0].strip(), parts[1].strip()
            if mst and rfid:
                rows.append((mst, rfid))
    return rows


def find_mst_for_rfid(rfid, data_rows):
    rfid_to_mst = {}
    for mst, r in data_rows:
        if r not in rfid_to_mst:
            rfid_to_mst[r] = mst
    rfid = rfid.strip()
    if not rfid:
        return None
    try:
        return rfid_to_mst.get(str(int(rfid)))
    except ValueError:
        return rfid_to_mst.get(rfid)


# ──────────────────────────────────────────────────────────
#  CHỨC NĂNG KẾT NỐI MÁY ZK
# ──────────────────────────────────────────────────────────
def export_one_device(ip: str) -> str:
    if ZK is None:
        raise RuntimeError("Chưa cài thư viện 'zk'. Hãy chạy: pip install zk")
    zk = ZK(ip, port=DEVICE_PORT, timeout=TIMEOUT, password=PASSWORD,
            force_udp=False, ommit_ping=False)
    conn = None
    output_file = f"{ip}.txt"
    try:
        conn = zk.connect()
        conn.disable_device()
        users = conn.get_users()
        with open(output_file, "w", encoding="utf-8") as f:
            if HEADER:
                f.write(HEADER + "\n")
            for u in users:
                mst = (u.user_id or "").strip()
                rfid = (str(u.card) if u.card is not None else "").strip()
                if mst and rfid and rfid != "0":
                    f.write(f"{mst}|{rfid}\n")
        return output_file
    except Exception as e:
        print(f"[{ip}] Lỗi: {e}")
        return ""
    finally:
        try:
            if conn:
                conn.enable_device()
                conn.disconnect()
        except:
            pass


def merge_txt_files(pattern="*.txt", merged_file=MERGED_FILE,
                    header=HEADER, dedup=True, sort_by_mst=True):
    files = sorted(glob.glob(pattern))
    files = [f for f in files if os.path.basename(f).replace(".txt", "") in LISTS_DEVICE_IP]
    if not files:
        return False
    seen, rows = set(), []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or (header and line.upper() == header.upper()):
                    continue
                if dedup:
                    if line in seen:
                        continue
                    seen.add(line)
                rows.append(line)
    if sort_by_mst:
        rows.sort(key=lambda s: s.split("|", 1)[0])
    with open(merged_file, "w", encoding="utf-8") as out:
        if header:
            out.write(header + "\n")
        for r in rows:
            out.write(r + "\n")
    return True


def update_list_rfid(callback_log=None):
    def _log(msg):
        if callback_log:
            callback_log(msg)
        else:
            print(msg)
    ok_files = []
    for ip in LISTS_DEVICE_IP:
        _log(f"[{datetime.now():%H:%M:%S}] Kết nối {ip} ...")
        path = export_one_device(ip)
        if path:
            _log(f"  ✓ Xuất xong {path}")
            ok_files.append(path)
        else:
            _log(f"  ✗ LỖI hoặc không có dữ liệu từ {ip}")
    if ok_files:
        _log("Đang gộp các file ...")
        if merge_txt_files():
            _log(f"✅ Đã gộp xong → {MERGED_FILE}")
        else:
            _log("⚠ Không gộp được.")
    else:
        _log("⛔ Không có file nào xuất ra, bỏ qua bước gộp.")


def delete_user_by_mst_on_all_devices(msts, callback_log=None):
    if ZK is None:
        raise RuntimeError("Chưa cài thư viện 'zk'. Hãy chạy: pip install zk")

    def _log(msg):
        if callback_log:
            callback_log(msg)
        else:
            print(msg)

    total_deleted = 0
    msts = [m.strip() for m in msts if m and m.strip()]
    if not msts:
        _log("⚠ Không có MST hợp lệ để xóa.")
        return 0

    for ip in LISTS_DEVICE_IP:
        zk = ZK(ip, port=DEVICE_PORT, timeout=TIMEOUT, password=PASSWORD,
                force_udp=False, ommit_ping=False)
        conn = None
        try:
            _log(f"[{datetime.now():%H:%M:%S}] Kết nối {ip} → xóa {len(msts)} MST ...")
            conn = zk.connect()
            conn.disable_device()
            users = conn.get_users()
            targets = []
            for u in users:
                uid = getattr(u, "uid", None)
                mst = (getattr(u, "user_id", "") or "").strip()
                if uid is not None and mst in msts:
                    targets.append((uid, mst))
            if not targets:
                _log(f"  [{ip}] Không có MST nào trùng.")
            else:
                deleted_here = 0
                for uid, mst in targets:
                    try:
                        conn.delete_user(uid)
                        deleted_here += 1
                    except Exception as inner_e:
                        _log(f"  [{ip}] ❌ Lỗi xóa UID={uid}, MST={mst}: {inner_e}")
                try:
                    conn.refresh_data()
                except Exception:
                    pass
                _log(f"  [{ip}] ✓ Đã xóa {deleted_here} bản ghi.")
                total_deleted += deleted_here
        except Exception as e:
            _log(f"  [{ip}] ❌ Lỗi kết nối: {e}")
        finally:
            try:
                if conn:
                    conn.enable_device()
                    conn.disconnect()
            except:
                pass

    _log(f"✅ Hoàn tất — Tổng đã xóa: {total_deleted} bản ghi")
    return total_deleted


# ──────────────────────────────────────────────────────────
#  CHỨC NĂNG LẤY DỮ LIỆU CHẤM CÔNG
# ──────────────────────────────────────────────────────────
def fetch_attendance_from_device(ip: str, date_from: date, date_to: date,
                                  callback_log=None):
    if ZK is None:
        raise RuntimeError("Chưa cài thư viện 'zk'. Hãy chạy: pip install zk")

    def _log(msg):
        if callback_log:
            callback_log(msg)
        else:
            print(msg)

    zk = ZK(ip, port=DEVICE_PORT, timeout=TIMEOUT, password=PASSWORD,
            force_udp=False, ommit_ping=False)
    conn = None
    records = []
    status_msg = "Thành công"
    try:
        conn = zk.connect()
        conn.disable_device()
        attendances = conn.get_attendance()

        dt_from = datetime.combine(date_from, datetime.min.time())
        dt_to   = datetime.combine(date_to,   datetime.max.time().replace(microsecond=0))

        for att in attendances:
            ts = att.timestamp
            if not ts:
                continue
            if isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
            if dt_from <= ts <= dt_to:
                records.append({
                    "ip":        ip,
                    "mst":       str(att.user_id).strip(),
                    "timestamp": ts,
                    "status":    getattr(att, "status", ""),
                    "punch":     getattr(att, "punch",  ""),
                })
        _log(f"  [{ip}] ✓ {len(records)} bản ghi chấm công.")
    except Exception as e:
        status_msg = f"Lỗi: {e}"
        _log(f"  [{ip}] ❌ Lỗi: {e}")
    finally:
        try:
            if conn:
                conn.enable_device()
                conn.disconnect()
        except:
            pass
    return records, status_msg


def fetch_attendance_all_devices(date_from: date, date_to: date,
                                  callback_log=None, target_ips=None):
    if target_ips is None:
        target_ips = LISTS_DEVICE_IP

    def _log(msg):
        if callback_log:
            callback_log(msg)
        else:
            print(msg)

    all_records = []
    history_logs = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ip in target_ips:
        _log(f"[{datetime.now():%H:%M:%S}] Kết nối {ip} → lấy chấm công ...")
        recs, status_msg = fetch_attendance_from_device(ip, date_from, date_to, _log)
        all_records.extend(recs)
        history_logs.append({
            "Thời gian lấy": now_str,
            "Máy (IP)": ip,
            "Từ ngày": date_from.strftime("%d/%m/%Y"),
            "Đến ngày": date_to.strftime("%d/%m/%Y"),
            "Số bản ghi": len(recs),
            "Trạng thái": status_msg
        })

    try:
        history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_history.csv")
        file_exists = os.path.exists(history_file)
        with open(history_file, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["Thời gian lấy", "Máy (IP)", "Từ ngày", "Đến ngày", "Số bản ghi", "Trạng thái"])
            if not file_exists:
                writer.writeheader()
            writer.writerows(history_logs)
        _log(f"Đã lưu lịch sử lấy dữ liệu vào fetch_history.csv")
    except Exception as e:
        _log(f"⚠ Lỗi lưu lịch sử: {e}")

    all_records.sort(key=lambda r: (_int_key(r["mst"]), r["timestamp"]))
    _log(f"✅ Tổng cộng: {len(all_records)} bản ghi từ {len(target_ips)} máy.")
    return all_records

# ──────────────────────────────────────────────────────────
#  SQL SERVER — LỚP QUẢN LÝ DB
# ──────────────────────────────────────────────────────────
class SqlServerDB:

    @staticmethod
    def _build_conn_str() -> str:
        c = DB_CONFIG
        return (
            f"DRIVER={{{c['driver']}}};"
            f"SERVER={c['server']};"
            f"DATABASE={c['database']};"
            f"UID={c['username']};"
            f"PWD={c['password']};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
        )

    @classmethod
    def test_connection(cls) -> tuple[bool, str]:
        if pyodbc is None:
            return False, "Chưa cài thư viện 'pyodbc'. Chạy: pip install pyodbc"
        try:
            with pyodbc.connect(cls._build_conn_str(), timeout=8) as conn:
                conn.cursor().execute("SELECT 1")
            return True, "Kết nối thành công!"
        except Exception as e:
            return False, str(e)

    @classmethod
    def insert_attendance(cls, records: list, rfid_map: dict = None,
                          callback_log=None) -> int:
        def _log(msg):
            if callback_log:
                callback_log(msg)

        if not records:
            _log("⚠ Không có bản ghi nào để lưu DB.")
            return 0

        tbl = DB_CONFIG["table"]
        sql = f"""
            IF NOT EXISTS (
                SELECT 1 FROM [{tbl}]
                WHERE MaChamCong = ?
                AND NgayCham = ?
                AND GioCham = ?
            )
            INSERT INTO [{tbl}]
            (MaChamCong, NgayCham, GioCham, KieuCham, NguonCham, MaSoMay, TenMay)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """

        rows = []
        for r in records:
            ts  = r["timestamp"]
            mst = r["mst"].strip()
            ip  = r["ip"]

            try:
                ma_cham_cong = int(mst)
            except ValueError:
                _log(f"  ⚠ Bỏ qua MST không phải số: {mst}")
                continue

            ngay_cham = datetime(ts.year, ts.month, ts.day, 0, 0, 0)
            gio_cham  = ts.replace(microsecond=0)

            ma_so_may, ten_may = _ip_to_ten_may(ip)

            rows.append((
                ma_cham_cong,
                ngay_cham,
                gio_cham,
                DB_DEFAULT_KIEU_CHAM,
                DB_DEFAULT_NGUON_CHAM,
                ma_so_may,
                ten_may,
            ))

        if not rows:
            _log("⚠ Không có dòng hợp lệ để INSERT.")
            return 0

        inserted = 0

        try:
            with pyodbc.connect(cls._build_conn_str(), timeout=15) as conn:
                cursor = conn.cursor()

                for row in rows:
                    try:
                        cursor.execute(sql,  row[:3] + row)
                        inserted += 1
                    except Exception as e:
                        _log(f"⚠ Bỏ qua dòng lỗi: {e}")
                        continue

                conn.commit()

            _log(f"✅ Đã lưu {inserted} bản ghi vào [{tbl}].")

        except Exception as e:
            _log(f"❌ Lỗi kết nối SQL: {e}")
        return inserted


def save_attendance_to_db(records, rfid_map=None, callback_log=None) -> int:
    if pyodbc is None:
        if callback_log:
            callback_log("❌ Chưa cài 'pyodbc'. Chạy: pip install pyodbc")
        return 0
    return SqlServerDB.insert_attendance(records, callback_log=callback_log)


# ──────────────────────────────────────────────────────────
#  UI HELPERS
# ──────────────────────────────────────────────────────────
def styled_button(parent, text, command, style="primary",
                  padx=14, pady=5, font=None):
    colors = {
        "primary":  (CLR["primary"],    CLR["primary_dk"],  "#FFFFFF"),
        "ghost":    (CLR["surface"],    CLR["border"],      CLR["text"]),
        "danger":   (CLR["danger"],     CLR["danger_dk"],   "#FFFFFF"),
        "muted":    ("#F3F4F6",         "#E5E7EB",          CLR["muted"]),
        "success":  (CLR["success"],    "#15803D",          "#FFFFFF"),
        "attend":   (CLR["attend_hdr"], "#065F46",          "#FFFFFF"),
    }
    bg, abg, fg = colors.get(style, colors["primary"])
    btn = Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
        font=font or FONT_BOLD, relief=FLAT, cursor="hand2",
        padx=padx, pady=pady, bd=0,
    )
    return btn


def section_label(parent, text):
    f = Frame(parent, bg=CLR["bg"])
    f.pack(fill=X, pady=(12, 4))
    Label(f, text=text, font=FONT_BOLD, bg=CLR["bg"],
          fg=CLR["text_muted"]).pack(side=LEFT)
    return f


def card(parent, **kw):
    kw.setdefault("bg", CLR["surface"])
    kw.setdefault("padx", 12)
    kw.setdefault("pady", 10)
    return Frame(parent, relief=FLAT, bd=0, **kw)


# ──────────────────────────────────────────────────────────
#  WIDGET BẢNG NHÂN VIÊN
# ──────────────────────────────────────────────────────────
class EmployeeTable(Frame):
    COLS = ("add_btn", "mst", "rfid")

    def __init__(self, master, on_add_row, **kw):
        kw.setdefault("bg", CLR["surface"])
        super().__init__(master, **kw)
        self.on_add_row = on_add_row
        self._all_rows = []
        self._row_map = {}
        self._sort_col = "mst"
        self._sort_dir = "asc"

        self._build_filter_bar()
        self._build_tree()

    def _build_filter_bar(self):
        bar = Frame(self, bg=CLR["surface"], pady=8, padx=4)
        bar.pack(fill=X)

        Label(bar, text="🔍", bg=CLR["surface"], font=("Segoe UI Emoji", 11)
              ).pack(side=LEFT, padx=(0, 4))

        ef = Frame(bar, bg=CLR["border"], padx=1, pady=1)
        ef.pack(side=LEFT)
        inner = Frame(ef, bg=CLR["surface"])
        inner.pack()
        self.filter_var = StringVar()
        self.filter_var.trace_add("write", self._on_filter_change)
        self._entry_filter = Entry(
            inner, textvariable=self.filter_var,
            font=FONT, width=20, relief=FLAT, bg=CLR["surface"],
            fg=CLR["text"], insertbackground=CLR["primary"]
        )
        self._entry_filter.pack(padx=6, pady=4)

        btn_clr = Button(
            bar, text="✕", command=lambda: self.filter_var.set(""),
            bg=CLR["surface"], fg=CLR["muted"], relief=FLAT,
            font=FONT_BOLD, cursor="hand2", padx=4, pady=2, bd=0,
            activebackground=CLR["bg"], activeforeground=CLR["danger"]
        )
        btn_clr.pack(side=LEFT, padx=(4, 0))

        self.lbl_count = Label(bar, text="", font=FONT_SM,
                               bg=CLR["surface"], fg=CLR["muted"])
        self.lbl_count.pack(side=RIGHT, padx=(0, 6))

    def _build_tree(self):
        st = Style()
        st.configure("Emp.Treeview",
                      font=FONT,
                      rowheight=28,
                      background=CLR["surface"],
                      fieldbackground=CLR["surface"],
                      foreground=CLR["text"],
                      borderwidth=0)
        st.configure("Emp.Treeview.Heading",
                      font=FONT_BOLD,
                      background=CLR["header_bg"],
                      foreground=CLR["header_fg"],
                      relief=FLAT,
                      padding=(6, 6))
        st.map("Emp.Treeview",
               background=[("selected", CLR["row_sel"])],
               foreground=[("selected", CLR["text"])])
        st.map("Emp.Treeview.Heading",
               background=[("active", CLR["primary_dk"])])

        tf = Frame(self, bg=CLR["border"], padx=1, pady=1)
        tf.pack(fill=BOTH, expand=True, padx=4, pady=(0, 4))

        self.tree = Treeview(
            tf, columns=self.COLS, show="headings",
            style="Emp.Treeview", selectmode="browse"
        )
        self.tree.heading("add_btn", text="")
        self.tree.heading("mst", text="MST  ↑",
                          command=lambda: self._sort_by("mst"))
        self.tree.heading("rfid", text="RFID",
                          command=lambda: self._sort_by("rfid"))
        self.tree.column("add_btn", width=36, anchor="center", stretch=False)
        self.tree.column("mst", width=180, minwidth=100)
        self.tree.column("rfid", width=200, minwidth=120)

        vsb = Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)

        self.tree.tag_configure("odd",     background=CLR["surface"])
        self.tree.tag_configure("even",    background=CLR["row_alt"])
        self.tree.tag_configure("in_list", foreground=CLR["in_list_fg"],
                                font=(FONT_FAMILY, 10, "italic"))

        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.bind("<Motion>", self._on_motion)
        self._hover_iid = None

    def load(self, rows):
        self._all_rows = list(rows)
        self._apply_filter_and_sort()

    def mark_in_list(self, msts_set):
        for iid, (mst, _) in self._row_map.items():
            base = self.tree.item(iid, "tags")
            base_tags = [t for t in (base or ()) if t in ("odd", "even")]
            if mst in msts_set:
                base_tags.append("in_list")
            self.tree.item(iid, tags=tuple(base_tags))

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_col = col
            self._sort_dir = "asc"
        self._update_heading_labels()
        self._apply_filter_and_sort()

    def _update_heading_labels(self):
        arrow = {"asc": "  ↑", "desc": "  ↓"}
        for col, label in (("mst", "MST"), ("rfid", "RFID")):
            suffix = arrow[self._sort_dir] if self._sort_col == col else ""
            self.tree.heading(col, text=label + suffix)

    def _apply_filter_and_sort(self):
        kw = self.filter_var.get().strip().lower()
        rows = [(m, r) for m, r in self._all_rows
                if kw in m.lower()] if kw else list(self._all_rows)
        idx = 0 if self._sort_col == "mst" else 1
        rows.sort(key=lambda t: _int_key(t[idx]),
                  reverse=(self._sort_dir == "desc"))
        self._render(rows)

    def _render(self, rows):
        self.tree.delete(*self.tree.get_children())
        self._row_map.clear()
        for i, (mst, rfid) in enumerate(rows):
            tag = "odd" if i % 2 == 0 else "even"
            iid = self.tree.insert("", END, values=(ADD_ICON, mst, rfid),
                                   tags=(tag,))
            self._row_map[iid] = (mst, rfid)
        n, total = len(rows), len(self._all_rows)
        self.lbl_count.config(
            text=f"{n} / {total} dòng" if n != total else f"{total} nhân viên"
        )

    def _on_filter_change(self, *_):
        self._apply_filter_and_sort()

    def _on_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        col    = self.tree.identify_column(event.x)
        iid    = self.tree.identify_row(event.y)
        if region == "cell" and col == "#1" and iid:
            mst, rfid = self._row_map.get(iid, (None, None))
            if mst:
                self.on_add_row(mst, rfid)

    def _on_motion(self, event):
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if col == "#1" and iid:
            self.tree.config(cursor="hand2")
        else:
            self.tree.config(cursor="")


# ──────────────────────────────────────────────────────────
#  WIDGET BẢNG CHẤM CÔNG
# ──────────────────────────────────────────────────────────
class AttendanceTable(Frame):
    COLS = ("stt", "mst", "rfid", "date", "time", "weekday",
            "status", "punch", "ip")
    COL_CFG = {
        "stt":     ("STT",          50,  "center"),
        "mst":     ("MST",         140,  "w"),
        "rfid":    ("RFID",        140,  "w"),
        "date":    ("Ngày",         90,  "center"),
        "time":    ("Giờ",          72,  "center"),
        "weekday": ("Thứ",          80,  "center"),
        "status":  ("Trạng thái",  100,  "center"),
        "punch":   ("Kiểu chấm",    90,  "center"),
        "ip":      ("Máy (IP)",    130,  "w"),
    }

    def __init__(self, master, **kw):
        kw.setdefault("bg", CLR["surface"])
        super().__init__(master, **kw)
        self._all_rows = []
        self._build_filter_bar()
        self._build_tree()

    def _build_filter_bar(self):
        bar = Frame(self, bg=CLR["surface"], pady=6, padx=4)
        bar.pack(fill=X)

        Label(bar, text="🔍", bg=CLR["surface"],
              font=("Segoe UI Emoji", 11)).pack(side=LEFT, padx=(0, 4))

        ef = Frame(bar, bg=CLR["border"], padx=1, pady=1)
        ef.pack(side=LEFT)
        inner = Frame(ef, bg=CLR["surface"])
        inner.pack()
        self.filter_var = StringVar()
        self.filter_var.trace_add("write", self._on_filter)
        Entry(inner, textvariable=self.filter_var,
              font=FONT, width=22, relief=FLAT,
              bg=CLR["surface"], fg=CLR["text"],
              insertbackground=CLR["primary"]).pack(padx=6, pady=4)

        Button(bar, text="✕", command=lambda: self.filter_var.set(""),
               bg=CLR["surface"], fg=CLR["muted"], relief=FLAT,
               font=FONT_BOLD, cursor="hand2", padx=4, pady=2, bd=0,
               activebackground=CLR["bg"],
               activeforeground=CLR["danger"]).pack(side=LEFT, padx=(4, 0))

        self.lbl_count = Label(bar, text="", font=FONT_SM,
                               bg=CLR["surface"], fg=CLR["muted"])
        self.lbl_count.pack(side=RIGHT, padx=(0, 6))

    def _build_tree(self):
        st = Style()
        st.configure("Att.Treeview",
                      font=FONT_SM, rowheight=26,
                      background=CLR["surface"],
                      fieldbackground=CLR["surface"],
                      foreground=CLR["text"], borderwidth=0)
        st.configure("Att.Treeview.Heading",
                      font=FONT_BOLD,
                      background=CLR["attend_hdr"],
                      foreground=CLR["attend_fg"],
                      relief=FLAT, padding=(4, 5))
        st.map("Att.Treeview",
               background=[("selected", CLR["attend_sel"])],
               foreground=[("selected", CLR["text"])])

        tf = Frame(self, bg=CLR["border"], padx=1, pady=1)
        tf.pack(fill=BOTH, expand=True, padx=4, pady=(0, 4))

        self.tree = Treeview(tf, columns=self.COLS, show="headings",
                             style="Att.Treeview", selectmode="extended")

        for col in self.COLS:
            label, width, anchor = self.COL_CFG[col]
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor, minwidth=40)

        vsb = Scrollbar(tf, orient="vertical",   command=self.tree.yview)
        hsb = Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        self.tree.tag_configure("odd",  background=CLR["surface"])
        self.tree.tag_configure("even", background=CLR["row_alt"])

    def load(self, records, rfid_map=None):
        WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư",
                       "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        STATUS_MAP  = {0: "Check-in", 1: "Check-out", 2: "OT In",
                       3: "OT Out",  4: "Break Out",  5: "Break In"}
        PUNCH_MAP   = {0: "Vân tay", 1: "Thẻ", 15: "Mật khẩu"}

        self._all_rows = []
        for i, r in enumerate(records, start=1):
            ts  = r["timestamp"]
            mst = r["mst"]
            self._all_rows.append((
                i,
                mst,
                (rfid_map or {}).get(mst, ""),
                ts.strftime("%d/%m/%Y"),
                ts.strftime("%H:%M:%S"),
                WEEKDAYS_VI[ts.weekday()],
                STATUS_MAP.get(r["status"], str(r["status"])),
                PUNCH_MAP.get(r["punch"],   str(r["punch"])),
                r["ip"],
            ))
        self._render(self._all_rows)

    def _render(self, rows):
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            tag = "odd" if i % 2 == 0 else "even"
            self.tree.insert("", END, values=row, tags=(tag,))
        n, total = len(rows), len(self._all_rows)
        self.lbl_count.config(
            text=f"{n} / {total} bản ghi" if n != total else f"{total} bản ghi"
        )

    def _on_filter(self, *_):
        kw = self.filter_var.get().strip().lower()
        if not kw:
            self._render(self._all_rows)
            return
        filtered = [r for r in self._all_rows
                    if any(kw in str(v).lower() for v in r)]
        self._render(filtered)

    def clear(self):
        self._all_rows = []
        self.tree.delete(*self.tree.get_children())
        self.lbl_count.config(text="")


# ──────────────────────────────────────────────────────────
#  WIDGET CHỌN NGÀY (DateEntry đơn giản)
# ──────────────────────────────────────────────────────────
class DateEntry(Frame):
    def __init__(self, master, initial: date = None, **kw):
        kw.setdefault("bg", CLR["surface"])
        super().__init__(master, **kw)
        self._date = initial or date.today()

        ef = Frame(self, bg=CLR["border"], padx=1, pady=1)
        ef.pack(side=LEFT)
        inner = Frame(ef, bg=CLR["surface"])
        inner.pack()

        self._var = StringVar(value=self._date.strftime("%d/%m/%Y"))
        self._entry = Entry(inner, textvariable=self._var,
                            font=FONT, width=11, relief=FLAT,
                            bg=CLR["surface"], fg=CLR["text"],
                            insertbackground=CLR["primary"], justify="center")
        self._entry.pack(padx=6, pady=4)
        self._entry.bind("<FocusOut>", self._parse)
        self._entry.bind("<Return>",   self._parse)

        Button(self, text="◀", command=lambda: self._shift(-1),
               bg=CLR["surface"], fg=CLR["muted"], relief=FLAT,
               font=FONT_SM, cursor="hand2", padx=3, pady=2, bd=0,
               activebackground=CLR["bg"]).pack(side=LEFT, padx=(2, 0))
        Button(self, text="▶", command=lambda: self._shift(+1),
               bg=CLR["surface"], fg=CLR["muted"], relief=FLAT,
               font=FONT_SM, cursor="hand2", padx=3, pady=2, bd=0,
               activebackground=CLR["bg"]).pack(side=LEFT)

    def _shift(self, delta):
        self._date += timedelta(days=delta)
        self._var.set(self._date.strftime("%d/%m/%Y"))

    def _parse(self, event=None):
        txt = self._var.get().strip()
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                self._date = datetime.strptime(txt, fmt).date()
                self._var.set(self._date.strftime("%d/%m/%Y"))
                return
            except ValueError:
                pass
        self._var.set(self._date.strftime("%d/%m/%Y"))

    def get(self) -> date:
        self._parse()
        return self._date

    def set(self, d: date):
        self._date = d
        self._var.set(d.strftime("%d/%m/%Y"))


# ──────────────────────────────────────────────────────────
#  APP CHÍNH
# ──────────────────────────────────────────────────────────
class TimeAttendanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mitapro  —  Quản lý RFID")
        self.root.geometry("1280x800")
        self.root.configure(bg=CLR["bg"])
        self.root.minsize(1000, 640)

        self._build_header()
        self._build_notebook()
        self._build_log()

        # State
        self.current_data   = []
        self.delete_list    = []
        self._attendance_records = []
        self._auto_fetch_ran_times = set()  # set các mốc giờ đã chạy hôm nay
        self._last_checked_date = date.today()
        self._auto_fetch_enabled = True     # flag bật/tắt auto-fetch

        # ── FIX NGÀY QUA ĐÊM ──────────────────────────────────────────
        # _view_date: ngày đang hiển thị trên tab chấm công.
        # KHÔNG cache giá trị date.today() tại đây — luôn tính lại
        # trong _get_view_date() để tránh sai khi app chạy qua đêm.
        self._view_date = date.today()
        # Flag: True khi người dùng chủ động chọn ngày khác hôm nay.
        # Khi False, _view_date sẽ tự cập nhật về date.today() thực.
        self._view_date_user_set = False
        # ──────────────────────────────────────────────────────────────

        self.load_employee_table()
        self.entry_rfid.focus_set()
        self._schedule_auto_fetch()

    # ═══════════════════════════════════════════
    #  HELPER: LẤY NGÀY XEM HIỆN TẠI (AN TOÀN QUA ĐÊM)
    # ═══════════════════════════════════════════
    def _get_view_date(self) -> date:
        """
        Trả về ngày đang xem.
        Nếu người dùng chưa chủ động chọn ngày riêng (_view_date_user_set=False),
        luôn trả về date.today() thực tế tại thời điểm gọi.
        Điều này đảm bảo khi app chạy qua đêm sang ngày mới,
        tab chấm công tự động hiển thị đúng ngày hôm nay.
        """
        if not self._view_date_user_set:
            real_today = date.today()
            if self._view_date != real_today:
                # Ngày đã lỗi thời (app chạy qua đêm) → cập nhật về hôm nay
                self._view_date = real_today
                self._view_date_var.set(self._fmt_nav_date(real_today))
                self._nav_date_entry.set(real_today)
        return self._view_date

    # ═══════════════════════════════════════════
    #  HEADER
    # ═══════════════════════════════════════════
    def _build_header(self):
        hdr = Frame(self.root, bg=CLR["sidebar_hdr"], pady=0)
        hdr.pack(side=TOP, fill=X)

        title_frame = Frame(hdr, bg=CLR["sidebar_hdr"])
        title_frame.pack(side=LEFT, padx=18, pady=10)
        Label(title_frame, text="⬡", font=("Segoe UI Emoji", 18),
              bg=CLR["sidebar_hdr"], fg=CLR["primary"]).pack(side=LEFT, padx=(0, 8))
        Label(title_frame, text="Mitapro", font=(FONT_FAMILY, 14, "bold"),
              bg=CLR["sidebar_hdr"], fg="#FFFFFF").pack(side=LEFT)
        Label(title_frame, text="  RFID Manager", font=(FONT_FAMILY, 11),
              bg=CLR["sidebar_hdr"], fg="#94A3B8").pack(side=LEFT)

        btn_frame = Frame(hdr, bg=CLR["sidebar_hdr"])
        btn_frame.pack(side=RIGHT, padx=14, pady=8)

        self.btn_update = styled_button(
            btn_frame, "⟳  Cập nhật từ máy",
            command=self.on_update_click, style="primary", padx=16, pady=6
        )
        self.btn_update.pack(side=LEFT, padx=(0, 8))

        self.btn_reload = styled_button(
            btn_frame, "↺  Tải lại file",
            command=self.load_employee_table, style="ghost", padx=14, pady=6
        )
        self.btn_reload.pack(side=LEFT)

        self.status_bar = Frame(self.root, bg=CLR["primary"], height=3)
        self.status_bar.pack(fill=X)

        self.status_label_frame = Frame(self.root, bg=CLR["surface"],
                                        pady=5, padx=16)
        self.status_label_frame.pack(fill=X)

        self.status_var = StringVar(value="Sẵn sàng.")
        self._status_dot = Label(self.status_label_frame, text="●",
                                 font=(FONT_FAMILY, 9), fg=CLR["success"],
                                 bg=CLR["surface"])
        self._status_dot.pack(side=LEFT, padx=(0, 5))
        Label(self.status_label_frame, textvariable=self.status_var,
              font=FONT_SM, bg=CLR["surface"], fg=CLR["muted"]
              ).pack(side=LEFT)

        self._ts_label = Label(self.status_label_frame, text="",
                               font=FONT_SM, bg=CLR["surface"],
                               fg=CLR["muted"])
        self._ts_label.pack(side=RIGHT, padx=8)
        self._tick()

    def _tick(self):
        self._ts_label.config(text=datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))
        self.root.after(1000, self._tick)

    # ═══════════════════════════════════════════
    #  NOTEBOOK (tabs)
    # ═══════════════════════════════════════════
    def _build_notebook(self):
        style = Style()
        style.configure("App.TNotebook",
                         background=CLR["bg"], borderwidth=0)
        style.configure("App.TNotebook.Tab",
                         font=FONT_BOLD, padding=(16, 8),
                         background=CLR["bg"],
                         foreground=CLR["muted"])
        style.map("App.TNotebook.Tab",
                  background=[("selected", CLR["surface"])],
                  foreground=[("selected", CLR["primary"])],
                  expand=[("selected", [1, 1, 1, 0])])

        self.notebook = Notebook(self.root, style="App.TNotebook")
        self.notebook.pack(side=TOP, fill=BOTH, expand=True,
                           padx=12, pady=(8, 0))

        tab1 = Frame(self.notebook, bg=CLR["bg"])
        self.notebook.add(tab1, text="👥  Nhân viên & RFID")
        self._build_rfid_tab(tab1)

        tab2 = Frame(self.notebook, bg=CLR["bg"])
        self.notebook.add(tab2, text="📋  Dữ liệu chấm công")
        self._build_attendance_tab(tab2)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ═══════════════════════════════════════════
    #  TAB 1: RFID
    # ═══════════════════════════════════════════
    def _build_rfid_tab(self, parent):
        body = Frame(parent, bg=CLR["bg"])
        body.pack(fill=BOTH, expand=True, padx=0, pady=(8, 0))
        self._build_left_panel(body)
        self._build_right_panel(body)

    def _build_left_panel(self, parent):
        lp = Frame(parent, bg=CLR["bg"])
        lp.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))

        title_bar = Frame(lp, bg=CLR["surface"], padx=12, pady=8)
        title_bar.pack(fill=X)
        Label(title_bar, text="👥  Danh sách nhân viên",
              font=FONT_LG, bg=CLR["surface"], fg=CLR["text"]
              ).pack(side=LEFT)
        Label(title_bar,
              text="Nhấn  ＋  trên mỗi dòng để thêm vào danh sách xóa",
              font=FONT_SM, bg=CLR["surface"], fg=CLR["muted"]
              ).pack(side=RIGHT)

        self.emp_table = EmployeeTable(lp, on_add_row=self._add_to_delete_list)
        self.emp_table.pack(fill=BOTH, expand=True)

    def _build_right_panel(self, parent):
        rp = Frame(parent, bg=CLR["bg"], width=420)
        rp.pack(side=RIGHT, fill=BOTH, expand=False)
        rp.pack_propagate(False)

        rfid_card = Frame(rp, bg=CLR["surface"], padx=14, pady=12)
        rfid_card.pack(fill=X)

        Label(rfid_card, text="Quét / Nhập RFID",
              font=FONT_LG, bg=CLR["surface"], fg=CLR["text"]
              ).pack(anchor=W, pady=(0, 6))
        Label(rfid_card, text="Nhập mã RFID rồi nhấn  Enter  hoặc nút Thêm",
              font=FONT_SM, bg=CLR["surface"], fg=CLR["muted"]
              ).pack(anchor=W, pady=(0, 8))

        ir = Frame(rfid_card, bg=CLR["surface"])
        ir.pack(fill=X)

        ef = Frame(ir, bg=CLR["primary"], padx=1, pady=1)
        ef.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        inner = Frame(ef, bg=CLR["surface"])
        inner.pack(fill=X)
        self.entry_rfid = Entry(
            inner, font=(FONT_FAMILY, 12), relief=FLAT,
            bg=CLR["surface"], fg=CLR["text"],
            insertbackground=CLR["primary"]
        )
        self.entry_rfid.pack(fill=X, padx=8, pady=6)
        self.entry_rfid.bind("<Return>",   self.on_rfid_enter)
        self.entry_rfid.bind("<KP_Enter>", self.on_rfid_enter)

        self.btn_add_rfid = styled_button(
            ir, "＋  Thêm", command=self.on_rfid_enter,
            style="primary", padx=14, pady=8
        )
        self.btn_add_rfid.pack(side=LEFT)

        self.lbl_rfid_status = Label(
            rfid_card, text="", font=FONT_SM,
            bg=CLR["surface"], fg=CLR["success"],
            wraplength=380, justify=LEFT, anchor=W
        )
        self.lbl_rfid_status.pack(fill=X, pady=(6, 0))

        dl_card = Frame(rp, bg=CLR["surface"], padx=14, pady=10)
        dl_card.pack(fill=BOTH, expand=True, pady=(8, 0))

        dl_hdr = Frame(dl_card, bg=CLR["surface"])
        dl_hdr.pack(fill=X, pady=(0, 6))
        Label(dl_hdr, text="🗑  Danh sách MST sẽ xóa",
              font=FONT_LG, bg=CLR["surface"], fg=CLR["text"]
              ).pack(side=LEFT)
        self.lbl_count = Label(dl_hdr, text="0 mục",
                               font=FONT_SM, bg="#FEF2F2",
                               fg=CLR["danger"], padx=8, pady=2)
        self.lbl_count.pack(side=RIGHT)

        st = Style()
        st.configure("Del.Treeview",
                      font=FONT_MONO_SM, rowheight=26,
                      background=CLR["surface"],
                      fieldbackground=CLR["surface"],
                      foreground=CLR["text"], borderwidth=0)
        st.configure("Del.Treeview.Heading",
                      font=FONT_BOLD,
                      background="#FEF2F2", foreground=CLR["danger"],
                      relief=FLAT, padding=(4, 5))
        st.map("Del.Treeview",
               background=[("selected", "#FECACA")],
               foreground=[("selected", CLR["danger_dk"])])

        tf2 = Frame(dl_card, bg=CLR["border"], padx=1, pady=1)
        tf2.pack(fill=BOTH, expand=True)

        self.tree_mst = Treeview(
            tf2, columns=("stt", "mst", "rfid"),
            show="headings", style="Del.Treeview"
        )
        self.tree_mst.heading("stt",  text="#")
        self.tree_mst.heading("mst",  text="MST")
        self.tree_mst.heading("rfid", text="RFID")
        self.tree_mst.column("stt",  width=30,  anchor="center", stretch=False)
        self.tree_mst.column("mst",  width=160, minwidth=80)
        self.tree_mst.column("rfid", width=160, minwidth=80)

        vsb2 = Scrollbar(tf2, orient="vertical", command=self.tree_mst.yview)
        self.tree_mst.configure(yscrollcommand=vsb2.set)
        self.tree_mst.pack(side=LEFT, fill=BOTH, expand=True)
        vsb2.pack(side=RIGHT, fill=Y)

        ar = Frame(dl_card, bg=CLR["surface"])
        ar.pack(fill=X, pady=(8, 0))

        styled_button(ar, "✕  Bỏ dòng chọn",
                      command=self.on_remove_selected,
                      style="muted", padx=10, pady=5
                      ).pack(side=LEFT, padx=(0, 6))
        styled_button(ar, "⊘  Xóa tất cả",
                      command=self.on_clear_list,
                      style="muted", padx=10, pady=5
                      ).pack(side=LEFT)

        self.btn_delete = Button(
            dl_card,
            text="⚠   Xóa tất cả MST trên MỌI MÁY",
            bg=CLR["danger"], fg="#FFFFFF",
            activebackground=CLR["danger_dk"], activeforeground="#FFFFFF",
            font=(FONT_FAMILY, 11, "bold"),
            relief=FLAT, bd=0, cursor="hand2",
            padx=14, pady=10,
            command=self.on_delete_click,
            state=DISABLED
        )
        self.btn_delete.pack(fill=X, pady=(10, 0))

    # ═══════════════════════════════════════════
    #  TAB 2: CHẤM CÔNG
    # ═══════════════════════════════════════════
    def _build_attendance_tab(self, parent):

        # ── Dòng 1: Navigator ngày ──────────────────────────────────
        nav_bar = Frame(parent, bg=CLR["surface"], padx=14, pady=8)
        nav_bar.pack(fill=X, pady=(8, 0))

        Label(nav_bar, text="📅", font=("Segoe UI Emoji", 14),
              bg=CLR["surface"]).pack(side=LEFT, padx=(0, 6))
        Label(nav_bar, text="Xem theo ngày",
              font=FONT_LG, bg=CLR["surface"], fg=CLR["text"]
              ).pack(side=LEFT, padx=(0, 16))

        self.btn_day_prev = Button(
            nav_bar, text="◀",
            command=self._nav_prev_day,
            bg=CLR["primary"], fg="#FFFFFF",
            activebackground=CLR["primary_dk"], activeforeground="#FFFFFF",
            font=FONT_BOLD, relief=FLAT, cursor="hand2",
            padx=10, pady=5, bd=0,
        )
        self.btn_day_prev.pack(side=LEFT, padx=(0, 4))

        self._view_date_var = StringVar(value=self._fmt_nav_date(date.today()))
        self._lbl_nav_date = Label(
            nav_bar, textvariable=self._view_date_var,
            font=(FONT_FAMILY, 13, "bold"),
            bg=CLR["primary"], fg="#FFFFFF",
            padx=18, pady=5, cursor="hand2",
        )
        self._lbl_nav_date.pack(side=LEFT)
        self._lbl_nav_date.bind("<ButtonRelease-1>",
                                lambda e: self._nav_go_today())

        self.btn_day_next = Button(
            nav_bar, text="▶",
            command=self._nav_next_day,
            bg=CLR["primary"], fg="#FFFFFF",
            activebackground=CLR["primary_dk"], activeforeground="#FFFFFF",
            font=FONT_BOLD, relief=FLAT, cursor="hand2",
            padx=10, pady=5, bd=0,
        )
        self.btn_day_next.pack(side=LEFT, padx=(4, 16))

        for lbl, fn in (
            ("Hôm nay",  self._nav_go_today),
            ("Hôm qua",  self._nav_go_yesterday),
        ):
            Button(
                nav_bar, text=lbl, command=fn,
                bg=CLR["bg"], fg=CLR["text"],
                activebackground=CLR["border"], activeforeground=CLR["text"],
                font=FONT_SM, relief=FLAT, cursor="hand2",
                padx=10, pady=5, bd=0,
            ).pack(side=LEFT, padx=(0, 4))

        Frame(nav_bar, bg=CLR["border"], width=1, height=28
              ).pack(side=LEFT, padx=10)

        Label(nav_bar, text="Đến ngày:", font=FONT_SM,
              bg=CLR["surface"], fg=CLR["text_muted"]
              ).pack(side=LEFT, padx=(0, 4))
        self._nav_date_entry = DateEntry(nav_bar, initial=date.today(),
                                         bg=CLR["surface"])
        self._nav_date_entry.pack(side=LEFT, padx=(0, 6))
        styled_button(nav_bar, "Xem", command=self._nav_go_custom,
                      style="ghost", padx=10, pady=4,
                      font=FONT_SM).pack(side=LEFT)

        self.lbl_att_summary = Label(
            nav_bar, text="", font=FONT_SM,
            bg=CLR["surface"], fg=CLR["muted"]
        )
        self.lbl_att_summary.pack(side=RIGHT, padx=(0, 4))

        # ── Dòng 2: Action toolbar ───────────────────────────────────
        toolbar = Frame(parent, bg="#F8FAFC", padx=14, pady=8)
        toolbar.pack(fill=X)

        Label(toolbar, text="Chọn máy:", font=FONT_SM,
              bg="#F8FAFC", fg=CLR["text_muted"]
              ).pack(side=LEFT, padx=(0, 4))
        
        self.cbo_device = Combobox(toolbar, state="readonly", font=FONT_SM, width=17)
        device_options = ["Tất cả các máy"]
        for ip in LISTS_DEVICE_IP:
            _, ten = _ip_to_ten_may(ip)
            device_options.append(f"{ten} ({ip})")
        self.cbo_device["values"] = device_options
        self.cbo_device.current(0)
        self.cbo_device.pack(side=LEFT, padx=(0, 12))

        Label(toolbar, text="Từ ngày:", font=FONT_SM,
              bg="#F8FAFC", fg=CLR["text_muted"]
              ).pack(side=LEFT, padx=(0, 4))
        first_of_month = date.today().replace(day=1)
        self._date_from = DateEntry(toolbar, initial=first_of_month,
                                    bg="#F8FAFC")
        self._date_from.pack(side=LEFT, padx=(0, 8))

        Label(toolbar, text="→", font=FONT_BOLD,
              bg="#F8FAFC", fg=CLR["muted"]
              ).pack(side=LEFT, padx=(0, 8))

        Label(toolbar, text="Đến ngày:", font=FONT_SM,
              bg="#F8FAFC", fg=CLR["text_muted"]
              ).pack(side=LEFT, padx=(0, 4))
        self._date_to = DateEntry(toolbar, initial=date.today(),
                                   bg="#F8FAFC")
        self._date_to.pack(side=LEFT, padx=(0, 12))

        self.btn_fetch = styled_button(
            toolbar, "⬇  Lấy từ máy ZK",
            command=self.on_fetch_attendance,
            style="attend", padx=14, pady=5
        )
        self.btn_fetch.pack(side=LEFT, padx=(0, 6))

        self.btn_fetch_quick = Button(
            toolbar,
            text="⚡  Hôm qua & Hôm nay",
            command=self.on_fetch_quick,
            bg="#7C3AED", fg="#FFFFFF",
            activebackground="#6D28D9", activeforeground="#FFFFFF",
            font=FONT_BOLD, relief=FLAT, cursor="hand2",
            padx=12, pady=5, bd=0,
        )
        self.btn_fetch_quick.pack(side=LEFT, padx=(0, 6))

        self.btn_save_db = styled_button(
            toolbar, "🗄  Lưu vào DB",
            command=self.on_save_db,
            style="primary", padx=12, pady=5
        )
        self.btn_save_db.pack(side=LEFT, padx=(0, 6))
        self.btn_save_db.config(state=DISABLED)

        styled_button(
            toolbar, "🔌  Test DB",
            command=self.on_test_db,
            style="ghost", padx=10, pady=5,
            font=FONT_SM
        ).pack(side=LEFT, padx=(0, 6))

        self.btn_export_csv = styled_button(
            toolbar, "📥  Xuất CSV",
            command=self.on_export_csv,
            style="ghost", padx=10, pady=5,
            font=FONT_SM
        )
        self.btn_export_csv.pack(side=LEFT, padx=(0, 6))
        self.btn_export_csv.config(state=DISABLED)

        self._lbl_auto_badge = Label(
            toolbar,
            text="⏰ Auto 07:31",
            font=FONT_SM,
            bg="#ECFDF5", fg=CLR["success"],
            padx=8, pady=3,
            relief=FLAT
        )
        self._lbl_auto_badge.pack(side=LEFT, padx=(8, 0))

        self.btn_toggle_auto = Button(
            toolbar, text="Tắt Auto", command=self.on_toggle_auto,
            bg="#FEE2E2", fg=CLR["danger"],
            activebackground="#FECACA", activeforeground=CLR["danger_dk"],
            font=FONT_SM, relief=FLAT, cursor="hand2",
            padx=8, pady=3, bd=0
        )
        self.btn_toggle_auto.pack(side=LEFT, padx=(4, 0))

        self.btn_config_auto = Button(
            toolbar, text="⚙", command=self.on_config_auto,
            bg="#F1F5F9", fg=CLR["text"],
            activebackground="#E2E8F0", activeforeground=CLR["text"],
            font=FONT_SM, relief=FLAT, cursor="hand2",
            padx=6, pady=3, bd=0
        )
        self.btn_config_auto.pack(side=LEFT, padx=(4, 0))

        self._update_auto_badge()

        # ── Bảng kết quả ──
        self.att_table = AttendanceTable(parent, bg=CLR["bg"])
        self.att_table.pack(fill=BOTH, expand=True, padx=0, pady=(4, 0))

    # ═══════════════════════════════════════════
    #  LOG PANEL
    # ═══════════════════════════════════════════
    def _build_log(self):
        log_wrap = Frame(self.root, bg=CLR["log_bg"])
        log_wrap.pack(side=BOTTOM, fill=X)

        hdr = Frame(log_wrap, bg=CLR["log_bg"], padx=12, pady=4)
        hdr.pack(fill=X)
        Label(hdr, text="▸  Nhật ký hoạt động",
              font=(FONT_FAMILY, 9, "bold"),
              bg=CLR["log_bg"], fg="#475569").pack(side=LEFT)

        btn_clear_log = Button(
            hdr, text="Xóa log", command=lambda: self.txt_log.delete("1.0", END),
            bg=CLR["log_bg"], fg="#475569", relief=FLAT,
            font=FONT_SM, cursor="hand2", padx=4, pady=0, bd=0,
            activebackground=CLR["log_bg"], activeforeground=CLR["muted"]
        )
        btn_clear_log.pack(side=RIGHT)

        self.txt_log = Text(
            log_wrap, height=5, font=FONT_MONO_SM,
            bg=CLR["log_bg"], fg=CLR["log_fg"],
            relief=FLAT, bd=0, padx=12, pady=4,
            wrap=WORD, insertbackground=CLR["log_fg"],
            selectbackground="#334155"
        )
        self.txt_log.pack(fill=X)

        self.txt_log.tag_configure("ts",   foreground="#475569")
        self.txt_log.tag_configure("ok",   foreground="#4ADE80")
        self.txt_log.tag_configure("err",  foreground="#F87171")
        self.txt_log.tag_configure("warn", foreground="#FCD34D")
        self.txt_log.tag_configure("info", foreground=CLR["log_fg"])

    # ═══════════════════════════════════════════
    #  HELPERS
    # ═══════════════════════════════════════════
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.insert(END, f"[{ts}]  ", "ts")
        if any(x in msg for x in ("✅", "✓", "xong", "Hoàn tất")):
            tag = "ok"
        elif any(x in msg for x in ("❌", "Lỗi", "LỖI", "⛔")):
            tag = "err"
        elif any(x in msg for x in ("⚠", "không", "Không")):
            tag = "warn"
        else:
            tag = "info"
        self.txt_log.insert(END, msg + "\n", tag)
        self.txt_log.see(END)

    def set_status(self, msg, color=None):
        self.status_var.set(msg)
        dot_color = color or CLR["success"]
        self._status_dot.config(fg=dot_color)
        self.root.update_idletasks()

    def _in_list_msts(self):
        return {item["mst"] for item in self.delete_list}

    def _refresh_delete_button(self):
        has = bool(self.delete_list)
        self.btn_delete.config(state=NORMAL if has else DISABLED,
                               bg=CLR["danger"] if has else "#9CA3AF")
        n = len(self.delete_list)
        self.lbl_count.config(
            text=f"{n} mục",
            bg="#FEF2F2" if n else CLR["bg"],
            fg=CLR["danger"] if n else CLR["muted"]
        )

    def _rebuild_mst_tree(self):
        self.tree_mst.delete(*self.tree_mst.get_children())
        for i, item in enumerate(self.delete_list, start=1):
            self.tree_mst.insert("", END, values=(i, item["mst"], item["rfid"]))
        self._refresh_delete_button()
        self.emp_table.mark_in_list(self._in_list_msts())

    def disable_actions(self):
        for w in (self.btn_update, self.btn_reload,
                  self.btn_add_rfid, self.btn_delete,
                  self.btn_fetch, self.btn_fetch_quick):
            w.config(state=DISABLED)
        self.cbo_device.config(state=DISABLED)
        self.entry_rfid.config(state=DISABLED)
        self.btn_export_csv.config(state=DISABLED)
        self.btn_save_db.config(state=DISABLED)
        self.set_status("Đang xử lý...", CLR["warning"])

    def enable_actions(self):
        for w in (self.btn_update, self.btn_reload,
                  self.btn_add_rfid, self.btn_fetch, self.btn_fetch_quick):
            w.config(state=NORMAL)
        self.cbo_device.config(state="readonly")
        self.entry_rfid.config(state=NORMAL)
        self._refresh_delete_button()
        if self._attendance_records:
            self.btn_export_csv.config(state=NORMAL)
            self.btn_save_db.config(state=NORMAL)
        self.set_status("Sẵn sàng.", CLR["success"])

    def _set_rfid_status(self, msg, kind="ok"):
        colors = {
            "ok":   CLR["success"],
            "warn": CLR["warning"],
            "err":  CLR["danger"],
            "info": CLR["muted"],
        }
        self.lbl_rfid_status.config(text=msg, fg=colors.get(kind, CLR["muted"]))

    def _rfid_map(self):
        return {mst: rfid for mst, rfid in self.current_data}

    # ═══════════════════════════════════════════
    #  LOGIC RFID
    # ═══════════════════════════════════════════
    def _add_to_delete_list(self, mst, rfid):
        if mst in self._in_list_msts():
            self._set_rfid_status(f"⚠  MST {mst} đã có trong danh sách.", "warn")
            return False
        self.delete_list.append({"mst": mst, "rfid": rfid})
        self._rebuild_mst_tree()
        self._set_rfid_status(f"✅  MST {mst}  (RFID {rfid}) — đã thêm vào DS xóa.", "ok")
        self.log(f"Thêm vào DS xóa: MST {mst} / RFID {rfid}")
        return True

    def load_employee_table(self):
        self.current_data = read_all_rfid_file(MERGED_FILE)
        self.emp_table.load(self.current_data)
        self.emp_table.mark_in_list(self._in_list_msts())
        self.set_status(f"Đã tải {len(self.current_data)} nhân viên từ {MERGED_FILE}.")
        self.log(f"Đọc xong {MERGED_FILE} — {len(self.current_data)} dòng.")

    def on_update_click(self):
        if ZK is None:
            messagebox.showerror("Thiếu thư viện",
                                 "Chưa cài 'zk'.\nHãy chạy:  pip install zk")
            return
        def worker():
            try:
                self.set_status("Đang kết nối và cập nhật...", CLR["warning"])
                self.disable_actions()
                update_list_rfid(self.log)
                self.load_employee_table()
                self.set_status("Cập nhật hoàn tất.")
            except Exception as e:
                self.log(f"❌ Lỗi cập nhật: {e}")
                self.set_status("Lỗi cập nhật.", CLR["danger"])
            finally:
                self.enable_actions()
        threading.Thread(target=worker, daemon=True).start()

    def on_rfid_enter(self, event=None):
        rfid = self.entry_rfid.get().strip()
        self.entry_rfid.delete(0, END)
        if not rfid:
            return
        existing_rfids = {item["rfid"] for item in self.delete_list}
        if rfid in existing_rfids:
            self._set_rfid_status(f"⚠  RFID {rfid} đã có trong danh sách.", "warn")
            self.entry_rfid.focus_set()
            return
        mst = find_mst_for_rfid(rfid, self.current_data)
        if mst:
            self._add_to_delete_list(mst, rfid)
        else:
            self._set_rfid_status(f"❌  Không tìm thấy MST cho RFID: {rfid}", "err")
            self.log(f"Không tìm thấy MST cho RFID: {rfid}")
        self.entry_rfid.focus_set()

    def on_remove_selected(self):
        selected = self.tree_mst.selection()
        if not selected:
            return
        indices = {int(self.tree_mst.item(iid, "values")[0]) - 1
                   for iid in selected
                   if self.tree_mst.item(iid, "values")}
        self.delete_list = [item for i, item in enumerate(self.delete_list)
                            if i not in indices]
        self._rebuild_mst_tree()
        self._set_rfid_status("Đã bỏ dòng đã chọn.", "info")

    def on_clear_list(self):
        if not self.delete_list:
            return
        if messagebox.askyesno("Xác nhận", "Xóa toàn bộ danh sách MST?"):
            self.delete_list.clear()
            self._rebuild_mst_tree()
            self._set_rfid_status("Đã xóa toàn bộ danh sách.", "info")

    def on_delete_click(self):
        if not self.delete_list:
            messagebox.showinfo("Thông báo", "Không có MST nào để xóa.")
            return
        msts = [item["mst"] for item in self.delete_list]
        mcount = len(msts)
        preview = ", ".join(msts[:5]) + (f"\n... và {mcount-5} MST khác" if mcount > 5 else "")
        if not messagebox.askyesno(
            "⚠  Xác nhận xóa",
            f"Bạn chắc chắn muốn xóa {mcount} MST trên TẤT CẢ MÁY?\n\n{preview}"
        ):
            return

        def worker():
            try:
                self.set_status(f"Đang xóa {mcount} MST trên các máy...", CLR["danger"])
                self.disable_actions()
                deleted = delete_user_by_mst_on_all_devices(msts, self.log)
                self.set_status(f"Hoàn tất — đã xóa {deleted} bản ghi.")
                self.delete_list.clear()
                self._rebuild_mst_tree()
                self.load_employee_table()
            except Exception as e:
                self.log(f"❌ Lỗi xóa: {e}")
                self.set_status("Lỗi xóa.", CLR["danger"])
            finally:
                self.enable_actions()

        threading.Thread(target=worker, daemon=True).start()

    def on_config_auto(self):
        top = Toplevel(self.root)
        top.title("Cấu hình giờ Auto")
        top.geometry("320x380")
        top.configure(bg=CLR["bg"])
        top.grab_set()
        top.transient(self.root)
        
        lbl = Label(top, text="Các mốc giờ tự động lấy (HH:MM):", font=FONT_BOLD, bg=CLR["bg"])
        lbl.pack(pady=(12, 4), padx=12, anchor=W)
        
        frame_list = Frame(top, bg=CLR["bg"])
        frame_list.pack(fill=BOTH, expand=True, padx=12, pady=4)
        
        lb = Listbox(frame_list, font=FONT_MONO, relief=FLAT)
        lb.pack(side=LEFT, fill=BOTH, expand=True)
        vsb = Scrollbar(frame_list, orient="vertical", command=lb.yview)
        vsb.pack(side=RIGHT, fill=Y)
        lb.configure(yscrollcommand=vsb.set)
        
        for t in sorted(AUTO_FETCH_TIMES):
            lb.insert(END, t)
            
        frame_add = Frame(top, bg=CLR["bg"])
        frame_add.pack(fill=X, padx=12, pady=8)
        
        var_time = StringVar()
        ent_time = Entry(frame_add, textvariable=var_time, font=FONT_MONO, width=10, relief=FLAT)
        ent_time.pack(side=LEFT, padx=(0, 8))
        
        def _add():
            t_str = var_time.get().strip()
            try:
                h, m = map(int, t_str.split(":"))
                new_t = f"{h:02d}:{m:02d}"
                items = lb.get(0, END)
                if new_t not in items:
                    lb.insert(END, new_t)
                var_time.set("")
            except:
                messagebox.showerror("Lỗi định dạng", "Vui lòng nhập giờ định dạng HH:MM (vd: 07:30)", parent=top)
                
        btn_add = styled_button(frame_add, "Thêm", _add, style="primary", padx=8, pady=3, font=FONT_SM)
        btn_add.pack(side=LEFT)
        
        def _del():
            sel = lb.curselection()
            if sel:
                lb.delete(sel[0])
                
        btn_del = styled_button(frame_add, "Xóa", _del, style="danger", padx=8, pady=3, font=FONT_SM)
        btn_del.pack(side=RIGHT)
        
        frame_btn = Frame(top, bg=CLR["bg"])
        frame_btn.pack(fill=X, padx=12, pady=(4, 12))
        
        def _save():
            global AUTO_FETCH_TIMES
            items = lb.get(0, END)
            AUTO_FETCH_TIMES = sorted(list(items))
            save_auto_fetch_times()
            self._last_checked_date = None # Force reset
            self._update_auto_badge()
            self.log(f"✅ Cập nhật danh sách giờ Auto: {', '.join(AUTO_FETCH_TIMES)}")
            top.destroy()
            
        btn_save = styled_button(frame_btn, "Lưu cấu hình", _save, style="success", padx=16, pady=5)
        btn_save.pack(fill=X)

    def on_toggle_auto(self):
        self._auto_fetch_enabled = not self._auto_fetch_enabled
        if self._auto_fetch_enabled:
            self.btn_toggle_auto.config(
                text="Tắt Auto", bg="#FEE2E2", fg=CLR["danger"],
                activebackground="#FECACA", activeforeground=CLR["danger_dk"]
            )
            self.log("✅ Đã BẬT chế độ tự động lấy dữ liệu.")
        else:
            self.btn_toggle_auto.config(
                text="Bật Auto", bg="#ECFDF5", fg=CLR["success"],
                activebackground="#D1FAE5", activeforeground="#065F46"
            )
            self.log("⚠ Đã TẮT chế độ tự động lấy dữ liệu.")
        self._update_auto_badge()

    def _update_auto_badge(self):
        """Cập nhật badge hiển thị trạng thái / giờ chạy tiếp theo."""
        now   = datetime.now()
        today = date.today()
        
        if getattr(self, "_last_checked_date", None) != today:
            self._auto_fetch_ran_times = set()
            self._last_checked_date = today
            
        enabled = getattr(self, "_auto_fetch_enabled", True)

        if not enabled:
            self._lbl_auto_badge.config(
                text="⏸ Tắt Auto",
                bg="#F3F4F6", fg=CLR["muted"]
            )
        else:
            # Tìm mốc giờ tiếp theo
            next_target = None
            all_targets = []
            for t_str in AUTO_FETCH_TIMES:
                try:
                    h, m = map(int, t_str.split(":"))
                    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    all_targets.append(t)
                except:
                    continue
            
            all_targets.sort()
            for t in all_targets:
                if now < t:
                    next_target = t
                    break
            
            if not next_target:
                # Đã qua hết các mốc hôm nay
                if AUTO_FETCH_TIMES:
                    self._lbl_auto_badge.config(
                        text=f"✅ Đã chạy xong hôm nay",
                        bg="#ECFDF5", fg=CLR["success"]
                    )
                else:
                    self._lbl_auto_badge.config(
                        text="Chưa cấu hình giờ Auto",
                        bg="#F3F4F6", fg=CLR["muted"]
                    )
            else:
                remaining = next_target - now
                h, rem = divmod(int(remaining.total_seconds()), 3600)
                m, s   = divmod(rem, 60)
                time_str = next_target.strftime("%H:%M")
                self._lbl_auto_badge.config(
                    text=f"⏰ Auto {time_str}  (còn {h:02d}:{m:02d}:{s:02d})",
                    bg="#EFF6FF", fg=CLR["primary"]
                )
        self.root.after(1000, self._update_auto_badge)

    # ═══════════════════════════════════════════
    #  TỰ ĐỘNG LẤY CHẤM CÔNG LÚC 07:31
    # ═══════════════════════════════════════════
    def _schedule_auto_fetch(self):
        """
        Kiểm tra mỗi 30 giây.
        Luôn gọi date.today() / datetime.now() tươi — không dùng biến đã cache —
        để tránh tính sai ngày khi app chạy qua đêm sang ngày mới.
        """
        now   = datetime.now()          # ← gọi tươi mỗi lần
        today = date.today()            # ← gọi tươi mỗi lần

        if getattr(self, "_last_checked_date", None) != today:
            self._auto_fetch_ran_times = set()
            self._last_checked_date = today

        enabled   = getattr(self, "_auto_fetch_enabled", True)

        if enabled:
            current_time_str = now.strftime("%H:%M")
            if current_time_str in AUTO_FETCH_TIMES and current_time_str not in self._auto_fetch_ran_times:
                self._auto_fetch_ran_times.add(current_time_str)
                self.log(f"⏰ Tự động lấy chấm công lúc {now:%H:%M:%S} ...")
                # Lấy hôm qua + hôm nay dựa trên today thực tế tại thời điểm này
                self._run_auto_fetch(today - timedelta(days=1), today)

        self.root.after(30_000, self._schedule_auto_fetch)

    def _run_auto_fetch(self, d_from: date, d_to: date):
        """Chạy fetch ngầm; tự động lưu CSV, cập nhật bảng và trạng thái."""
        if ZK is None:
            self.log("⚠ Bỏ qua auto-fetch: chưa cài thư viện 'zk'.")
            return

        self.root.after(0, lambda: self._date_from.set(d_from))
        self.root.after(0, lambda: self._date_to.set(d_to))
        self.root.after(0, lambda: self.notebook.select(1))
        self.root.after(0, lambda: self.att_table.clear())
        self.root.after(0, lambda: self.lbl_att_summary.config(
            text="⏰ Đang tự động lấy dữ liệu..."))

        def worker():
            try:
                self.set_status(
                    f"[Auto] Đang lấy chấm công {d_from:%d/%m/%Y}–{d_to:%d/%m/%Y} ...",
                    CLR["warning"]
                )
                records = fetch_attendance_all_devices(d_from, d_to, self.log)
                self._attendance_records = records

                unique_msts = len({r["mst"] for r in records})
                summary = (f"⏰ Auto  |  {len(records)} bản ghi  |  "
                           f"{unique_msts} nhân viên  |  "
                           f"{d_from:%d/%m/%Y} – {d_to:%d/%m/%Y}")

                rfid_map = self._rfid_map()
                self.root.after(0, lambda: self.att_table.load(records, rfid_map))
                self.root.after(0, lambda: self.lbl_att_summary.config(
                    text=summary, fg=CLR["success"]))
                self.root.after(0, lambda: self.set_status(
                    f"[Auto] Đã lấy {len(records)} bản ghi chấm công."))

                self._auto_save_csv(records, rfid_map, d_from, d_to)
                self._auto_save_db(records, rfid_map)

            except Exception as e:
                self.log(f"❌ Lỗi auto-fetch: {e}")
                self.set_status("Lỗi auto-fetch.", CLR["danger"])
                self.root.after(0, lambda: self.lbl_att_summary.config(
                    text="❌ Auto-fetch thất bại.", fg=CLR["danger"]))

        threading.Thread(target=worker, daemon=True).start()

    def _auto_save_csv(self, records, rfid_map, d_from: date, d_to: date):
        """Lưu CSV tự động vào thư mục auto_chamcong/."""
        WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư",
                       "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        try:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "auto_chamcong")
            os.makedirs(out_dir, exist_ok=True)
            filename = f"auto_{d_from:%d%m%Y}_{d_to:%d%m%Y}.csv"
            filepath = os.path.join(out_dir, filename)

            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["STT", "MST", "RFID", "Ngày", "Giờ",
                                  "Thứ", "IP"])
                for i, r in enumerate(records, 1):
                    ts = r["timestamp"]
                    writer.writerow([
                        i,
                        r["mst"],
                        rfid_map.get(r["mst"], ""),
                        ts.strftime("%d/%m/%Y"),
                        ts.strftime("%H:%M:%S"),
                        WEEKDAYS_VI[ts.weekday()],
                        r["ip"],
                    ])
            self.log(f"✅ Auto-CSV đã lưu → {filepath}  ({len(records)} dòng)")
        except Exception as e:
            self.log(f"⚠ Không lưu được auto-CSV: {e}")

    def _auto_save_db(self, records, rfid_map):
        """Lưu tự động vào SQL Server sau auto-fetch."""
        if pyodbc is None:
            self.log("⚠ Bỏ qua lưu DB: chưa cài 'pyodbc'.")
            return
        try:
            inserted = save_attendance_to_db(records, rfid_map, self.log)
            if inserted:
                self.root.after(0, lambda: self.set_status(
                    f"[Auto] Đã lưu {inserted} bản ghi vào SQL Server."
                ))
        except Exception as e:
            self.log(f"❌ Lỗi auto lưu DB: {e}")

    # ═══════════════════════════════════════════
    #  NAVIGATOR NGÀY — XEM DỮ LIỆU TRONG DB
    # ═══════════════════════════════════════════
    @staticmethod
    def _fmt_nav_date(d: date) -> str:
        WEEKDAYS_VI = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        thu = WEEKDAYS_VI[d.weekday()]
        today = date.today()            # ← gọi tươi, không cache
        if d == today:
            suffix = "  (Hôm nay)"
        elif d == today - timedelta(days=1):
            suffix = "  (Hôm qua)"
        else:
            suffix = ""
        return f"{thu}  {d:%d/%m/%Y}{suffix}"

    def _nav_go_date(self, d: date):
        """
        Đặt ngày xem và load dữ liệu từ DB.
        Cập nhật _view_date_user_set để phân biệt người dùng
        chủ động chọn ngày hay hệ thống tự điều chỉnh.
        """
        self._view_date = d
        # Nếu người dùng chọn ngày khác hôm nay thực tế → đánh dấu user_set
        # để hệ thống không tự override khi sang ngày mới
        self._view_date_user_set = (d != date.today())
        self._view_date_var.set(self._fmt_nav_date(d))
        self._nav_date_entry.set(d)
        self._load_db_for_date(d)

    def _nav_prev_day(self):
        self._nav_go_date(self._view_date - timedelta(days=1))

    def _nav_next_day(self):
        self._nav_go_date(self._view_date + timedelta(days=1))

    def _nav_go_today(self):
        """
        Về hôm nay — luôn dùng date.today() tươi,
        reset _view_date_user_set để hệ thống tự cập nhật khi qua đêm.
        """
        self._view_date_user_set = False        # ← reset: theo hôm nay thực
        self._nav_go_date(date.today())

    def _nav_go_yesterday(self):
        """
        Về hôm qua — đánh dấu user_set=True vì người dùng chủ động chọn,
        không để hệ thống tự override về hôm nay.
        """
        yesterday = date.today() - timedelta(days=1)
        self._view_date_user_set = True         # ← giữ nguyên hôm qua
        self._nav_go_date(yesterday)

    def _nav_go_custom(self):
        """Người dùng nhập ngày tùy ý → luôn đánh dấu user_set=True."""
        d = self._nav_date_entry.get()
        self._view_date_user_set = (d != date.today())
        self._nav_go_date(d)

    def _on_tab_changed(self, event=None):
        """
        Khi chuyển sang tab chấm công → load dữ liệu.

        FIX QUA ĐÊM: Không dùng self._view_date đã cache từ trước.
        Thay vào đó gọi _get_view_date() — hàm này tự so sánh với
        date.today() thực tế và cập nhật _view_date nếu app đã chạy
        qua đêm sang ngày mới (và người dùng chưa chủ động chọn ngày khác).
        """
        try:
            idx = self.notebook.index(self.notebook.select())
        except Exception:
            return
        if idx == 1:
            self._nav_go_date(self._get_view_date())

    def _load_db_for_date(self, d: date):
        """Đọc dữ liệu chấm công từ DB cho ngày d và hiển thị lên bảng."""
        if pyodbc is None:
            self.lbl_att_summary.config(
                text="⚠ Chưa cài pyodbc — không đọc được DB.",
                fg=CLR["warning"]
            )
            return

        self.att_table.clear()
        self.lbl_att_summary.config(
            text=f"Đang đọc DB ngày {d:%d/%m/%Y} ...",
            fg=CLR["muted"]
        )

        def worker():
            records = []
            try:
                tbl = DB_CONFIG["table"]
                sql = (
                    f"SELECT MaChamCong, NgayCham, GioCham, "
                    f"       KieuCham, NguonCham, MaSoMay, TenMay "
                    f"FROM [{tbl}] "
                    f"WHERE CAST(NgayCham AS DATE) = ? "
                    f"ORDER BY MaChamCong, GioCham"
                )
                with pyodbc.connect(SqlServerDB._build_conn_str(), timeout=10) as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, (d,))
                    for row in cursor.fetchall():
                        ma, ngay, gio, kieu, nguon, ma_may, ten_may = row
                        ts = gio if isinstance(gio, datetime) \
                             else datetime.combine(d, gio)
                        records.append({
                            "ip":        ten_may or "",
                            "mst":       str(ma),
                            "timestamp": ts,
                            "status":    kieu  if kieu  is not None else 255,
                            "punch":     nguon if nguon is not None else 4,
                        })

                unique  = len({r["mst"] for r in records})
                summary = (f"🗄 DB  |  {len(records)} bản ghi  |  "
                           f"{unique} nhân viên  |  {d:%d/%m/%Y}")
                rfid_map = self._rfid_map()
                self._attendance_records = records
                self.root.after(0, lambda: self.att_table.load(records, rfid_map))
                self.root.after(0, lambda: self.lbl_att_summary.config(
                    text=summary, fg=CLR["success"]))
                self.root.after(0, lambda: self.btn_export_csv.config(state=NORMAL))

            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self.lbl_att_summary.config(
                    text=f"❌ Lỗi đọc DB: {err}", fg=CLR["danger"]))
                self.log(f"❌ Lỗi đọc DB ngày {d:%d/%m/%Y}: {err}")

        threading.Thread(target=worker, daemon=True).start()

    def on_fetch_quick(self):
        """
        Lấy ngay chấm công hôm qua + hôm nay.
        Gọi date.today() tươi tại thời điểm bấm nút —
        đảm bảo đúng ngày dù app chạy qua đêm.
        """
        today     = date.today()                    # ← tươi tại thời điểm bấm
        yesterday = today - timedelta(days=1)
        self._date_from.set(yesterday)
        self._date_to.set(today)
        self._do_fetch(yesterday, today)

    # ═══════════════════════════════════════════
    #  LOGIC CHẤM CÔNG
    # ═══════════════════════════════════════════
    def on_fetch_attendance(self):
        if ZK is None:
            messagebox.showerror("Thiếu thư viện",
                                 "Chưa cài 'zk'.\nHãy chạy:  pip install zk")
            return
        d_from = self._date_from.get()
        d_to   = self._date_to.get()
        if d_from > d_to:
            messagebox.showwarning("Ngày không hợp lệ",
                                   "Ngày bắt đầu phải ≤ ngày kết thúc.")
            return
        self._do_fetch(d_from, d_to)

    def _do_fetch(self, d_from: date, d_to: date):
        """Lõi fetch chấm công — dùng chung cho nút thủ công và nút nhanh."""
        if ZK is None:
            messagebox.showerror("Thiếu thư viện",
                                 "Chưa cài 'zk'.\nHãy chạy:  pip install zk")
            return

        self.log(f"Bắt đầu lấy chấm công từ {d_from:%d/%m/%Y} → {d_to:%d/%m/%Y}")
        self.att_table.clear()
        self._attendance_records = []
        self.lbl_att_summary.config(text="Đang lấy dữ liệu...")

        sel_idx = self.cbo_device.current()
        target_ips = LISTS_DEVICE_IP if sel_idx <= 0 else [LISTS_DEVICE_IP[sel_idx - 1]]

        def worker():
            try:
                self.disable_actions()
                self.set_status(
                    f"Đang lấy chấm công {d_from:%d/%m/%Y}–{d_to:%d/%m/%Y} ...",
                    CLR["warning"]
                )
                records = fetch_attendance_all_devices(d_from, d_to, self.log, target_ips=target_ips)
                self._attendance_records = records

                unique_msts = len({r["mst"] for r in records})
                summary = (f"{len(records)} bản ghi  |  "
                           f"{unique_msts} nhân viên  |  "
                           f"{d_from:%d/%m/%Y} – {d_to:%d/%m/%Y}")
                self.lbl_att_summary.config(text=summary, fg=CLR["text"])

                rfid_map = self._rfid_map()
                self.root.after(0, lambda: self.att_table.load(records, rfid_map))
                self.root.after(0, lambda: self.set_status(
                    f"Đã lấy {len(records)} bản ghi chấm công."
                ))
            except Exception as e:
                self.log(f"❌ Lỗi lấy chấm công: {e}")
                self.set_status("Lỗi lấy dữ liệu chấm công.", CLR["danger"])
                self.lbl_att_summary.config(text="Lỗi.", fg=CLR["danger"])
            finally:
                self.enable_actions()

        threading.Thread(target=worker, daemon=True).start()

    def on_export_csv(self):
        if not self._attendance_records:
            messagebox.showinfo("Không có dữ liệu", "Chưa có dữ liệu chấm công.")
            return

        d_from = self._date_from.get()
        d_to   = self._date_to.get()
        default_name = (f"chamcong_{d_from:%d%m%Y}_{d_to:%d%m%Y}.csv")

        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_name,
            title="Lưu file chấm công"
        )
        if not filepath:
            return

        WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư",
                       "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        try:
            rfid_map = self._rfid_map()
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["STT", "MST", "RFID", "Ngày", "Giờ",
                                  "Thứ", "IP"])
                for i, r in enumerate(self._attendance_records, 1):
                    ts = r["timestamp"]
                    writer.writerow([
                        i,
                        r["mst"],
                        rfid_map.get(r["mst"], ""),
                        ts.strftime("%d/%m/%Y"),
                        ts.strftime("%H:%M:%S"),
                        WEEKDAYS_VI[ts.weekday()],
                        r["ip"],
                    ])
            self.log(f"✅ Đã xuất {len(self._attendance_records)} bản ghi → {filepath}")
            messagebox.showinfo("Xuất CSV thành công",
                                f"Đã lưu {len(self._attendance_records)} bản ghi\n→ {filepath}")
        except Exception as e:
            self.log(f"❌ Lỗi xuất CSV: {e}")
            messagebox.showerror("Lỗi xuất file", str(e))

    # ═══════════════════════════════════════════
    #  LOGIC SQL SERVER
    # ═══════════════════════════════════════════
    def on_test_db(self):
        self.log("🔌 Đang kiểm tra kết nối SQL Server ...")
        self.set_status("Đang test kết nối DB ...", CLR["warning"])

        def worker():
            ok, msg = SqlServerDB.test_connection()
            if ok:
                self.log(f"✅ SQL Server — {msg}")
                self.root.after(0, lambda: self.set_status(
                    f"DB OK: {DB_CONFIG['server']} / {DB_CONFIG['database']}",
                    CLR["success"]
                ))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Kết nối thành công",
                    f"✅ Kết nối thành công!\n\n"
                    f"Server  : {DB_CONFIG['server']}\n"
                    f"Database: {DB_CONFIG['database']}\n"
                    f"Bảng    : {DB_CONFIG['table']}"
                ))
            else:
                self.log(f"❌ Lỗi kết nối DB: {msg}")
                self.root.after(0, lambda: self.set_status(
                    "Kết nối DB thất bại.", CLR["danger"]
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Kết nối thất bại",
                    f"❌ Không kết nối được SQL Server.\n\n{msg}\n\n"
                    f"Hãy kiểm tra lại DB_CONFIG ở đầu file."
                ))

        threading.Thread(target=worker, daemon=True).start()

    def on_save_db(self):
        if not self._attendance_records:
            messagebox.showinfo("Không có dữ liệu",
                                "Chưa có dữ liệu chấm công để lưu.")
            return
        if pyodbc is None:
            messagebox.showerror("Thiếu thư viện",
                                 "Chưa cài 'pyodbc'.\nHãy chạy: pip install pyodbc")
            return

        n = len(self._attendance_records)
        if not messagebox.askyesno(
            "Xác nhận lưu DB",
            f"Lưu {n} bản ghi chấm công vào:\n\n"
            f"  Server  : {DB_CONFIG['server']}\n"
            f"  Database: {DB_CONFIG['database']}\n"
            f"  Bảng    : {DB_CONFIG['table']}\n\n"
            f"Tiếp tục?"
        ):
            return

        self.log(f"🗄 Bắt đầu lưu {n} bản ghi vào SQL Server ...")

        def worker():
            try:
                self.disable_actions()
                self.set_status("Đang lưu dữ liệu vào SQL Server ...",
                                CLR["warning"])
                rfid_map = self._rfid_map()
                inserted = save_attendance_to_db(
                    self._attendance_records, rfid_map, self.log
                )
                if inserted:
                    self.root.after(0, lambda: self.set_status(
                        f"Đã lưu {inserted} bản ghi vào DB.", CLR["success"]
                    ))
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Lưu DB thành công",
                        f"✅ Đã lưu {inserted} bản ghi vào [{DB_CONFIG['table']}]."
                    ))
                else:
                    self.root.after(0, lambda: self.set_status(
                        "Lưu DB thất bại.", CLR["danger"]
                    ))
            except Exception as e:
                self.log(f"❌ Lỗi lưu DB: {e}")
                self.root.after(0, lambda: self.set_status(
                    "Lỗi lưu DB.", CLR["danger"]
                ))
            finally:
                self.enable_actions()

        threading.Thread(target=worker, daemon=True).start()


# ──────────────────────────────────────────────────────────
def main():
    root = Tk()
    app = TimeAttendanceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()