"""First-run dialog prompting the user to install the IDA-MCP plugin."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class FirstRunInstallDialog(QDialog):
    """Shown on startup when IDA-MCP is not detected in the global plugins dir.

    Offers a one-click path to the Settings page (where install can be triggered)
    or a Skip button that suppresses future prompts.
    """

    def __init__(self, plugin_dir: str, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui(plugin_dir)

    def _setup_ui(self, plugin_dir: str) -> None:
        self.setWindowTitle("IDA-MCP 未安装")
        self.setObjectName("firstRunInstallDialog")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QLabel("<b>IDA-MCP 插件未检测到</b>")
        header.setObjectName("firstRunInstallHeader")
        layout.addWidget(header)

        body = QLabel(
            f"全局插件目录中未发现 IDA-MCP：\n"
            f"<code>{plugin_dir}</code>\n\n"
            f"安装后 IDE 可通过 MCP 协议与 IDA Pro 通信，"
            f"实现反汇编、函数分析等自动化操作。"
        )
        body.setWordWrap(True)
        body.setTextFormat(QLabel.TextFormat.RichText)
        body.setObjectName("firstRunInstallBody")
        layout.addWidget(body)

        btn_box = QDialogButtonBox()

        self._install_btn = QPushButton("前往安装")
        self._install_btn.setObjectName("firstRunInstallBtn")
        self._install_btn.clicked.connect(self.accept)
        btn_box.addButton(self._install_btn, QDialogButtonBox.AcceptRole)

        skip_btn = QPushButton("跳过（不再提示）")
        skip_btn.setObjectName("firstRunSkipBtn")
        skip_btn.clicked.connect(self.reject)
        btn_box.addButton(skip_btn, QDialogButtonBox.RejectRole)

        layout.addWidget(btn_box)

    def wants_install(self) -> bool:
        """Return True if the user clicked *前往安装*."""
        return self.result() == QDialog.DialogCode.Accepted
