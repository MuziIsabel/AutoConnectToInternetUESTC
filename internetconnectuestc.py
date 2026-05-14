#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动认证 - requests版 (无 Selenium / WebDriver 依赖)
当前仓库主实现。

配置: 通过 .env 文件或环境变量设置
  UESTC_PHONE       - 手机号
  UESTC_PASSWORD    - 密码
  UESTC_HOST        - ping探测地址 (默认 223.5.5.5)
  UESTC_WAIT_TIME   - 检测间隔秒数 (默认 10)
  UESTC_PORTAL_URL  - 认证页面地址 (默认 http://aaa.uestc.edu.cn/)
"""

import time
import os
import sys
import re
import logging
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass, field

import ping3
import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# 环境变量 & CA证书
# ---------------------------------------------------------------------------

def _load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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
# 常见门户认证端点 (按优先级排序)
# ---------------------------------------------------------------------------

# UESTC aaa.uestc.edu.cn 常见 AJAX 认证路径
KNOWN_AUTH_ENDPOINTS = [
    "/eportal/InterFace.do?method=login",
    "/eportal/InterFace.do?method=loginByWeb",
    "/eportal/gb/index.jsp",
    "/ac_portal/default/portal.jsp",
    "/",
]


# ---------------------------------------------------------------------------
# HTML 表单解析器
# ---------------------------------------------------------------------------

@dataclass
class ParsedForm:
    """从门户页面解析出的表单信息"""
    action: str = ""
    method: str = "POST"
    username_field: str = "username"
    password_field: str = "pwd"
    hidden_fields: dict = field(default_factory=dict)
    extra_data: dict = field(default_factory=dict)


def parse_portal_html(html: str, base_url: str) -> Optional[ParsedForm]:
    """
    解析门户页面 HTML, 提取登录表单的结构.
    返回 ParsedForm 或 None.
    """
    soup = BeautifulSoup(html, "lxml")

    # 策略1: 找 <form> 标签
    form_tag = soup.find("form")
    if form_tag:
        pf = ParsedForm()
        pf.action = form_tag.get("action", "") or base_url
        pf.method = (form_tag.get("method", "POST") or "POST").upper()

        # 如果 action 是相对路径, 补全。既支持 /login，也支持 ./validateHaijun.do 这类写法。
        from urllib.parse import urljoin
        if not pf.action.lower().startswith(("http://", "https://")):
            pf.action = urljoin(base_url, pf.action)

        # 提取所有 hidden input
        for inp in form_tag.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                pf.hidden_fields[name] = value

        # 识别用户名/密码字段
        for inp in form_tag.find_all("input"):
            field_name = inp.get("name") or ""
            name = field_name.lower()
            id_attr = (inp.get("id") or "").lower()
            input_type = (inp.get("type") or "").lower()

            # 先识别密码字段，避免 userPassword 这类字段被 "user" 误判为用户名
            is_password = (
                input_type == "password"
                or "pwd" in name
                or "pass" in name
                or "pwd" in id_attr
                or "password" in id_attr
            )
            if is_password:
                pf.password_field = field_name or "pwd"
                continue

            is_username = (
                name in ("username", "user", "userid", "useraccount", "account")
                or id_attr in ("username", "user", "userid", "useraccount", "account")
                or ("user" in name and "pass" not in name and "pwd" not in name)
                or ("user" in id_attr and "pass" not in id_attr and "pwd" not in id_attr)
            )
            if is_username:
                pf.username_field = field_name or "username"

        return pf

    # 策略2: 没有 <form> 标签, 但有已知字段 (AJAX 模式)
    username_el = soup.find(id="username") or soup.find(attrs={"name": "username"})
    pwd_el = soup.find(id="pwd") or soup.find(attrs={"name": "pwd"})

    if username_el or pwd_el:
        pf = ParsedForm()
        pf.action = base_url  # AJAX 模式下默认 POST 到同一页面或已知端点
        return pf

    return None


def extract_js_login_endpoint(html: str) -> Optional[str]:
    """
    尝试从页面 JavaScript 中提取 AJAX 登录端点.
    常见模式: $.post("/eportal/InterFace.do?method=login", ...)
    """
    patterns = [
        r'(?:url|action|href)\s*[=:]\s*["\']([^"\']*(?:login|Login|interFace|Interface)[^"\']*)["\']',
        r'\.post\s*\(\s*["\']([^"\']+)["\']',
        r'\.ajax\s*\([^)]*url\s*:\s*["\']([^"\']+)["\']',
        r'XMLHttpRequest[^;]*open\s*\(\s*["\']POST["\']\s*,\s*["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# 主连接类
# ---------------------------------------------------------------------------

class ConnectRequests:
    """基于 requests 的校园网自动认证 (无 Selenium 依赖)"""

    def __init__(self):
        self.logger = self._log_config()

        _load_env_file()
        self.PHONENUM = os.getenv("UESTC_PHONE", "").strip()
        self.PASSWD = os.getenv("UESTC_PASSWORD", "")
        self.host = os.getenv("UESTC_HOST", "223.5.5.5").strip()
        self.waitime = int(os.getenv("UESTC_WAIT_TIME", "10").strip() or "10")
        self.portal_url = os.getenv("UESTC_PORTAL_URL", "http://aaa.uestc.edu.cn/").strip()

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
            ),
            # 部分校园网门户会在未声明 Content-Encoding 的情况下返回压缩内容，
            # 明确要求 identity 可以减少乱码页面导致的误判。
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        # 不验证 SSL (门户可能自签证书)
        self.session.verify = False

        self._ensure_ca_bundle()

        if not self.PHONENUM or not self.PASSWD:
            self.logger.error(
                "未设置账号密码环境变量：请设置 UESTC_PHONE / UESTC_PASSWORD 后再运行。"
            )
            raise SystemExit(2)

        self.logger.info("校园网自动认证(requests版)已启动 ♪(´▽｀)")

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
        logger.setLevel(logging.DEBUG)  # logger 本身接收所有级别

        # 是否开启 DEBUG 模式: 环境变量 UESTC_DEBUG=1 或命令行 --debug
        debug_mode = os.getenv("UESTC_DEBUG", "").strip() in ("1", "true", "yes")
        if "--debug" in sys.argv:
            debug_mode = True
        console_level = logging.DEBUG if debug_mode else logging.INFO

        # ---- 文件 handler (始终 DEBUG 级别) ----
        fh = logging.FileHandler(
            "BOCCHI THE ROCK.log", mode="w", encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s:%(levelname)s:%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # ---- 控制台 handler ----
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(console_level)
        ch.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-5s %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(ch)

        if debug_mode:
            logger.info("DEBUG 模式已启用 (文件+控制台均 DEBUG)")
        else:
            logger.debug("控制台 INFO 级别; 文件 DEBUG 级别 (设置 UESTC_DEBUG=1 开启控制台 DEBUG)")

        return logger

    # --- HTTP 请求/响应追踪 ---

    def _log_response(self, resp: requests.Response, label: str = "") -> None:
        """详细记录 HTTP 响应信息 (DEBUG 级别)"""
        prefix = f"[{label}] " if label else ""
        self.logger.debug(
            f"{prefix}<<< 响应: {resp.status_code} {resp.reason} | "
            f"url={resp.url} | len={len(resp.text)} | "
            f"encoding={resp.encoding}"
        )
        # 记录响应头 (关键字段)
        interesting_headers = [
            "Content-Type", "Content-Encoding", "Content-Length",
            "Set-Cookie", "Location", "Server",
        ]
        hdrs = {k: v for k, v in resp.headers.items() if k in interesting_headers}
        if hdrs:
            self.logger.debug(f"{prefix}    响应头: {hdrs}")
        # 截断记录响应体 (前 500 字符)
        body_preview = resp.text[:500].replace("\n", "\\n").replace("\r", "")
        self.logger.debug(f"{prefix}    响应体(前500): {body_preview}")

    def _log_request_summary(self, method: str, url: str, **kwargs) -> None:
        """记录即将发出的 HTTP 请求摘要 (DEBUG 级别)"""
        data = kwargs.get("data") or kwargs.get("json") or kwargs.get("params")
        data_desc = ""
        if data:
            # 隐藏密码字段
            safe = {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if any(p in k.lower() for p in ("pwd", "pass", "password")):
                        safe[k] = "***"
                    else:
                        safe[k] = v
                data_desc = str(safe)[:200]
            else:
                data_desc = str(data)[:200]
        self.logger.debug(f">>> {method} {url} | data={data_desc}")


    def _log_auth_decision(self, strategy: str, success: bool, detail: str = "") -> None:
        """记录认证决策链的每一步结果"""
        status = "SUCCESS" if success else "FAIL"
        self.logger.debug(f"决策链: [{status}] {strategy} | {detail}")

    def is_connected(self) -> int:
        """
        检测网络连通性
        返回: 0=已连接, 2=断网
        """
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

    # --- 核心认证逻辑 ---

    def _try_auth_post_form(self, portal_html: str, portal_url: str) -> Tuple[bool, str]:
        """
        策略A: 解析HTML中的表单, 按照表单结构POST提交
        """
        pf = parse_portal_html(portal_html, portal_url)
        if pf is None:
            return False, "无法解析门户页面表单"

        data = {**pf.hidden_fields}
        data[pf.username_field] = self.PHONENUM
        data[pf.password_field] = self.PASSWD

        self.logger.info(f"策略A: POST 表单到 {pf.action}")
        self.logger.debug(f"  字段: username={pf.username_field}, password={pf.password_field}")
        self.logger.debug(f"  hidden_fields: {list(pf.hidden_fields.keys())}")

        try:
            self._log_request_summary("POST", pf.action, data=data)
            resp = self.session.post(pf.action, data=data, timeout=15, allow_redirects=True)
            self._log_response(resp, "策略A")
            return self._check_auth_response(resp)
        except requests.RequestException as e:
            return False, f"POST 请求失败: {e}"

    def _try_auth_known_endpoints(self, base_url: str) -> Tuple[bool, str]:
        """
        策略B: 依次尝试已知认证端点
        """
        # 先从页面JS中探测端点
        try:
            resp = self.session.get(base_url, timeout=10, allow_redirects=True)
            html = resp.text
            js_endpoint = extract_js_login_endpoint(html)
            if js_endpoint:
                if not js_endpoint.startswith("http"):
                    from urllib.parse import urljoin
                    js_endpoint = urljoin(base_url, js_endpoint)
                # 把 JS 探测到的端点放到最前面
                if js_endpoint not in KNOWN_AUTH_ENDPOINTS:
                    KNOWN_AUTH_ENDPOINTS.insert(0, js_endpoint)
        except Exception:
            pass

        from urllib.parse import urljoin, urlsplit

        eportal_query = urlsplit(base_url).query
        if eportal_query:
            self.logger.debug(f"ePortal queryString 已提取: {eportal_query[:300]}")

        for endpoint in KNOWN_AUTH_ENDPOINTS:
            full_url = urljoin(base_url, endpoint)
            self.logger.info(f"策略B: 尝试已知端点 {full_url}")

            # 常见 payload 格式
            payloads = [
                # 格式0: ePortal/Ruijie 常见 AJAX 登录格式，queryString 必须来自 index.jsp 的 URL 参数
                {
                    "userId": self.PHONENUM,
                    "password": self.PASSWD,
                    "service": "",
                    "queryString": eportal_query,
                    "operatorPwd": "",
                    "operatorUserId": "",
                    "validcode": "",
                    "passwordEncrypt": "false",
                },
                # 格式1: 标准表单
                {"username": self.PHONENUM, "pwd": self.PASSWD, "password": self.PASSWD},
                # 格式2: eportal 简化格式
                {"userId": self.PHONENUM, "password": self.PASSWD, "service": "", "queryString": eportal_query},
                # 格式3: userPwd 模式
                {"userAccount": self.PHONENUM, "userPassword": self.PASSWD},
            ]

            for payload in payloads:
                try:
                    self._log_request_summary("POST", full_url, data=payload)
                    resp = self.session.post(full_url, data=payload, timeout=10, allow_redirects=True)
                    self._log_response(resp, "策略B")
                    ok, msg = self._check_auth_response(resp)
                    if ok:
                        return True, msg
                except requests.RequestException:
                    continue

        return False, "所有已知端点均失败"

    def _try_auth_get_with_params(self, base_url: str) -> Tuple[bool, str]:
        """
        策略C: GET 请求带参数 (少数门户用GET认证)
        """
        params = {
            "username": self.PHONENUM,
            "pwd": self.PASSWD,
            "password": self.PASSWD,
        }
        self.logger.info(f"策略C: GET 带参数 {base_url}")
        try:
            self._log_request_summary("GET", base_url, params=params)
            resp = self.session.get(base_url, params=params, timeout=10, allow_redirects=True)
            self._log_response(resp, "策略C")
            return self._check_auth_response(resp)
        except requests.RequestException as e:
            return False, f"GET 请求失败: {e}"

    def _try_auth_json_post(self, base_url: str) -> Tuple[bool, str]:
        """
        策略D: JSON POST (现代AJAX门户)
        """
        from urllib.parse import urljoin

        for endpoint in KNOWN_AUTH_ENDPOINTS:
            full_url = urljoin(base_url, endpoint)
            payloads = [
                {"username": self.PHONENUM, "password": self.PASSWD},
                {"userId": self.PHONENUM, "password": self.PASSWD},
                {"userAccount": self.PHONENUM, "userPassword": self.PASSWD},
            ]
            for payload in payloads:
                try:
                    self._log_request_summary("POST", full_url, json=payload)
                    resp = self.session.post(
                        full_url, json=payload, timeout=10, allow_redirects=True
                    )
                    self._log_response(resp, "策略D")
                    ok, msg = self._check_auth_response(resp)
                    if ok:
                        return True, msg
                except requests.RequestException:
                    continue

        return False, "JSON POST 均失败"

    def _check_auth_response(self, resp: requests.Response) -> Tuple[bool, str]:
        """
        检查认证响应是否表示成功.
        返回 (成功?, 描述消息)
        """
        status = resp.status_code
        text = resp.text
        url = resp.url

        # HTTP 2xx
        if 200 <= status < 400:
            # 检查响应中是否包含成功标志
            success_indicators = ["success", "登录成功", "认证成功", "已连接", "已登录"]
            fail_indicators = ["fail", "error", "错误", "密码错误", "用户名或密码", "账号或密码"]

            text_lower = text.lower()
            for si in success_indicators:
                if si.lower() in text_lower:
                    return True, f"认证成功 (匹配到'{si}'), status={status}"

            # 如果是 JSON 响应
            try:
                j = resp.json()
                result = str(j.get("result", j.get("status", j.get("ret", "")))).lower()
                if result in ("success", "0", "true", "ok"):
                    return True, f"认证成功 (JSON result={result})"
                elif result and result not in ("fail", "error", "-1", "false"):
                    # 可能是不确定的结果, 但不是明确的失败
                    pass
            except Exception:
                pass

            # 检查是否有明确的失败
            for fi in fail_indicators:
                if fi.lower() in text_lower:
                    return False, f"认证失败: 匹配到'{fi}', status={status}"

            # 如果仍然停留在 ePortal/index.jsp，一般表示还在认证门户，不能当作成功。
            url_lower = url.lower()
            if "/eportal/" in url_lower and ("index.jsp" in url_lower or "userip=" in url_lower):
                return False, f"仍在认证门户页面, status={status}"

            # 如果响应很短且是2xx, 可能是重定向后的成功页面
            # 检查是否还在门户页面 (如果不在, 说明认证可能成功)
            portal_indicators = ["username", "password", "loginLink", "登录", "eportal", "userip="]
            still_portal = any(p.lower() in text_lower for p in portal_indicators)
            if not still_portal and len(text) < 5000:
                return True, f"可能成功 (已离开门户页面), status={status}"

            # 默认: 状态码正常但无法确认
            self.logger.debug(f"不确定的响应: status={status}, len={len(text)}")
            return False, f"响应状态正常但无法确认成功, status={status}"

        return False, f"HTTP {status}"

    # --- 主认证入口 ---

    def authenticate(self) -> bool:
        """
        执行一次认证尝试, 使用多种策略回退.
        返回 True 表示认证成功, False 表示失败.
        """
        self.session.cookies.clear()

        # Step 1: 获取门户页面
        self.logger.info(f"正在访问门户页面: {self.portal_url}")
        try:
            self._log_request_summary("GET", self.portal_url)
            resp = self.session.get(self.portal_url, timeout=15, allow_redirects=True)
            self._log_response(resp, "门户页面")
            portal_html = resp.text
            final_url = resp.url
            self.logger.info(f"门户页面已获取: status={resp.status_code}, url={final_url}, len={len(portal_html)}")
        except requests.RequestException as e:
            self.logger.error(f"无法访问门户页面: {e}")
            return False

        # 如果页面没有登录表单，不能直接判定成功：
        # 真实断网时 ePortal 可能返回乱码/压缩页面，导致关键字检测失败。
        html_lower = portal_html.lower()
        has_login_form = any(
            kw in html_lower for kw in ["username", "loginlink", "password", "pwd", "登录", "eportal"]
        )
        if not has_login_form:
            final_url_lower = final_url.lower()
            looks_like_captive_portal = (
                "/eportal/" in final_url_lower
                or "index.jsp" in final_url_lower
                or "userip=" in final_url_lower
                or "nasip=" in final_url_lower
            )
            if not looks_like_captive_portal and self.is_connected() == 0:
                self.logger.info("门户页面未包含登录表单，且网络已连通，判定为已认证")
                return True
            self.logger.warning(
                "门户页面未识别到登录表单，但当前像是认证门户/断网状态，将继续尝试接口认证"
            )

        # Step 2: 依次尝试各种认证策略
        strategies = [
            ("策略A: HTML表单解析POST", lambda: self._try_auth_post_form(portal_html, final_url)),
            ("策略B: 已知端点轮询", lambda: self._try_auth_known_endpoints(final_url)),
            ("策略D: JSON POST", lambda: self._try_auth_json_post(final_url)),
            ("策略C: GET参数", lambda: self._try_auth_get_with_params(final_url)),
        ]

        for name, strategy_fn in strategies:
            self.logger.debug(f"决策链: 尝试 {name}")
            try:
                ok, msg = strategy_fn()
                if ok:
                    self._log_auth_decision(name, success=True, detail=msg)
                    self.logger.info(f"{name} -> {msg}")
                    return True
                else:
                    self._log_auth_decision(name, success=False, detail=msg)
                    self.logger.warning(f"{name} -> {msg}")
            except Exception as e:
                self._log_auth_decision(name, success=False, detail=f"异常: {e}")
                self.logger.warning(f"{name} -> 异常: {e}")
                continue

        self.logger.error("所有认证策略均失败")
        return False

    # --- 主循环 ---

    def run(self):
        """主循环: 周期性检测网络, 断网时自动认证"""
        self.logger.info(f"主循环启动, 检测间隔={self.waitime}s")
        cycle = 0
        while True:
            cycle += 1
            # 检测网络
            while self.is_connected() != 0:
                self.logger.info(f"[周期#{cycle}] 检测到断网, 开始认证...")
                if self.authenticate():
                    self.logger.info(f"[周期#{cycle}] 认证成功! o((>ω< ))o")
                    # 等待几秒让网络生效
                    time.sleep(3)
                    if self.is_connected() == 0:
                        break
                    self.logger.warning(f"[周期#{cycle}] 认证后仍无法连通, 将重试...")
                else:
                    self.logger.error(f"[周期#{cycle}] 认证失败, 等待后重试...")
                time.sleep(self.waitime)

            self.logger.debug(f"[周期#{cycle}] 网络正常, 等待{self.waitime}s")
            time.sleep(self.waitime)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    connector = ConnectRequests()
    connector.run()