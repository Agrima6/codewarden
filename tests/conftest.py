import pytest

from codewarden.config import Config

SAMPLE_DIFF = """diff --git a/app/db.py b/app/db.py
index 1111111..2222222 100644
--- a/app/db.py
+++ b/app/db.py
@@ -10,6 +10,8 @@ def connect():
     conn = open_conn()
     return conn

+def find(conn, name):
+    return conn.execute(f"SELECT * FROM users WHERE name = '{name}'")

 def close(conn):
     conn.close()
@@ -30,2 +32,3 @@ def other():
     a = 1
-    b = 2
+    b = 3
+    c = 4
diff --git a/package-lock.json b/package-lock.json
index 3333333..4444444 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,2 +1,2 @@
-old
+new
"""


@pytest.fixture
def sample_diff():
    return SAMPLE_DIFF


@pytest.fixture
def cfg():
    c = Config()
    c.rag.enabled = False
    return c


class StubLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response
