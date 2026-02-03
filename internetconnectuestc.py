import time
import datetime
import shutil
import ping3
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.common.exceptions import (
    NoSuchElementException,
    ElementNotVisibleException,
    ElementNotInteractableException,
    TimeoutException,
    WebDriverException,
)
import logging

# --- 新增的导入 ---
import winreg  # 用于读取注册表来获取Edge版本
import requests # 用于网络请求
from bs4 import BeautifulSoup # 用于解析HTML
import zipfile # 用于处理zip文件
import io # 用于在内存中处理zip文件
import subprocess
import winreg  # 用于读取注册表来获取Edge版本

class connect:
    PHONENUM = "**********"  # 手机号
    PASSWD = "**********"  # 密码
    host = "223.5.5.5"
    waitime = 10
    current_date = 0

    def __init__(self):
        self.logger = self.log_config()
        self.logger.info("自动网络认证已启动~~ 喜多酱的吉他开始演奏了！♪(´▽｀)")
        self.driver_path = Path("driver").joinpath("msedgedriver.exe")
        
        # 启动时就执行一次驱动更新检查
        self.ensure_driver_updated()

    def get_edge_version(self):
        """通过查询注册表获取本地Edge浏览器的版本号"""
        try:
            # 打开Edge的注册表键
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Edge\BLBeacon')
            # 读取名为 "version" 的值
            version, _ = winreg.QueryValueEx(key, 'version')
            self.logger.info(f"成功检测到本地Edge浏览器版本: {version} 小孤独的浏览器版本呢~ (´• ω •`)")
            return version
        except FileNotFoundError:
            self.logger.error("未在注册表中找到Edge浏览器版本信息。 波奇酱躲在角落里发抖了... (´；ω；`)")
            return None
        except Exception as e:
            self.logger.error(f"读取Edge版本时发生未知错误: {e} 凉酱也不知道该怎么办了... (⊙﹏⊙)")
            return None

    def get_local_driver_version(self):
        """通过执行 msedgedriver.exe --version 获取本地驱动的版本号"""
        if not self.driver_path.exists():
            self.logger.warning(f"驱动文件 {self.driver_path} 不存在。虹夏酱找不到了... (。﹏。*)")
            return None
        try:
            # 使用 subprocess 模块执行命令并捕获输出
            # 添加 CREATE_NO_WINDOW 标志以防止控制台窗口闪烁
            result = subprocess.run(
                [str(self.driver_path), "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 输出格式: "Microsoft Edge WebDriver 140.0.3485.54 (3cc379a8a5fb6b704b2169c01830296ed862ce0d)"
            # 我们需要提取版本号部分
            version_str = result.stdout.strip()
            self.logger.debug(f"驱动版本输出: {version_str}")
            
            # 使用正则表达式提取版本号
            import re
            version_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', version_str)
            if version_match:
                version = version_match.group(1)
                self.logger.debug(f"使用正则表达式解析到的驱动版本: {version}")
                self.logger.info(f"成功获取到本地驱动版本: {version} 喜多酱的吉他调好音了！o(￣▽￣)o")
                return version
            
            # 如果正则表达式方法不行，尝试按空格分割
            parts = version_str.split()
            if len(parts) > 2 and "WebDriver" in parts[1]:
                version = parts[2]  # "Microsoft Edge WebDriver 140.0..."
                self.logger.debug(f"解析到的驱动版本: {version}")
                self.logger.info(f"成功获取到本地驱动版本: {version} 喜多酱的吉他调好音了！o(￣▽￣)o")
                return version
            elif len(parts) > 1:
                version = parts[1]  # "EdgeDriver 140.0..." 或 "Edge 140.0..."
                self.logger.debug(f"解析到的驱动版本: {version}")
                self.logger.info(f"成功获取到本地驱动版本: {version} 喜多酱的吉他调好音了！o(￣▽￣)o")
                return version
            
            self.logger.warning(f"无法从输出中解析版本号: {version_str} 波奇酱搞不懂了... (´• ω •`)")
            return version_str  # 作为最后的备用
        except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
            self.logger.error(f"获取本地驱动版本失败: {e} 凉也不知道该怎么办... (⊙﹏⊙)")
            return None


    def update_driver(self):
        """核心功能：实现驱动的自动下载和更新 (最终精确版)"""
        local_version = self.get_edge_version()
        if not local_version:
            self.logger.error("无法获取本地Edge版本，更新过程终止。波奇酱不知道该怎么办了... (´；ω；`)")
            return False

        try:
            # 1. 访问微软官方WebDriver页面
            url = "https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/"
            self.logger.info(f"正在访问WebDriver官网: {url} 喜多酱要努力查找驱动了！٩(ˊᗜˋ*)و")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0'}
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()

            # 2. 使用精确的解析逻辑
            self.logger.info("使用针对当前官网结构的精确解析逻辑... 虹夏酱要仔细查找了！(￣▽￣)")
            soup = BeautifulSoup(response.text, 'lxml')
            download_url = None

            # 寻找所有包含版本信息的父级div
            version_blocks = soup.find_all('div', class_='block-web-driver__versions')
            if not version_blocks:
                self.logger.error("在页面中未能找到任何 'block-web-driver__versions' 的区块，页面结构可能已改变。凉酱也搞不懂了... (⊙﹏⊙)")
                return False

            for block in version_blocks:
                # 在区块内，版本号是 <strong> 标签的下一个兄弟节点
                # 我们需要获取这个文本节点并去除首尾空格
                version_text_node = block.strong.next_sibling
                if version_text_node:
                    page_version = version_text_node.strip()
                    self.logger.debug(f"检测到页面上的版本: '{page_version}' 小孤独在仔细检查... (´• ω •`)")
                    
                    # 检查页面上的版本是否与本地版本匹配
                    if page_version == local_version:
                        self.logger.info(f"成功匹配到版本 {local_version}! 喜多酱找到了！o(≧∇≦o)")
                        # 在当前区块内寻找 x64 的下载链接
                        # 最可靠的方法是寻找 href 中包含 "win64.zip" 的链接
                        link_tag = block.find('a', href=lambda href: href and 'edgedriver_win64.zip' in href)
                        
                        if link_tag:
                            download_url = link_tag['href']
                            self.logger.info(f"成功找到 x64 下载链接: {download_url} 太棒了！(*^▽^*)")
                            break # 找到后就跳出循环
                        else:
                             self.logger.warning("匹配到版本但未找到 x64 下载链接。波奇酱有点困惑... (´• ω •`)")
            
            if not download_url:
                self.logger.error(f"在官网未找到与本地版本 {local_version} 匹配的 x64 驱动下载链接。凉酱也找不到... (；´д｀)ゞ")
                return False

            # 3. 下载、解压流程 (这部分不变)
            self.logger.info(f"正在下载驱动文件: {download_url} 喜多酱要努力下载了！٩(ˊᗜˋ*)و")
            driver_zip_response = requests.get(download_url, timeout=60)
            driver_zip_response.raise_for_status()

            self.logger.info("下载完成，正在解压... 虹夏酱要小心解压哦！(￣▽￣)")
            temp_dir = Path("temp_driver")
            temp_dir.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(io.BytesIO(driver_zip_response.content)) as zf:
                for member in zf.infolist():
                    if member.filename.endswith('msedgedriver.exe'):
                        zf.extract(member, temp_dir)
                        extracted_path = temp_dir / member.filename
                        self.logger.info(f"文件已解压到: {extracted_path} 解压成功！o(≧∇≦o)")
                        
                        # 确保目标目录存在
                        self.driver_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # 如果目标文件已存在，先删除它
                        if self.driver_path.exists():
                            try:
                                self.driver_path.unlink()
                                self.logger.info("已删除旧的驱动文件 旧驱动再见啦！~(￣▽￣)~")
                            except Exception as e:
                                self.logger.error(f"删除旧驱动文件失败: {e} 波奇酱删除失败了... (´；ω；`)")
                        
                        # 移动文件
                        try:
                            shutil.move(str(extracted_path), str(self.driver_path))
                            self.logger.info(f"驱动已成功更新并放置在: {self.driver_path} 驱动搬家成功！o(≧∇≦o)")
                            
                            # 验证文件是否真的存在
                            if self.driver_path.exists():
                                self.logger.info("验证：驱动文件已成功保存到目标位置 喜多酱完成任务了！٩(ˊᗜˋ*)و")
                            else:
                                self.logger.error("错误：驱动文件未能成功保存到目标位置 波奇酱搞砸了... (´；ω；`)")
                                return False
                            
                            # 清理临时目录
                            shutil.rmtree(temp_dir)
                            return True
                        except Exception as e:
                            self.logger.error(f"移动驱动文件失败: {e} 凉也不知道该怎么办... (⊙﹏⊙)")
                            return False
            
            self.logger.error("在下载的压缩包中未找到 msedgedriver.exe 文件。波奇酱找不到文件... (´；ω；`)")
            return False

        except requests.exceptions.RequestException as e:
            self.logger.error(f"网络请求失败: {e} 网络连接出问题了... (っ °Д °;)っ")
            return False
        except Exception as e:
            self.logger.error(f"驱动更新过程中发生未知错误: {e} 小孤独也不知道该怎么办... (；´д｀)ゞ")
            return False

    def ensure_driver_updated(self):
        """检查驱动是否存在且版本是否匹配，仅在需要时尝试更新"""
        folder_path_methode = Path("driver")
        if not folder_path_methode.exists():
            folder_path_methode.mkdir()
            self.logger.info("driver文件夹已创建~ 虹夏酱创建新文件夹啦！(￣▽￣)")
        
        # 检查网络连接
        if self.isConnectedNet() != 0:
            self.logger.warning("网络未连接，无法检查驱动更新。将使用已有的驱动（如果存在）。波奇酱没有网络了... (´；ω；`)")
            return

        # --- 核心优化逻辑 ---
        required_version = self.get_edge_version()
        if not required_version:
            self.logger.error("无法获取Edge浏览器版本，跳过驱动更新检查。凉酱也不知道版本... (⊙﹏⊙)")
            return

        local_driver_version = self.get_local_driver_version()

        if local_driver_version == required_version:
            self.logger.info(f"本地驱动版本 ({local_driver_version}) 与浏览器版本匹配，无需更新。 喜多酱的吉他调好音了！o(￣▽￣)d")
            self.current_date = datetime.date.today() # 标记今天已检查
            return
        
        self.logger.info(f"驱动版本不匹配或不存在 (本地: {local_driver_version}, 需要: {required_version})。小孤独需要更新驱动了... (´• ω •`)")
        self.logger.info("开始执行驱动自动更新流程... 喜多酱要努力更新了！٩(ˊᗜˋ*)و")

        if self.update_driver():
            self.logger.info("驱动更新流程成功完成。喜多酱太厉害了！o(≧∇≦o)")
            self.current_date = datetime.date.today() # 记录更新日期
        else:
            self.logger.error("驱动更新流程失败。将尝试使用旧的驱动文件（如果存在）。波奇酱更新失败了... (´；ω；`)")

    def isConnectedNet(self):
        # ... (这部分代码保持不变) ...
        response_time = ping3.ping(self.host)
        if response_time is not None:
            self.logger.debug("好耶~网络连接正常~~ 喜多酱可以上网了！(●'◡'●)")
            return 0
        else:
            self.logger.info("完蛋，没有网络连接了！波奇酱断网了... (っ °Д °;)っ")
            return 2

    def log_config(self):
        # ... (这部分代码保持不变) ...
        logging.basicConfig(
            filename="BOCCHI THE ROCK.log",
            filemode="w",
            format="%(asctime)s %(name)s:%(levelname)s:%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.INFO,
            encoding="utf-8",
        )
        logger = logging.getLogger("BOCCHI")
        return logger

# --- main 部分的代码保持不变 ---
if __name__ == "__main__":
    cnt = connect()
    while True:
        cnterror = 0
        new_date = datetime.date.today()

        # 检查是否跨天了，如果跨天了就再执行一次更新检查
        if (new_date != cnt.current_date) and (cnt.isConnectedNet() == 0):
            cnt.logger.info("新的一天开始了，检查驱动是否需要更新... 虹夏酱要开始新的一天了！(￣▽￣)")
            cnt.ensure_driver_updated()

        while cnt.isConnectedNet() != 0:
            cnterror += 1
            if cnterror >= 3:
                cnt.logger.info(r"正在打开Edge... 喜多酱要打开浏览器了！¯\_(ツ)_/¯")
                if not cnt.driver_path.exists():
                    cnt.logger.error("找不到msedgedriver.exe文件，并且自动更新失败！请检查网络或手动下载。波奇酱找不到驱动了... (´；ω；`)")
                    time.sleep(cnt.waitime * 5)
                    break
                
                Se = Service(cnt.driver_path)
                options = webdriver.EdgeOptions()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")

                # 禁用各种网络相关的功能，避免断网时启动失败
                options.add_argument("--no-proxy-server")  # 忽略代理设置
                options.add_argument("--disable-background-networking")  # 禁用后台网络请求
                options.add_argument("--disable-sync")  # 禁用同步
                options.add_argument("--disable-extensions")  # 禁用扩展
                options.add_argument("--disable-default-apps")  # 禁用默认应用
                options.add_argument("--disable-component-update")  # 禁用组件更新
                options.add_argument("--disable-features=NetworkService")  # 禁用网络服务
                options.add_argument("--disable-domain-reliability")  # 禁用域名可靠性监控
                options.add_argument("--disable-client-side-phishing-detection")  # 禁用钓鱼检测

                driver = None
                try:
                    driver = webdriver.Edge(service=Se, options=options)
                    driver.get("http://aaa.uestc.edu.cn/")
                    cnt.logger.info("连接中... 小孤独在努力连接中... (。・ω・。)")
                    user_input = driver.find_element(by=By.XPATH, value='//*[@id="username"]')
                    pw_input = driver.find_element(by=By.ID, value="pwd")
                    login_btn = driver.find_element(by=By.ID, value="loginLink_div")
                    user_input.send_keys(cnt.PHONENUM)
                    driver.execute_script(f"arguments[0].value={cnt.PASSWD};", pw_input)
                    time.sleep(0.5)
                    login_btn.click()
                    time.sleep(0.5)
                    driver.quit()
                    time.sleep(1)
                    cnt.logger.info("连接成功!!! 喜多酱的吉他连接成功了！o((>ω< ))o")
                    cnterror = 0
                except Exception as e:
                    cnt.logger.error(f"认证过程中发生错误: {e} 波奇酱搞砸了... (´；ω；`)")
                    # 如果认证失败，关闭driver（如果已创建）
                    if driver is not None:
                        try:
                            driver.quit()
                        except:
                            pass
            time.sleep(cnt.waitime)
        time.sleep(cnt.waitime)
