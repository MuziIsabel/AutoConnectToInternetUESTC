# AutoConnectToInternetUESTC

电子科技大学校园网电信手机认证自动登录脚本 V2.0

## 1. 介绍
- **适用于宿舍有线电信的网页手机认证**
- 本项目是基于[Auto-Connect-Net-UESTC](https://github.com/innns/Auto-Connect-Net-UESTC)修改而来，主要修改并实现了对于电信校园网的手机认证支持。
- 默认支持每10s检测一次网络，三次无连接则重连。
添加账号密码即可运行。

## 2. 如何使用
本项目基于`python3.11.5`建立
> **重要提示：第一次运行时请在有网络的环境下运行，程序会在启动时自动下载WebDriver文件。**
> **之后程序会在电脑日期发生变更时下载最新的[WebDriver](https://developer.microsoft.com/zh-cn/microsoft-edge/tools/webdriver/)文件**
> *为了解决因edge浏览器自动更新而失效的问题，因此现在不用禁止edge浏览器自动更新也可以使用
### 2.1 一键下载
下载安装`requirements.txt`文件中描述的依赖
```shell
pip install -r requirements.txt
```
### 2.2 在代码中填写你的手机号和密码
```python
  PHONENUM = "**************"  # 手机号
  PASSWD = "********"  # 密码
```

## 3. 打包为exe文件
1. 在终端中使用`cd`命令定位到AutoConnectToInternetUESTC文件夹
2. 运行下面的命令，没安装`pyinstaller`的安装一下
   ```shell
   pyinstaller -F -w internetconnectuestc.py
   ```
3. exe文件生成到了dist文件夹里

## 4. 添加打包好的exe文件到开机自启动

1. `win+R`打开`运行`
2. 输入`shell:startup`，这将会打开“启动”文件夹
3. 为程序创建一个快捷方式，并把它放到“启动”文件夹
4. 完成！这样你就可以在任务管理器里看到自己的程序被成功添加为自启动项了

## 5. 其他问题
- 如果被Windows自带的防火墙误删了，请手动添加为排除项。
  >"Windows安全中心"->"病毒和威胁防护"->"添加或删除排除项"，将exe文件添加进去即可
- 如果使用的代理软件，现在无须担心，认证时会自动跳过代理。