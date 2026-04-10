# 临床试验数据下载器 v1.0

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![R](https://img.shields.io/badge/R-4.0%2B-green.svg)](https://www.r-project.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PySide6](https://img.shields.io/badge/PySide6-6.5%2B-orange.svg)](https://doc.qt.io/qtforpython/)

基于 `ctrdata` R包的桌面GUI应用程序，用于从多个国际临床试验注册中心下载、提取和导出结构化临床试验数据。使用 Python + PySide6 构建。

## 功能特点

### 📋 三步工作流
- **数据库管理**：连接SQLite数据库，查询历史记录，支持增量更新
- **搜索与下载**：多条件搜索、粘贴URL、按试验ID下载，支持多注册中心同时搜索
- **提取与导出**：数据提取、多维度过滤、CSV导出、文档下载

### 🔍 核心功能
- **多注册中心支持**：
  - ClinicalTrials.gov (CTGOV2)
  - EU Clinical Trials Register (EUCTR)
  - ISRCTN
  - EU CTIS

- **智能搜索**：
  - 多条件搜索（关键词、试验阶段、招募状态、目标人群）
  - 多注册中心同时搜索
  - 预览结果数量后再下载

- **后下载过滤**：
  - 试验阶段过滤
  - 招募状态过滤
  - 日期范围过滤
  - 适应症/干预措施过滤
  - 注册中心过滤

- **文档下载**：
  - PDF文档下载（协议、统计分析计划等）
  - 断点续传功能
  - 自定义文档类型过滤器

- **用户体验**：
  - 深色/浅色/系统主题切换
  - R环境自动检测与引导配置
  - 设置持久化（通过QSettings）
  - 右键菜单（复制单元格、行、选中内容）

## 系统要求

### Python环境
- Python 3.10 或更高版本
- PySide6 6.5+
- pandas
- qtawesome
- pyqtdarktheme
- darkdetect (可选)

### R环境
- R 4.0 或更高版本
- R包：
  - `ctrdata` (核心下载包)
  - `nodbi` (数据库接口)
  - `RSQLite` (SQLite支持)

### 操作系统
- Windows（主要支持平台）
- macOS/Linux（部分支持，需手动配置R环境）

## 安装步骤

### 1. 安装Python依赖
```bash
# 克隆或下载项目
cd Clinicaltrial-docs-downloader

# 安装Python依赖
pip install -r requirements.txt
```

### 2. 安装R依赖
在R控制台中安装所需包：
```r
install.packages("ctrdata")
install.packages("nodbi")
install.packages("RSQLite")
```

### 3. 配置R环境
程序会自动检测R安装路径。如果检测失败：
- Windows：确保R已安装并在PATH中
- 手动设置：`set R_HOME="C:\Program Files\R\R-4.3.1"`

## 快速开始

### 启动程序
```bash
# 启动PySide6现代界面（默认）
python main.py

# 启动传统tkinter界面
python main.py --ui legacy
```

### 操作流程

#### 步骤1：数据库设置
1. 输入数据库文件名（默认：trials.sqlite）
2. 点击"创建/连接数据库"
3. 查看数据库信息和历史记录

#### 步骤2：搜索与下载
1. **多条件搜索**：
   - 输入搜索关键词（必填）
   - 选择注册中心（可多选）
   - 设置试验阶段和招募状态
   - 点击"生成查询"

2. **预览与下载**：
   - 查看查询结果统计
   - 点击"下载数据"
   - 可选：勾选"同时下载PDF文档"

#### 步骤3：提取与导出
1. 选择要提取的字段
2. 应用过滤器（阶段、状态、日期等）
3. 点击"提取数据"
4. 导出CSV文件
5. 可选：下载文档

## 架构概览

```
Clinicaltrial-docs-downloader/
├── main.py                    # 程序入口点
├── requirements.txt          # Python依赖
├── build.py                  # 构建脚本（PyInstaller）
├── README.md                 # 使用说明
├── ctrdata/                  # R桥接层
│   ├── bridge.py            # 主要R接口
│   ├── process.py            # 进程管理
│   ├── connection.py        # 数据库连接
│   ├── search_query.py      # 搜索查询
│   ├── search_download.py   # 搜索下载
│   ├── extract.py           # 数据提取
│   ├── documents.py         # 文档下载
│   ├── template_loader.py   # 模板加载器
│   └── templates/           # R模板文件
├── ui/                      # PySide6 UI层
│   ├── app.py               # 应用程序
│   ├── main_window.py       # 主窗口
│   ├── theme.py             # 主题系统
│   ├── settings_dialog.py   # 设置对话框
│   ├── tabs/               # 标签页
│   │   ├── database_tab.py
│   │   ├── search_tab.py
│   │   └── export_tab.py
│   └── widgets/            # 自定义控件
├── core/                   # 核心模块
│   ├── constants.py        # 常量定义
│   ├── exceptions.py       # 异常类
│   ├── models.py           # 数据模型
│   └── logger.py           # 日志系统
├── service/                # 业务逻辑
│   ├── extract_service.py
│   └── download_service.py
├── gui/                    # 传统tkinter界面
│   └── ctrdata_gui.py
├── data/                   # 数据目录
└── tests/                  # 测试
```

## 构建可执行文件

使用PyInstaller打包为独立可执行文件：

```bash
# 安装PyInstaller
pip install pyinstaller

# 构建程序
python build.py
```

### 构建命令详解
```bash
# 开发模式（快速测试）
python build.py --dev

# 发布模式（包含所有依赖）
python build.py --release

# 清理构建文件
python build.py --clean
```

## 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| GUI框架 | PySide6 6.5+ | Qt for Python，LGPL许可证 |
| 数据处理 | pandas 1.3+ | 数据分析和处理 |
| R集成 | subprocess + JSON-RPC | 跨进程通信，避免rpy2编码问题 |
| 主题系统 | pyqtdarktheme + QSS | 深色/浅色主题支持 |
| 图标 | qtawesome 1.3+ | FontAwesome图标库 |
| 数据库 | SQLite + nodbi | 轻量级数据存储 |
| 测试 | pytest | 单元测试框架 |

## 设计原则

1. **模块化设计**：清晰的接口，低耦合
2. **渐进式进展**：小步快跑，快速验证
3. **清晰优于简洁**：编写直观易维护的代码
4. **实用优先**：适应项目现实，选择实际解决方案
5. **质量第一**：不牺牲质量换速度，修复根本问题

## 常见问题

### R环境问题
```bash
# 检查R是否可用
R --version

# 检查包是否安装
R -e "library(ctrdata)"
```

### 文档下载失败
如果文档下载功能显示"共下载 0 个文档"：
1. 在R中重新安装包：
   ```r
   remove.packages("nodbi")
   remove.packages("ctrdata")
   install.packages("nodbi")
   install.packages("ctrdata")
   ```

### 网络问题
- 确保网络连接正常
- 使用VPN时可能需要配置代理
- 检查防火墙设置

## 版本历史

### v1.0 (当前版本)
- 完整的PySide6界面
- 多注册中心支持
- 文档下载与断点续传
- 主题切换功能
- R环境自动检测

### v0.3 (Legacy)
- 传统tkinter界面
- 基础下载功能
- 简单的过滤选项

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 致谢

- **Ralf Herold** 及 `ctrdata` 包团队 - 提供强大的临床试验数据下载功能
- **Qt Team** 及 PySide6 项目 - 提供优秀的跨平台GUI框架
- **Pandas Team** - 提供强大的数据处理能力

## 贡献指南

欢迎提交Issue和Pull Request！在提交前请确保：

1. 遵循现有代码风格
2. 添加适当的测试
3. 更新相关文档
4. 确保功能正常工作

---

**作者**: Damon Liang  
**项目地址**: [GitHub Repository]  
**问题反馈**: [Issues]