"""Python loader — ctypes (stdlib, zero deps). Loads the prebuilt core."""
import ctypes
import os
import sys

lib_path = os.environ["SPIKE_LIB"]
lib = ctypes.CDLL(lib_path)

lib.citenexus_spike_version.restype = ctypes.c_char_p
lib.citenexus_spike_add.restype = ctypes.c_int
lib.citenexus_spike_add.argtypes = [ctypes.c_int, ctypes.c_int]

ver = lib.citenexus_spike_version().decode()
total = lib.citenexus_spike_add(2, 3)
print(f"[python] version={ver} add(2,3)={total}")

if ver != "citenexus-spike-0.1.0" or total != 5:
    print("[python] MISMATCH", file=sys.stderr)
    sys.exit(1)
print("[python] OK")
