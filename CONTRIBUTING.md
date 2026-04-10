# 贡献指南 (CONTRIBUTING)

感谢您对临床试验数据下载器项目的兴趣！

## 如何贡献

### 报告问题

如果您发现了bug或有功能建议，请：

1. 搜索现有issue确保不是重复
2. 创建新的issue，提供：
   - 清晰的标题和描述
   - 复现步骤
   - 预期行为 vs 实际行为
   - 环境信息 (Python版本、R版本、操作系统)

### 提交代码

1. **Fork仓库**
2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

3. **开发**
   - 遵循现有代码风格
   - 添加必要的类型提示
   - 编写测试用例
   - 更新相关文档

4. **提交**
   ```bash
   git commit -m "feat: 添加新功能"
   git commit -m "fix: 修复某问题"
   ```

5. **Push并创建PR**
   ```bash
   git push origin feature/your-feature-name
   ```

### 代码规范

#### Python
- 使用类型提示
- 遵循PEP 8
- docstring使用中文
- 变量和函数使用英文命名

#### 提交信息格式
```
<type>(<scope>): <subject>

<body>

<footer>
```

type:
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更改
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具

#### 测试要求
- 核心模块需要有单元测试
- 测试文件放在 `tests/` 目录
- 运行测试：
  ```bash
  python tests/test_suite.py
  ```

### 项目结构

```
v0.3 new/
├── main.py              # 程序入口
├── ctrdata_core.py     # 核心业务逻辑
├── ctrdata_gui.py      # GUI界面
├── ctrdata_functions.R # R函数封装
├── config_manager.py    # 配置管理
├── validators.py        # 输入验证
├── requirements.txt     # Python依赖
├── tests/
│   ├── __init__.py
│   └── test_suite.py    # 测试套件
├── CHANGELOG.md         # 更新日志
├── CONTRIBUTING.md      # 本文件
└── README.md            # 项目说明
```

### 开发环境设置

1. **克隆代码**
   ```bash
   git clone <repo-url>
   cd "Clinicaltrial docs downloader"
   ```

2. **创建虚拟环境** (推荐)
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **安装R依赖**
   ```R
   install.packages("ctrdata")
   install.packages("nodbi")
   install.packages("DBI")
   install.packages("RSQLite")
   ```

5. **验证环境**
   ```bash
   python test_simple.py
   ```

### 运行测试

```bash
# 运行完整测试套件
python tests/test_suite.py

# 或使用 pytest (如果已安装)
pytest tests/ -v
```

### 许可证

通过贡献代码，您同意您的代码将在MIT许可证下发布。
