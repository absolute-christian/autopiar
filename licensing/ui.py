from typing import Optional

from PyQt5 import QtCore, QtWidgets

from licensing.model import LicensePayload
from licensing.storage import (
    get_license_path,
    save_license_from_file,
    validate_current_license,
)


class LicenseDialog(QtWidgets.QDialog):
    def __init__(self, public_key_b64: str, expected_product: str, parent=None):
        super().__init__(parent)
        self.public_key_b64 = public_key_b64
        self.expected_product = expected_product
        self.payload: Optional[LicensePayload] = None

        self.setWindowTitle("Лицензия")
        self.setModal(True)
        self.resize(640, 420)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Проверка лицензии")
        title.setObjectName("dlgTitle")

        self.lbl_status = QtWidgets.QLabel("Ожидание проверки...")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setObjectName("statusLabel")

        self.lbl_path = QtWidgets.QLabel(f"Ожидаемый файл: {get_license_path()}")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setObjectName("pathLabel")

        card = QtWidgets.QFrame()
        card.setObjectName("infoCard")
        card_lay = QtWidgets.QVBoxLayout(card)
        card_lay.setContentsMargins(12, 12, 12, 12)
        card_lay.setSpacing(8)
        card_lay.addWidget(self.lbl_status)
        card_lay.addWidget(self.lbl_path)

        self.btn_select = QtWidgets.QPushButton("Выбрать license.json")
        self.btn_check = QtWidgets.QPushButton("Проверить")
        self.btn_exit = QtWidgets.QPushButton("Выход")
        self.btn_select.setObjectName("ghostButton")
        self.btn_check.setObjectName("primaryButton")
        self.btn_exit.setObjectName("ghostButton")

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.btn_select)
        row.addWidget(self.btn_check)
        row.addStretch(1)
        row.addWidget(self.btn_exit)

        self.txt_details = QtWidgets.QPlainTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setPlaceholderText("Лог проверки лицензии")
        self.txt_details.setObjectName("logBox")

        root.addWidget(title)
        root.addWidget(card)
        root.addLayout(row)
        root.addWidget(self.txt_details, 1)

        self.btn_select.clicked.connect(self.select_license)
        self.btn_check.clicked.connect(self.check_license)
        self.btn_exit.clicked.connect(self.reject)

        self._apply_soft_style()
        QtCore.QTimer.singleShot(0, self.check_license)

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
            QFrame#infoCard {
                background: #121b24;
                border: 1px solid #54697f;
                border-radius: 12px;
            }
            QLabel#statusLabel {
                padding: 8px 10px;
                border-radius: 10px;
                background: #1a2530;
                border: 1px solid #4f6479;
                color: #d1e0ef;
                font-weight: 600;
            }
            QLabel#pathLabel {
                color: #9fb3c7;
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
            """
        )

    def append(self, text: str) -> None:
        self.txt_details.appendPlainText(text)

    def select_license(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите license.json",
            "",
            "License JSON (*.json);;All Files (*.*)",
        )
        if not path:
            return
        try:
            dst = save_license_from_file(path)
            self.append(f"Сохранено: {dst}")
        except Exception as exc:
            self.append(f"Ошибка копирования: {exc}")

    def _set_status_style(self, ok: bool) -> None:
        if ok:
            self.lbl_status.setStyleSheet(
                "background:#17302b;border:1px solid #3f8a74;color:#c9f1e4;padding:8px 10px;border-radius:10px;"
            )
        else:
            self.lbl_status.setStyleSheet(
                "background:#2f1a1a;border:1px solid #8a5151;color:#ffd7d2;padding:8px 10px;border-radius:10px;"
            )

    def check_license(self):
        result = validate_current_license(
            public_key_b64=self.public_key_b64,
            expected_product=self.expected_product,
        )
        self.lbl_status.setText(result.message)
        self._set_status_style(result.ok)
        self.append(result.message)
        if result.ok and result.payload:
            self.payload = result.payload
            self.append(
                f"license_to={result.payload.license_to}, "
                f"type={result.payload.type}, expires={result.payload.expires_date.isoformat()}"
            )
            self.accept()


def require_valid_license(
    public_key_b64: str,
    expected_product: str,
    parent=None,
) -> Optional[LicensePayload]:
    dlg = LicenseDialog(public_key_b64=public_key_b64, expected_product=expected_product, parent=parent)
    rc = dlg.exec_()
    if rc == QtWidgets.QDialog.Accepted:
        return dlg.payload
    return None
