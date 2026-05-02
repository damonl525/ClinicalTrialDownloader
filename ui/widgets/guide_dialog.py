#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Operation guide dialog — step-by-step usage instructions.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox,
    QCheckBox,
)
from PySide6.QtCore import QSettings, Qt

from ui.theme import SPACING

SETTINGS_KEY = "guide_dont_show"


class GuideDialog(QDialog):
    """Dialog showing operation guide for the application."""

    def __init__(self, parent=None, auto_opened=False):
        super().__init__(parent)
        self.setWindowTitle("操作指南")
        self.setMinimumWidth(600)
        self.setMinimumHeight(520)
        self._auto_opened = auto_opened
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setHtml(_GUIDE_HTML)
        layout.addWidget(guide)

        if self._auto_opened:
            self._dont_show_cb = QCheckBox("不再提醒")
            layout.addWidget(self._dont_show_cb, alignment=Qt.AlignRight)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

    def done(self, result):
        if self._auto_opened and hasattr(self, "_dont_show_cb"):
            settings = QSettings("ctrdata_downloader", "MainWindow")
            settings.setValue(SETTINGS_KEY, self._dont_show_cb.isChecked())
        super().done(result)


_GUIDE_HTML = """
<h2 style="color: #3B82F6;">操作指南</h2>

<h3>1. 数据库连接</h3>
<ol>
  <li>打开「数据库」标签页</li>
  <li>输入文件名（如 <code>my_trials</code>），点击「连接」</li>
  <li>SQLite 数据库自动创建，R 环境自动检测</li>
  <li><b>首次使用</b>：需要安装 R 语言和 ctrdata 包，参见环境检查提示</li>
</ol>

<h3>2. 搜索与下载</h3>
<ol>
  <li>切换到「搜索与下载」标签页</li>
  <li>输入关键词（疾病、干预措施等），选择注册中心</li>
  <li>点击「生成查询」→「预览数量」确认结果</li>
  <li>点击「下载」将数据存入数据库</li>
</ol>

<h3>3. 提取与导出</h3>
<ol>
  <li>下载完成后自动跳转到「提取与导出」标签页</li>
  <li>选择需要的标准化字段，点击「提取」</li>
  <li>使用过滤器（阶段、状态、日期等）筛选数据</li>
  <li>导出 CSV 或下载文档（Protocol、SAP 等）</li>
</ol>

<h3>4. FDA 审评资料</h3>
<ol>
  <li>「FDA审评资料」标签页独立运行，无需数据库</li>
  <li>输入药物名称或日期范围搜索</li>
  <li>批量下载 FDA 审评报告 PDF</li>
</ol>

<h3>5. CDE 上市药品</h3>
<ol>
  <li>「CDE上市药品」标签页独立运行，无需数据库</li>
  <li>搜索国家药监局药审中心上市药品目录</li>
  <li>下载审评报告和说明书 PDF</li>
</ol>

<hr>

<h3 style="color: #F59E0B;">⚠ 网络环境说明</h3>
<ul>
  <li><b>ClinicalTrials.gov (CTGOV2)</b>：覆盖全球 <b>80%+</b> 的注册临床试验，国内可直接访问，速度稳定</li>
  <li><b>EU CTR、ISRCTN、CTIS</b>：服务器位于海外，<b>强烈建议使用代理/VPN</b>，否则可能连接超时或不稳定</li>
  <li>文档下载速度取决于网络环境，大批量下载请耐心等待</li>
</ul>

<hr>

<h3>支持的注册中心</h3>
<table cellpadding="4" style="border-collapse: collapse;">
  <tr style="background: #F1F5F9;">
    <td><b>注册中心</b></td><td><b>覆盖范围</b></td><td><b>网络要求</b></td>
  </tr>
  <tr>
    <td>ClinicalTrials.gov</td><td>全球 80%+ 临床研究</td><td>直连可用</td>
  </tr>
  <tr>
    <td>EU CTR (EUCTR)</td><td>欧盟临床试验</td><td>建议代理</td>
  </tr>
  <tr>
    <td>ISRCTN</td><td>国际标准随机对照试验</td><td>建议代理</td>
  </tr>
  <tr>
    <td>EU CTIS</td><td>欧盟临床试验信息系统</td><td>建议代理</td>
  </tr>
</table>

<h3 style="color: #F59E0B;">⚠ EUCTR / CTIS 数据限制说明</h3>
<p>由于 ctrdata R 包的技术限制，<b>EUCTR</b> 和 <b>CTIS</b> 注册中心存在以下已知限制：</p>
<ul>
  <li><b>字段缺失</b>：EUCTR 的开始日期、招募状态、干预措施等概念函数字段为空，仅「试验阶段」有值。CTIS 字段完整度类似</li>
  <li><b>日期筛选精度有限</b>：EUCTR 日期筛选使用注册年份近似（精度仅到年份），无法精确到具体日期</li>
  <li><b>文档下载受限</b>：
    <ul>
      <li>EUCTR：不支持按文档类型筛选（Protocol / SAP），所有文档会被全部下载</li>
      <li>CTIS：无公开 API，文档下载依赖网页抓取，速度慢且容易超时</li>
    </ul>
  </li>
  <li><b>建议</b>：提取筛选和文档下载请以 <b>ClinicalTrials.gov</b> 和 <b>ISRCTN</b> 为主，EUCTR/CTIS 仅用于浏览参考</li>
</ul>

<hr>
<p style="color: #64748B; font-size: 9pt;">
  如有问题或建议，请在项目仓库提交 Issue。
</p>
"""
