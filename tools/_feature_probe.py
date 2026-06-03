import hid, time

dev = hid.device()
dev.open(0x0F8B, 0x0051)
dev.set_nonblocking(0)

def has_data(timeout_ms=500):
    t0 = time.monotonic()
    while (time.monotonic()-t0)*1000 < timeout_ms:
        d = dev.read(64, timeout_ms=100)
        if d:
            t = bytes(d).decode("ascii","ignore").replace("\x00","").strip()
            if t.startswith("%Z"):
                return True
    return False

print("Testing Feature Reports...")
candidates = [
    [0x00], [0x01], [0x02], [0x03], [0xAA], [0xA5], [0xFF],
    [0x00, 0x01], [0x00, 0x02], [0x00, 0x0B], [0x00, 0xB0],
    [0x00, 0x30, 0xD4, 0x09, 0x27],
    [0x00, 0x30, 0xD4, 0x09, 0x27, 0xC0, 0x01, 0x00, 0x00],
]
for seq in candidates:
    hex_s = " ".join(f"{b:02X}" for b in seq)
    try:
        dev.send_feature_report(seq)
    except Exception as e:
        print(f"  [{hex_s}] write error: {e}")
        continue
    time.sleep(0.08)
    result = has_data(400)
    status = "DATA!" if result else "no data"
    print(f"  [{hex_s}] -> {status}")
    if result:
        break

# Also try get_feature_report to see what the device reports
print("\nReading feature reports (get_feature_report)...")
for report_id in range(0, 4):
    try:
        data = dev.get_feature_report(report_id, 64)
        if data:
            print(f"  report_id={report_id}: {' '.join(f'{b:02X}' for b in data)}")
    except Exception as e:
        print(f"  report_id={report_id}: error: {e}")

dev.close()
