import time
import datetime
import shutil
import ping3
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
import logging


"""
    修改PHONENUM 和 PASSWD两项就好，waitime项可修改联网查询间隔时间
    默认每10s检查一次连接，若三次无连接，则重连
    第一次运行请在有网络的环境下运行，程序启动时会自动下载webdriver
    之后程序会在每次系统日期发生变更的时候自动下载最新版webdriver
"""


class connect:
    PHONENUM = "191********"  # 手机号
    PASSWD = "********"  # 密码
    host = "223.5.5.5"  # 联网查询目标地址
    waitime = 10  # 每次联网查询间隔秒数
    current_date = 0  # 驱动下载日期

    def __init__(self):
        self.logger = self.log_config()
        self.logger.info("自动网络认证已启动~~ (～￣▽￣)～")
        self.driver_path = self.driver_file_download()

    def isConnectedNet(self):
        response_time = ping3.ping(self.host)
        if response_time is not None:
            self.logger.debug("好耶~网络连接正常~~ (●'◡'●)")
            return 0
        else:
            self.logger.info("完蛋，没有网络连接了！ (っ °Д °;)っ")
            return 2

    def driver_file_download(self):
        folder_path = "driver"
        driver_path = Path(folder_path).joinpath("msedgedriver.exe")

        # 创建 Path 对象
        folder_path_methode = Path(folder_path)
        # 检查文件夹是否存在
        if not folder_path_methode.exists():
            # 创建文件夹
            folder_path_methode.mkdir()
            self.logger.info("driver文件夹已创建~")
        else:
            self.logger.info("driver文件夹已存在...")
        if self.isConnectedNet() == 0:
            self.logger.info("有网络连接！快快把最新驱动端上来罢！！")
            try:
                download_path = EdgeChromiumDriverManager().install()
                # 复制文件到目标位置
                shutil.copy(download_path, folder_path)
                self.logger.info("驱动下载成功!!! ( •̀ ω •́ )✧")
                # 获取驱动下载日期
                self.current_date = datetime.date.today()
                self.logger.info("驱动下载日期：%s", self.current_date)
            except:
                self.logger.info("下载失败，先不下载了Orz..")
            else:
                pass
        return driver_path

    def log_config(self):
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


if __name__ == "__main__":
    cnt = connect()

    while True:
        cnterror = 0  # 错误次数
        # 获取当前日期
        new_date = datetime.date.today()

        # 检查是否发生了日期变化
        if (new_date != cnt.current_date) and (cnt.isConnectedNet() == 0):
            cnt.logger.info("早上好~ 程序已经运行一天啦，先下载驱动吧！")
            # 下载驱动，并更新cnt.current_date
            cnt.driver_file_download()

        while cnt.isConnectedNet() != 0:
            cnterror += 1
            #  logger.info("错误次数:", cnterror)
            if cnterror >= 3:  # 经过(错误次数*cnt.waitime)时间后，开始重连
                cnt.logger.info("正在打开Edge... ¯\_(ツ)_/¯")
                Se = Service(cnt.driver_path)  # msedgedriver.exe文件存放位置
                options = webdriver.EdgeOptions()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                driver = webdriver.Edge(service=Se, options=options)
                # print(driver.capabilities["browserVersion"])
                try:
                    driver.get("http://aaa.uestc.edu.cn/")
                    cnt.logger.info("连接中... (。・ω・。)")

                    user_input = driver.find_element(
                        by=By.XPATH, value='//*[@id="username"]'
                    )
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

                except:
                    pass
                else:
                    cnterror = 0
            time.sleep(cnt.waitime)
        time.sleep(cnt.waitime)

# pyinstaller -F -w internetconnectuestc.py
