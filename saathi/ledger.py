"""Postgres ledger INSIDE the Meko datapack (Meko AMP) - "Postgres inside the context".

Every answered ticket and every caseworker decision becomes a row, so the audit report is plain SQL.

    PgLedger.connect(meko, conversation_id)   # live: finds or creates the AMP cluster "saathi-ledger" in the datapack
    SqliteLedger()                            # offline tests / demo: same tables in memory

Password rule (owner never handles passwords): the DB password is derived from MEKO_API_KEY with HMAC, so it is never
printed or typed and any Colab session can derive it again.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import urllib.request
from typing import Any

CLUSTER_NAME = "saathi-ledger"

TABLES = [
    """CREATE TABLE IF NOT EXISTS tickets (
        id {serial}, asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ticket_id TEXT, mode TEXT, path TEXT,
        language TEXT, issue_key TEXT, intent TEXT, tokens INTEGER, llm_calls INTEGER, latency_s REAL,
        reused_memory_id TEXT, conversation_id TEXT, run_tag TEXT)""",
    """CREATE TABLE IF NOT EXISTS reviews (
        id {serial}, at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ticket_id TEXT, conversation_id TEXT,
        issue_key TEXT, decision TEXT, caseworker TEXT, memory_id TEXT, run_tag TEXT)""",
]

AUDIT_SQL = {   # {f} = optional "AND run_tag = <placeholder>" filter
    "tickets": "SELECT COUNT(*) FROM tickets WHERE mode = 'meko'{f}",
    "reused": "SELECT COUNT(*) FROM tickets WHERE mode = 'meko' AND path = 'reused'{f}",
    "fresh": "SELECT COUNT(*) FROM tickets WHERE mode = 'meko' AND path = 'fresh'{f}",
    "avg_tokens_fresh": "SELECT AVG(tokens) FROM tickets WHERE mode = 'meko' AND path = 'fresh'{f}",
    "avg_tokens_reused": "SELECT AVG(tokens) FROM tickets WHERE mode = 'meko' AND path = 'reused'{f}",
    "approved": "SELECT COUNT(*) FROM reviews WHERE decision = 'approved'{f}",
    "rejected": "SELECT COUNT(*) FROM reviews WHERE decision = 'rejected'{f}",
}
BY_ISSUE_SQL = ("SELECT issue_key, COUNT(*), SUM(CASE WHEN path = 'reused' THEN 1 ELSE 0 END) FROM tickets "
                "WHERE mode = 'meko'{f} GROUP BY issue_key ORDER BY COUNT(*) DESC")


def derived_password(api_key: str) -> str:
    return hmac.new(api_key.encode(), CLUSTER_NAME.encode(), hashlib.sha256).hexdigest()[:32]


def my_ip() -> str:
    return urllib.request.urlopen("https://api.ipify.org", timeout=15).read().decode().strip()


def find_key(obj: Any, keys: tuple) -> Any:
    """First value of any of `keys`, searching nested dicts / lists (Meko reply shapes vary)."""
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) not in (None, "", []):
                return obj[k]
        for v in obj.values():
            hit = find_key(v, keys)
            if hit not in (None, "", []):
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find_key(v, keys)
            if hit not in (None, "", []):
                return hit
    return None


def items(obj: Any, *names: str) -> list:
    """The list of things inside a Meko reply (e.g. {"clusters": [...]})."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for n in names + ("items", "results", "data"):
            if isinstance(obj.get(n), list):
                return obj[n]
    return []


def safe(obj: Any) -> str:
    """JSON for logs with anything password-like removed."""
    def clean(o):
        if isinstance(o, dict):
            return {k: ("***" if "pass" in k.lower() or "secret" in k.lower() else clean(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    return json.dumps(clean(obj))[:1200]


class _Base:
    ph = "?"            # SQL placeholder
    serial = "INTEGER PRIMARY KEY AUTOINCREMENT"

    def _setup(self) -> None:
        cur = self.conn.cursor()
        for sql in TABLES:
            cur.execute(sql.format(serial=self.serial))
        self.conn.commit()

    def _insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join([self.ph] * len(row))
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
        self.conn.commit()

    def log_ticket(self, res, run_tag: str | None = None) -> None:
        self._insert("tickets", {
            "ticket_id": res.ticket_id, "mode": res.mode, "path": res.path, "language": res.language,
            "issue_key": res.issue_key, "intent": res.intent, "tokens": res.total_tokens,
            "llm_calls": res.llm_calls, "latency_s": float(res.latency_s or 0),
            "reused_memory_id": res.reused_memory_id, "conversation_id": res.conversation_id, "run_tag": run_tag})

    def log_review(self, res, decision: str, caseworker: str, memory_id: str | None, run_tag: str | None = None):
        self._insert("reviews", {
            "ticket_id": res.ticket_id, "conversation_id": res.conversation_id, "issue_key": res.issue_key,
            "decision": decision, "caseworker": caseworker, "memory_id": memory_id, "run_tag": run_tag})

    def audit(self, run_tag: str | None = None) -> dict:
        """Totals straight from SQL. run_tag = only the rows of one evaluation run."""
        cur = self.conn.cursor()
        f = f" AND run_tag = {self.ph}" if run_tag else ""
        params = [run_tag] if run_tag else []
        out = {}
        for name, sql in AUDIT_SQL.items():
            cur.execute(sql.format(f=f), params)
            v = cur.fetchone()[0]
            out[name] = round(float(v), 1) if isinstance(v, float) or (v is not None and not isinstance(v, int)) else (v or 0)
        cur.execute(BY_ISSUE_SQL.format(f=f), params)
        out["by_issue"] = [{"issue_key": r[0], "tickets": int(r[1]), "reused": int(r[2] or 0)} for r in cur.fetchall()]
        out["reuse_rate_pct"] = round(100 * out["reused"] / out["tickets"]) if out["tickets"] else 0
        return out


def audit_markdown(a: dict) -> str:
    lines = ["# Yojana Saathi - audit report (from the Postgres ledger inside the Meko datapack)", "",
             f"- Tickets answered with Meko: **{a['tickets']}** (reused an approved fix: {a['reused']}, "
             f"solved fresh: {a['fresh']}, reuse rate {a['reuse_rate_pct']}%)",
             f"- Average tokens: fresh {a['avg_tokens_fresh'] or 0}, reused {a['avg_tokens_reused'] or 0}",
             f"- Caseworker decisions: approved {a['approved']}, rejected {a['rejected']}", "",
             "| Issue | Tickets | Reused |", "|---|---|---|"]
    lines += [f"| {r['issue_key']} | {r['tickets']} | {r['reused']} |" for r in a["by_issue"]]
    return "\n".join(lines) + "\n"


class SqliteLedger(_Base):
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._setup()


class PgLedger(_Base):
    ph = "%s"
    serial = "SERIAL PRIMARY KEY"

    def __init__(self, **dsn):
        import psycopg
        self.conn = psycopg.connect(connect_timeout=20, **dsn)
        self._setup()

    @classmethod
    async def connect(cls, meko, conversation_id: str, api_key: str, create: bool = False, log=print) -> "PgLedger":
        """Find (or, with create=True, make) the AMP cluster, make sure this machine's IP may connect, then log in."""
        conv = conversation_id
        pw = derived_password(api_key)
        ip = my_ip()
        cidr = f"{ip}/32"
        clusters = items(await meko.call("amp_cluster_list", conversation_id=conv), "clusters")
        cluster = next((c for c in clusters if find_key(c, ("name",)) == CLUSTER_NAME), None)
        if cluster is None:
            if not create:
                raise RuntimeError(f"No AMP cluster '{CLUSTER_NAME}' yet. Run scripts/ledger.py --create first.")
            log("budget:", safe(await meko.call("amp_core_budget", conversation_id=conv)))
            made = await meko.call("amp_cluster_create", name=CLUSTER_NAME, with_writer=True, password=pw,
                                   connectivity_mode="ingress_external", allowed_cidrs=[cidr], conversation_id=conv)
            log("created:", safe(made))
            clusters = items(await meko.call("amp_cluster_list", conversation_id=conv), "clusters")
            cluster = next((c for c in clusters if find_key(c, ("name",)) == CLUSTER_NAME), None) or made
        cluster_id = find_key(cluster, ("cluster_id", "id"))
        branches = items(await meko.call("amp_branch_list", cluster_id=cluster_id, conversation_id=conv), "branches")
        branch = next((b for b in branches if find_key(b, ("name",)) == "main"), branches[0] if branches else {})
        branch_id = find_key(branch, ("branch_id", "id"))
        computes = items(await meko.call("amp_compute_list", cluster_id=cluster_id, branch_id=branch_id,
                                         conversation_id=conv), "computes", "endpoints")
        writer = next((c for c in computes if "write" in str(find_key(c, ("role", "type")) or "").lower()), None)
        log("writer:", safe(writer))
        if writer is not None:
            # Live 10 Nov 2026: the listing does NOT show the allow-list, so first just try to log in.
            ledger, err = await cls._login(writer, pw, log, tries=10)
            if ledger:
                return ledger
            log(f"existing writer unreachable from {ip} ({err[:120]}) -> re-creating it for this IP")
            await meko.call("amp_compute_delete", cluster_id=cluster_id, branch_id=branch_id,
                            compute_id=find_key(writer, ("compute_id", "id")), conversation_id=conv)
        # Colab's public IP changes per runtime and the allow-list is fixed per endpoint -> (re)create the writer.
        writer = await meko.call("amp_compute_create", cluster_id=cluster_id, branch_id=branch_id,
                                 role="read_write", password=pw, connectivity_mode="ingress_external",
                                 allowed_cidrs=[cidr], conversation_id=conv)
        log("new writer:", safe(writer))
        if not find_key(writer, ("address", "host", "hostname")):   # create may not return the address -> list
            computes = items(await meko.call("amp_compute_list", cluster_id=cluster_id, branch_id=branch_id,
                                             conversation_id=conv), "computes", "endpoints")
            writer = next((c for c in computes if "write" in str(find_key(c, ("role",)) or "").lower()), writer)
        ledger, err = await cls._login(writer, pw, log, tries=16)   # a NEW address needs a few minutes for DNS
        if ledger:
            return ledger
        raise RuntimeError(f"Could not log in to the AMP database: {err}")

    @classmethod
    async def _login(cls, writer, pw: str, log, tries: int):
        """Log in to the endpoint. DNS errors (brand-new address) are retried every 15 s; wrong user -> next user."""
        import asyncio
        host = find_key(writer, ("address", "host", "hostname", "external_address", "endpoint"))
        port = int(find_key(writer, ("port",)) or 5432)
        user = find_key(writer, ("login_user", "user", "username", "db_user")) or "cloud_admin"
        dbname = find_key(writer, ("database", "dbname", "db_name")) or "postgres"
        if isinstance(host, str) and ":" in host and not host.startswith("["):
            host, _, p = host.partition(":")
            port = int(p) if p.isdigit() else port
        err = "no address"
        for attempt in range(tries):
            dns_problem = False
            for u in dict.fromkeys([user, "admin", "cloud_admin"]):
                try:
                    return cls(host=host, port=port, user=u, password=pw, dbname=dbname), ""
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    if "resolve host" in err or "Name or service not known" in err:
                        dns_problem = True
                        break
                    log(f"login as {u} failed: {err[:150]}")
            if not dns_problem:
                return None, err
            log(f"address {host} not live yet (try {attempt + 1}/{tries}), waiting 15 s")
            await asyncio.sleep(15)
        return None, err
