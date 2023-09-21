import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import ping3

"""
    修改SCHOOLID 和 PASSWD两项就好，waitime项可修改联网查询间隔时间
    默认每10s检查一次连接，若三次无连接，则重连。
"""
# 12341234


class connect():

    PHONENUM = '191********'    # 手机号
    PASSWD = '********'         # 密码
    host = "223.5.5.5"  # 联网查询目标地址
    waitime = 10  # 每次联网查询间隔秒数

    def isConnectedNet(self):
        response_time = ping3.ping(self.host)
        if response_time is not None:
            print("Connect succeed", time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(time.time())))
            return 0
        else:
            print("Connect lose", time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(time.time())))
            return 2


if __name__ == "__main__":
    cnt = connect()
    while True:
        cnterror = 0  # 错误次数
        while (cnt.isConnectedNet() != 0):
            cnterror += 1
            # print("错误次数:", cnterror)
            if cnterror >= 3:  # 经过(错误次数*cnt.waitime)时间后，开始重连

                from selenium.webdriver.edge.service import Service
                # from selenium.webdriver.chrome.service import Service as Se
                print("Using Edge")

                Se = Service('msedgedriver.exe')
                options = webdriver.EdgeOptions()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                driver = webdriver.Edge(service=Se, options=options)

                try:
                    driver.get('http://aaa.uestc.edu.cn/')
                    user_input = driver.find_element(
                        by=By.XPATH, value='//*[@id="username"]')
                    pw_input = driver.find_element(by=By.ID, value='pwd')
                    login_btn = driver.find_element(
                        by=By.ID, value='loginLink_div')
                    user_input.send_keys(cnt.PHONENUM)
                    driver.execute_script(
                        f"arguments[0].value={cnt.PASSWD};", pw_input)
                    time.sleep(0.5)
                    login_btn.click()
                    time.sleep(0.5)
                    driver.quit()
                    time.sleep(1)
                except:
                    pass
                else:
                    cnterror = 0
        time.sleep(cnt.waitime)

# pyinstaller -F -w internetconnectuestc.py
