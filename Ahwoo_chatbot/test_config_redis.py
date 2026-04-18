"""
test_config_redis.py — Bug B3 修復驗證
測試範圍：
  1. config.py 正確讀取 UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
  2. 缺少任一 Upstash 變數時，import config 立即 raise KeyError（fail fast）
  3. session_handler._get_redis() 使用 config 的值初始化，不再繞道 os.environ

執行：python3 test_config_redis.py
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ── 確保從專案根目錄匯入 ─────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# ── 第三方套件 stub（本地無安裝時也能執行）──────────────────────────────────
def _install_stubs():
    """若環境沒有 upstash_redis / dotenv，插入 stub 避免 ImportError。"""
    if "dotenv" not in sys.modules:
        stub = types.ModuleType("dotenv")
        stub.load_dotenv = lambda *a, **kw: None
        sys.modules["dotenv"] = stub

    if "upstash_redis" not in sys.modules:
        stub = types.ModuleType("upstash_redis")
        stub_async = types.ModuleType("upstash_redis.asyncio")
        stub_async.Redis = MagicMock
        stub.asyncio = stub_async
        sys.modules["upstash_redis"] = stub
        sys.modules["upstash_redis.asyncio"] = stub_async

_install_stubs()


# ── 輔助：清除模組快取以便重新 import ───────────────────────────────────────
def _reload_config(extra_env: dict) -> types.ModuleType:
    """以指定的 env 重新 import config，回傳模組物件。"""
    for mod in list(sys.modules.keys()):
        if mod in ("config",):
            del sys.modules[mod]
    with patch.dict(os.environ, extra_env, clear=False):
        import config as cfg
        return cfg


# ── 測試用基礎 env（所有必填變數）──────────────────────────────────────────
BASE_ENV = {
    "LINE_CHANNEL_SECRET":        "fake_secret",
    "LINE_CHANNEL_ACCESS_TOKEN":  "fake_token",
    "TELEGRAM_BOT_TOKEN":         "fake_tg_token",
    "TELEGRAM_CHAT_ID":           "12345",
    "GOOGLE_SHEET_ID":            "fake_sheet_id",
    "UPSTASH_REDIS_REST_URL":     "https://test.upstash.io",
    "UPSTASH_REDIS_REST_TOKEN":   "fake_redis_token",
}


class TestConfigLoadsUpstash(unittest.TestCase):
    """config.py 正確從 env 讀取 Upstash 變數"""

    def test_upstash_url_loaded(self):
        """config.UPSTASH_REDIS_REST_URL 應等於環境變數值"""
        cfg = _reload_config(BASE_ENV)
        self.assertEqual(cfg.UPSTASH_REDIS_REST_URL, "https://test.upstash.io")

    def test_upstash_token_loaded(self):
        """config.UPSTASH_REDIS_REST_TOKEN 應等於環境變數值"""
        cfg = _reload_config(BASE_ENV)
        self.assertEqual(cfg.UPSTASH_REDIS_REST_TOKEN, "fake_redis_token")


class TestConfigFailFastOnMissingUpstash(unittest.TestCase):
    """缺少 Upstash 變數時應在 import 時就 raise KeyError"""

    def test_missing_url_raises(self):
        """缺少 UPSTASH_REDIS_REST_URL → KeyError"""
        env = {k: v for k, v in BASE_ENV.items() if k != "UPSTASH_REDIS_REST_URL"}
        # 確保環境中真的沒有此變數
        env_without_url = {**env, "UPSTASH_REDIS_REST_URL": ""}
        # 用完整移除的方式測試
        for mod in list(sys.modules.keys()):
            if mod == "config":
                del sys.modules[mod]
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("UPSTASH_REDIS_REST_URL", None)
            with self.assertRaises(KeyError):
                import config  # noqa: F401

    def test_missing_token_raises(self):
        """缺少 UPSTASH_REDIS_REST_TOKEN → KeyError"""
        for mod in list(sys.modules.keys()):
            if mod == "config":
                del sys.modules[mod]
        env = {k: v for k, v in BASE_ENV.items()}
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)
            with self.assertRaises(KeyError):
                import config  # noqa: F401


SESSION_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "handlers", "session_handler.py"
)


class TestSessionHandlerUsesConfig(unittest.TestCase):
    """session_handler.py 原始碼必須透過 config 取得 Upstash 變數，不直接讀 os.environ"""

    def _read_src(self) -> str:
        with open(SESSION_HANDLER_PATH, encoding="utf-8") as f:
            return f.read()

    def test_no_direct_os_environ_upstash_url(self):
        """不應出現 os.environ["UPSTASH_REDIS_REST_URL"]"""
        self.assertNotIn(
            'os.environ["UPSTASH_REDIS_REST_URL"]',
            self._read_src(),
            "session_handler 仍直接用 os.environ 讀 URL，應改用 config"
        )

    def test_no_direct_os_environ_upstash_token(self):
        """不應出現 os.environ["UPSTASH_REDIS_REST_TOKEN"]"""
        self.assertNotIn(
            'os.environ["UPSTASH_REDIS_REST_TOKEN"]',
            self._read_src(),
            "session_handler 仍直接用 os.environ 讀 TOKEN，應改用 config"
        )

    def test_uses_config_url(self):
        """應使用 config.UPSTASH_REDIS_REST_URL"""
        self.assertIn(
            "config.UPSTASH_REDIS_REST_URL",
            self._read_src(),
            "session_handler 未改用 config.UPSTASH_REDIS_REST_URL"
        )

    def test_uses_config_token(self):
        """應使用 config.UPSTASH_REDIS_REST_TOKEN"""
        self.assertIn(
            "config.UPSTASH_REDIS_REST_TOKEN",
            self._read_src(),
            "session_handler 未改用 config.UPSTASH_REDIS_REST_TOKEN"
        )


# ── 執行 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestConfigLoadsUpstash,
                TestConfigFailFastOnMissingUpstash,
                TestSessionHandlerUsesConfig]:  # type: ignore
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
