# 头环四相机标定采集辅助工具


日常采集与 Kalibr 操作流程：[打开内置 SD 卡版终版 Word 文档](docs/头环四鱼眼相机标定采集流程_内置SD卡版_日常快速启动版本终版.docx)；另有[纯文本版](docs/daily_workflow.zh-CN.txt)。
[English](README.md) | [简体中文](README.zh-CN.md)

本工具用于四路实时预览、Kalibr原生角点证据与摆板提示。版本v1.10.4。预览不保证标定成功。以下是辅助工具的完整部署步骤，不自动运行相机、IMU或联合标定。

## 1 下载完整包

打开Release：
https://github.com/BAAI-Ego/headband-calibration-tools/releases/tag/v1.10.4

在Assets下载两个文件到同一目录：
- headband-calibration-assistant-v1.10.4-full-v2.tar，约1.6GB，包含源码、环境镜像、配置及中英README。
- headband-calibration-assistant-v1.10.4-full-v2.tar.sha256，完整包校验值。

Git仓库和自动Source code下载不含镜像。私有仓库需要有读取权限的账号。该新Release由配套更新脚本成功执行后创建，旧版Release保留。

## 2 准备Linux工作站

镜像平台linux/amd64，工作站需x86_64。头环需已有ROS Noetic、OpenCV、NumPy及原四相机驱动/服务。本包不部署空白头环固件。宿主机不需要另装ROS。建议准备至少20GB空闲空间供下载、解压和Docker镜像层使用；这是预留建议，不是实测最低需求。

```bash
# Linux工作站：检查架构、空间、实际网络接口
uname -m
df -h "$HOME" /var/lib/docker
ip -br addr
ip route
```

Ubuntu/Debian基础工具；Docker已安装则不要重新安装或混用docker.io与Docker CE：

```bash
sudo apt-get update
sudo apt-get install -y openssh-client python3 unzip rsync arp-scan netcat-openbsd
# 仅未安装Docker的新电脑执行
sudo apt-get install -y docker.io
sudo systemctl start docker
docker info
```

当前用户需能直接运行docker。专用工作站可由管理员授权：docker组拥有等同root的访问能力，按本机管理要求执行。

```bash
sudo groupadd --force docker
sudo usermod -aG docker "$USER"
# 完整退出登录后重新登录，再检查
docker info
```

官方权限说明：https://docs.docker.com/engine/install/linux-postinstall/

## 3 校验并导入附件镜像

在两个下载附件所在目录执行。已有同名解压目录时换空目录，避免覆盖。

```bash
sha256sum -c headband-calibration-assistant-v1.10.4-full-v2.tar.sha256
tar -xf headband-calibration-assistant-v1.10.4-full-v2.tar
cd headband-calibration-assistant-v1.10.4-full
sha256sum -c SHA256SUMS

# 检查本机是否已有同名镜像；没有时显示错误是正常的
docker image inspect kalibr:noetic --format '{{.Id}}'
cat environment/image-id-platform.txt
```

若已有不同镜像，先保留并核对，不直接覆盖其标签。确认可以导入后：

```bash
cd environment
sha256sum -c SHA256SUMS
docker load -i kalibr-environment.tar.gz
cd ..
bash tools/check_preview_environment.sh
```

应出现DEPENDENCIES_PASS。镜像ID为sha256:ddbe45d2bd03e8a415688355dc23c4ceedf6eb576e1c6d7eeafa51567fa10b29。它已含ROS和Kalibr绑定，不要在宿主机安装ROS或用pip随意替换编译模块。预览启动临时容器，不需要创建永久kalibr容器。

## 4 找到并检查头环

工作站执行，eno1与网段按现场实际值修改；一次只连接一台头环：

```bash
sudo arp-scan --interface=eno1 192.168.10.0/24
# 修改实际头环IP；确认设备SSH指纹
ssh orangepi@192.168.10.109
```

出现REMOTE HOST IDENTIFICATION HAS CHANGED时，先在头环本地核对指纹，确认后才删除旧记录：

```bash
# 头环本地终端
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
# 工作站终端，核验后执行，IP按实际修改
ssh-keygen -f "$HOME/.ssh/known_hosts" -R 192.168.10.109
```

22端口拒绝连接时，需固件维护者做首次本地SSH/相机服务设置，不是预览软件故障。原流程中的enable/restart服务、SD卡写测试属于明确的一次性操作；不混入只读检查。

SSH进入头环后：

```bash
# 头环终端，只检查现有环境
source /opt/ros/noetic/setup.bash
export ROS_MASTER_URI=http://localhost:11311
python3 -c 'import rospy,cv2,numpy; from sensor_msgs.msg import CompressedImage; print("HEADBAND_DEPENDENCIES_PASS")'
systemctl is-active seeker_cam_bridge.service
for TOPIC in /fisheye/left/image_raw/compressed /fisheye/right/image_raw/compressed /fisheye/bright/image_raw/compressed /fisheye/bleft/image_raw/compressed; do
  if timeout 8 rostopic echo -n 1 "$TOPIC" >/dev/null; then
    echo "PASS $TOPIC"
  else
    echo "FAIL $TOPIC"
  fi
done
exit
```

检查会短时订阅图像并增加负载。四路应PASS。头环IP不能固定写死；SSH通不代表ROS双向网络可达。不要为了预览关闭防火墙或更改相机分辨率。

## 5 核对板配置并启动

preview/config/april_6x6.yaml参考值为6×6、tagSize=0.088m、tagSpacing=0.3。实测黑边长a、白缝b应对应tagSize=a、tagSpacing=b/a。确认本次板后配置，不覆盖历史YAML。

工作站、本包根目录执行；两个IP按实际修改：

```bash
cd preview
# 头环IP 工作站有线IP 档位 自动结束秒数
bash run_temporary_four_preview.sh 192.168.10.109 192.168.10.10 balanced 60
```

浏览器打开http://127.0.0.1:8766。默认单行BRIGHT、RIGHT、LEFT、BLEFT。balanced宽640、目标5FPS，不是录制频率。首次先做60秒验收；正式人工结束模式省略第四参数：

```bash
bash run_temporary_four_preview.sh 192.168.10.109 192.168.10.10 balanced
```

启动会通过SSH在头环临时运行中继，订阅原图、缩放压缩，增加负载，不写持久程序或改驱动。不要同时启动多个实例。未观察到144/144只能表示低清证据不足。

## 6 结束、报告与正式录制

人工模式在预览终端Ctrl+C，等待退出。确认JSON报告已保存后：

```bash
# 当前仍在preview目录
bash ../tools/package_preview_report.sh
```

报告在preview/output。网络中断时清理可能不完整，应核对本次中继，不能默认退出即远端清理成功。文件权限问题应检查输出目录所有权，不对整个工程chmod 777。

原rosbag录制独立执行。头环先确认SD卡挂载/空间：

```bash
# 头环终端
findmnt -no SOURCE,TARGET,FSTYPE /media/orangepi/sdcard
df -h /media/orangepi/sdcard
```

每次新BAG名，正常Ctrl+C一次并等回提示符，再rosbag info、sync、传输、双端SHA256。原命令在docs/头环四鱼眼相机标定采集流程_内置SD卡版_日常快速启动版本终版.docx；不改变原录制。对副本做恢复，.orig.bag通常是未索引备份。reindex成功不代表完整：还需核对时长、四路CompressedImage类型及解码。5.2秒恢复文件、Topic不匹配与DLT点数不足不能当作硬件故障结论。

正式Kalibr仍用独立副本，检查误差和内外参。DS输出在独立测试目录，第三步必须明确指定真实camchain，不能认为自动出现在camera目录。Camera与Camera-IMU分开；第三步模板5Hz、--cams，另需动态Camera-IMU BAG与imu.yaml，本部署包不提供。

## 7 本次遇到的问题

| 现象 | 处理 |
|---|---|
| 文件不存在 | 先确认文件已下载、真实文件名/路径；聊天链接不是工作站路径。 |
| 终端一直显示 > | 引号或heredoc没结束，Ctrl+C取消；用脚本文件，避免长段粘贴。 |
| NameError 本地依赖导入通过 | 旧检查脚本引号错误，现版使用Python heredoc；不靠安装软件修复。 |
| GDK连接失败/rosdep view empty | 检查是否有后续Traceback及退出码；警告本身不证明通过，不为消警告盲目rosdep init或启动GUI。 |
| aslam_cv等导入失败 | 核对镜像ID、setup.bash，停止并核实环境，不pip替换绑定。 |
| 缺少kalibr:noetic | 导入Release中的实际镜像；不等于需要启动原kalibr容器。 |
| docker权限不足 | 按第2节由管理员配置，重新登录。 |
| SSH通但无视频 | 查实际IP、ROS双向可达、Topic和服务；不是只检查22端口。 |
| 8766占用 | ss -ltnp检查，只停止确认属于旧预览的进程。 |
| 校验值不一致 | 停止导入，重新下载对应附件。 |
| 上传GitHub中断 | 不重复提交源码；先查看main与Release Assets，按缺失附件续传。 |

## 8 发布状态与验收

原工作站镜像导出及SHA256已通过；Python/Shell语法检查完成。未做新工作站完整验收，不承诺下载后必然标定成功。另一工作站应记录平台、镜像ID、日期、四路视频连续性、探针完成/异常、报告保存、正常退出清理、并行录制及独立Kalibr质量检查。

离线扫描原脚本含历史路径及20Hz取样，不等同当前10Hz标定，迁移前核对。工具许可证由权利人确认，第三方许可保留。
