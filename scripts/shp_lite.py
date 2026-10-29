"""Minimal DBF + polygon SHP reader and Korea 2000 UTM-K (EPSG:5179) projection. No external deps."""
import struct, math

def read_dbf(path, encoding="euc-kr"):
    with open(path, "rb") as f:
        hdr = f.read(32)
        n, hlen, rlen = struct.unpack("<IHH", hdr[4:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D: break
            name = d[:11].split(b"\x00")[0].decode("ascii")
            fields.append((name, d[11:12].decode(), d[16]))
        f.seek(hlen)
        rows = []
        for _ in range(n):
            rec = f.read(rlen)
            if not rec: break
            pos, row = 1, {}
            for name, typ, ln in fields:
                row[name] = rec[pos:pos+ln].decode(encoding, "replace").strip()
                pos += ln
            rows.append(row)
    return [f[0] for f in fields], rows

def read_polygons(shp, shx, indices):
    out = {}
    with open(shx, "rb") as fx, open(shp, "rb") as fs:
        for i in indices:
            fx.seek(100 + 8*i)
            off, ln = struct.unpack(">ii", fx.read(8))
            fs.seek(off*2 + 8)
            body = fs.read(ln*2)
            st = struct.unpack("<i", body[:4])[0]
            if st == 0: out[i] = []; continue
            nparts, npts = struct.unpack("<ii", body[36:44])
            parts = list(struct.unpack(f"<{nparts}i", body[44:44+4*nparts]))
            p0 = 44 + 4*nparts
            pts = struct.unpack(f"<{2*npts}d", body[p0:p0+16*npts])
            pts = list(zip(pts[0::2], pts[1::2]))
            parts.append(npts)
            out[i] = [pts[parts[k]:parts[k+1]] for k in range(nparts)]
    return out

def to_utmk(lat, lon):
    """WGS84/GRS80 -> EPSG:5179 (TM, lon0=127.5, lat0=38, k=0.9996, FE=1e6, FN=2e6)."""
    a, f = 6378137.0, 1/298.257222101
    e2 = f*(2-f); ep2 = e2/(1-e2); k0 = 0.9996
    lat0, lon0 = math.radians(38), math.radians(127.5)
    def M(p):
        return a*((1-e2/4-3*e2**2/64-5*e2**3/256)*p - (3*e2/8+3*e2**2/32+45*e2**3/1024)*math.sin(2*p)
                  + (15*e2**2/256+45*e2**3/1024)*math.sin(4*p) - (35*e2**3/3072)*math.sin(6*p))
    p, l = math.radians(lat), math.radians(lon)
    N = a/math.sqrt(1-e2*math.sin(p)**2); T = math.tan(p)**2; C = ep2*math.cos(p)**2; A = (l-lon0)*math.cos(p)
    x = 1e6 + k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T*T+72*C-58*ep2)*A**5/120)
    y = 2e6 + k0*(M(p)-M(lat0)+N*math.tan(p)*(A*A/2+(5-T+9*C+4*C*C)*A**4/24+(61-58*T+T*T+600*C-330*ep2)*A**6/720))
    return x, y

def point_in_ring(x, y, ring):
    ins = False; j = len(ring)-1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi: ins = not ins
        j = i
    return ins

def dist_to_rings(x, y, rings):
    best = float("inf")
    for r in rings:
        if point_in_ring(x, y, r): return 0.0
        for (x1, y1), (x2, y2) in zip(r, r[1:]):
            dx, dy = x2-x1, y2-y1; L = dx*dx+dy*dy
            t = 0 if L == 0 else max(0, min(1, ((x-x1)*dx+(y-y1)*dy)/L))
            best = min(best, math.hypot(x-(x1+t*dx), y-(y1+t*dy)))
    return best
