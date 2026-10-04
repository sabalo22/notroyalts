
import sqlite3
import shutil
from pathlib import Path
APP=Path.home()/"Library"/"Application Support"/"NotRoyalTs"
DB=APP/"notroyalts.db"

LEGACY_APP=Path.home()/"Library"/"Application Support"/"SSHDesk"
LEGACY_DB=LEGACY_APP/"sshdesk.db"

def migrate_legacy_database():
    """Carry the existing SSHDesk database into the renamed app once."""
    if DB.exists() or not LEGACY_DB.exists():
        return
    APP.mkdir(parents=True,exist_ok=True)
    shutil.copy2(LEGACY_DB,DB)

migrate_legacy_database()


def c():
    APP.mkdir(parents=True,exist_ok=True)
    x=sqlite3.connect(DB); x.row_factory=sqlite3.Row; x.execute("PRAGMA foreign_keys=ON"); return x
def init():
    with c() as x:x.executescript("""
    CREATE TABLE IF NOT EXISTS folders(id INTEGER PRIMARY KEY,name TEXT NOT NULL,parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS connections(id INTEGER PRIMARY KEY,name TEXT NOT NULL,folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,host TEXT NOT NULL,port INTEGER DEFAULT 22,username TEXT NOT NULL,identity_file TEXT,proxy_jump TEXT,extra_args TEXT,notes TEXT,sort_order INTEGER DEFAULT 0);
    """)
def folders():
    with c() as x:
        return x.execute(
            "SELECT * FROM folders ORDER BY COALESCE(parent_id,0), name COLLATE NOCASE"
        ).fetchall()
def conns(q=""):
    with c() as x:
        if q:
            q=f"%{q}%";return x.execute("SELECT * FROM connections WHERE name LIKE ? OR host LIKE ? ORDER BY name COLLATE NOCASE",(q,q)).fetchall()
        return x.execute("SELECT * FROM connections ORDER BY name COLLATE NOCASE").fetchall()
def conn(i):
    with c() as x:return x.execute("SELECT * FROM connections WHERE id=?",(i,)).fetchone()
def add_folder(n,p=None):
    with c() as x:x.execute("INSERT INTO folders(name,parent_id) VALUES(?,?)",(n,p))
def rename_folder(i,n):
    with c() as x:x.execute("UPDATE folders SET name=? WHERE id=?",(n,i))
def del_folder(i):
    with c() as x:x.execute("DELETE FROM folders WHERE id=?",(i,))
def save_conn(d,i=None):
    vals=(d["name"],d.get("folder_id"),d["host"],d["port"],d["username"],d.get("identity_file") or None,d.get("proxy_jump") or None,d.get("extra_args") or None,d.get("notes") or None)
    with c() as x:
        if i:x.execute("UPDATE connections SET name=?,folder_id=?,host=?,port=?,username=?,identity_file=?,proxy_jump=?,extra_args=?,notes=? WHERE id=?",vals+(i,))
        else:x.execute("INSERT INTO connections(name,folder_id,host,port,username,identity_file,proxy_jump,extra_args,notes) VALUES(?,?,?,?,?,?,?,?,?)",vals)
def del_conn(i):
    with c() as x:x.execute("DELETE FROM connections WHERE id=?",(i,))


def import_folder(name, parent_id=None, sort_order=0):
    with c() as x:
        cur=x.execute(
            "INSERT INTO folders(name,parent_id,sort_order) VALUES(?,?,?)",
            (name, parent_id, int(sort_order or 0))
        )
        return int(cur.lastrowid)

def find_folder(name, parent_id=None):
    with c() as x:
        if parent_id is None:
            return x.execute(
                "SELECT * FROM folders WHERE name=? AND parent_id IS NULL LIMIT 1",
                (name,)
            ).fetchone()
        return x.execute(
            "SELECT * FROM folders WHERE name=? AND parent_id=? LIMIT 1",
            (name,parent_id)
        ).fetchone()

def connection_exists(folder_id, name, host, port):
    with c() as x:
        if folder_id is None:
            row=x.execute(
                """SELECT id FROM connections
                   WHERE folder_id IS NULL AND name=? AND host=? AND port=?
                   LIMIT 1""",
                (name,host,int(port))
            ).fetchone()
        else:
            row=x.execute(
                """SELECT id FROM connections
                   WHERE folder_id=? AND name=? AND host=? AND port=?
                   LIMIT 1""",
                (folder_id,name,host,int(port))
            ).fetchone()
        return row is not None


def update_folder_sort(folder_id, sort_order):
    with c() as x:
        x.execute(
            "UPDATE folders SET sort_order=? WHERE id=?",
            (int(sort_order or 0), folder_id)
        )
