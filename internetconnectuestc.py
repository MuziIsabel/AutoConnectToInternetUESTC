#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动认证 - requests版 (无Selenium依赖)

适配电子科技大学新门户 (锐捷 RG-SMP+/SAM 5.0, CAS SSO 登录)。
旧 ePortal (172.x / InterFace.do) 逻辑已废弃移除。

配置: 通过 .env 文件或环境变量设置
  UESTC_PHONE              - 手机号/学号 (必填)
  UESTC_PASSWORD           - 密码 (必填)
  UESTC_HOST               - ping 探测地址 (默认 223.5.5.5)
  UESTC_WAIT_TIME          - 主循环检测间隔秒数 (默认 10)
  UESTC_PORTAL_BASE        - 门户基址 (默认 http://110.184.24.61)
  UESTC_HEARTBEAT_INTERVAL - 在线状态心跳间隔秒数 (默认 60)
  UESTC_SESSION_CACHE_ENABLED - 启用本地会话缓存, 重启后复用 sessionId (默认 1)
  UESTC_SESSION_STATE_PATH    - 本地会话缓存文件路径
  UESTC_LOG_PATH           - 日志文件路径
  UESTC_DEBUG              - DEBUG 日志开关 (默认 0)
"""

import time
import datetime
import os
import sys
import re
import json
import base64
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode

try:
    import ping3
except ImportError:
    ping3 = None

import requests
from bs4 import BeautifulSoup

# AES-128-ECB-PKCS7 加密, 用于 CAS SSO 登录的密码/captcha_payload 字段
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError:
    AES = None
    pad = None


# ---------------------------------------------------------------------------
# 环境变量 & CA证书
# ---------------------------------------------------------------------------

def _runtime_candidate_dirs() -> list:
    """返回配置/日志搜索目录, 兼容源码运行和 PyInstaller exe 自启动。"""
    candidates = []
    base_paths = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        base_paths.extend([Path.cwd(), exe_dir, exe_dir.parent])
    else:
        script_dir = Path(__file__).resolve().parent
        base_paths.extend([Path.cwd(), script_dir])
    for p in base_paths:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def _load_env_file() -> Optional[Path]:
    """读取 .env; 默认依次查找当前目录、exe 目录、源码目录。"""
    paths = [base / ".env" for base in _runtime_candidate_dirs()]
    for env_path in paths:
        if not env_path.exists():
            continue
        try:
            content = env_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return env_path
    return None


def _default_log_path() -> Path:
    """日志默认写到项目目录; exe 在 dist/ 自启动时也能落到项目根目录。"""
    explicit = os.getenv("UESTC_LOG_PATH", "").strip()
    if explicit:
        return Path(explicit)
    for base in _runtime_candidate_dirs():
        if (base / ".env").exists() or (base / "internetconnectuestc.py").exists():
            return base / "BOCCHI THE ROCK.log"
    return Path.cwd() / "BOCCHI THE ROCK.log"


def _default_session_state_path() -> Path:
    """本地会话缓存默认写到项目目录, 避免重启后丢失 sessionId。"""
    explicit = os.getenv("UESTC_SESSION_STATE_PATH", "").strip()
    if explicit:
        return Path(explicit)
    for base in _runtime_candidate_dirs():
        if (base / ".env").exists() or (base / "internetconnectuestc.py").exists():
            return base / ".uestc_session_state.json"
    return Path.cwd() / ".uestc_session_state.json"


def _get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "y")


def _get_env_int(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(minimum, int(raw_value))
    except ValueError:
        return default


def _preload_requests_ca_bundle_env() -> None:
    """在 import requests 之前设置 CA 证书路径 (PyInstaller 兼容)"""
    try:
        import certifi
        ca_path = certifi.where()
        if ca_path and Path(ca_path).exists():
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
            os.environ.setdefault("SSL_CERT_FILE", ca_path)
            return
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if isinstance(meipass, str) and meipass:
        candidate = Path(meipass).joinpath("certifi", "cacert.pem")
        if candidate.exists():
            ca_path = str(candidate)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
            os.environ.setdefault("SSL_CERT_FILE", ca_path)


_preload_requests_ca_bundle_env()


# ---------------------------------------------------------------------------
# 主连接类
# ---------------------------------------------------------------------------

class ConnectRequests:
    """基于 requests 的校园网自动认证 (锐捷 SAM 5.0 CAS SSO, 无 Selenium 依赖)"""

    # 默认门户基址 (学校新门户)
    DEFAULT_PORTAL_BASE = "http://110.184.24.61"
    # CAS SSO 登录路径
    CAS_LOGIN_PATH = "/cas-sso/login"
    # 工作流节点查询
    WORKFLOW_GET_NODE_PATH = "/eportal/workFlow/getCurrentNode"
    # 上线接口
    NETWORK_USERONLINE_PATH = "/eportal/network/userOnline"
    # 在线用户信息 (心跳/保活)
    GET_ONLINE_USER_INFO_PATH = "/eportal/adaptor/getOnlineUserInfo"
    # 终端信息查询 (拿 userIp/nasIp)
    QUERY_TERMINAL_INFO_PATH = "/eportal/adaptor/queryTerminalInfo"
    # 触发 AC 重定向用的外部探测地址 (会被劫持到门户)
    AC_PROBE_URL = "http://123.123.123.123/"

    def __init__(self):
        loaded_env_path = _load_env_file()
        self.logger = self._log_config()
        if loaded_env_path:
            self.logger.debug(f"已加载配置文件: {loaded_env_path}")
        else:
            self.logger.debug("未找到 .env 配置文件, 将仅使用系统环境变量")

        self.PHONENUM = os.getenv("UESTC_PHONE", "").strip()
        self.PASSWD = os.getenv("UESTC_PASSWORD", "")
        self.host = os.getenv("UESTC_HOST", "223.5.5.5").strip()
        self.waitime = _get_env_int("UESTC_WAIT_TIME", 10)
        self.portal_base = os.getenv("UESTC_PORTAL_BASE", self.DEFAULT_PORTAL_BASE).strip().rstrip("/")
        self.heartbeat_interval = _get_env_int("UESTC_HEARTBEAT_INTERVAL", 60)
        # 会话缓存
        self.session_state_enabled = _get_env_bool("UESTC_SESSION_CACHE_ENABLED", True)
        self.session_state_path = _default_session_state_path()
        # CAS 会话状态: sessionId 由服务端分配, 缓存复用
        self.session_id = ""
        self.user_ip = ""
        self.nas_ip = ""
        self.user_index = ""
        # 时间追踪
        self.last_login_at: Optional[datetime.datetime] = None
        self.last_heartbeat_at: Optional[datetime.datetime] = None
        self.auth_success_count = 0
        self.auth_fail_count = 0
        # 心跳状态
        self.heartbeat_confirmed_online = False
        self.heartbeat_offline_count = 0

        self._load_session_state()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
            ),
            # 部分校园网门户会在未声明 Content-Encoding 的情况下返回压缩内容,
            # 明确要求 identity 可以减少乱码页面导致的误判。
            "Accept-Encoding": "identity",
            # 不要设置 Accept-Language: 失效 sessionId 会被电信链路改写成
            # HTTP 555 并跳转到 189.cn, 从而掩盖门户返回的业务 code=400。
        })
        # 不验证 SSL (门户可能自签证书)
        self.session.verify = False

        self._ensure_ca_bundle()

        if not self.PHONENUM or not self.PASSWD:
            self.logger.error(
                "未设置账号密码环境变量: 请设置 UESTC_PHONE / UESTC_PASSWORD 后再运行。"
            )
            raise SystemExit(2)

        if AES is None:
            self.logger.error(
                "pycryptodome 未安装, CAS SSO 登录需要 AES 加密; 请运行 pip install pycryptodome"
            )
            raise SystemExit(2)

        self.logger.info("校园网自动认证(CAS SSO版)已启动 ♪(´▽｀)")
        self.logger.info(f"门户基址: {self.portal_base} | 心跳间隔={self.heartbeat_interval}s")
        if self.session_id:
            self.logger.info(
                f"已从缓存加载 sessionId: {self._mask_value(self.session_id)} "
                f"(userIp={self._mask_value(self.user_ip)})"
            )

    # --- 辅助方法 ---

    def _ensure_ca_bundle(self):
        """确保 HTTPS 证书路径可用 (PyInstaller 兼容)"""
        try:
            import certifi
            ca_path = certifi.where()
            if ca_path and Path(ca_path).exists():
                os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
                os.environ.setdefault("SSL_CERT_FILE", ca_path)
                try:
                    import requests.adapters as ra
                    import requests.utils as ru
                    ra.DEFAULT_CA_BUNDLE_PATH = ca_path
                    ru.DEFAULT_CA_BUNDLE_PATH = ca_path
                except Exception:
                    pass
        except ImportError:
            self.logger.warning("certifi 未安装, HTTPS 可能受影响")

    def _log_config(self) -> logging.Logger:
        logger = logging.getLogger("BOCCHI")
        logger.setLevel(logging.DEBUG)

        debug_mode = os.getenv("UESTC_DEBUG", "").strip() in ("1", "true", "yes")
        if "--debug" in sys.argv:
            debug_mode = True
        console_level = logging.DEBUG if debug_mode else logging.INFO

        if logger.handlers:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        log_path = _default_log_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            log_path = Path.cwd() / "BOCCHI THE ROCK.log"
        fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s:%(levelname)s:%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # 控制台 handler: PyInstaller -w 模式下 sys.stdout 是 GBK 管道,
        # 无法输出颜文字/特殊符号 (UnicodeEncodeError), 所以无控制台时跳过;
        # 有真实控制台时也用 errors='replace' 兜底, 避免偶发编码异常中断主循环。
        real_console = sys.stdout is not None and hasattr(sys.stdout, "fileno")
        try:
            real_console = real_console and sys.stdout.fileno() >= 0
        except (OSError, ValueError):
            real_console = False
        if real_console and not getattr(sys, "frozen", False):
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(console_level)
            ch.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)-5s %(message)s",
                datefmt="%H:%M:%S",
            ))
            logger.addHandler(ch)

        logger.info(f"日志文件已打开: {log_path}")
        if debug_mode:
            logger.info("DEBUG 模式已启用 (文件+控制台均 DEBUG)")
        else:
            logger.debug("控制台 INFO 级别; 文件 DEBUG 级别 (设置 UESTC_DEBUG=1 开启控制台 DEBUG)")

        return logger

    # --- 脱敏 ---

    def _mask_value(self, value, head: int = 8, tail: int = 6) -> str:
        """日志里遮蔽 sessionId、ticket、账号、IP 等敏感值。"""
        text = str(value or "")
        if not text:
            return ""
        if len(text) <= head + tail + 3:
            return text[: max(1, min(4, len(text)))] + "..."
        return f"{text[:head]}...{text[-tail:]}"

    def _sanitize_log_text(self, text: str) -> str:
        """避免 DEBUG 日志泄露 sessionId、ticket、账号、IP/MAC、Cookie 等信息。"""
        sanitized = str(text or "")
        # JSON 键
        sensitive_json_keys = (
            "sessionId", "userIndex", "userName", "userId", "account", "username",
            "userIp", "online_ip", "client_ip", "userMac", "nasIp",
            "ticket", "execution", "croypto", "flowSessionId",
        )
        for key in sensitive_json_keys:
            sanitized = re.sub(
                rf'("{key}"\s*:\s*")([^"]+)(")',
                lambda m: m.group(1) + self._mask_value(m.group(2)) + m.group(3),
                sanitized,
                flags=re.IGNORECASE,
            )
        # URL 查询参数
        sanitized = re.sub(
            r'([?&](?:sessionId|flowsessionid|userindex|userip|nasip|wlanparameter|'
            r'userlocation|usermac|mac|username|userid|useraccount|pwd|password|'
            r'userpassword|pass|phone|account|ticket|execution|croypto)=)([^&\s"\']+)',
            lambda m: m.group(1) + self._mask_value(m.group(2)),
            sanitized,
            flags=re.IGNORECASE,
        )
        # 门户错误文案会把令牌嵌在普通文本中, 例如 sessionId:abcdef123456。
        sanitized = re.sub(
            r'((?:sessionId|flowSessionId|userIndex)\s*[:=]\s*)([A-Za-z0-9._~-]+)',
            lambda m: m.group(1) + self._mask_value(m.group(2)),
            sanitized,
            flags=re.IGNORECASE,
        )
        # Cookie
        sanitized = re.sub(
            r'(JSESSIONID=)([^;\s]+)',
            lambda m: m.group(1) + self._mask_value(m.group(2)),
            sanitized,
            flags=re.IGNORECASE,
        )
        return sanitized

    # --- 会话缓存 (version 3, CAS SSO 字段) ---

    def _load_session_state(self) -> None:
        """加载上一次成功登录保存的 sessionId/userIp/nasIp, 供重启后复用。"""
        if not self.session_state_enabled:
            self.logger.debug("本地会话缓存已禁用")
            return
        path = self.session_state_path
        if not path.exists():
            self.logger.debug(f"未找到本地会话缓存: {path}")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("缓存文件不是 JSON 对象")
        except Exception as e:
            self.logger.warning(f"读取本地会话缓存失败, 将忽略旧缓存: {e}")
            return

        version = data.get("version", 0)
        self.session_id = str(data.get("session_id") or "").strip()
        self.user_ip = str(data.get("user_ip") or "").strip()
        self.nas_ip = str(data.get("nas_ip") or "").strip()
        self.user_index = str(data.get("user_index") or "").strip()

        def _parse_dt(val):
            if not val:
                return None
            try:
                return datetime.datetime.fromisoformat(str(val))
            except Exception:
                return None

        self.last_login_at = _parse_dt(data.get("last_login_at"))
        self.last_heartbeat_at = _parse_dt(data.get("last_heartbeat_at"))
        try:
            self.auth_success_count = max(0, int(data.get("auth_success_count") or 0))
            self.auth_fail_count = max(0, int(data.get("auth_fail_count") or 0))
        except (TypeError, ValueError):
            pass

        if version < 3:
            self.logger.info(
                f"会话缓存版本从 v{version} 升级到 v3 (旧 ePortal 缓存字段已弃用)"
            )
        if self.session_id:
            self.logger.info(f"已从缓存加载 sessionId: {self._mask_value(self.session_id)}")

    def _save_session_state(self, reason: str = "") -> None:
        """保存 sessionId/userIp/nasIp; 文件已加入 .gitignore, 不输出明文。"""
        if not self.session_state_enabled:
            return
        data = {
            "version": 3,
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "session_id": self.session_id,
            "user_ip": self.user_ip,
            "nas_ip": self.nas_ip,
            "user_index": self.user_index,
            "last_login_at": self.last_login_at.isoformat(timespec="seconds") if self.last_login_at else None,
            "last_heartbeat_at": self.last_heartbeat_at.isoformat(timespec="seconds") if self.last_heartbeat_at else None,
            "auth_success_count": self.auth_success_count,
            "auth_fail_count": self.auth_fail_count,
        }
        try:
            self.session_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.session_state_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                os.chmod(self.session_state_path, 0o600)
            except Exception:
                pass
            self.logger.debug(f"已更新本地会话缓存{reason}".rstrip())
        except Exception as e:
            self.logger.warning(f"写入本地会话缓存失败: {e}")

    # --- HTTP 请求/响应日志 ---

    def _response_text_best_effort(self, resp: requests.Response) -> str:
        """用最佳编码解码响应体, 避免日志显示乱码。"""
        raw = resp.content or b""
        if not raw:
            return resp.text or ""
        declared = (resp.encoding or "").lower()
        candidates = ["utf-8"]
        if declared and declared != "iso-8859-1" and declared not in candidates:
            candidates.append(declared)
        for enc in ("gbk", "gb18030", "gb2312"):
            if enc not in candidates:
                candidates.append(enc)
        ae = resp.apparent_encoding
        if ae and ae.lower() not in candidates:
            candidates.append(ae.lower())
        for enc in candidates:
            if not enc:
                continue
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return resp.text or ""

    def _log_response(self, resp: requests.Response, label: str = "") -> None:
        """详细记录 HTTP 响应信息 (DEBUG 级别)"""
        prefix = f"[{label}] " if label else ""
        decoded_text = self._response_text_best_effort(resp)
        self.logger.debug(
            f"{prefix}<<< 响应: {resp.status_code} {resp.reason} | "
            f"url={self._sanitize_log_text(resp.url)} | len={len(decoded_text)} | "
            f"encoding={resp.encoding}"
        )
        interesting_headers = [
            "Content-Type", "Content-Encoding", "Content-Length",
            "Set-Cookie", "Location", "Server",
        ]
        hdrs = {
            k: ("<已脱敏>" if k.lower() == "set-cookie" else self._sanitize_log_text(v))
            for k, v in resp.headers.items()
            if k in interesting_headers
        }
        if hdrs:
            self.logger.debug(f"{prefix}    响应头: {hdrs}")
        body_preview = decoded_text[:500].replace("\n", "\\n").replace("\r", "")
        self.logger.debug(f"{prefix}    响应体(前500): {self._sanitize_log_text(body_preview)}")

    def _log_request_summary(self, method: str, url: str, **kwargs) -> None:
        """记录即将发出的 HTTP 请求摘要 (DEBUG 级别)"""
        data = kwargs.get("data") or kwargs.get("json") or kwargs.get("params")
        data_desc = ""
        if data:
            safe = {}
            if isinstance(data, dict):
                for k, v in data.items():
                    key_lower = k.lower()
                    if any(p in key_lower for p in ("pwd", "pass", "password", "phone", "account")) or key_lower in (
                        "username", "userid", "sessionid", "flowsessionid", "userindex",
                        "userip", "nasip", "ticket", "execution", "croypto",
                    ):
                        safe[k] = self._mask_value(v)
                    else:
                        safe[k] = v
                data_desc = self._sanitize_log_text(str(safe))[:200]
            else:
                data_desc = self._sanitize_log_text(str(data))[:200]
        self.logger.debug(f">>> {method} {self._sanitize_log_text(url)} | data={data_desc}")

    # --- 网络探测 ---

    def is_connected(self) -> int:
        """
        检测网络连通性
        返回: 0=已连接, 2=断网
        """
        if ping3 is None:
            self.logger.warning("ping3 未安装, 无法执行网络探测; 请先运行 pip install -r requirements.txt")
            return 2
        try:
            response_time = ping3.ping(self.host, timeout=2)
        except Exception as e:
            self.logger.warning(f"网络探测失败: {e}")
            return 2
        if response_time is not None:
            self.logger.debug("网络连接正常 (●'◡'●)")
            return 0
        else:
            self.logger.info("检测到断网 (っ °Д °;)っ")
            return 2

    # ===================================================================
    # CAS SSO 认证 (锐捷 SAM 5.0)
    # ===================================================================

    @staticmethod
    def _aes_encrypt(key_b64: str, plaintext: str) -> str:
        """AES-128-ECB-PKCS7 加密, 返回 base64 字符串。

        与 cas-login 前端 Ln.aesEncrypt 等价:
          key = base64decode(login-croypto)   # 16 字节
          ct = AES.encrypt(plaintext, key, mode=ECB, padding=Pkcs7)
          return base64(ct)
        """
        if AES is None or pad is None:
            raise RuntimeError("pycryptodome 未安装, 无法执行 AES 加密")
        key_bytes = base64.b64decode(key_b64)
        cipher = AES.new(key_bytes, AES.MODE_ECB)
        ct = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        return base64.b64encode(ct).decode("ascii")

    @staticmethod
    def _extract_cas_tokens(html: str) -> Tuple[str, str]:
        """从 cas-sso/login 响应 HTML 提取两个 hidden token。

        返回 (croypto_key, execution):
          croypto_key: #login-croypto 元素内容, AES key 的 base64 (24字符)
          execution:   #login-page-flowkey 元素内容, CAS 状态令牌 (~4881字符)
        """
        croypto_key = ""
        execution = ""

        # 用 BeautifulSoup 解析, 兼容属性顺序和引号风格
        soup = BeautifulSoup(html, "html.parser")
        node = soup.find(id="login-croypto")
        if node and node.get_text(strip=True):
            croypto_key = node.get_text(strip=True)
        node = soup.find(id="login-page-flowkey")
        if node and node.get_text(strip=True):
            execution = node.get_text(strip=True)

        # 正则兜底 (BeautifulSoup 对极端畸形 HTML 可能漏)
        if not croypto_key:
            m = re.search(r'id="login-croypto"[^>]*>([^<]+)<', html)
            if m:
                croypto_key = m.group(1).strip()
        if not execution:
            m = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', html)
            if m:
                execution = m.group(1).strip()

        return croypto_key, execution

    def _build_cas_login_url(self, flow_session_id: str, user_ip: str = "", nas_ip: str = "") -> str:
        """构造 /cas-sso/login 的完整 URL (含 query)。"""
        params = {
            "flowSessionId": flow_session_id,
            "customPageId": "5f8dcce7c1904743951c7112e62691b7",
            "preview": "false",
            "appType": "normal",
            "language": "zh-CN",
            "timer": str(int(time.time() * 1000)),
        }
        if user_ip:
            params["userIp"] = user_ip
        if nas_ip:
            params["nasIp"] = nas_ip
        return urljoin(self.portal_base, self.CAS_LOGIN_PATH) + "?" + urlencode(params)

    def _get_current_node(self, session_id: str) -> Optional[Dict[str, Any]]:
        """POST /eportal/workFlow/getCurrentNode, 验证 sessionId 有效性并返回节点信息。

        成功返回 {"currentNodePath": "...", "sessionId": "...", ...};
        sessionId 失效返回 code!=200 (message 含 "没有查找到当前sessionId");
        其他异常返回 None。
        """
        url = urljoin(self.portal_base, self.WORKFLOW_GET_NODE_PATH)
        payload = {"sessionId": session_id, "flowKey": "portal_auth"}
        headers = {"Content-Type": "application/json", "isPortal": "true"}
        self._log_request_summary("POST", url, json=payload)
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=10, allow_redirects=False)
        except requests.RequestException as e:
            self.logger.warning(f"getCurrentNode 请求失败: {e}")
            return None
        self._log_response(resp, "getCurrentNode")
        try:
            data = resp.json()
        except ValueError:
            self.logger.warning(f"getCurrentNode 响应非 JSON: HTTP {resp.status_code}")
            return None
        code = data.get("code")
        if code != 200:
            detail = self._sanitize_log_text(f"code={code} message={data.get('message')}")
            self.logger.debug(f"getCurrentNode 失败: {detail}")
            return data
        return data

    @staticmethod
    def _is_invalid_session_response(node_info: Optional[Dict[str, Any]]) -> bool:
        """判断 getCurrentNode 是否明确表示 sessionId 已失效。"""
        if not isinstance(node_info, dict) or node_info.get("code") != 400:
            return False
        message = str(node_info.get("message") or "").lower()
        return "sessionid" in message or "session id" in message

    def _clear_invalid_session(self) -> None:
        """清除门户已判定失效的会话, 等真实断网时重新捕获。"""
        self.logger.warning("缓存 sessionId 已失效, 清除旧会话并等待断网后重新捕获 (＞﹏＜)")
        self.session_id = ""
        self.user_ip = ""
        self.nas_ip = ""
        self.user_index = ""
        self.heartbeat_confirmed_online = False
        self.heartbeat_offline_count = 0
        self._save_session_state("(清除失效会话)")

    def _fetch_cas_login_page(self, flow_session_id: str, user_ip: str = "", nas_ip: str = "") -> Optional[str]:
        """GET /cas-sso/login, 返回登录页 HTML (含 croypto/execution token)。"""
        url = self._build_cas_login_url(flow_session_id, user_ip, nas_ip)
        self._log_request_summary("GET", url)
        try:
            resp = self.session.get(url, timeout=15, allow_redirects=True)
        except requests.RequestException as e:
            self.logger.warning(f"获取 CAS 登录页失败: {e}")
            return None
        self._log_response(resp, "cas-sso/login")
        if resp.status_code != 200:
            self.logger.warning(f"CAS 登录页返回 HTTP {resp.status_code}")
            return None
        return self._response_text_best_effort(resp)

    def _submit_cas_login(
        self,
        flow_session_id: str,
        croypto_key: str,
        execution: str,
        username: str,
        password: str,
        user_ip: str = "",
        nas_ip: str = "",
    ) -> Optional[str]:
        """POST /cas-sso/login 提交加密的账密, 跟随 302 拿 ticket。

        成功返回 Location 里的 ticket; 失败返回 None。
        """
        url = self._build_cas_login_url(flow_session_id, user_ip, nas_ip) + "&accept-language=zh-CN"
        # 加密密码和 captcha_payload
        encrypted_password = self._aes_encrypt(croypto_key, password)
        captcha_payload_plain = json.dumps({}, separators=(",", ":"))
        encrypted_captcha = self._aes_encrypt(croypto_key, captcha_payload_plain)

        # form-urlencoded body (与浏览器一致, 字段顺序也保持)
        form_data = {
            "username": username,
            "type": "UsernamePassword",
            "_eventId": "submit",
            "geolocation": "",
            "execution": execution,
            "captcha_code": "",
            "croypto": croypto_key,
            "password": encrypted_password,
            "captcha_payload": encrypted_captcha,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.portal_base,
            "Referer": url,
        }
        self._log_request_summary("POST", url, data=form_data)
        try:
            # 不自动跟随 302, 手动提取 Location 里的 ticket
            resp = self.session.post(url, data=form_data, headers=headers, timeout=15, allow_redirects=False)
        except requests.RequestException as e:
            self.logger.warning(f"CAS 登录提交失败: {e}")
            return None
        self._log_response(resp, "cas-sso/login POST")

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            self.logger.debug(f"CAS 登录 302 跳转: {self._sanitize_log_text(location)}")
            # 从 location 提取 ticket (形如 .../auth-success.html?ticket=ST-xxx)
            m = re.search(r'[?&]ticket=([^&\s"\']+)', location)
            if m:
                return m.group(1)
            # 没有 ticket 的 302 通常是登录失败 (回到 login 页)
            self.logger.warning("CAS 登录 302 但未携带 ticket, 可能账密错误或被拦截")
            return None

        # 非 3xx: 登录失败, 响应体可能含错误信息
        body = self._response_text_best_effort(resp)
        self.logger.warning(f"CAS 登录未跳转: HTTP {resp.status_code}")
        # 尝试从 HTML 提取错误码 (cas 登录页 #login-error-code)
        m = re.search(r'id="login-error-code"[^>]*>([^<]+)<', body)
        if m and m.group(1).strip():
            self.logger.warning(f"登录页错误码: {m.group(1).strip()}")
        return None

    def _bring_online(self, session_id: str) -> Tuple[bool, str]:
        """POST /eportal/network/userOnline, 让服务端把终端标记为上线。

        返回 (success, detail):
          success: 响应 data.online == true
          detail: 给日志用的描述
        """
        url = urljoin(self.portal_base, self.NETWORK_USERONLINE_PATH)
        payload = {"sessionId": session_id}
        headers = {"Content-Type": "application/json", "isPortal": "true"}
        self._log_request_summary("POST", url, json=payload)
        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=10, allow_redirects=False)
        except requests.RequestException as e:
            return False, f"userOnline 请求失败: {e}"
        self._log_response(resp, "userOnline")
        try:
            data = resp.json()
        except ValueError:
            return False, f"userOnline 响应非 JSON: HTTP {resp.status_code}"
        if data.get("code") != 200:
            return False, f"userOnline code={data.get('code')} message={data.get('message')}"
        payload_data = data.get("data") or {}
        online = bool(payload_data.get("online"))
        user_index = str(payload_data.get("userIndex") or "").strip()
        if user_index and user_index != self.user_index:
            self.user_index = user_index
        detail = f"online={online} userIndex={self._mask_value(user_index)}"
        return online, detail

    def _check_online(self, session_id: str) -> Tuple[str, str]:
        """GET /eportal/adaptor/getOnlineUserInfo, 心跳用。

        返回 (state, detail):
          state: "online" | "offline" | "unknown"
          detail: 给日志用的描述
        """
        url = urljoin(self.portal_base, self.GET_ONLINE_USER_INFO_PATH)
        params = {"sessionId": session_id}
        headers = {"isPortal": "true"}
        self._log_request_summary("GET", url, params=params)
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=10, allow_redirects=False)
        except requests.RequestException as e:
            return "unknown", f"getOnlineUserInfo 请求失败: {e}"
        self._log_response(resp, "getOnlineUserInfo")
        try:
            data = resp.json()
        except ValueError:
            return "unknown", f"getOnlineUserInfo 响应非 JSON: HTTP {resp.status_code}"
        if data.get("code") != 200:
            return "unknown", f"getOnlineUserInfo code={data.get('code')} message={data.get('message')}"
        payload = data.get("data") or {}
        user_info = payload.get("portalOnlineUserInfo") or {}
        result = str(user_info.get("result") or "").lower()
        # 严格判定: 只认 result==success (与旧 ePortal 一致的严格性红线)
        if result == "success":
            keepalive_interval = user_info.get("keepaliveInterval")
            try:
                if keepalive_interval:
                    self.heartbeat_interval = max(10, int(keepalive_interval))
            except (TypeError, ValueError):
                pass
            return "online", f"result=success keepaliveInterval={keepalive_interval}"
        message = user_info.get("message") or ""
        if "offline" in message.lower() or "failed" in message.lower():
            return "offline", f"result={result} message={message}"
        return "offline", f"result={result} message={message}"

    def _query_terminal_info(self, session_id: str) -> Tuple[str, str]:
        """GET /eportal/adaptor/queryTerminalInfo, 拿本机 userIp。

        返回 (user_ip, detail)。userIp 可能为空 (服务端未识别到终端)。
        """
        url = urljoin(self.portal_base, self.QUERY_TERMINAL_INFO_PATH)
        params = {"sessionId": session_id, "macAddr": ""}
        headers = {"isPortal": "true"}
        self._log_request_summary("GET", url, params=params)
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=10, allow_redirects=False)
        except requests.RequestException as e:
            return "", f"queryTerminalInfo 请求失败: {e}"
        self._log_response(resp, "queryTerminalInfo")
        try:
            data = resp.json()
        except ValueError:
            return "", f"queryTerminalInfo 响应非 JSON: HTTP {resp.status_code}"
        if data.get("code") != 200:
            return "", f"queryTerminalInfo code={data.get('code')} message={data.get('message')}"
        payload = data.get("data") or {}
        user_ip = str(payload.get("ipAddr") or "").strip()
        return user_ip, f"ipAddr={self._mask_value(user_ip)}"

    def _rediscover_session(self) -> bool:
        """sessionId 失效时, 通过 AC 重定向重新捕获 userIp/nasIp 并触发服务端分配新 sessionId。

        策略:
          1. 访问 AC 探测地址 (http://123.123.123.123/), 被 AC 劫持重定向
          2. 从重定向链里解析 userIp/nasIp
          3. 如果当前有 sessionId, 用它重新走 getCurrentNode 让服务端刷新会话
          4. 没有 sessionId 时, 此处无法创建 (创建接口未确认), 返回 False

        返回 True 表示成功刷新了 session 元数据。
        """
        self.logger.info("触发 AC 重定向重新捕获 session 参数 (●'◡'●)...")
        try:
            resp = self.session.get(self.AC_PROBE_URL, timeout=10, allow_redirects=True)
            final_url = resp.url
            self.logger.debug(f"AC 探测最终落地: {self._sanitize_log_text(final_url)}")
            # 从最终 URL 解析 userIp/nasIp
            parsed = urlsplit(final_url)
            query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            new_user_ip = query_params.get("userIp") or query_params.get("userip") or ""
            new_nas_ip = query_params.get("nasIp") or query_params.get("nasip") or ""
            new_session_id = query_params.get("flowSessionId") or query_params.get("sessionId") or ""
            if new_user_ip:
                self.user_ip = new_user_ip
            if new_nas_ip:
                self.nas_ip = new_nas_ip
            if new_session_id and new_session_id != self.session_id:
                self.session_id = new_session_id
                self.logger.info(f"AC 重定向捕获到新 sessionId: {self._mask_value(self.session_id)}")
            if new_user_ip or new_nas_ip or new_session_id:
                self._save_session_state("(AC 重定向捕获)")
                return True
            # AC 没有劫持 (可能已在线, 或网段不触发)
            self.logger.debug("AC 探测未捕获到 session 参数 (可能已在线或网段未触发劫持)")
            return False
        except requests.RequestException as e:
            self.logger.warning(f"AC 探测失败: {e}")
            return False

    def authenticate(self) -> bool:
        """CAS SSO 认证主入口。

        完整流程:
          1. 用缓存或新获取的 sessionId 调 getCurrentNode 验证
          2. 取终端信息 (userIp)
          3. 拉 CAS 登录页, 提取 croypto_key + execution
          4. AES 加密密码, POST 提交, 跟随 302 拿 ticket
          5. 调 userOnline 上线
          6. 持久化 session

        返回 True 表示认证成功 (严格判定: userOnline 返回 online==true)。
        """
        if not self.session_id:
            # 没有缓存 sessionId, 尝试 AC 重定向获取
            self.logger.info("无缓存 sessionId, 尝试通过 AC 重定向获取...")
            if not self._rediscover_session():
                self.logger.error("无法获取 sessionId (AC 未劫持或网段不支持), 认证失败")
                self.auth_fail_count += 1
                return False

        # Step 1: 验证 sessionId
        node_info = self._get_current_node(self.session_id)
        if node_info is None or node_info.get("code") != 200:
            if self._is_invalid_session_response(node_info):
                # 门户已明确拒绝旧会话。先清空它, 避免公网正常时每分钟反复认证;
                # 若此刻确实断网, 后面的 AC 探测仍可捕获新 sessionId。
                self._clear_invalid_session()
            else:
                self.logger.info("getCurrentNode 未确认有效会话, 尝试 AC 重定向刷新...")

            if self._rediscover_session():
                node_info = self._get_current_node(self.session_id)

            if node_info is None or node_info.get("code") != 200:
                if self._is_invalid_session_response(node_info) and self.session_id:
                    self._clear_invalid_session()
                detail = self._sanitize_log_text(str(node_info))
                self.logger.error(f"getCurrentNode 仍失败, 无法继续认证: {detail}")
                self.auth_fail_count += 1
                self._save_session_state("(认证失败)")
                return False

        current_path = (node_info.get("data") or {}).get("currentNodePath") or ""
        self.logger.info(f"工作流当前节点: {current_path} (sessionId={self._mask_value(self.session_id)})")

        # Step 2: 取终端信息 (刷新 userIp, 兜底用缓存的)
        if not self.user_ip:
            user_ip, detail = self._query_terminal_info(self.session_id)
            if user_ip:
                self.user_ip = user_ip
                self.logger.info(f"获取到终端 IP: {self._mask_value(self.user_ip)}")
            else:
                self.logger.debug(f"未获取到终端 IP ({detail}), 将用缓存值")

        # Step 3: 拉 CAS 登录页
        html = self._fetch_cas_login_page(self.session_id, self.user_ip, self.nas_ip)
        if not html:
            self.logger.error("无法获取 CAS 登录页, 认证失败")
            self.auth_fail_count += 1
            return False
        croypto_key, execution = self._extract_cas_tokens(html)
        if not croypto_key or not execution:
            self.logger.error(
                f"无法从 CAS 登录页提取 token: croypto={'有' if croypto_key else '无'} "
                f"execution={'有' if execution else '无'}"
            )
            self.auth_fail_count += 1
            return False
        self.logger.debug(
            f"提取到 CAS token: croypto={self._mask_value(croypto_key)} "
            f"execution={self._mask_value(execution)}"
        )

        # Step 4: 提交登录
        ticket = self._submit_cas_login(
            self.session_id, croypto_key, execution,
            self.PHONENUM, self.PASSWD, self.user_ip, self.nas_ip,
        )
        if not ticket:
            self.logger.error("CAS 登录提交失败 (账密错误或被拦截), 认证失败")
            self.auth_fail_count += 1
            return False
        self.logger.info(f"CAS 登录成功, 获得 ticket: {self._mask_value(ticket)}")

        # Step 5: 上线
        online, detail = self._bring_online(self.session_id)
        if not online:
            self.logger.error(f"userOnline 失败: {detail}")
            self.auth_fail_count += 1
            return False

        # Step 6: 成功, 持久化
        self.last_login_at = datetime.datetime.now()
        self.auth_success_count += 1
        self.heartbeat_confirmed_online = True
        self.heartbeat_offline_count = 0
        self._save_session_state(f"(认证成功 {detail})")
        self.logger.info(f"认证成功! 已上线 o((>ω< ))o | {detail}")
        return True

    def heartbeat_check(self) -> Tuple[str, str]:
        """心跳/在线状态检查, 每 heartbeat_interval 秒调一次。

        返回 (state, detail):
          state: "online" | "offline" | "unknown"

        无 sessionId 时不在这里触发认证 (避免在线时反复 AC 探测刷屏);
        sessionId 的获取交给 run() 里 ping 检测到断网时的 authenticate()。

        两段式判定 (2026-07-16 实测得来):
          1. getOnlineUserInfo 报 offline 时, 不能轻信 —— 实测认证成功 ~60s 后它就开始报
             dx.failed.user.offline, 但 userOnline 复查 online=true、userIndex 不变、
             网络实际正常, 是 portal 侧状态不同步/误报。
          2. 因此先用便宜的 userOnline (_bring_online) 复查: 在线则信任复查、跳过重认证,
             避免每分钟一次的全量 CAS 重登 (实测那样会加速 sessionId 被服务端作废,
             ~15-21 分钟即失效); 复查也失败才返回 offline 让 run() 全量重认证。
        """
        if not self.session_id:
            return "unknown", "无缓存 sessionId (等断网触发认证时获取)"
        state, detail = self._check_online(self.session_id)
        if state == "online":
            self.last_heartbeat_at = datetime.datetime.now()
            self.heartbeat_confirmed_online = True
            self.heartbeat_offline_count = 0
            self.logger.debug(f"心跳正常: {detail}")
        elif state == "offline":
            online, verify_detail = self._bring_online(self.session_id)
            if online:
                self.last_heartbeat_at = datetime.datetime.now()
                self.heartbeat_confirmed_online = True
                self.heartbeat_offline_count = 0
                self.logger.info(
                    f"心跳报离线但 userOnline 复查在线, 信任复查跳过重认证 (˶ᵔᵕᵔ˶): "
                    f"{detail} | {verify_detail}"
                )
                return "online", f"复查在线 (原报告: {detail})"
            self.heartbeat_offline_count += 1
            self.logger.info(f"心跳显示离线: {detail} | 复查也失败: {verify_detail} (连续 {self.heartbeat_offline_count} 次)")
        return state, detail

    def probe_auth_once(self) -> bool:
        """一次性探测 CAS 登录全流程 (不进主循环, --probe-auth 调用)。

        在线机器上 getCurrentNode/userOnline 会失败, 但能验证 token 提取/加密逻辑。
        返回 True 表示流程跑通 (不要求最终上线)。
        """
        self.logger.info("====== CAS SSO 认证探测开始 ======")
        # 即使在线, 也尝试拉一次 CAS 登录页验证 token 提取
        probe_session_id = self.session_id or "probe" + datetime.datetime.now().strftime("%H%M%S")
        self.logger.info(f"探测用 sessionId: {self._mask_value(probe_session_id)}")

        # Step 1: getCurrentNode (在线机器预期失败)
        node_info = self._get_current_node(probe_session_id)
        if node_info:
            self.logger.info(f"getCurrentNode 响应: code={node_info.get('code')} (在线机器预期非200)")
        else:
            self.logger.warning("getCurrentNode 无响应")

        # Step 2: 拉 CAS 登录页 (验证 token 提取)
        html = self._fetch_cas_login_page(probe_session_id, self.user_ip, self.nas_ip)
        if not html:
            self.logger.error("探测失败: 无法获取 CAS 登录页")
            return False
        croypto_key, execution = self._extract_cas_tokens(html)
        if not croypto_key or not execution:
            self.logger.error(
                f"探测失败: token 提取失败 (croypto={'有' if croypto_key else '无'}, "
                f"execution={'有' if execution else '无'})"
            )
            return False
        self.logger.info(f"[OK] token 提取成功: croypto={self._mask_value(croypto_key)} (len={len(croypto_key)})")
        self.logger.info(f"[OK] execution 提取成功: len={len(execution)}")

        # Step 3: 验证 AES 加密 (用提取到的 key 加密一个测试值)
        try:
            test_ct = self._aes_encrypt(croypto_key, "probe_test")
            self.logger.info(f"[OK] AES 加密测试通过: {self._mask_value(test_ct)}")
        except Exception as e:
            self.logger.error(f"探测失败: AES 加密异常: {e}")
            return False

        # Step 4: 如果有真实账密, 尝试完整提交 (在线机器预期失败, 但能看错误码)
        if self.PHONENUM and self.PASSWD:
            self.logger.info("尝试完整 CAS 登录提交 (在线机器预期被拒)...")
            ticket = self._submit_cas_login(
                probe_session_id, croypto_key, execution,
                self.PHONENUM, self.PASSWD, self.user_ip, self.nas_ip,
            )
            if ticket:
                self.logger.info(f"[OK] CAS 登录获得 ticket: {self._mask_value(ticket)}")
                online, detail = self._bring_online(probe_session_id)
                self.logger.info(f"userOnline 结果: online={online} | {detail}")
            else:
                self.logger.info("CAS 登录未获得 ticket (在线机器属正常, 真实断网时才会成功)")
        else:
            self.logger.info("未配置账密, 跳过完整登录提交测试")

        self.logger.info("====== CAS SSO 认证探测完成 (token 提取 + AES 加密逻辑验证通过) ======")
        return True

    # --- 主循环 ---

    def run(self):
        """主循环: 周期性检测网络; 断网时走 CAS SSO 认证; 在线时定期心跳保活。"""
        self.logger.info(f"主循环启动, 检测间隔={self.waitime}s, 心跳间隔={self.heartbeat_interval}s")
        cycle = 0
        next_heartbeat_time = time.monotonic()

        while True:
            cycle += 1
            # 检测网络: 断网则认证
            while self.is_connected() != 0:
                self.logger.info(f"[周期#{cycle}] 检测到断网, 开始 CAS SSO 认证...")
                if self.authenticate():
                    self.logger.info(f"[周期#{cycle}] 认证成功! o((>ω< ))o")
                    time.sleep(3)
                    if self.is_connected() == 0:
                        next_heartbeat_time = time.monotonic() + self.heartbeat_interval
                        break
                    self.logger.warning(f"[周期#{cycle}] 认证后仍无法连通, 将重试...")
                else:
                    self.logger.error(f"[周期#{cycle}] 认证失败, 等待后重试...")
                time.sleep(self.waitime)

            # 在线时定期心跳: 检测会话是否失效
            if time.monotonic() >= next_heartbeat_time:
                state, detail = self.heartbeat_check()
                if state == "offline":
                    # 心跳显示离线: 优先用缓存 sessionId 重新认证自愈 (不等真断网)
                    self.logger.info(f"[周期#{cycle}] 心跳显示会话失效, 尝试主动重新认证: {detail}")
                    if self.authenticate():
                        self.logger.info(f"[周期#{cycle}] 主动重新认证成功, 继续保活")
                    else:
                        self.logger.warning(f"[周期#{cycle}] 主动重新认证失败, 等待下次断网触发")
                elif state == "unknown":
                    self.logger.debug(f"[周期#{cycle}] 心跳状态未知: {detail}")
                next_heartbeat_time = time.monotonic() + self.heartbeat_interval

            self.logger.debug(f"[周期#{cycle}] 网络正常, 等待{self.waitime}s")
            time.sleep(self.waitime)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        debug_mode = "--debug" in sys.argv or os.environ.get("UESTC_DEBUG", "").lower() in ("1", "true", "yes")
        probe_auth = "--probe-auth" in sys.argv
        connector = ConnectRequests()
        if probe_auth:
            raise SystemExit(0 if connector.probe_auth_once() else 1)
        connector.run()
    except SystemExit:
        raise
    except Exception:
        logging.getLogger("BOCCHI").exception("程序遇到未捕获异常, 已写入日志方便排查")
        raise
