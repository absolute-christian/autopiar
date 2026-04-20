import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from PyQt5 import QtWidgets

from licensing.crypto import build_signed_license_document, load_private_key_from_file
from licensing.storage import get_license_path, get_runtime_dir


class DevToolsDialog(QtWidgets.QDialog):
    def __init__(self, product_name: str, parent=None):
        super().__init__(parent)
        self.product_name = product_name
        self.private_key_path: Optional[str] = None

        self.setWindowTitle("Разработчик")
        self.resize(860, 610)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Инструменты разработчика")
        title.setObjectName("dlgTitle")
        subtitle = QtWidgets.QLabel(
            "Рекомендуемый режим: один универсальный EXE + разные license.json для клиентов."
        )
        subtitle.setObjectName("subTitle")
        subtitle.setWordWrap(True)

        license_box = QtWidgets.QGroupBox("Генератор лицензий")
        form = QtWidgets.QFormLayout(license_box)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.in_license_to = QtWidgets.QLineEdit()
        self.in_license_to.setPlaceholderText("username / имя / ID")
        self.spin_days = QtWidgets.QSpinBox()
        self.spin_days.setRange(1, 3650)
        self.spin_days.setValue(30)
        self.cmb_type = QtWidgets.QComboBox()
        self.cmb_type.addItems(["user", "dev"])
        self.lbl_private = QtWidgets.QLabel("private.key: не выбран")
        self.lbl_private.setWordWrap(True)
        self.lbl_private.setObjectName("keyState")

        form.addRow("License To:", self.in_license_to)
        form.addRow("Days:", self.spin_days)
        form.addRow("Type:", self.cmb_type)
        form.addRow("Private Key:", self.lbl_private)

        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setSpacing(8)
        self.btn_pick_key = QtWidgets.QPushButton("Выбрать private.key")
        self.btn_generate = QtWidgets.QPushButton("Сгенерировать license.json")
        self.btn_pick_key.setObjectName("ghostButton")
        self.btn_generate.setObjectName("primaryButton")
        actions_row.addWidget(self.btn_pick_key)
        actions_row.addWidget(self.btn_generate)
        actions_row.addStretch(1)

        build_box = QtWidgets.QGroupBox("Сборка")
        build_lay = QtWidgets.QVBoxLayout(build_box)
        build_lay.setSpacing(8)
        build_note = QtWidgets.QLabel(
            "Опция для случаев, когда нужен exe. Этот путь тяжелее в сопровождении, "
            "чем выдача отдельного license.json."
        )
        build_note.setWordWrap(True)
        self.btn_build = QtWidgets.QPushButton("Собрать EXE (PyInstaller)")
        self.btn_build.setObjectName("softButton")
        build_lay.addWidget(build_note)
        build_lay.addWidget(self.btn_build, 0)

        self.txt_log = QtWidgets.QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setPlaceholderText("Лог разработчика")
        self.txt_log.setObjectName("logBox")

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(license_box)
        root.addLayout(actions_row)
        root.addWidget(build_box)
        root.addWidget(self.txt_log, 1)

        self.btn_pick_key.clicked.connect(self.pick_private_key)
        self.btn_generate.clicked.connect(self.generate_license)
        self.btn_build.clicked.connect(self.build_exe)

        self._apply_soft_style()

    def _apply_soft_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #0d1218;
                color: #dde8f4;
                font-family: Bahnschrift, "Segoe UI Variable Text", "Trebuchet MS";
                font-size: 13px;
            }
            QLabel#dlgTitle {
                font-size: 20px;
                font-weight: 700;
                color: #f1f7ff;
            }
            QLabel#subTitle {
                color: #93a6b9;
                margin-bottom: 2px;
            }
            QGroupBox {
                background: #121b24;
                border: 1px solid #54697f;
                border-radius: 12px;
                margin-top: 10px;
                padding: 10px 12px 12px 12px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #d7e7f6;
            }
            QLineEdit, QComboBox, QSpinBox {
                background: #0f151d;
                border: 1px solid #4f6479;
                border-radius: 8px;
                padding: 7px 9px;
                color: #dde8f4;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #6ca9d9;
            }
            QLabel#keyState {
                background: #1a2530;
                border: 1px solid #4f6479;
                color: #ccddee;
                border-radius: 8px;
                padding: 7px 9px;
            }
            QPlainTextEdit#logBox {
                background: #0f151d;
                border: 1px solid #4f6479;
                border-radius: 12px;
                padding: 8px;
                color: #d5e3f1;
            }
            QPushButton {
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
                border: 1px solid transparent;
            }
            QPushButton#primaryButton {
                background: #2f78ad;
                color: #f1f8ff;
            }
            QPushButton#primaryButton:hover {
                background: #3b89c1;
            }
            QPushButton#ghostButton {
                background: #17212b;
                color: #cee0f2;
                border: 1px solid #4f6479;
            }
            QPushButton#ghostButton:hover {
                background: #223140;
            }
            QPushButton#softButton {
                background: #1f2f3f;
                color: #d9ebfd;
                border: 1px solid #4f6479;
            }
            QPushButton#softButton:hover {
                background: #2a3f52;
            }
            """
        )

    def log(self, text: str) -> None:
        self.txt_log.appendPlainText(text)

    def pick_private_key(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите private key (Ed25519)",
            "",
            "Key files (*.key *.pem *.txt);;All files (*.*)",
        )
        if not path:
            return
        self.private_key_path = path
        self.lbl_private.setText(f"private.key: {path}")
        self.lbl_private.setStyleSheet(
            "background:#17302b;border:1px solid #3f8a74;color:#c9f1e4;border-radius:8px;padding:7px 9px;"
        )
        self.log(f"Ключ выбран: {path}")

    def generate_license(self):
        if not self.private_key_path:
            self.log("Сначала выберите private.key.")
            return

        license_to = self.in_license_to.text().strip()
        if not license_to:
            self.log("Поле license_to пустое.")
            return

        days = int(self.spin_days.value())
        issued = date.today()
        expires = issued + timedelta(days=days)

        payload = {
            "product": self.product_name,
            "license_to": license_to,
            "issued_at": issued.isoformat(),
            "expires": expires.isoformat(),
            "type": self.cmb_type.currentText().strip().lower(),
        }

        try:
            private_key = load_private_key_from_file(self.private_key_path)
            doc = build_signed_license_document(payload, private_key)
        except Exception as exc:
            self.log(f"Ошибка подписи: {exc}")
            return

        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить license.json",
            "license.json",
            "License JSON (*.json)",
        )
        if not save_path:
            self.log("Сохранение отменено.")
            return

        try:
            Path(save_path).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.log(f"Лицензия создана: {save_path}")
            self.log(f"type={payload['type']} expires={payload['expires']} license_to={license_to}")
        except Exception as exc:
            self.log(f"Ошибка сохранения: {exc}")

    def build_exe(self):
        project_root = get_runtime_dir()
        main_py = project_root / "main.py"
        if not main_py.exists():
            self.log(f"main.py не найден: {main_py}")
            return

        cmd = ["pyinstaller", "--onefile", "--noconsole", str(main_py)]
        self.log(f"Запуск: {' '.join(cmd)}")
        self.log("Если команда не работает: установите PyInstaller (pip install pyinstaller).")

        try:
            completed = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                check=False,
                shell=(sys.platform.startswith("win")),
            )
        except Exception as exc:
            self.log(f"Ошибка запуска PyInstaller: {exc}")
            return

        if completed.stdout:
            self.log(completed.stdout.strip())
        if completed.stderr:
            self.log(completed.stderr.strip())

        if completed.returncode != 0:
            self.log(f"Сборка не удалась, код={completed.returncode}")
            return

        dist_exe = project_root / "dist" / "main.exe"
        self.log(f"EXE собран: {dist_exe}")

        lic_path = get_license_path()
        if lic_path.exists() and dist_exe.exists():
            try:
                shutil.copy2(lic_path, dist_exe.parent / "license.json")
                self.log(f"Скопирован {lic_path.name} рядом с EXE.")
            except Exception as exc:
                self.log(f"Не удалось скопировать license.json: {exc}")
