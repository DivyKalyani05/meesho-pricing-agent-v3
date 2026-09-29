"""Read-only data browser for the Data tab: paging, search, sorting, exact filters, CSV export."""
import csv
import io
import sqlite3

from .engine import InputError

MAX_PAGE = 100
MAX_CSV_ROWS = 20000


class DBView:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _con(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        return con

    def _schema(self, con):
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        out = {}
        for t in tables:
            fks = {f[3]: {"table": f[2], "column": f[4]} for f in con.execute(f'PRAGMA foreign_key_list("{t}")')}
            cols = [{"name": c[1], "type": c[2] or "TEXT", "pk": bool(c[5]), "fk": fks.get(c[1])}
                    for c in con.execute(f'PRAGMA table_info("{t}")')]
            out[t] = cols
        return out

    def schema(self):
        con = self._con()
        try:
            sch = self._schema(con)
            tables = []
            for t, cols in sch.items():
                n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                refs = sorted({o for o, ocols in sch.items() for c in ocols if c["fk"] and c["fk"]["table"] == t})
                tables.append({"table": t, "rows": n, "columns": cols, "referenced_by": refs})
            return {"tables": tables}
        finally:
            con.close()

    def _query(self, con, name, q, filter_col, filter_val, sort, direction):
        sch = self._schema(con)
        if name not in sch:
            raise InputError("Unknown table.")
        cols = [c["name"] for c in sch[name]]
        where, params = [], []
        if filter_col:
            if filter_col not in cols:
                raise InputError("Unknown filter column.")
            where.append(f'CAST("{filter_col}" AS TEXT) = ?')
            params.append(str(filter_val))
        if q:
            q = str(q)[:100]
            where.append("(" + " OR ".join(f'CAST("{c}" AS TEXT) LIKE ?' for c in cols) + ")")
            params += [f"%{q}%"] * len(cols)
        sql_where = (" WHERE " + " AND ".join(where)) if where else ""
        order = ""
        if sort:
            if sort not in cols:
                raise InputError("Unknown sort column.")
            order = f' ORDER BY "{sort}" {"DESC" if direction == "desc" else "ASC"}'
        else:
            order = " ORDER BY rowid DESC" if name == "pricing_recommendations" else " ORDER BY rowid"
        return sch[name], cols, sql_where, params, order

    def page(self, name, page=1, size=25, q="", filter_col="", filter_val="", sort="", direction="asc"):
        try:
            page, size = max(1, int(page)), max(1, min(MAX_PAGE, int(size)))
        except (TypeError, ValueError):
            raise InputError("Invalid page.")
        con = self._con()
        try:
            columns, cols, where, params, order = self._query(con, name, q, filter_col, filter_val, sort, direction)
            total = con.execute(f'SELECT count(*) FROM "{name}"{where}', params).fetchone()[0]
            pages = max(1, -(-total // size))
            page = min(page, pages)
            select = ", ".join(f'"{c}"' for c in cols)
            rows = con.execute(f'SELECT {select} FROM "{name}"{where}{order} LIMIT ? OFFSET ?',
                               params + [size, (page - 1) * size]).fetchall()
            # long JSON blobs are trimmed for display (the CSV has them in full)
            rows = [[(v[:160] + "…") if isinstance(v, str) and len(v) > 160 else v for v in r] for r in rows]
            return {"table": name, "columns": columns, "rows": rows, "total": total, "page": page,
                    "pages": pages, "size": size}
        finally:
            con.close()

    def csv(self, name, q="", filter_col="", filter_val="", sort="", direction="asc"):
        con = self._con()
        try:
            _, cols, where, params, order = self._query(con, name, q, filter_col, filter_val, sort, direction)
            select = ", ".join(f'"{c}"' for c in cols)
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            for r in con.execute(f'SELECT {select} FROM "{name}"{where}{order} LIMIT {MAX_CSV_ROWS}', params):
                w.writerow(r)
            return buf.getvalue()
        finally:
            con.close()
