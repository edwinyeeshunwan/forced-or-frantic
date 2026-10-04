"""Minimal, dependency-light Parquet reader used ONLY when pyarrow is unavailable.

Why this exists: the reanalysis was run in environments where pyarrow could not
be installed. pandas.read_parquet (pyarrow engine) is always tried first; this
module is the fallback. It supports exactly what the supplied files use
(written by pyarrow 19 via pandas): flat schemas, REQUIRED/OPTIONAL columns,
PLAIN / PLAIN_DICTIONARY / RLE_DICTIONARY encodings, data pages v1 and v2,
UNCOMPRESSED / SNAPPY / GZIP codecs, and INT32/INT64/FLOAT/DOUBLE/BOOLEAN/
BYTE_ARRAY physical types, with TIMESTAMP and STRING logical types. Anything
else raises NotImplementedError rather than guessing.

Correctness is checked in tests/test_parquet_fallback.py (round trip against
files whose content is known) and indirectly by the exact reproduction of the
legacy benchmark tables (reanalysis/run_all.py, stage 'legacy').
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- thrift
class _Thrift:
    """Generic Thrift compact-protocol decoder -> nested dicts keyed by field id."""

    def __init__(self, buf: bytes, pos: int = 0):
        self.b = buf
        self.p = pos

    def varint(self) -> int:
        shift = res = 0
        while True:
            c = self.b[self.p]
            self.p += 1
            res |= (c & 0x7F) << shift
            if not c & 0x80:
                return res
            shift += 7

    def zigzag(self) -> int:
        n = self.varint()
        return (n >> 1) ^ -(n & 1)

    def read_value(self, t: int):
        if t == 1:
            return True
        if t == 2:
            return False
        if t == 3:
            v = struct.unpack_from("b", self.b, self.p)[0]
            self.p += 1
            return v
        if t in (4, 5, 6):
            return self.zigzag()
        if t == 7:
            v = struct.unpack_from("<d", self.b, self.p)[0]
            self.p += 8
            return v
        if t == 8:
            n = self.varint()
            v = self.b[self.p:self.p + n]
            self.p += n
            return v
        if t in (9, 10):
            h = self.b[self.p]
            self.p += 1
            size, et = h >> 4, h & 0x0F
            if size == 15:
                size = self.varint()
            out = []
            for _ in range(size):
                if et in (1, 2):  # bools inside containers are a full byte
                    out.append(self.b[self.p] == 1)
                    self.p += 1
                else:
                    out.append(self.read_value(et))
            return out
        if t == 11:
            size = self.varint()
            if size == 0:
                return {}
            h = self.b[self.p]
            self.p += 1
            kt, vt = h >> 4, h & 0x0F
            return {self.read_value(kt): self.read_value(vt) for _ in range(size)}
        if t == 12:
            return self.struct()
        raise NotImplementedError(f"thrift type {t}")

    def struct(self) -> dict:
        out, last = {}, 0
        while True:
            h = self.b[self.p]
            self.p += 1
            if h == 0:
                return out
            delta, t = h >> 4, h & 0x0F
            fid = last + delta if delta else self.zigzag()
            last = fid
            out[fid] = self.read_value(t)


# --------------------------------------------------------------------------- codecs
_SNAPPY = None


def _load_snappy():
    global _SNAPPY
    if _SNAPPY is None:
        name = ctypes.util.find_library("snappy") or "libsnappy.so.1"
        try:
            lib = ctypes.CDLL(name)
            lib.snappy_uncompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                              ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
            _SNAPPY = lib
        except OSError:
            _SNAPPY = False
    return _SNAPPY


def _snappy_py(src: bytes) -> bytes:
    """Pure-Python raw snappy decompression (fallback when libsnappy is absent)."""
    t = _Thrift(src)
    n = t.varint()
    p = t.p
    out = bytearray()
    while p < len(src):
        tag = src[p]
        p += 1
        kind = tag & 3
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(src[p:p + nb], "little")
                p += nb
            ln += 1
            out += src[p:p + ln]
            p += ln
            continue
        if kind == 1:
            ln = ((tag >> 2) & 7) + 4
            off = ((tag >> 5) << 8) | src[p]
            p += 1
        elif kind == 2:
            ln = (tag >> 2) + 1
            off = int.from_bytes(src[p:p + 2], "little")
            p += 2
        else:
            ln = (tag >> 2) + 1
            off = int.from_bytes(src[p:p + 4], "little")
            p += 4
        start = len(out) - off
        if off >= ln:
            out += out[start:start + ln]
        else:
            for i in range(ln):
                out.append(out[start + i])
    if len(out) != n:
        raise ValueError("snappy length mismatch")
    return bytes(out)


def _decompress(codec: int, data: bytes, usize: int) -> bytes:
    if codec == 0:
        return data
    if codec == 1:  # SNAPPY
        lib = _load_snappy()
        if lib:
            out = ctypes.create_string_buffer(usize)
            n = ctypes.c_size_t(usize)
            if lib.snappy_uncompress(data, len(data), out, ctypes.byref(n)) != 0:
                raise ValueError("snappy failure")
            return out.raw[:n.value]
        return _snappy_py(data)
    if codec == 2:  # GZIP
        return zlib.decompress(data, 47)
    raise NotImplementedError(f"parquet codec {codec} (only UNCOMPRESSED/SNAPPY/GZIP supported)")


# --------------------------------------------------------------------------- encodings
def _rle_bitpacked(buf: bytes, pos: int, end: int, bit_width: int, count: int) -> np.ndarray:
    out = np.empty(count, dtype=np.int64)
    filled = 0
    t = _Thrift(buf, pos)
    bw_bytes = (bit_width + 7) // 8
    while filled < count and t.p < end:
        header = t.varint()
        if header & 1:
            groups = header >> 1
            nvals = groups * 8
            nbytes = groups * bit_width
            raw = np.frombuffer(buf, dtype=np.uint8, count=nbytes, offset=t.p)
            t.p += nbytes
            if bit_width == 0:
                vals = np.zeros(nvals, dtype=np.int64)
            else:
                bits = np.unpackbits(raw, bitorder="little").reshape(-1, bit_width)
                vals = (bits.astype(np.int64) << np.arange(bit_width, dtype=np.int64)).sum(axis=1)
            take = min(nvals, count - filled)
            out[filled:filled + take] = vals[:take]
            filled += take
        else:
            run = header >> 1
            v = int.from_bytes(buf[t.p:t.p + bw_bytes], "little") if bw_bytes else 0
            t.p += bw_bytes
            take = min(run, count - filled)
            out[filled:filled + take] = v
            filled += take
    if filled < count:
        raise ValueError("RLE stream ended early")
    return out


_NP = {1: "<i4", 2: "<i8", 4: "<f4", 5: "<f8"}


def _plain(buf: bytes, pos: int, ptype: int, n: int, type_length=None):
    if ptype in _NP:
        dt = np.dtype(_NP[ptype])
        return np.frombuffer(buf, dtype=dt, count=n, offset=pos).copy(), pos + n * dt.itemsize
    if ptype == 0:
        nb = (n + 7) // 8
        bits = np.unpackbits(np.frombuffer(buf, np.uint8, nb, pos), bitorder="little")[:n]
        return bits.astype(bool), pos + nb
    if ptype == 6:
        out = []
        for _ in range(n):
            ln = struct.unpack_from("<i", buf, pos)[0]
            pos += 4
            out.append(buf[pos:pos + ln])
            pos += ln
        return np.array(out, dtype=object), pos
    raise NotImplementedError(f"physical type {ptype}")


# --------------------------------------------------------------------------- reader
def _column(buf: bytes, meta: dict, ptype: int, max_def: int, nrows: int):
    codec = meta[4]
    start = meta.get(11, meta[9])
    if 11 in meta and meta[11] is not None and meta[11] > 0:
        start = min(meta[11], meta[9])
    end = start + meta[7]
    pos = start
    dictionary = None
    pieces, masks = [], []
    got = 0
    while pos < end and got < meta[5]:
        t = _Thrift(buf, pos)
        ph = t.struct()
        pos = t.p
        ptype_page, usize, csize = ph[1], ph[2], ph[3]
        payload = buf[pos:pos + csize]
        pos += csize
        if ptype_page == 2:  # dictionary page
            data = _decompress(codec, payload, usize)
            dictionary, _ = _plain(data, 0, ptype, ph[7][1])
            continue
        if ptype_page == 0:
            hdr = ph[5]
            nvals, enc = hdr[1], hdr[2]
            data = _decompress(codec, payload, usize)
            p = 0
            if max_def > 0:
                ln = struct.unpack_from("<i", data, p)[0]
                p += 4
                d = _rle_bitpacked(data, p, p + ln, 1, nvals)
                p += ln
            else:
                d = np.ones(nvals, dtype=np.int64)
        elif ptype_page == 3:
            hdr = ph[8]
            nvals, enc = hdr[1], hdr[4]
            dl, rl = hdr[5], hdr[6]
            if rl:
                raise NotImplementedError("repetition levels")
            levels = payload[:dl]
            body = payload[dl:]
            compressed = hdr.get(7, True)
            data_body = _decompress(codec, body, usize - dl) if compressed else body
            d = _rle_bitpacked(levels, 0, dl, 1, nvals) if max_def > 0 else np.ones(nvals, np.int64)
            data, p = data_body, 0
        else:
            continue
        present = d == 1
        nnz = int(present.sum())
        if enc == 0:
            vals, _ = _plain(data, p, ptype, nnz)
        elif enc in (2, 8):
            bw = data[p]
            idx = _rle_bitpacked(data, p + 1, len(data), bw, nnz)
            vals = dictionary[idx]
        else:
            raise NotImplementedError(f"encoding {enc}")
        pieces.append(vals)
        masks.append(present)
        got += nvals
    vals = np.concatenate(pieces) if pieces else np.array([])
    mask = np.concatenate(masks) if masks else np.array([], bool)
    return vals, mask


def _convert(name, vals, mask, el):
    ptype = el.get(1)
    logical = el.get(10) or {}
    conv = el.get(6)
    n = len(mask)
    if ptype == 6:
        out = np.full(n, None, dtype=object)
        dec = [v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v for v in vals]
        out[mask] = dec
        return pd.Series(out, name=name, dtype=object)
    if ptype == 2 and (8 in logical or conv in (9, 10)):
        unit = "ms"
        if 8 in logical:
            u = logical[8].get(2, {})
            unit = "ms" if 1 in u else "us" if 2 in u else "ns"
        elif conv == 10:
            unit = "us"
        utc = True if 8 not in logical else bool(logical[8].get(1, True))
        full = np.zeros(n, dtype=np.int64)
        full[mask] = vals
        ts = pd.to_datetime(full, unit=unit, utc=utc)
        s = pd.Series(ts, name=name)
        s[~mask] = pd.NaT
        return s
    if ptype == 0:
        if mask.all():
            return pd.Series(vals, name=name, dtype=bool)
        out = np.full(n, None, dtype=object)
        out[mask] = vals
        return pd.Series(out, name=name, dtype=object)
    dt = np.float64 if ptype in (4, 5) or not mask.all() else vals.dtype
    full = np.full(n, np.nan, dtype=np.float64) if not mask.all() else np.empty(n, dtype=dt)
    full[mask] = vals
    return pd.Series(full, name=name)


def read_parquet_fallback(path) -> pd.DataFrame:
    buf = Path(path).read_bytes()
    if buf[:4] != b"PAR1" or buf[-4:] != b"PAR1":
        raise ValueError(f"not a parquet file: {path}")
    mlen = struct.unpack("<i", buf[-8:-4])[0]
    fm = _Thrift(buf, len(buf) - 8 - mlen).struct()
    schema = fm[2]
    leaves = schema[1:]
    if any(el.get(5) for el in leaves):
        raise NotImplementedError("nested schemas are not supported")
    names = [el[4].decode() for el in leaves]
    cols = {nm: [] for nm in names}
    masks = {nm: [] for nm in names}
    for rg in fm.get(4, []):
        for cc, el, nm in zip(rg[1], leaves, names):
            max_def = 1 if el.get(3, 0) == 1 else 0
            v, m = _column(buf, cc[3], el[1], max_def, rg[3])
            cols[nm].append(v)
            masks[nm].append(m)
    data = {}
    for el, nm in zip(leaves, names):
        v = np.concatenate(cols[nm]) if cols[nm] else np.array([])
        m = np.concatenate(masks[nm]) if masks[nm] else np.array([], bool)
        data[nm] = _convert(nm, v, m, el)
    df = pd.DataFrame(data)
    # honour pandas metadata for index columns / ordering, if present
    kv = {k[1].decode(): k.get(2, b"").decode() for k in fm.get(5, []) if 1 in k}
    if "pandas" in kv:
        meta = json.loads(kv["pandas"])
        idx = [c for c in meta.get("index_columns", []) if isinstance(c, str)]
        if idx:
            df = df.set_index(idx)
            if len(idx) == 1 and idx[0].startswith("__index_level_"):
                df.index.name = None
    return df


def read_parquet(path) -> pd.DataFrame:
    """pandas/pyarrow first; minimal fallback reader otherwise."""
    try:
        import pyarrow  # noqa: F401
        return pd.read_parquet(path)
    except ImportError:
        return read_parquet_fallback(path)


def engine_name() -> str:
    try:
        import pyarrow
        return f"pyarrow {pyarrow.__version__}"
    except ImportError:
        lib = _load_snappy()
        return "fallback reader (" + ("libsnappy via ctypes" if lib else "pure-Python snappy") + ")"
