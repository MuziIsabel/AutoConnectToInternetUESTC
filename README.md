# AutoConnectToInternetUESTC

电子科技大学（UESTC）校园网自动认证脚本。当前实现为 **requests 版**，无需 Selenium、Edge 浏览器或 WebDriver，体积更小、启动更快，适合后台常驻检测并在断网/未认证时自动登录。

## 特性

- 无 Selenium / WebDriver 依赖
- 自动检测网络连通性，默认 ping `223.5.5.5`
- 断网后自动访问 `http://aaa.uestc.edu.cn/` 获取真实认证门户
- 自动跟随 ePortal 重定向并提取 `queryString`，不硬编码认证服务器 IP、用户 IP、NAS IP
- 支持 UESTC 当前 ePortal 接口：`/eportal/InterFace.do?method=login`
- 多策略回退：表单 POST、已知端点、JSON POST、GET 参数
- `.env` / 环境变量配置账号密码，避免在代码中写入敏感信息
- 文件 DEBUG 日志 + 可选控制台 DEBUG 输出

## 安装

建议使用独立 Python / conda 环境。

```bash
pip install -r requirements.txt
```

## 配置账号密码

复制示例配置：

```bash
copy .env.example .env
```

然后编辑 `.env`：

```env
UESTC_PHONE=你的手机号或账号
UESTC_PASSWORD=你的密码
```

> 注意：`.env` 已加入 `.gitignore`，不要把真实账号密码提交到 GitHub。

可选配置：

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `UESTC_PHONE` | 手机号/账号，必填 | 无 |
| `UESTC_PASSWORD` | 密码，必填 | 无 |
| `UESTC_HOST` | 网络探测地址 | `223.5.5.5` |
| `UESTC_WAIT_TIME` | 检测间隔，单位秒 | `10` |
| `UESTC_PORTAL_URL` | 认证入口地址 | `http://aaa.uestc.edu.cn/` |
| `UESTC_DEBUG` | 控制台 DEBUG 开关，`1/true/yes` 开启 | 关闭 |

## 运行

```bash
python internetconnectuestc.py
```

开启详细调试输出：

```bash
python internetconnectuestc.py --debug
```

如果你使用 conda 但 `conda activate` 不可用，可以直接指定环境中的 Python，例如：

```powershell
& "C:\Users\你的用户名\.conda\envs\internetconnect\python.exe" ".\internetconnectuestc.py" --debug
```

## 认证流程说明

程序不会硬编码本机 IP 或认证服务器 IP。真实流程如下：

1. 周期性 ping `UESTC_HOST` 检测网络是否连通。
2. 断网时访问默认入口：
   ```text
   http://aaa.uestc.edu.cn/
   ```
3. 未认证时，校园网会重定向到真实 ePortal 门户，例如：
   ```text
   http://172.x.x.x/eportal/index.jsp?userip=...&nasip=...&wlanparameter=...&userlocation=...
   ```
4. 程序从该 URL 动态提取整段 query 参数作为 `queryString`。
5. 程序向当前门户主机提交登录请求：
   ```text
   /eportal/InterFace.do?method=login
   ```
6. 如果返回 `result=success` 或页面包含成功标志，则认为认证成功，并再次检测网络。

因此下面这些值都是运行时动态获取的：

- 真实认证服务器地址，例如 `172.x.x.x`
- `userip`
- `nasip`
- `wlanparameter`
- `userlocation`

## 日志

日志文件：

```text
BOCCHI THE ROCK.log
```

- 文件日志始终为 DEBUG 级别
- 控制台默认 INFO 级别
- 使用 `--debug` 或 `UESTC_DEBUG=1` 可开启控制台 DEBUG
- 日志会隐藏密码字段，避免直接输出密码

查看日志：

```powershell
type "BOCCHI THE ROCK.log"
```

## 打包为 exe

调试版，带控制台：

```bash
pyinstaller -F --clean --noconfirm --collect-data certifi internetconnectuestc.py
```

后台版，无控制台窗口：

```bash
pyinstaller -F -w --clean --noconfirm --collect-data certifi internetconnectuestc.py
```

> `--collect-data certifi` 用于把 CA 证书一起打包，避免 onefile 模式下 HTTPS 请求找不到证书。

打包产物位于：

```text
dist/internetconnectuestc.exe
```

## 开机自启动

1. `Win + R`
2. 输入 `shell:startup`
3. 将 exe 或脚本快捷方式放入启动文件夹

## 故障排查

### 缺少依赖

如果出现：

```text
ModuleNotFoundError: No module named 'ping3'
```

说明当前 Python 环境不对或依赖未安装。请执行：

```bash
pip install -r requirements.txt
```

或使用正确 conda 环境中的 Python。

### 认证失败

使用 DEBUG 模式运行：

```bash
python internetconnectuestc.py --debug
```

然后查看：

```text
BOCCHI THE ROCK.log
```

重点关注：

- `门户页面已获取`
- `ePortal queryString 已提取`
- `策略B: 尝试已知端点`
- `result=success` 或失败 message

### PowerShell 中 conda activate 失败

可以不用 `conda activate`，直接调用环境里的 Python：

```powershell
& "C:\Users\你的用户名\.conda\envs\internetconnect\python.exe" ".\internetconnectuestc.py" --debug
```

## 更新日志

### V3.0 requests 版

- 切换为纯 requests 实现，移除 Selenium / Edge WebDriver 依赖
- 账号密码改为 `.env` / 环境变量配置，避免硬编码敏感信息
- 适配 UESTC ePortal：自动提取门户 URL 中的 `queryString`
- 修复未认证门户页面被误判为已认证的问题
- 增强日志：请求摘要、响应摘要、认证策略决策链
- 支持 PyInstaller 打包时收集 certifi CA 证书

### V2.x Selenium 版

- 使用 Edge WebDriver 自动打开认证页面登录
- 支持 WebDriver 自动下载与版本匹配
