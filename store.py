"""제보·수거 완료·순찰 기록 저장소.

- Supabase(무료 Postgres)가 설정돼 있으면 거기에 저장 → 앱을 재시작해도, 여러 사람이 동시에 써도 기록이 남음
- 설정이 없거나 연결이 안 되면 앱 폴더의 JSON 파일에 저장 (로컬 실행용)

Supabase 테이블 하나(events)에 종류(kind)와 기록 내용(data, JSON)을 그대로 담는다.
추가 라이브러리 없이 표준 urllib로 Supabase REST API(PostgREST)를 호출한다.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

KINDS = ("reports", "cleanups", "patrols", "reviews")
TABLE = "events"

# 이미 만든 테이블에 'reviews'(제보 검토) 종류를 허용하는 변경
UPGRADE_SQL = """alter table public.events drop constraint if exists events_kind_check;
alter table public.events add constraint events_kind_check
  check (kind in ('reports', 'cleanups', 'patrols', 'reviews'));"""

SETUP_SQL = """create table if not exists public.events (
  id text primary key,
  kind text not null check (kind in ('reports', 'cleanups', 'patrols', 'reviews')),
  data jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists events_kind_created on public.events (kind, created_at);
alter table public.events enable row level security;  -- 정책 없음 = 공개 키로는 접근 불가, 서버의 secret 키만 접근
grant select, insert, delete on public.events to service_role;  -- 서버(secret 키)만 읽기·쓰기"""


class StoreError(Exception):
    pass


def new_id():
    return uuid.uuid4().hex


class LocalStore:
    backend = "local"

    def __init__(self, folder):
        self.folder = Path(folder)

    def _path(self, kind):
        return self.folder / f"{kind}.json"

    def _read(self, kind):
        try:
            rows = json.loads(self._path(kind).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        for r in rows:                       # 예전 파일에는 id가 없음
            r.setdefault("_id", new_id())
        return rows

    def _write(self, kind, rows):
        self._path(kind).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def load(self):
        return {k: self._read(k) for k in KINDS}

    def add(self, kind, rec):
        rec = dict(rec, _id=rec.get("_id") or new_id())
        rows = self._read(kind)
        rows.append(rec)
        self._write(kind, rows)
        return rec

    def remove(self, kind, ids):
        ids = set(ids)
        if ids:
            self._write(kind, [r for r in self._read(kind) if r["_id"] not in ids])


class SupabaseStore:
    backend = "supabase"

    def __init__(self, url, key, timeout=8):
        self.base = url.rstrip("/") + "/rest/v1/" + TABLE
        self.key = key
        self.timeout = timeout

    def _req(self, method, query="", body=None, prefer=None):
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):       # 예전 형식(JWT) service_role 키
            headers["Authorization"] = "Bearer " + self.key
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + query, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise StoreError(f"Supabase {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StoreError(f"Supabase 연결 실패: {e}") from None
        return json.loads(raw) if raw.strip() else None

    def load(self):
        out = {k: [] for k in KINDS}
        rows, offset = [], 0
        while True:                           # PostgREST 기본 최대 1000행씩
            page = self._req("GET", f"?select=id,kind,data&order=created_at.asc,id.asc&limit=1000&offset={offset}")
            rows += page or []
            if not page or len(page) < 1000:
                break
            offset += 1000
        for r in rows:
            if r["kind"] in out:
                out[r["kind"]].append(dict(r["data"], _id=r["id"]))
        return out

    def add(self, kind, rec):
        rec = dict(rec, _id=rec.get("_id") or new_id())
        data = {k: v for k, v in rec.items() if k != "_id"}
        self._req("POST", "", {"id": rec["_id"], "kind": kind, "data": data}, prefer="return=minimal")
        return rec

    def remove(self, kind, ids):
        ids = [i for i in ids if i]
        if ids:
            q = "?kind=eq." + urllib.parse.quote(kind) + "&id=in.(" + ",".join(urllib.parse.quote(i) for i in ids) + ")"
            self._req("DELETE", q, prefer="return=minimal")


def open_store(url, key, local_folder):
    """Supabase 설정이 있으면 Supabase, 없으면 로컬 JSON."""
    if url and key:
        return SupabaseStore(url, key)
    return LocalStore(local_folder)
