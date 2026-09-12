"""Xóa danh sách user trên các máy chấm công ZK theo mã số thẻ (MST).

Quy trình:
- Đọc file `list_user_id.txt` (mỗi dòng 1 MST).
- Đọc `auto_get_data/all_rfid.txt` để ánh xạ MST -> RFID (file định dạng MST|RFID).
- Kết nối tới danh sách IP (mặc định lấy từ `auto_get_data.cardsystem.LISTS_DEVICE_IP` nếu có),
  duyệt users trên máy và xóa những user có `user_id` trùng MST hoặc `card` trùng RFID.

Yêu cầu: `pip install zk`
"""

import os
import sys
from zk import ZK

DEVICE_PORT = 4370
TIMEOUT = 10
PASSWORD = 0

HERE = os.path.dirname(os.path.abspath(__file__))
LIST_FILE = os.path.join(HERE, "list_user_id.txt")
ALL_RFID = os.path.join(os.path.dirname(HERE), "auto_get_data", "all_rfid.txt")

LISTS_DEVICE_IP = ["172.17.60.21", "172.17.60.22", "172.17.60.23", "172.17.60.24", "172.17.60.25", "172.17.60.26", "172.17.60.27", "172.17.60.28"]


def read_msts(path):
	if not os.path.exists(path):
		print(f"⚠ Không tìm thấy file MST: {path}")
		return []
	out = []
	with open(path, "r", encoding="utf-8") as f:
		for ln in f:
			ln = ln.strip()
			if not ln:
				continue
			out.append(ln)
	return out


def load_mst_to_rfid(path):
	mapping = {}
	if not os.path.exists(path):
		return mapping
	with open(path, "r", encoding="utf-8") as f:
		for ln in f:
			ln = ln.strip()
			if not ln or "|" not in ln:
				continue
			a, b = ln.split("|", 1)
			a = a.strip()
			b = b.strip()
			if a and b:
				mapping.setdefault(a, set()).add(b)
	return mapping


def delete_users_on_devices(msts, rfids, ips=None):
	if ips is None:
		ips = LISTS_DEVICE_IP
	zk = ZK
	if zk is None:
		raise RuntimeError("Thiếu thư viện 'zk'. Chạy: pip install zk")

	total_deleted = 0
	for ip in ips:
		print(f"Kết nối {ip} ...")
		zkcli = ZK(ip, port=DEVICE_PORT, timeout=TIMEOUT, password=PASSWORD,
				   force_udp=False, ommit_ping=False)
		conn = None
		try:
			conn = zkcli.connect()
			conn.disable_device()
			users = conn.get_users()
			targets = []
			for u in users:
				uid = getattr(u, "uid", None)
				mst = (getattr(u, "user_id", "") or "").strip()
				card = (str(getattr(u, "card", "")) if getattr(u, "card", None) is not None else "").strip()
				if (mst and mst in msts) or (card and card in rfids):
					targets.append((uid, mst, card))

			if not targets:
				print(f"  [{ip}] Không tìm thấy user trùng MST/RFID.")
			else:
				deleted_here = 0
				for uid, mst, card in targets:
					try:
						conn.delete_user(uid)
						deleted_here += 1
						print(f"  [{ip}] Đã xóa UID={uid} MST={mst} CARD={card}")
					except Exception as e:
						print(f"  [{ip}] Lỗi xóa UID={uid}: {e}")
				try:
					conn.refresh_data()
				except Exception:
					pass
				print(f"  [{ip}] Đã xóa {deleted_here} bản ghi.")
				total_deleted += deleted_here
		except Exception as e:
			print(f"  [{ip}] Lỗi kết nối: {e}")
		finally:
			try:
				if conn:
					conn.enable_device()
					conn.disconnect()
			except Exception:
				pass

	print(f"Hoàn tất. Tổng đã xóa: {total_deleted}")
	return total_deleted


def main():
	# allow optional ips via argv: comma-separated
	ips = None
	if len(sys.argv) > 1:
		arg = sys.argv[1].strip()
		if arg:
			ips = [s.strip() for s in arg.split(",") if s.strip()]

	msts = read_msts(LIST_FILE)
	if not msts:
		print("Không có MST để xóa. Hãy sửa file list_user_id.txt")
		return

	mapping = load_mst_to_rfid(ALL_RFID)
	rfids = set()
	for m in msts:
		if m in mapping:
			rfids.update(mapping[m])

	print(f"Đọc {len(msts)} MST, tìm được {len(rfids)} RFID tương ứng.")
	delete_users_on_devices(set(msts), rfids, ips=ips)


if __name__ == '__main__':
	main()
