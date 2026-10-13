# NetFlow bulk：实测容量与查询报告

日期：2026-10-13；Issue [#304](https://github.com/Notyet1307/Exposure-Agent/issues/304)，固定合同 `ee61c8c`；业务源码 `6d491d737f4f9f6eef60d372e507cad99a0a629b`，测试/harness提交 `795d119`。这里只报告合成数据实测。**TB 验收未执行**。

## 结论与范围

1 GB（十进制）输入在 Linux arm64、768 MiB 硬容器内存限制内完成，实际发生外存 spill。另以同一输入完成 PostgreSQL 投影与独立进程 worker/API 查询验证；真实 agent-compose/Linux guest/HTTP 链路完成128 MB。三项不是同一个测试，不把离线引擎当成真实调度验收。

10 GB预检需要130,064,771,072字节可用磁盘，当时只有113,013,784,576字节，停止生成和执行。100 GB、1 TB未继续。未估算TB吞吐、日新增量或正式硬件要求。

## 环境和输入

宿主 Apple M1 Pro、16 GiB RAM；容器 Linux 7.2.9 / aarch64、OrbStack。Linux引擎Python3.14.8，macOS API/worker Python3.14.6；DuckDB1.5.6、PyArrow26.0.0，均来自锁文件。Linux arm64 runner已实际构建并运行；Linux amd64完整镜像/运行仍NOT_RUN。

固定seed304，4个CSV；目标约1024字节/行，IPv6比例0.35、生成器duplicate参数0.1、跨文件overlap参数0.1、热点参数0.1、对象目标100,000、peer目标500,000。这些是输入控制参数，不能相加当作实际重复率。真实输入1,000,001,608字节、1,053,312逻辑行；不是全相同行。输入和分片摘要见[机器回执](evidence/netflow-bulk/engine-1gb-hard-memory.json)。

结果：raw=1,053,312，invalid=0，filtered=0，retained=1,053,312，unique=830,253，duplicate=223,059。实际合并副本约21.18%；表示当前合同下重复导出记录，不表示真实会话数。

## 1 GB硬内存引擎

| 指标 | 实测 |
|---|---:|
| 容器memory / memory-swap | 805,306,368 / 805,306,368 B（无额外swap） |
| CPU / pids | 1 CPU / 128 |
| DuckDB buffer / threads | 128 MB / 1 |
| 进程RSS检查预算 / temp配额 | 640 MiB / 8 GiB |
| 生成耗时 | 28.872 s |
| 标准化耗时 | 61.483 s |
| 去重与聚合耗时 | 59.851 s |
| 处理耗时（含一次再过滤） | 121.789 s |
| 含生成端到端 | 150.664 s |
| 处理吞吐 | 8,648.68 rows/s |
| 进程峰值RSS | 504,446,976 B |
| 采样峰值临时盘 | 1,253,277,696 B |
| 采样峰值工作目录 | 2,039,968,396 B |
| 标准化Parquet | 881,686,459 B |
| 结果Parquet | 135,334,757 B |
| 退出/OOM | exit0 / false |

[资源限制读回](evidence/netflow-bulk/hard-limit.json)。临时盘/RSS是周期采样峰值，可能遗漏采样间尖峰；容器memory是另行读回的硬限制，DuckDB参数不代表整个进程硬限制。

IPv6源过滤的零结果再分析0.216秒。该回执的CSV零调用/零读取字段依据复用路径结构与测试断言，并非操作系统全局I/O追踪。正确性用例另将CSV解析器替换为立即失败，验证重复分析不触发；普通查询则实际移走原始快照目录。

复现（新输出目录；先预检资源，不使用已有生产目录）：

```sh
docker run --name nf-bulk-hard-validation --network none \
  --memory 768m --memory-swap 768m --cpus 1 --pids-limit 128 \
  -v /new/isolated/benchmark:/bench \
  nf-bulk-304-runner:6d491d737f4f9f6eef60d372e507cad99a0a629b \
  /app/.venv/bin/python -m app.netflow_bulk benchmark \
  --output /bench/run --bytes 1000000000 --memory-mb 128 \
  --threads 1 --rss-mb 640 --temp-gb 8 --reserve-gb 20
```

## 1 GB PostgreSQL/API及独立worker

[完整回执](evidence/netflow-bulk/api-1gb.json)。真实本机PostgreSQL和应用HTTP接口由TestClient执行，worker为独立OS进程；agent-compose控制面是fixture。源码与真实运行时验证使用相同bulk路径，但这次不宣称真实网络调度或容器硬内存验收。

封存2.079秒，封存至完成357.523秒；worker339.936秒，其中标准化100.092秒、投影174.443秒；RSS峰值436,371,456字节。处理1,053,312行、1,000,001,608字节，生成808,466观测对象与720,169 peer，计数与Linux引擎完全一致。投影阶段已占较大比例，这是后续容量验证必须继续观察的瓶颈。

每类查询20次、每页25条，原始snapshot目录在查询期间已实际改名为offline-snapshots；因此查询不能访问原始CSV。cold表示重新建立数据库连接，**未清空操作系统缓存**；不能称磁盘冷启动测试。

| API | p50 (ms) | p95 (ms) | max (ms) |
|---|---:|---:|---:|
| 观测，冷连接 | 849.59 | 5203.87 | 5203.87 |
| 观测，热查询 | 270.72 | 1043.97 | 1043.97 |
| peer，冷连接 | 252.64 | 1244.31 | 1244.31 |
| peer，热查询 | 138.59 | 257.86 | 257.86 |
| 处理中读取项目，1135次 | 15.72 | 229.16 | 4488.74 |

处理中API全部HTTP200，但不据此宣称没有延迟影响；同机浏览器/审阅进程也运行，未建立独占机器基准。20样本的p95接近最慢值，不能作稳定服务SLA。这里验证单个bulk任务与API并行，不测试多个重任务并发；准入合同本就限制一个活动bulk。

首次最终API尝试因测试fixture同时清空专用库，在登记前项目已不存在，未启动分析。该尝试保留为NOT_RUN环境失败；上述数据来自测试结束后的串行重跑，不覆盖失败痕迹。

## 真实异步链路、恢复和后续规模

[真实运行时回执](evidence/netflow-bulk/runtime-128mb.json)：128,002,652字节，134,826行；真实agent-compose、Linux arm64 guest、PostgreSQL、HTTP完成，43.896秒；worker38.431秒（标准化16.447、投影14.706），RSS632,254,464字节；unique106,271 / duplicate28,555，观测106,028 / peer106,271。该runner实际使用RSS检查，不能把它称作前述768 MiB硬容器实验。

加强证据身份检查后的最终干净构建fa08480再次完成同一128 MB真实链路：49.704秒、worker44.360秒（标准化18.221、投影18.890）、RSS624,156,672字节，所有计数相同。[最终回执](evidence/netflow-bulk/runtime-delivery.json)。该构建的业务源码和锁定依赖与6d491d7完全相同，测试脚本和文档已有更新。

实际SIGKILL发生在已提交checkpoint后，原版本未发布；reconcile确认Session终止后显式重试，恢复2.019秒，结果与无故障小样本一致。lease竞争/过期/fencing、rename后checkpoint失败、最终事务提交失败、模拟ENOSPC和磁盘预留不足均有故障测试。磁盘耗尽采用注入，未填满宿主磁盘；恢复时间只来自小样本，不外推TB。[测试回执](evidence/netflow-bulk/bulk-recovery.xml)。

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1 GB | PASS（已执行范围） | 硬内存引擎及PG/API独立进程两项分开实测 |
| 10 GB | NOT_RUN | [资源预检不通过](evidence/netflow-bulk/preflight-10gb.json)，未生成 |
| 100 GB | NOT_RUN | 前级停止，不继续 |
| 1 TB | NOT_RUN | **TB 验收未执行** |

高基数投影/查询延迟、完整磁盘冷缓存、独占硬件、Linux amd64运行、10 GB及以上、跨dataset/跨日增量去重均未验证或未实现。当前可交付的是已经实现并按上述规模验证的路径，不是TB生产容量承诺。
