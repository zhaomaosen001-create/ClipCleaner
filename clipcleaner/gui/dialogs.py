"""设置对话框."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from clipcleaner.config import ConfigManager


class SettingsDialog(QDialog):
    """设置对话框."""

    def __init__(self, config_manager: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_provider = QComboBox()
        self.api_provider.addItems([
            "auto - 自动（内置 → API 回退）",
            "builtin - 仅内置解析",
            "douyin_wtf - douyin.wtf 混合 API",
            "custom - 自定义 API",
        ])
        form.addRow("解析提供方:", self.api_provider)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("必填（多数第三方 API 的 apikey）")
        form.addRow("API Key:", self.api_key_edit)

        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText(
            "如 https://api.xxx.com/parse?url={url}  （支持 {apikey} 占位符）"
        )
        form.addRow("API 地址:", self.api_url_edit)

        out_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        btn_out = QPushButton("浏览...")
        btn_out.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit)
        out_row.addWidget(btn_out)
        form.addRow("输出目录:", out_row)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 8)
        self.concurrent_spin.setValue(2)
        form.addRow("最大并发下载:", self.concurrent_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _provider_key(self) -> str:
        text = self.api_provider.currentText()
        return text.split(" - ")[0].strip()

    def _set_provider(self, key: str) -> None:
        for i in range(self.api_provider.count()):
            if self.api_provider.itemText(i).startswith(key):
                self.api_provider.setCurrentIndex(i)
                return

    def _load_values(self) -> None:
        cfg = self.config_manager.config
        self._set_provider(cfg.api_provider or "auto")
        self.api_key_edit.setText(cfg.api_key)
        self.api_url_edit.setText(cfg.api_base_url)
        self.output_edit.setText(cfg.output_dir)
        self.concurrent_spin.setValue(cfg.max_concurrent_downloads)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_edit.setText(path)

    def _save(self) -> None:
        self.config_manager.update(
            api_provider=self._provider_key(),
            api_key=self.api_key_edit.text().strip(),
            api_base_url=self.api_url_edit.text().strip(),
            output_dir=self.output_edit.text().strip(),
            max_concurrent_downloads=self.concurrent_spin.value(),
        )
        self.accept()
