# 联合仿真公开数据附件

本仓库仅交付已审阅的仿真数据和独立读取工具，主项目源码仍为私有。当前附件是 `latest-small` 七条件既有执行的匿名诊断事实及其冻结观测；没有重新仿真，也没有产生新的方法成绩。

[下载 Release](https://github.com/baoy21/moe-ub-cosim-artifacts/releases/tag/latest-small-execution-facts-v1)。附件可匿名下载，不需要 GitHub 账户、`gh` 或令牌。

## 下载与核验

需要 Linux 的 `curl`、`tar`、`sha256sum`，以及已安装 NumPy 的 Python 3。所有文件放在一个新目录；两份数据包合计约106 MiB。下载并解压后总占用约225 MiB。

```bash
mkdir received-facts
cd received-facts
base=https://github.com/baoy21/moe-ub-cosim-artifacts/releases/download/latest-small-execution-facts-v1
for file in SHA256SUMS delivery-index.json provenance.json FORMAT.md check_execution_facts.py latest-small.tar.gz latest-small-execution-facts.tar.gz; do
  curl --disable --fail --location --connect-timeout 30 --max-time 1500 --output "$file" "$base/$file" || break
done
sha256sum -c SHA256SUMS && \
  tar -xzf latest-small-execution-facts.tar.gz && \
  tar -xzf latest-small.tar.gz && \
  python3 check_execution_facts.py \
    --package diagnostic-facts \
    --published latest-small \
    --output receiver-receipt.json
```

核验报告要求 `status=completed`，包含七条件的包归属、源接入口、FIFO（先进先出队列）等待与阻塞关系，以及1024ns和8192ns两粒度原始包数和出口字节数的精确重建。`receiver-receipt.json` 必须不存在，避免覆盖旧核验。下载中断时保留半成品，可用 `curl --disable --fail --location --continue-at - --output 文件 URL` 续传，最终仍须完整校验摘要。

## 文件和来源

- `latest-small-execution-facts.tar.gz`：全部七条件、64个捕获出口、完整时间的诊断事实，解压为 `diagnostic-facts/`。
- `latest-small.tar.gz`：核验所需原观测和原评价标签，解压为 `latest-small/`；`observed/` 与 `truth/` 分离。
- `check_execution_facts.py`：独立读取脚本，仅依赖 Python 和 NumPy；不依赖主仓库、历史运行目录或账户授权。
- `FORMAT.md`：字段、时间与缺项说明。
- `delivery-index.json`、`SHA256SUMS`：文件大小、下载地址及SHA256摘要。
- `provenance.json`：原包与公开包的对应。公开事实包只删除根清单中的执行命令和本机工作目录；其余文件逐字节保持不变。原观测包逐字节保持不变。

原执行使用程序生成的小型输入（路由随机种子4013/4021），并非真实专家路由数据集；不含原始请求/专家路由、文本、报文载荷、凭证、主项目源码历史或完整仿真日志。来源文件摘要用于绑定原执行，不代表其原文件也已公开。事实包的匿名编号只在声明的组内或执行内有效。

全部资料属于已经见过的开发执行，标记为 `diagnostic_only`。波次与提交、实际队列服务可以辅助诊断，但不是正式检测器可读输入，也不能充当新的独立验证。三类来源部分工作量不匹配和逐包VOQ（虚拟输出队列）缺项按原包保留，不能用零代替。发送服务、排队与业务影响不可混为一个因果结论。

公开可下载不等于为私有主项目或第三方软件重新授予许可证；本次没有改变主项目的许可证或可见性。
