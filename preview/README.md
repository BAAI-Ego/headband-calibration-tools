# 临时四路低分辨率预览中继 v1.10.3

这是采集辅助工具，不替代原 `rosbag record` 或 Kalibr。头环端中继代码仅经 SSH 标准输入运行 `python3 -`：只在内存运行，退出即消失；不创建头环文件、不安装软件、不设置参数、不修改 BAG、YAML、录制命令、相机驱动或持久配置。

## v1.10.3 默认一字排开

- 默认从左到右：`BRIGHT → RIGHT → LEFT → BLEFT`。
- 四路固定一行；窗口不足时横向滚动，不自动变为两行。
- “编辑排布”和“恢复默认排布”保留；本版本使用新的浏览器布局键，不读取旧版本的排布缓存。

## v1.10.2 的新增只读 BAG 分析

- `run_readonly_bag_evidence_scan.sh` 直接复用当前 Kalibr 源码的 `BagImageDatasetReader(..., bag_freq=20.0)`，因此选帧规则与最终验证一致。
- 对原始高分辨率图逐帧运行 Kalibr 原生 AprilGrid detector，输出每路完整 `144/144` 候选计数、位置、板框面积代理量和完整候选 CSV。
- 不修改头环、BAG、YAML、原 `rosbag record` 或官方 Kalibr 命令；它只在 Linux `/data/validation_runs/` 写入新的分析结果。
- 结束时自动生成分析包和 SHA256，便于上传核验。
- 新增可选 `all-detected` 离线模式：除完整 `144/144` 候选外，额外写出每帧“检测到 AprilGrid 且有角点”的时间戳、角点数、板框面积和画面位置。它仅用于历史 BAG 的共同可见/重叠分析；不包含图像像素，不改变 BAG 或 YAML。

运行当前正式 BAG：

```bash
cd /home/key/Downloads/headband_calibration_preview_relay_v1.10.1
chmod +x run_readonly_bag_evidence_scan.sh
./run_readonly_bag_evidence_scan.sh \
  /data/live_bags/formal_headband_20260917_151338.bag \
  readonly_formal_headband_20260917_151338
```

运行“所有检测到板的观测”离线分析（扫描时间与普通扫描同量级，输出包会更大）：

```bash
./run_readonly_bag_evidence_scan.sh \
  /data/live_bags/formal_headband_20260917_151338.bag \
  readonly_formal_headband_20260917_151338_all_detected \
  all-detected
```

批量扫描五个历史纯相机 BAG，并输出一个可上传的汇总包：

```bash
cd /home/key/Downloads/headband_calibration_preview_relay_v1.10.3
chmod +x run_historical_camera_overlap_scan.sh
./run_historical_camera_overlap_scan.sh
```

该命令默认只读历史目录 `/media/key/A8D0F8ACD0F8823C/头环原件(温)/kalibr`，并只在 Linux 的 `/home/key/文档/kalibr/data/validation_runs/` 写入新结果；不访问头环。

## v1.9.2 的界面变化

- 四路视频默认改为单行：① BRIGHT、② RIGHT、③ LEFT、④ BLEFT；窄窗口时可横向滚动，不会回落为双层。
- “编辑排布”和“恢复默认排布”继续保留。拖拽仅改变单行中的左右顺序、相邻关系与摆板箭头；布局仍只保存在 Linux 浏览器本地。

## v1.9 的变化

- 删除“优先检测此路”和“恢复四路轮询”按钮。
- Linux 端四路 Kalibr 原生探针独立自动运行；每路只取检测开始时的最新低清帧，旧帧不排队，因此一条慢探针不会阻塞视频或其他三路。
- 页面和报告记录每路实际完成检测数、最近检测耗时、超时数和异常数。每路的约 1 FPS 只是目标，不能提前承诺。
- 临时中继时长成为第 4 个参数，允许 60–900 秒；页面显示剩余时间。
- 同一预览帧不重复检测；倒计时归零会自动保存 `relay_time_limit_reached` 快照并退出，避免中继停止后重复检测旧帧或由迟点保存造成的 `STALE` 混入本次基准。

## 固定边界

- 蓝色是当前动作或已观察证据；黄色是证据不足或不确定；红色仅是低清预览流异常。三者都不是 Kalibr 成功/失败结论。
- `144/144` 是 Kalibr 原生 `imageGridPoint` 角点计数；低清预览未观察到完整网格只能表示不确定。
- 最终有效性仍以不变的官方 Kalibr 自动标定及重投影验证决定。
- 点击“结束并保存报告”会固定点击瞬间状态；结束后预览自然停止造成的 `STALE` 不覆盖该快照。

## 运行 60 秒性能基准

```bash
cd /home/key/Downloads
tar -xzf headband_calibration_preview_relay_v1.10.tar.gz
cd headband_calibration_preview_relay_v1.10
chmod +x run_temporary_four_preview.sh
./run_temporary_four_preview.sh 192.168.10.11 192.168.10.10 balanced 60
```

浏览器打开 `http://127.0.0.1:8766`。让 AprilGrid 依次或尽量同时进入四路画面。可在倒计时结束前点击“结束并保存报告”；若不点击，到时会自动保存并结束。不录 BAG。运行结束后，Linux 的 `output/` 目录会生成 `output.tar.gz` 及 SHA256；上传该报告包用于核验。
