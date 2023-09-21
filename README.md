# AutoConnectToInternetUESTC

电子科技大学校园网电信手机认证自动登录脚本

## 介绍
本项目是基于[Auto-Connect-Net-UESTC](https://github.com/innns/Auto-Connect-Net-UESTC)修改而来，主要修改并实现了对于电信校园网的手机认证支持。

## 如何使用
本项目基于`python3.11.5`建立

配置 WebDriver，需要选择对应版本的 WebDriver

[msedgedriver.exe](https://developer.microsoft.com/zh-cn/microsoft-edge/tools/webdriver/)文件请放在AutoConnectToInternetUESTC文件夹里

请自行检查依赖，包括selenium,ping3和time模块
```shell
pip install selenium
pip install ping3
```
默认支持每10s检测一次网络，三次无连接则重连。
添加账号密码即可运行。


## 测试环境
宿舍有线电信，采用网页手机认证。

## 打包为exe文件
1. 控制台中使用`cd`命令定位到AutoConnectToInternetUESTC文件夹
2. 运行下面的命令，记得检查是否安装了`pyinstaller`
```shell
pyinstaller -F -w internetconnectuestc.py
```
3. exe文件生成到了dist文件夹里

## 添加打包好的exe文件到开机自启动

1. `win+R`打开`运行`
2. 输入`shell:startup`，这将会打开“启动”文件夹
3. 把自己的exe文件（或快捷方式）放进去
4. 完成！这样你就可以在任务管理器里看到自己的程序被成功添加为自启动项了

（测试使用Windows11系统，其他版本自行测试）

## 存在的问题
当程序启动，重新连接网络时会弹出控制台，等待连接完成关闭即可~
