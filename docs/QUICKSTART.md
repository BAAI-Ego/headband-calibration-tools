# 新工作站部署与使用

## 0 交付者先准备两份交付物

A. 本源码包：preview/、tools/、docs/、README、SHA256SUMS。
B. 现有工作站导出的kalibr:noetic环境包：kalibr-environment.tar.gz、SHA256SUMS、image-id-platform.txt。

这两个包齐备后才进入新工作站部署。工具源码不包含相机硬件驱动或镜像。空白头环需要由设备维护者先部署原固件/驱动；本工具不替代此步骤。

在原Linux工作站解压源码包，进入headband-calibration-assistant-release目录后运行：

```bash
bash tools/check_preview_environment.sh
bash tools/export_kalibr_environment.sh kalibr:noetic ./kalibr-environment-delivery
```

脚本只导出预览实际使用的镜像。不会修改生产容器、生产镜像标签、BAG或数据卷；会启动短时本地依赖检查容器、写入交付目录。不是docker commit。若正式kalibr容器写层另有补丁，其结果不代表预览镜像环境，需要分开审计，不自动混入。

导出完成后把kalibr-environment-delivery目录单独移交。不要提交镜像大包到Git源码。若提供公开下载，发布者填写真实下载地址，记录SHA256与平台；当前尚无发布地址，不填写虚构地址。

## 1 新工作站前置条件

推荐使用与现有工作站相同的Linux x86_64环境。Docker需可用，用户能运行docker info；不要求宿主机安装ROS或Kalibr。arm64工作站不在本次验证范围。

Docker按官方指南安装：https://docs.docker.com/engine/install/ 。不要重复安装现有Docker。Ubuntu/Debian上缺少基础工具时，可由管理员执行：

```bash
sudo apt-get update
sudo apt-get install -y openssh-client python3 unzip rsync arp-scan netcat-openbsd
```

工作站需要能通过实际有线地址连接头环，ROS端点需要双向可达。仅ssh22可通不能证明ROS预览可通。网络配置按现场网段设置，不自动覆盖已有网络配置。

## 2 解压与验证源码

```bash
unzip headband-calibration-assistant-release-20261012-v3.zip
cd headband-calibration-assistant-release
sha256sum -c SHA256SUMS
```

有已存在同名目录时先使用新的解压目录，不直接覆盖。

## 3 导入环境镜像

把环境交付目录放到当前源码目录下：

```bash
cd kalibr-environment-delivery
sha256sum -c SHA256SUMS
docker image inspect kalibr:noetic
```

最后一条若显示已有镜像，先比较image-id-platform.txt，不直接覆盖不同环境。新电脑没有该标签时运行：

```bash
docker load -i kalibr-environment.tar.gz
cd ..
bash tools/check_preview_environment.sh
```

本地依赖检查失败时停止，不通过pip随意替换Kalibr绑定。

## 4 确认头环现有依赖

一次只接一台头环。Linux工作站查IP：

```bash
sudo arp-scan --interface=eno1 192.168.10.0/24
```

eno1与网段均为原工作站示例，新机器按实际接口/网段修改。核验SSH指纹后连接。下面IP示例必须改为刚扫描到的实际IP：

```bash
ssh orangepi@192.168.10.109
```

进入orangepi头环终端，仅检查：

```bash
source /opt/ros/noetic/setup.bash
export ROS_MASTER_URI=http://localhost:11311
python3 -c 'import rospy, cv2, numpy; from sensor_msgs.msg import CompressedImage; print("头环依赖导入通过")'
systemctl is-active seeker_cam_bridge.service
findmnt -no SOURCE,TARGET,FSTYPE /media/orangepi/sdcard
for TOPIC in /fisheye/left/image_raw/compressed /fisheye/right/image_raw/compressed /fisheye/bright/image_raw/compressed /fisheye/bleft/image_raw/compressed; do
  if timeout 8 rostopic echo -n 1 "$TOPIC" >/dev/null; then
    echo "PASS $TOPIC"
  else
    echo "FAIL $TOPIC"
  fi
done
exit
```

检查会临时订阅图像，存在短时负载。服务缺失或依赖缺失应交由固件维护者处理；不要在头环盲目安装依赖、改分辨率或持久配置。

## 5 核对标定板

preview/config/april_6x6.yaml是参考配置，不是所有板的通用尺寸。实测黑色边长a、白缝b：tagSize=a，tagSpacing=b/a。仅确认后配置本次工具目标；不覆盖已有生产或历史YAML。

## 6 启动实时辅助工具

回到Linux工作站源码根目录。先告知标定员：启动会在头环临时运行中继并增加负载。以下示例IP必须改为实际值：

```bash
cd preview
bash run_temporary_four_preview.sh 192.168.10.109 192.168.10.10 balanced
```

浏览器打开 http://127.0.0.1:8766 。默认单行BRIGHT、RIGHT、LEFT、BLEFT。balanced为宽640、目标5FPS；不是原相机发布频率。省略第四参数为人工结束。做60秒验收时：

```bash
bash run_temporary_four_preview.sh 192.168.10.109 192.168.10.10 balanced 60
```

不要同时启动多个预览实例。不要更改原录制命令或相机驱动。

## 7 停止与查看报告

人工模式在预览终端按Ctrl+C，等待命令退出；网页可结束并保存报告。报告在preview/output/；原脚本可能受中断退出码影响未执行外层打包，检查JSON实际存在后再打包：

```bash
bash ../tools/package_preview_report.sh
```

该命令生成新报告包和SHA256，不覆盖已有包。SSH网络突然中断时退出清理可能不完整，需要核实本次中继状态，不能把终端退出当作远端清理成功证据。

## 8 录BAG与正式标定

预览验收后再按docs/source_workflow.docx采集；录制正常Ctrl+C后等待收尾、rosbag info、sync、传输SHA256。正式标定使用独立副本并检查四路类型/消息数。本文只部署采集辅助工具，不自动执行第一步、IMU或联合标定，也不自动重建原BAG索引。

## 9 常见阻断

- 缺少kalibr:noetic：先导入交付镜像。
- aslam_cv等导入失败：镜像环境不匹配，停止并查环境版本。
- SSH身份改变：核验新头环本地指纹，不直接删记录接受。
- SSH通但预览无流：查实际ROS地址、双向网络、服务和Topic。
- 端口8766被占用：先结束已确认的旧预览实例，不盲目kill其他进程。
- 没观察到144/144：只是当前低清证据不足，不能标为BAG失败。
- reindex成功：仍需检查时长、类型和解码；不能证明完整。

## 10 发布验收与源码构建备选

在新工作站记录镜像ID、平台、四路视频连续性、探针完成/异常、报告、正常退出清理和并行录制状态。未做实测前不标注“新电脑即用”。

无法拿到已验证镜像时，可参考官方Kalibr构建指南：https://github.com/ethz-asl/kalibr/wiki/Installation 。先clone官方仓库，再checkout原记录提交1f60227，并检查该提交是否有Dockerfile_ros1_20_04，再按其Dockerfile构建为kalibr:noetic。不能把最新版构建直接当成历史环境复现。构建需要外网和编译资源，Python绑定通过本包检查后仍需头环验收。

## GitHub上架顺序

1. 解压源码到目标Git仓库的新目录，检查README和源码清单。
2. 原工具未带LICENSE，由权利人确定许可证；第三方库保留原许可。
3. 不提交output、BAG、视频、镜像大包、密码和SSH文件。
4. 用Git源码提供本包；镜像通过独立交付资产提供，填写真实下载地址与校验值。
5. 完成另一台工作站验收，再打正式版本标签。
