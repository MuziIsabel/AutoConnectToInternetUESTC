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
    PHONENUM = "*********"  # 手机号
    PASSWD = "*********"  # 密码
    host = "223.5.5.5"
    waitime = 10
    current_date = 0

    def __init__(self):
        self.logger = self.log_config()
        self.logger.info("自动网络认证已启动~~ (～￣▽￣)～")
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
            self.logger.info(f"成功检测到本地Edge浏览器版本: {version}")
            return version
        except FileNotFoundError:
            self.logger.error("未在注册表中找到Edge浏览器版本信息。")
            return None
        except Exception as e:
            self.logger.error(f"读取Edge版本时发生未知错误: {e}")
            return None

    def get_local_driver_version(self):
        """通过执行 msedgedriver.exe --version 获取本地驱动的版本号"""
        if not self.driver_path.exists():
            return None
        try:
            # 使用 subprocess 模块执行命令并捕获输出
            result = subprocess.run(
                [str(self.driver_path), "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            # 输出通常是 "Microsoft Edge WebDriver 125.0.2535.85 ..."
            # 我们需要提取版本号部分
            version_str = result.stdout.strip()
            # 按空格分割后，版本号通常在第二个位置（索引1）或第三个位置（索引2）
            parts = version_str.split()
            if len(parts) > 2 and "WebDriver" in parts[1]:
                 return parts[2] # "Microsoft Edge WebDriver 125.0..."
            elif len(parts) > 1:
                 return parts[1] # "EdgeDriver 125.0..."
            return version_str # 作为最后的备用
        except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
            self.logger.error(f"获取本地驱动版本失败: {e}")
            return None


    def update_driver(self):
        """核心功能：实现驱动的自动下载和更新 (最终精确版)"""
        local_version = self.get_edge_version()
        if not local_version:
            self.logger.error("无法获取本地Edge版本，更新过程终止。")
            return False

        try:
            # 1. 访问微软官方WebDriver页面
            url = "https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/"
            self.logger.info(f"正在访问WebDriver官网: {url}")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0'}
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()

            # 2. 使用精确的解析逻辑
            self.logger.info("使用针对当前官网结构的精确解析逻辑...")
            soup = BeautifulSoup(response.text, 'lxml')
            download_url = None

            # 寻找所有包含版本信息的父级div
            version_blocks = soup.find_all('div', class_='block-web-driver__versions')
            if not version_blocks:
                self.logger.error("在页面中未能找到任何 'block-web-driver__versions' 的区块，页面结构可能已改变。")
                return False

            for block in version_blocks:
                # 在区块内，版本号是 <strong> 标签的下一个兄弟节点
                # 我们需要获取这个文本节点并去除首尾空格
                version_text_node = block.strong.next_sibling
                if version_text_node:
                    page_version = version_text_node.strip()
                    self.logger.debug(f"检测到页面上的版本: '{page_version}'")
                    
                    # 检查页面上的版本是否与本地版本匹配
                    if page_version == local_version:
                        self.logger.info(f"成功匹配到版本 {local_version}!")
                        # 在当前区块内寻找 x64 的下载链接
                        # 最可靠的方法是寻找 href 中包含 "win64.zip" 的链接
                        link_tag = block.find('a', href=lambda href: href and 'edgedriver_win64.zip' in href)
                        
                        if link_tag:
                            download_url = link_tag['href']
                            self.logger.info(f"成功找到 x64 下载链接: {download_url}")
                            break # 找到后就跳出循环
                        else:
                             self.logger.warning("匹配到版本但未找到 x64 下载链接。")
            
            if not download_url:
                self.logger.error(f"在官网未找到与本地版本 {local_version} 匹配的 x64 驱动下载链接。")
                return False

            # 3. 下载、解压流程 (这部分不变)
            self.logger.info(f"正在下载驱动文件: {download_url}")
            driver_zip_response = requests.get(download_url, timeout=60)
            driver_zip_response.raise_for_status()

            self.logger.info("下载完成，正在解压...")
            with zipfile.ZipFile(io.BytesIO(driver_zip_response.content)) as zf:
                for member in zf.infolist():
                    if member.filename.endswith('msedgedriver.exe'):
                        zf.extract(member, "temp_driver")
                        extracted_path = Path("temp_driver") / member.filename
                        self.driver_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(extracted_path), str(self.driver_path))
                        self.logger.info(f"驱动已成功更新并放置在: {self.driver_path}")
                        shutil.rmtree("temp_driver")
                        return True
            
            self.logger.error("在下载的压缩包中未找到 msedgedriver.exe 文件。")
            return False

        except requests.exceptions.RequestException as e:
            self.logger.error(f"网络请求失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"驱动更新过程中发生未知错误: {e}")
            return False

    def ensure_driver_updated(self):
        """检查驱动是否存在且版本是否匹配，仅在需要时尝试更新"""
        folder_path_methode = Path("driver")
        if not folder_path_methode.exists():
            folder_path_methode.mkdir()
            self.logger.info("driver文件夹已创建~")
        
        # 检查网络连接
        if self.isConnectedNet() != 0:
            self.logger.warning("网络未连接，无法检查驱动更新。将使用已有的驱动（如果存在）。")
            return

        # --- 核心优化逻辑 ---
        required_version = self.get_edge_version()
        if not required_version:
            self.logger.error("无法获取Edge浏览器版本，跳过驱动更新检查。")
            return

        local_driver_version = self.get_local_driver_version()

        if local_driver_version == required_version:
            self.logger.info(f"本地驱动版本 ({local_driver_version}) 与浏览器版本匹配，无需更新。 o(￣▽￣)d")
            self.current_date = datetime.date.today() # 标记今天已检查
            return
        
        self.logger.info(f"驱动版本不匹配或不存在 (本地: {local_driver_version}, 需要: {required_version})。")
        self.logger.info("开始执行驱动自动更新流程...")

        if self.update_driver():
            self.logger.info("驱动更新流程成功完成。")
            self.current_date = datetime.date.today() # 记录更新日期
        else:
            self.logger.error("驱动更新流程失败。将尝试使用旧的驱动文件（如果存在）。")

    def isConnectedNet(self):
        # ... (这部分代码保持不变) ...
        response_time = ping3.ping(self.host)
        if response_time is not None:
            self.logger.debug("好耶~网络连接正常~~ (●'◡'●)")
            return 0
        else:
            self.logger.info("完蛋，没有网络连接了！ (っ °Д °;)っ")
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
            cnt.logger.info("新的一天开始了，检查驱动是否需要更新...")
            cnt.ensure_driver_updated()

        while cnt.isConnectedNet() != 0:
            cnterror += 1
            if cnterror >= 3:
                cnt.logger.info(r"正在打开Edge... ¯\_(ツ)_/¯")
                if not cnt.driver_path.exists():
                    cnt.logger.error("找不到msedgedriver.exe文件，并且自动更新失败！请检查网络或手动下载。")
                    time.sleep(cnt.waitime * 5)
                    break
                
                Se = Service(cnt.driver_path)
                options = webdriver.EdgeOptions()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                
                # --- 新增的魔法代码 ---
                # 这个参数告诉浏览器实例忽略所有代理，进行直接网络连接
                options.add_argument("--no-proxy-server")
                
                driver = webdriver.Edge(service=Se, options=options)
                try:
                    driver.get("http://aaa.uestc.edu.cn/")
                    cnt.logger.info("连接中... (。・ω・。)")
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
                    cnt.logger.info("连接成功!!! o((>ω< ))o")
                except Exception as e:
                    cnt.logger.info(f"认证过程中发生错误: {e}")
                    # 如果认证失败，可以考虑关闭driver
                    try:
                        driver.quit()
                    except:
                        pass
                else:
                    cnterror = 0
            time.sleep(cnt.waitime)
        time.sleep(cnt.waitime)
