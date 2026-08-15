# oes指示灯

适用于 OES 一代三盘位设备的 Linux `mdadm` RAID 指示灯控制器。

## 功能

- RAID 正常时，三个硬盘绿灯同步柔和呼吸。
- RAID 降级、阵列异常或成员盘丢失时，对应盘位快速爆闪。
- 故障时关闭绿色电源灯，并让红色电源灯常亮。
- 每 200 毫秒检查一次 `/sys/block/md0/md`，故障能快速反映到灯光。
- 服务停止时恢复内核原有的 `ata1`、`ata2`、`ata3` 硬盘活动触发器。
- 不联网、无遥测、无账号密码，也不读取硬盘文件内容。

> OES 一代的单个硬盘灯只有绿色通道，不能单独显示红色。因此坏盘采用“对应绿灯快速爆闪 + 红色电源灯常亮”的策略。

## 默认硬件映射

| 盘位 | LED sysfs 名称 | 恢复触发器 |
| --- | --- | --- |
| 1 | `green:disk` | `ata1` |
| 2 | `green:disk_1` | `ata2` |
| 3 | `green:disk_2` | `ata3` |

默认阵列为 `md0`，电源灯为 `green:power` 和 `red:power`。

## 安装

```bash
git clone https://github.com/w87051809/oes-raid-led-controller.git
cd oes-raid-led-controller
sudo ./install.sh
```

查看运行状态：

```bash
systemctl status oes-raid-leds.service
journalctl -u oes-raid-leds.service -f
```

## 配置

配置文件为 `/etc/default/oes-raid-leds`。修改后执行：

```bash
sudo systemctl restart oes-raid-leds.service
```

常用参数：

| 参数 | 作用 | 默认值 |
| --- | --- | --- |
| `--md` | md 阵列名称 | `md0` |
| `--led` | 硬盘 LED 名称，可重复 | OES 三盘位名称 |
| `--ata-trigger` | 服务停止时恢复的触发器，可重复 | `ata1`～`ata3` |
| `--breath-seconds` | 一次完整呼吸的秒数 | `4.0` |
| `--health-interval` | RAID 检查间隔 | `0.20` |
| `--failure-on-ms` | 故障爆闪亮灯时间 | `80` |
| `--failure-off-ms` | 故障爆闪灭灯时间 | `80` |

查看本机可用 LED：

```bash
ls -1 /sys/class/leds
```

## 卸载

```bash
sudo ./uninstall.sh
```

卸载会保留 `/etc/default/oes-raid-leds`，避免误删用户配置。

## 开发检查

```bash
python3 -m py_compile src/oes-raid-leds.py
python3 -m unittest discover -s tests -v
```

## 许可

[MIT](LICENSE)
