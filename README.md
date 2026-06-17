# 📊 美股科技巨头财报自动分析系统

自动从 SEC 抓取 12 家科技公司财报，生成中文分析报告，并通过邮件发送。

## ✨ 功能特性

- **自动抓取**：从 SEC EDGAR 自动获取最新财报数据
- **多公司支持**：覆盖 12 家热门科技公司
- **智能分析**：基于 XBRL 结构化数据，准确提取财务指标
- **投资信号**：从股票投资角度判断利好/利空
- **定时发送**：每周自动运行并发送报告到邮箱
- **中文报告**：全中文财务分析报告

## 📋 支持的公司

| 公司 | CIK | 报告类型 |
|------|-----|---------|
| Tesla 特斯拉 | 0001318605 | 10-K/10-Q |
| NVIDIA 英伟达 | 0001045810 | 10-K/10-Q |
| Microsoft 微软 | 0000789019 | 10-K/10-Q |
| Apple 苹果 | 0000320193 | 10-K/10-Q |
| Micron 美光 | 0000723125 | 10-K/10-Q |
| Broadcom 博通 | 0001730168 | 10-K/10-Q |
| AMD 超威半导体 | 0000002488 | 10-K/10-Q |
| Intel 英特尔 | 0000050863 | 10-K/10-Q |
| Meta Platforms | 0001326801 | 10-K/10-Q |
| Alphabet 谷歌 | 0001652044 | 10-K/10-Q |
| Amazon 亚马逊 | 0001018724 | 10-K/10-Q |
| TSMC 台积电 | 0001158449 | 20-F |

## 📈 报告内容

### 投资信号速览
- 综合信号：🟢 强烈利好 / 🟢 利好 / 🟡 偏利好 / 🟡 偏利空 / 🔴 利空 / 🔴 强烈利空 / ⚪ 中性
- 营收变化、净利润变化、毛利率

### 核心财务指标
- 营业收入、毛利润、净利润、毛利率
- 研发费用、现金及等价物、每股收益

### 股票投资分析
- 利好因素（营收增长、毛利率提升等）
- 利空因素（营收下滑、净利润下降等）
- 综合投资信号判断

### 整体市场分析
- 利好/利空/中性公司数量统计
- 市场情绪判断

## 🚀 部署说明

### 方式一：GitHub Actions（推荐）

1. **Fork 本仓库**
   - 访问 https://github.com/luochan1028/tesla-sec-fetcher
   - 点击 "Fork" 创建副本

2. **配置 Secrets**
   - 进入仓库 Settings → Secrets and variables → Actions → New repository secret
   - 添加以下三个 Secrets：
     - `SMTP_USER`: 发件人邮箱（如 your_email@126.com）
     - `SMTP_PASSWORD`: 邮箱授权码（不是登录密码，需在邮箱设置中获取）
     - `RECIPIENT`: 收件人邮箱（如 your_email@126.com）

3. **开启 Actions**
   - 进入仓库 Actions 页面
   - 点击 "I understand my workflows, go ahead and enable them"

4. **手动触发测试**
   - 在 Actions 页面，选择 "Tesla SEC Fetcher"
   - 点击 "Run workflow" → "Run workflow"

5. **定时任务**
   - 默认每周一 9:00 UTC（北京时间周一 17:00）自动运行
   - 如需修改时间，编辑 `.github/workflows/fetcher.yml` 中的 cron 表达式

### 方式二：本地运行

1. **安装依赖**
   ```bash
   pip install requests
   ```

2. **设置环境变量**
   ```bash
   export SMTP_USER="your_email@126.com"
   export SMTP_PASSWORD="your_auth_code"
   export RECIPIENT="your_email@126.com"
   ```

3. **运行脚本**
   ```bash
   python tesla/sec_tesla_fetcher.py
   ```

### 方式三：云服务器部署

1. **安装 Python**
   ```bash
   apt-get update && apt-get install -y python3 python3-pip
   ```

2. **安装依赖**
   ```bash
   pip3 install requests
   ```

3. **克隆仓库**
   ```bash
   git clone https://github.com/luochan1028/tesla-sec-fetcher.git
   cd tesla-sec-fetcher
   ```

4. **设置环境变量**
   ```bash
   echo 'export SMTP_USER="your_email@126.com"' >> ~/.bashrc
   echo 'export SMTP_PASSWORD="your_auth_code"' >> ~/.bashrc
   echo 'export RECIPIENT="your_email@126.com"' >> ~/.bashrc
   source ~/.bashrc
   ```

5. **设置定时任务**
   ```bash
   # 每周一上午9点执行
   crontab -e
   # 添加：
   0 9 * * 1 cd /path/to/tesla-sec-fetcher && python3 tesla/sec_tesla_fetcher.py >> /var/log/tesla_sec.log 2>&1
   ```

## 🔧 配置说明

### 邮箱授权码获取

**126邮箱：**
1. 登录 https://mail.126.com
2. 点击右上角齿轮 → 设置 → POP3/SMTP/IMAP
3. 开启 POP3/SMTP 服务
4. 验证身份后获取授权码

**其他邮箱：**
- Gmail: 开启 2FA 后创建 App Password
- QQ邮箱: 设置 → 账户 → 开启 SMTP → 获取授权码

### 修改公司列表

编辑 `tesla/sec_tesla_fetcher.py` 中的 `COMPANIES` 列表：
```python
COMPANIES = [
    ("公司名称", "CIK代码"),
    # 添加更多公司...
]
```

### 修改运行时间

编辑 `.github/workflows/fetcher.yml`：
```yaml
on:
  schedule:
    - cron: '0 9 * * 1'  # 每周一 9:00 UTC
```

cron 表达式格式：`分 时 日 月 周`

## 📁 项目结构

```
tesla-sec-fetcher/
├── tesla/
│   ├── sec_tesla_fetcher.py   # 主脚本
│   └── requirements.txt        # 依赖列表
├── .github/
│   └── workflows/
│       └── fetcher.yml         # GitHub Actions 配置
├── sec_filings/                # 下载的财报文件（自动生成）
└── README.md                   # 本文件
```

## ⚠️ 风险提示

- 本报告基于 SEC 公开财报数据，仅供参考
- 投资有风险，入市需谨慎
- 建议结合其他因素综合分析后再做决策

## 📝 更新日志

### v1.0.0
- 支持 12 家科技公司财报抓取
- 基于 SEC XBRL API 提取财务数据
- 生成中文分析报告
- GitHub Actions 定时发送邮件
- 股票投资角度利好/利空判断

## 📄 许可证

MIT License

## 📧 联系方式

如有问题或建议，欢迎提交 Issue 或 PR。

---

*数据来源: SEC EDGAR (sec.gov)*
