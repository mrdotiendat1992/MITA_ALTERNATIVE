import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# ============================================================
# THƯ VIỆN
# ============================================================

try:
    import pyodbc
except ImportError:
    pyodbc = None

try:
    from zk import ZK
except ImportError:
    ZK = None


# ============================================================
# CẤU HÌNH MÁY CHẤM CÔNG
# ============================================================

DEVICE_PORT = 4370
DEVICE_TIMEOUT = 10
DEVICE_PASSWORD = 0

DEVICE_IPS = [
    "172.17.60.21",
    "172.17.60.22",
    "172.17.60.23",
    "172.17.60.24",
    "172.17.60.25",
    "172.17.60.26",
    "172.17.60.27",
    "172.17.60.28",
]


# ============================================================
# CẤU HÌNH SQL SERVER
#
# Có thể sửa trực tiếp tại đây hoặc nhập trên giao diện.
# ============================================================

SQL_SERVER = r"172.16.60.100"
SQL_DATABASE = "MITACOSQL"

# SQL Authentication:
SQL_USERNAME = "it"
SQL_PASSWORD = ".<>N@mthu4n@123#"

# True  = Windows Authentication
# False = SQL Server Authentication
SQL_WINDOWS_AUTH = False

# Driver ưu tiên:
# ODBC Driver 18 for SQL Server
# hoặc ODBC Driver 17 for SQL Server
SQL_DRIVER = "ODBC Driver 17 for SQL Server"


# ============================================================
# QUERY SQL
#
# Ô "MST lọc" trên giao diện:
# - Để trống: lấy toàn bộ nhân viên
# - Nhập 15478: lấy riêng 15478
# - Nhập 15478,15479: lấy nhiều MST
# ============================================================

SQL_QUERY_ALL = """
SELECT
    LTRIM(RTRIM(CAST(MaNhanVien AS VARCHAR(50)))) AS MaNhanVien,
    LTRIM(RTRIM(ISNULL(TenChamCong, ''))) AS TenChamCong,
    LTRIM(RTRIM(ISNULL(Mathe, ''))) AS Mathe
FROM NHANVIEN
WHERE MaNhanVien IS NOT NULL
ORDER BY MaNhanVien
"""


# ============================================================
# HÀM TIỆN ÍCH
# ============================================================

def normalize_card(card):
    """
    RFID trên pyzk phải là số nguyên.

    Trả về:
        None = không có RFID / RFID không hợp lệ
        int  = RFID hợp lệ
    """
    if card is None:
        return None

    text = str(card).strip()

    if not text:
        return None

    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def get_device_card(user):
    value = getattr(user, "card", None)

    if value is None:
        return 0

    try:
        text = str(value).strip()

        if not text:
            return 0

        return int(text)

    except (ValueError, TypeError):
        return 0


def get_used_uids(users):
    used = set()

    for user in users:
        try:
            uid = int(getattr(user, "uid", 0) or 0)

            if uid > 0:
                used.add(uid)

        except Exception:
            pass

    return used


def get_new_uid(used_uids):
    uid = 1

    while uid in used_uids:
        uid += 1

    return uid


# ============================================================
# SQL SERVER
# ============================================================

def get_connection_string(
    server,
    database,
    username,
    password,
    windows_auth,
    driver
):
    if windows_auth:
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
            f"TrustServerCertificate=yes;"
        )

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )


def connect_sql(
    server,
    database,
    username,
    password,
    windows_auth,
    driver
):
    if pyodbc is None:
        raise RuntimeError(
            "Chưa cài pyodbc.\n\n"
            "Chạy:\n"
            "pip install pyodbc"
        )

    conn_str = get_connection_string(
        server,
        database,
        username,
        password,
        windows_auth,
        driver
    )

    return pyodbc.connect(
        conn_str,
        timeout=10
    )


def build_query(mst_filter):
    """
    Tạo SQL query.

    mst_filter:
        ""                    -> toàn bộ
        "15478"               -> một MST
        "15478,15479,15480"   -> nhiều MST
    """

    mst_filter = safe_text(mst_filter)

    if not mst_filter:
        return SQL_QUERY_ALL, []

    values = []

    for item in mst_filter.split(","):
        item = item.strip()

        if item:
            values.append(item)

    if not values:
        return SQL_QUERY_ALL, []

    placeholders = ",".join("?" for _ in values)

    query = f"""
    SELECT
        LTRIM(RTRIM(CAST(MaNhanVien AS VARCHAR(50)))) AS MaNhanVien,
        LTRIM(RTRIM(ISNULL(TenChamCong, ''))) AS TenChamCong,
        LTRIM(RTRIM(ISNULL(Mathe, ''))) AS Mathe
    FROM NHANVIEN
    WHERE MaNhanVien IS NOT NULL
      AND CAST(MaNhanVien AS VARCHAR(50)) IN ({placeholders})
    ORDER BY MaNhanVien
    """

    return query, values


def load_employees_from_sql(
    server,
    database,
    username,
    password,
    windows_auth,
    driver,
    mst_filter=""
):
    conn = None
    cursor = None

    try:
        conn = connect_sql(
            server,
            database,
            username,
            password,
            windows_auth,
            driver
        )

        query, params = build_query(mst_filter)

        cursor = conn.cursor()
        cursor.execute(query, params)

        rows = cursor.fetchall()

        employees = []

        for row in rows:
            mst = safe_text(row[0])
            name = safe_text(row[1])
            card = safe_text(row[2])

            if not mst:
                continue

            if not name:
                name = mst

            employees.append({
                "mst": mst,
                "name": name,
                "card": card
            })

        return employees

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass

        try:
            if conn:
                conn.close()
        except Exception:
            pass


# ============================================================
# ĐẨY NHÂN VIÊN LÊN MỘT MÁY
# ============================================================

def push_to_device(ip, employees, log):
    if ZK is None:
        log(
            "THIẾU pyzk. Chạy: pip install pyzk"
        )
        return 0, 0, len(employees)

    zk = ZK(
        ip,
        port=DEVICE_PORT,
        timeout=DEVICE_TIMEOUT,
        password=DEVICE_PASSWORD,
        force_udp=False,
        ommit_ping=False
    )

    conn = None

    added = 0
    updated = 0
    failed = 0

    try:
        log("")
        log("=" * 78)
        log(f"KẾT NỐI: {ip}")

        conn = zk.connect()

        log(f"[{ip}] Kết nối thành công")

        try:
            conn.disable_device()
        except Exception:
            pass

        # ----------------------------------------------------
        # LẤY USER TRÊN MÁY
        # ----------------------------------------------------

        users = conn.get_users()

        log(
            f"[{ip}] Có {len(users)} user trên máy"
        )

        # ----------------------------------------------------
        # INDEX USER THEO MST / CARD
        # ----------------------------------------------------

        by_user_id = {}
        by_card = {}

        for user in users:
            user_id = safe_text(
                getattr(user, "user_id", "")
            )

            card = safe_text(
                getattr(user, "card", "")
            )

            if user_id:
                by_user_id[user_id] = user

            if card:
                by_card[card] = user

        used_uids = get_used_uids(users)

        # ----------------------------------------------------
        # ĐẨY NHÂN VIÊN
        # ----------------------------------------------------

        for emp in employees:
            mst = safe_text(emp.get("mst"))
            name = safe_text(emp.get("name"))
            card_text = safe_text(emp.get("card"))

            if not mst:
                continue

            if not name:
                name = mst

            # Nhiều dòng máy giới hạn tên khoảng 24 ký tự.
            device_name = name[:24]

            file_card = normalize_card(card_text)

            try:
                # --------------------------------------------
                # TÌM THEO MST
                # --------------------------------------------

                existing = by_user_id.get(mst)

                # Nếu chưa thấy MST mà DB có RFID,
                # thử tìm theo RFID.
                if existing is None and file_card is not None:
                    existing = by_card.get(str(file_card))

                # --------------------------------------------
                # UPDATE
                # --------------------------------------------

                if existing is not None:
                    uid = int(
                        getattr(existing, "uid", 0) or 0
                    )

                    old_card = get_device_card(existing)

                    # DB có RFID:
                    # cập nhật RFID.
                    #
                    # DB không có RFID:
                    # giữ RFID hiện tại trên máy.
                    if file_card is not None:
                        card_value = file_card
                        card_log = str(file_card)
                    else:
                        card_value = old_card
                        card_log = (
                            f"{old_card} "
                            "(giữ nguyên)"
                        )

                    log(
                        f"[{ip}] UPDATE | "
                        f"MST={mst} | "
                        f"NAME={device_name} | "
                        f"CARD={card_log}"
                    )

                    conn.set_user(
                        uid=uid,
                        name=device_name,
                        privilege=0,
                        password="",
                        group_id="",
                        user_id=mst,
                        card=card_value
                    )

                    updated += 1

                # --------------------------------------------
                # ADD
                # --------------------------------------------

                else:
                    uid = get_new_uid(used_uids)

                    # User mới không có RFID:
                    # pyzk cần card là số -> 0.
                    if file_card is None:
                        card_value = 0
                        card_log = "0 (không có RFID)"
                    else:
                        card_value = file_card
                        card_log = str(file_card)

                    log(
                        f"[{ip}] ADD | "
                        f"UID={uid} | "
                        f"MST={mst} | "
                        f"NAME={device_name} | "
                        f"CARD={card_log}"
                    )

                    conn.set_user(
                        uid=uid,
                        name=device_name,
                        privilege=0,
                        password="",
                        group_id="",
                        user_id=mst,
                        card=card_value
                    )

                    used_uids.add(uid)
                    added += 1

                    # Cập nhật index để tránh trùng trong cùng lượt.
                    # Không dùng object giả cho by_card.
                    by_user_id[mst] = type(
                        "TempUser",
                        (),
                        {
                            "uid": uid,
                            "user_id": mst,
                            "card": card_value
                        }
                    )()

                    if card_value:
                        by_card[str(card_value)] = by_user_id[mst]

            except Exception as e:
                failed += 1

                log(
                    f"[{ip}] ERROR | "
                    f"MST={mst} | {e}"
                )

        # ----------------------------------------------------
        # REFRESH
        # ----------------------------------------------------

        try:
            conn.refresh_data()
        except Exception:
            pass

        log(
            f"[{ip}] HOÀN TẤT | "
            f"Thêm={added} | "
            f"Cập nhật={updated} | "
            f"Lỗi={failed}"
        )

    except Exception as e:
        log(
            f"[{ip}] LỖI KẾT NỐI / ĐỌC MÁY: {e}"
        )

    finally:
        try:
            if conn:
                try:
                    conn.enable_device()
                except Exception:
                    pass

                try:
                    conn.disconnect()
                except Exception:
                    pass

        except Exception:
            pass

    return added, updated, failed


# ============================================================
# GIAO DIỆN
# ============================================================

class PushUserApp:

    def __init__(self, root):
        self.root = root

        self.root.title(
            "ĐẨY NHÂN VIÊN SQL SERVER - MÁY CHẤM CÔNG"
        )

        self.root.geometry("1250x800")
        self.root.minsize(1050, 650)

        self.running = False

        self.build_ui()
        self.load_default_sql_config()

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def build_ui(self):
        # ====================================================
        # SQL CONFIG
        # ====================================================

        sql_frame = ttk.LabelFrame(
            self.root,
            text="Kết nối SQL Server",
            padding=8
        )

        sql_frame.pack(
            fill="x",
            padx=10,
            pady=(10, 5)
        )

        # Row 1
        ttk.Label(
            sql_frame,
            text="Server:"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=4,
            pady=3
        )

        self.txt_server = ttk.Entry(
            sql_frame,
            width=28
        )

        self.txt_server.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=4,
            pady=3
        )

        ttk.Label(
            sql_frame,
            text="Database:"
        ).grid(
            row=0,
            column=2,
            sticky="w",
            padx=4,
            pady=3
        )

        self.txt_database = ttk.Entry(
            sql_frame,
            width=25
        )

        self.txt_database.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=4,
            pady=3
        )

        ttk.Label(
            sql_frame,
            text="Driver:"
        ).grid(
            row=0,
            column=4,
            sticky="w",
            padx=4,
            pady=3
        )

        self.cbo_driver = ttk.Combobox(
            sql_frame,
            width=25,
            values=[
                "ODBC Driver 17 for SQL Server",
                "ODBC Driver 18 for SQL Server",
                "SQL Server"
            ]
        )

        self.cbo_driver.grid(
            row=0,
            column=5,
            sticky="ew",
            padx=4,
            pady=3
        )

        # Row 2
        self.windows_auth = tk.BooleanVar(value=False)

        self.chk_windows = ttk.Checkbutton(
            sql_frame,
            text="Windows Authentication",
            variable=self.windows_auth,
            command=self.toggle_auth
        )

        self.chk_windows.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            padx=4,
            pady=3
        )

        ttk.Label(
            sql_frame,
            text="User:"
        ).grid(
            row=1,
            column=2,
            sticky="w",
            padx=4,
            pady=3
        )

        self.txt_username = ttk.Entry(
            sql_frame,
            width=25
        )

        self.txt_username.grid(
            row=1,
            column=3,
            sticky="ew",
            padx=4,
            pady=3
        )

        ttk.Label(
            sql_frame,
            text="Password:"
        ).grid(
            row=1,
            column=4,
            sticky="w",
            padx=4,
            pady=3
        )

        self.txt_password = ttk.Entry(
            sql_frame,
            width=25,
            show="*"
        )

        self.txt_password.grid(
            row=1,
            column=5,
            sticky="ew",
            padx=4,
            pady=3
        )

        # Row 3
        ttk.Label(
            sql_frame,
            text="Lọc MST:"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            padx=4,
            pady=3
        )

        self.txt_mst_filter = ttk.Entry(
            sql_frame,
            width=28
        )

        self.txt_mst_filter.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=4,
            pady=3
        )

        ttk.Label(
            sql_frame,
            text="Trống = tất cả | nhiều MST cách nhau bằng dấu phẩy"
        ).grid(
            row=2,
            column=2,
            columnspan=3,
            sticky="w",
            padx=4,
            pady=3
        )

        self.btn_test_db = ttk.Button(
            sql_frame,
            text="KIỂM TRA SQL",
            command=self.test_sql
        )

        self.btn_test_db.grid(
            row=2,
            column=5,
            sticky="ew",
            padx=4,
            pady=3
        )

        for col in range(6):
            sql_frame.columnconfigure(
                col,
                weight=1 if col in (1, 3, 5) else 0
            )

        # ====================================================
        # TITLE
        # ====================================================

        header = ttk.Frame(
            self.root,
            padding=(10, 5)
        )

        header.pack(
            fill="x"
        )

        ttk.Label(
            header,
            text="DANH SÁCH NHÂN VIÊN",
            font=("Segoe UI", 15, "bold")
        ).pack(
            side="left"
        )

        # ====================================================
        # MAIN
        # ====================================================

        main = ttk.Frame(
            self.root,
            padding=(10, 5)
        )

        main.pack(
            fill="both",
            expand=True
        )

        # ----------------------------------------------------
        # LEFT DEVICE
        # ----------------------------------------------------

        left = ttk.LabelFrame(
            main,
            text="Máy chấm công",
            padding=8
        )

        left.pack(
            side="left",
            fill="y",
            padx=(0, 8)
        )

        self.device_vars = {}

        for ip in DEVICE_IPS:
            var = tk.BooleanVar(value=True)

            self.device_vars[ip] = var

            ttk.Checkbutton(
                left,
                text=ip,
                variable=var
            ).pack(
                anchor="w",
                pady=3
            )

        ttk.Separator(
            left
        ).pack(
            fill="x",
            pady=10
        )

        ttk.Button(
            left,
            text="Chọn tất cả",
            command=self.select_all
        ).pack(
            fill="x",
            pady=2
        )

        ttk.Button(
            left,
            text="Bỏ chọn",
            command=self.unselect_all
        ).pack(
            fill="x",
            pady=2
        )

        # ----------------------------------------------------
        # RIGHT
        # ----------------------------------------------------

        right = ttk.Frame(main)

        right.pack(
            side="left",
            fill="both",
            expand=True
        )

        # ----------------------------------------------------
        # EMPLOYEE TABLE
        # ----------------------------------------------------

        employee_frame = ttk.LabelFrame(
            right,
            text="Nhân viên lấy từ SQL Server",
            padding=5
        )

        employee_frame.pack(
            fill="both",
            expand=True
        )

        columns = (
            "select",
            "mst",
            "name",
            "card"
        )

        self.tree = ttk.Treeview(
            employee_frame,
            columns=columns,
            show="headings",
            selectmode="extended"
        )

        self.tree.heading(
            "select",
            text="STT"
        )

        self.tree.heading(
            "mst",
            text="MST"
        )

        self.tree.heading(
            "name",
            text="Tên chấm công"
        )

        self.tree.heading(
            "card",
            text="Mã thẻ / RFID"
        )

        self.tree.column(
            "select",
            width=60,
            anchor="center"
        )

        self.tree.column(
            "mst",
            width=140,
            anchor="center"
        )

        self.tree.column(
            "name",
            width=350
        )

        self.tree.column(
            "card",
            width=220,
            anchor="center"
        )

        scroll_y = ttk.Scrollbar(
            employee_frame,
            orient="vertical",
            command=self.tree.yview
        )

        scroll_x = ttk.Scrollbar(
            employee_frame,
            orient="horizontal",
            command=self.tree.xview
        )

        self.tree.configure(
            yscrollcommand=scroll_y.set,
            xscrollcommand=scroll_x.set
        )

        self.tree.pack(
            side="top",
            fill="both",
            expand=True
        )

        scroll_y.pack(
            side="right",
            fill="y"
        )

        scroll_x.pack(
            side="bottom",
            fill="x"
        )

        # ----------------------------------------------------
        # BUTTONS
        # ----------------------------------------------------

        buttons = ttk.Frame(
            right,
            padding=(0, 8)
        )

        buttons.pack(
            fill="x"
        )

        self.btn_load = ttk.Button(
            buttons,
            text="ĐỌC NHÂN VIÊN TỪ SQL",
            command=self.load_data
        )

        self.btn_load.pack(
            side="left",
            padx=4
        )

        self.btn_select_rows = ttk.Button(
            buttons,
            text="CHỌN TẤT CẢ NHÂN VIÊN",
            command=self.select_all_rows
        )

        self.btn_select_rows.pack(
            side="left",
            padx=4
        )

        self.btn_clear_rows = ttk.Button(
            buttons,
            text="BỎ CHỌN NHÂN VIÊN",
            command=self.clear_rows
        )

        self.btn_clear_rows.pack(
            side="left",
            padx=4
        )

        self.btn_push = ttk.Button(
            buttons,
            text="▶ ĐẨY NHÂN VIÊN LÊN MÁY",
            command=self.start_push
        )

        self.btn_push.pack(
            side="left",
            padx=4
        )

        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

        log_frame = ttk.LabelFrame(
            right,
            text="Log",
            padding=5
        )

        log_frame.pack(
            fill="both",
            expand=True
        )

        self.log_text = tk.Text(
            log_frame,
            height=10,
            font=("Consolas", 9)
        )

        log_scroll = ttk.Scrollbar(
            log_frame,
            command=self.log_text.yview
        )

        self.log_text.configure(
            yscrollcommand=log_scroll.set
        )

        self.log_text.pack(
            side="left",
            fill="both",
            expand=True
        )

        log_scroll.pack(
            side="right",
            fill="y"
        )

        # ====================================================
        # STATUS
        # ====================================================

        self.status = ttk.Label(
            self.root,
            text="Sẵn sàng",
            relief="sunken",
            anchor="w"
        )

        self.status.pack(
            fill="x",
            side="bottom"
        )

    # --------------------------------------------------------
    # LOAD DEFAULT CONFIG
    # --------------------------------------------------------

    def load_default_sql_config(self):
        self.txt_server.insert(
            0,
            SQL_SERVER
        )

        self.txt_database.insert(
            0,
            SQL_DATABASE
        )

        self.txt_username.insert(
            0,
            SQL_USERNAME
        )

        self.txt_password.insert(
            0,
            SQL_PASSWORD
        )

        self.cbo_driver.set(
            SQL_DRIVER
        )

        self.windows_auth.set(
            SQL_WINDOWS_AUTH
        )

        self.toggle_auth()

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    def toggle_auth(self):
        if self.windows_auth.get():
            self.txt_username.config(
                state="disabled"
            )

            self.txt_password.config(
                state="disabled"
            )
        else:
            self.txt_username.config(
                state="normal"
            )

            self.txt_password.config(
                state="normal"
            )

    # --------------------------------------------------------
    # GET SQL CONFIG
    # --------------------------------------------------------

    def get_sql_config(self):
        return {
            "server": self.txt_server.get().strip(),
            "database": self.txt_database.get().strip(),
            "username": self.txt_username.get(),
            "password": self.txt_password.get(),
            "windows_auth": self.windows_auth.get(),
            "driver": self.cbo_driver.get().strip()
        }

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    def log(self, text):
        def update():
            self.log_text.insert(
                "end",
                text + "\n"
            )

            self.log_text.see("end")

        self.root.after(
            0,
            update
        )

    # --------------------------------------------------------
    # TEST SQL
    # --------------------------------------------------------

    def test_sql(self):
        config = self.get_sql_config()

        if not config["server"]:
            messagebox.showwarning(
                "SQL Server",
                "Chưa nhập Server."
            )
            return

        if not config["database"]:
            messagebox.showwarning(
                "SQL Server",
                "Chưa nhập Database."
            )
            return

        self.btn_test_db.config(
            state="disabled"
        )

        def worker():
            conn = None

            try:
                self.log("")
                self.log("=" * 78)
                self.log("KIỂM TRA KẾT NỐI SQL SERVER")

                conn = connect_sql(
                    config["server"],
                    config["database"],
                    config["username"],
                    config["password"],
                    config["windows_auth"],
                    config["driver"]
                )

                self.log(
                    "Kết nối SQL Server thành công."
                )

                def done():
                    self.btn_test_db.config(
                        state="normal"
                    )

                    messagebox.showinfo(
                        "SQL Server",
                        "Kết nối SQL Server thành công."
                    )

                self.root.after(0, done)

            except Exception as e:
                self.log(
                    f"LỖI SQL: {str(e)}"
                )

                def failed():
                    self.btn_test_db.config(
                        state="normal"
                    )

                    messagebox.showerror(
                        "SQL Server",
                        str(e)
                    )

                self.root.after(0, failed)

            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    # --------------------------------------------------------
    # LOAD DATA FROM SQL
    # --------------------------------------------------------

    def load_data(self):
        config = self.get_sql_config()

        if not config["server"]:
            messagebox.showwarning(
                "SQL Server",
                "Chưa nhập Server."
            )
            return

        if not config["database"]:
            messagebox.showwarning(
                "SQL Server",
                "Chưa nhập Database."
            )
            return

        self.btn_load.config(
            state="disabled"
        )

        self.btn_push.config(
            state="disabled"
        )

        mst_filter = self.txt_mst_filter.get().strip()

        def worker():
            try:
                self.log("")
                self.log("=" * 78)
                self.log("ĐỌC NHÂN VIÊN TỪ SQL SERVER")

                if mst_filter:
                    self.log(
                        f"Lọc MST: {mst_filter}"
                    )
                else:
                    self.log(
                        "Lọc MST: TẤT CẢ"
                    )

                employees = load_employees_from_sql(
                    config["server"],
                    config["database"],
                    config["username"],
                    config["password"],
                    config["windows_auth"],
                    config["driver"],
                    mst_filter
                )

                def update_table():
                    for item in self.tree.get_children():
                        self.tree.delete(item)

                    for index, emp in enumerate(
                        employees,
                        start=1
                    ):
                        self.tree.insert(
                            "",
                            "end",
                            iid=f"emp_{index}",
                            values=(
                                index,
                                emp["mst"],
                                emp["name"],
                                emp["card"]
                            )
                        )

                    self.status.config(
                        text=(
                            f"SQL Server: "
                            f"đọc {len(employees)} nhân viên"
                        )
                    )

                    self.log(
                        f"Đọc được {len(employees)} nhân viên."
                    )

                    for emp in employees[:10]:
                        self.log(
                            f"  {emp['mst']} | "
                            f"{emp['name']} | "
                            f"{emp['card'] or '(không có thẻ)'}"
                        )

                    self.btn_load.config(
                        state="normal"
                    )

                    self.btn_push.config(
                        state="normal"
                    )

                self.root.after(
                    0,
                    update_table
                )

            except Exception as e:
                self.log(
                    f"LỖI ĐỌC SQL: {e}"
                )

                def failed():
                    self.btn_load.config(
                        state="normal"
                    )

                    self.btn_push.config(
                        state="normal"
                    )

                    messagebox.showerror(
                        "Lỗi đọc SQL Server",
                        str(e)
                    )

                self.root.after(
                    0,
                    failed
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    # --------------------------------------------------------
    # GET EMPLOYEES FROM TABLE
    # --------------------------------------------------------

    def get_table_employees(self):
        employees = []

        for item in self.tree.get_children():
            values = self.tree.item(item, "values")

            if len(values) < 4:
                continue

            employees.append({
                "mst": safe_text(values[1]),
                "name": safe_text(values[2]),
                "card": safe_text(values[3])
            })

        return employees

    # --------------------------------------------------------
    # SELECT DEVICES
    # --------------------------------------------------------

    def select_all(self):
        for var in self.device_vars.values():
            var.set(True)

    def unselect_all(self):
        for var in self.device_vars.values():
            var.set(False)

    # --------------------------------------------------------
    # SELECT EMPLOYEES
    # --------------------------------------------------------

    def select_all_rows(self):
        children = self.tree.get_children()

        if children:
            self.tree.selection_set(children)

    def clear_rows(self):
        self.tree.selection_remove(
            self.tree.selection()
        )

    # --------------------------------------------------------
    # START PUSH
    # --------------------------------------------------------

    def start_push(self):
        if self.running:
            return

        selected_ips = [
            ip
            for ip, var in self.device_vars.items()
            if var.get()
        ]

        if not selected_ips:
            messagebox.showwarning(
                "Thông báo",
                "Chưa chọn máy chấm công."
            )
            return

        selected_items = self.tree.selection()

        if selected_items:
            employees = []

            for item in selected_items:
                values = self.tree.item(
                    item,
                    "values"
                )

                if len(values) >= 4:
                    employees.append({
                        "mst": safe_text(values[1]),
                        "name": safe_text(values[2]),
                        "card": safe_text(values[3])
                    })

            employee_mode = (
                f"{len(employees)} nhân viên được chọn"
            )

        else:
            employees = self.get_table_employees()

            employee_mode = (
                f"{len(employees)} nhân viên trong danh sách"
            )

        if not employees:
            messagebox.showwarning(
                "Thông báo",
                "Không có nhân viên để đẩy."
            )
            return

        confirm = messagebox.askyesno(
            "Xác nhận đẩy nhân viên",
            f"{employee_mode}\n\n"
            f"Lên {len(selected_ips)} máy chấm công?\n\n"
            "Nhân viên đã có trên máy sẽ UPDATE.\n"
            "Nhân viên chưa có sẽ ADD.\n"
            "Không xóa nhân viên khác."
        )

        if not confirm:
            return

        self.running = True

        self.btn_push.config(
            state="disabled"
        )

        self.btn_load.config(
            state="disabled"
        )

        self.btn_test_db.config(
            state="disabled"
        )

        thread = threading.Thread(
            target=self.push_thread,
            args=(selected_ips, employees),
            daemon=True
        )

        thread.start()

    # --------------------------------------------------------
    # PUSH THREAD
    # --------------------------------------------------------

    def push_thread(
        self,
        ips,
        employees
    ):
        total_added = 0
        total_updated = 0
        total_failed = 0

        self.log("")
        self.log("=" * 78)
        self.log(
            f"BẮT ĐẦU ĐẨY {len(employees)} NHÂN VIÊN"
        )
        self.log(
            f"SỐ MÁY: {len(ips)}"
        )

        for ip in ips:
            added, updated, failed = push_to_device(
                ip,
                employees,
                self.log
            )

            total_added += added
            total_updated += updated
            total_failed += failed

        self.log("")
        self.log("=" * 78)
        self.log("HOÀN TẤT TOÀN BỘ")
        self.log(f"Thêm mới : {total_added}")
        self.log(f"Cập nhật : {total_updated}")
        self.log(f"Lỗi      : {total_failed}")

        def finish():
            self.running = False

            self.btn_push.config(
                state="normal"
            )

            self.btn_load.config(
                state="normal"
            )

            self.btn_test_db.config(
                state="normal"
            )

            self.status.config(
                text=(
                    f"Hoàn tất | "
                    f"Thêm {total_added} | "
                    f"Cập nhật {total_updated} | "
                    f"Lỗi {total_failed}"
                )
            )

            messagebox.showinfo(
                "Hoàn tất",
                f"Đã hoàn thành.\n\n"
                f"Thêm mới: {total_added}\n"
                f"Cập nhật: {total_updated}\n"
                f"Lỗi: {total_failed}"
            )

        self.root.after(
            0,
            finish
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    missing = []

    if pyodbc is None:
        missing.append(
            "pyodbc"
        )

    if ZK is None:
        missing.append(
            "pyzk"
        )

    if missing:
        root = tk.Tk()
        root.withdraw()

        messagebox.showerror(
            "Thiếu thư viện",
            "Thiếu thư viện:\n\n"
            + "\n".join(
                f"- {x}" for x in missing
            )
            + "\n\nCài bằng lệnh:\n"
            "pip install pyodbc pyzk"
        )

        root.destroy()
        sys.exit(1)

    root = tk.Tk()

    try:
        style = ttk.Style()

        if "vista" in style.theme_names():
            style.theme_use("vista")

    except Exception:
        pass

    app = PushUserApp(root)

    root.mainloop()