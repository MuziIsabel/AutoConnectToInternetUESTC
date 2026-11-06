# AutoConnectToInternetUESTC

电子科技大学（UESTC）校园网自动认证工具，V4.0。纯 `requests` 实现，无 Selenium / WebDriver，适合后台常驻、断网自动重登。

## 特性

- 纯 requests，无浏览器依赖，体积更小、启动更快
- 自动检测网络连通性，断网后自动重新认证上线
- 会话缓存与失效自动处理；日志脱敏
- `.env` 配置账号密码，敏感信息不入库

## 安装

```bash
pip install -r requirements.txt
```

## 配置

```bash
copy .env.example .env
```

编辑 `.env`：

```env
UESTC_PHONE=你的手机号（账号）
UESTC_PASSWORD=你的密码
```

> `.env` 已加入 `.gitignore`，不要把真实账号密码提交到 GitHub。

可选配置见 `.env.example` 中的注释项。

## 运行

```bash
python internetconnectuestc.py
```

调试（不进入主循环，只跑一次认证自检）：

```bash
python internetconnectuestc.py --probe-auth --debug
```

## 日志

`BOCCHI THE ROCK.log`（每次启动覆盖，内容已脱敏）。控制台默认 INFO，`--debug` 或 `UESTC_DEBUG=1` 开启 DEBUG。

## 打包为 exe

```bash
pyinstaller -F -w --clean --noconfirm --collect-data certifi --collect-submodules Crypto internetconnectuestc.py
```

产物在 `dist/`。

## 开机自启动

`Win + R` → 输入 `shell:startup` → 将 exe 快捷方式放入启动文件夹。

## 故障排查

| 现象 | 解决 |
| --- | --- |
| `ModuleNotFoundError` | `pip install -r requirements.txt`，并确认用对 Python 环境 |
| 认证失败 | 检查 `.env` 账号密码；跑 `--probe-auth --debug` 后查日志 |
| 打包后运行报错 | 确认打包命令完整（见上文） |

## 更新日志

- **V4.1**：稳定性增强
  - 联网探测改用 HTTP `generate_204`（captive-portal detection），避免"ping 通但上不了网"的假在线误判
  - 连续探测失败阈值（默认 2 次）后才触发认证，避免单次抖动误判
  - 认证失败指数退避（10→20→…上限 300s），避免高频刷认证、加速会话失效
  - 单实例锁（`.uestc.lock`），防止多进程互相顶掉 sessionId
  - 日志改为轮转（1MB × 5），保留崩溃现场
  - sessionId 失效时多探针重新捕获（AC 探测 IP + 门户基址）
- **V4.0**：适配学校现行门户，重写认证实现
- V3.0：纯 requests 版（已失效）
- V2.x：Selenium 版（已废弃）
