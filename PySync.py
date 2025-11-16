import os
import sys
import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFileDialog, QListWidget, QCheckBox,
    QMessageBox, QTextEdit, QProgressBar
)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, Qt

# --- Core Synchronization Logic ---

def sync_folders_for_gui(worker, source_dir: Path, dest_dirs: list[Path], dry_run: bool):
    try:
        worker.progress.emit(f"Scanning for files to sync from '{source_dir}'...")

        files_to_copy = []
        for dirpath, _, filenames in os.walk(source_dir):
            if worker.is_cancellation_requested():
                break
            for filename in filenames:
                if worker.is_cancellation_requested():
                    break
                source_file_path = Path(dirpath) / filename
                relative_path = source_file_path.relative_to(source_dir)
                for dest_dir in dest_dirs:
                    dest_file_path = dest_dir / relative_path

                    should_copy = True
                    if dest_file_path.exists():
                        if source_file_path.stat().st_mtime <= dest_file_path.stat().st_mtime:
                            should_copy = False

                    if should_copy:
                        files_to_copy.append((source_file_path, dest_file_path))

        if worker.is_cancellation_requested():
            worker.progress.emit("Scan cancelled.")
            return

        worker.total_files.emit(len(files_to_copy))

        if dry_run:
            worker.progress.emit("--- DRY RUN MODE ENABLED ---")
            for src, dest in files_to_copy:
                if worker.is_cancellation_requested():
                    break
                worker.progress.emit(f"Will copy '{src.name}' to '{dest.parent}'")
                worker.file_copied.emit()
            worker.progress.emit("--- DRY RUN MODE CONCLUDED ---")
            return

        worker.progress.emit(f"Found {len(files_to_copy)} files to copy. Starting...")

        with ThreadPoolExecutor() as executor:
            for _, dest_path in files_to_copy:
                if not dest_path.parent.exists():
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

            futures = {executor.submit(shutil.copy2, src, dest): src for src, dest in files_to_copy}

            for future in as_completed(futures):
                if worker.is_cancellation_requested():
                    for f in futures:
                        f.cancel()
                    break
                source_file = futures[future]
                try:
                    future.result()
                    worker.progress.emit(f"Copied '{source_file.name}'")
                    worker.file_copied.emit()
                except Exception as e:
                    if not isinstance(e, shutil.SameFileError):
                        worker.progress.emit(f"Error copying '{source_file.name}': {e}")

        if worker.is_cancellation_requested():
            worker.progress.emit("Synchronization cancelled by user.")
        else:
            worker.progress.emit("Synchronization process completed successfully.")

    except Exception as e:
        worker.progress.emit(f"An unexpected error occurred: {e}")

# --- Worker Thread ---

class SyncWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    total_files = pyqtSignal(int)
    file_copied = pyqtSignal()

    def __init__(self, source_dir, dest_dirs, dry_run):
        super().__init__()
        self.source_dir = source_dir
        self.dest_dirs = dest_dirs
        self.dry_run = dry_run
        self._is_cancellation_requested = False

    def run(self):
        if self.source_dir and self.dest_dirs:
            sync_folders_for_gui(self, self.source_dir, self.dest_dirs, self.dry_run)
        self.finished.emit()

    def request_cancellation(self):
        self._is_cancellation_requested = True

    def is_cancellation_requested(self):
        return self._is_cancellation_requested

# --- Main Application Window ---

class SyncApp(QWidget):
    def __init__(self):
        super().__init__()
        self.source_dir = None
        self.thread = None
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Folder Synchronization Tool')
        self.setGeometry(200, 200, 700, 500)
        main_layout = QVBoxLayout(self)

        # Profile Management
        profile_layout = QHBoxLayout()
        self.save_profile_btn = QPushButton("Save Profile")
        self.load_profile_btn = QPushButton("Load Profile")
        self.save_profile_btn.clicked.connect(self.save_profile)
        self.load_profile_btn.clicked.connect(self.load_profile)
        profile_layout.addStretch()
        profile_layout.addWidget(self.save_profile_btn)
        profile_layout.addWidget(self.load_profile_btn)
        main_layout.addLayout(profile_layout)

        # Source Folder Selection
        source_layout = QHBoxLayout()
        self.source_label = QLabel("Source Folder:")
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_browse_btn = QPushButton("Browse...")
        self.source_browse_btn.clicked.connect(self.select_source_folder)
        source_layout.addWidget(self.source_label)
        source_layout.addWidget(self.source_path_edit)
        source_layout.addWidget(self.source_browse_btn)
        main_layout.addLayout(source_layout)

        # Destination Folders
        dest_label = QLabel("Destination Folders:")
        main_layout.addWidget(dest_label)
        self.dest_list_widget = QListWidget()
        main_layout.addWidget(self.dest_list_widget)
        dest_buttons_layout = QHBoxLayout()
        self.dest_add_btn = QPushButton("Add Folder")
        self.dest_add_btn.clicked.connect(self.add_destination_folder)
        self.dest_remove_btn = QPushButton("Remove Selected")
        self.dest_remove_btn.clicked.connect(self.remove_destination_folder)
        dest_buttons_layout.addStretch()
        dest_buttons_layout.addWidget(self.dest_add_btn)
        dest_buttons_layout.addWidget(self.dest_remove_btn)
        main_layout.addLayout(dest_buttons_layout)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Controls
        controls_layout = QHBoxLayout()
        self.dry_run_checkbox = QCheckBox("Dry Run (Simulate sync)")
        self.sync_btn = QPushButton("Start Sync")
        self.sync_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.sync_btn.clicked.connect(self.start_sync)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_sync)
        self.cancel_btn.setEnabled(False)
        controls_layout.addWidget(self.dry_run_checkbox)
        controls_layout.addStretch()
        controls_layout.addWidget(self.sync_btn)
        controls_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(controls_layout)

        # Log Output
        log_layout = QHBoxLayout()
        log_label = QLabel("Log:")
        self.save_log_btn = QPushButton("Save Log...")
        self.save_log_btn.clicked.connect(self.save_log_to_file)
        log_layout.addWidget(log_label)
        log_layout.addStretch()
        log_layout.addWidget(self.save_log_btn)
        main_layout.addLayout(log_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(self.log_output)

    def select_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if folder:
            self.source_dir = Path(folder)
            self.source_path_edit.setText(str(self.source_dir))

    def add_destination_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.dest_list_widget.addItem(folder)

    def remove_destination_folder(self):
        for item in self.dest_list_widget.selectedItems():
            self.dest_list_widget.takeItem(self.dest_list_widget.row(item))

    def save_log_to_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log", "sync_log.txt", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_output.toPlainText())
                QMessageBox.information(self, "Success", f"Log saved to {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not save log: {e}")

    def save_profile(self):
        if not self.source_dir:
            QMessageBox.warning(self, "Warning", "Cannot save an empty profile. Please select a source folder.")
            return

        dest_paths = [self.dest_list_widget.item(i).text() for i in range(self.dest_list_widget.count())]
        profile_data = {
            "source": str(self.source_dir),
            "destinations": dest_paths,
            "dry_run": self.dry_run_checkbox.isChecked()
        }

        file_path, _ = QFileDialog.getSaveFileName(self, "Save Profile", "sync_profile.json", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(profile_data, f, indent=4)
                QMessageBox.information(self, "Success", "Profile saved successfully.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save profile: {e}")

    def load_profile(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Profile", "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    profile_data = json.load(f)

                self.source_dir = Path(profile_data["source"])
                self.source_path_edit.setText(profile_data["source"])

                self.dest_list_widget.clear()
                for dest in profile_data["destinations"]:
                    self.dest_list_widget.addItem(dest)

                self.dry_run_checkbox.setChecked(profile_data.get("dry_run", False))
                QMessageBox.information(self, "Success", "Profile loaded successfully.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load profile: {e}")

    def set_progress_max(self, value):
        self.progress_bar.setMaximum(value)

    def update_progress_bar(self):
        self.progress_bar.setValue(self.progress_bar.value() + 1)

    def set_controls_enabled(self, enabled):
        is_syncing = not enabled
        self.source_browse_btn.setEnabled(enabled)
        self.dest_add_btn.setEnabled(enabled)
        self.dest_remove_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.dry_run_checkbox.setEnabled(enabled)
        self.save_log_btn.setEnabled(enabled)
        self.save_profile_btn.setEnabled(enabled)
        self.load_profile_btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(is_syncing)
        self.sync_btn.setText("Start Sync" if enabled else "Syncing...")

    def start_sync(self):
        if not self.source_dir:
            QMessageBox.warning(self, "Warning", "Please select a source folder.")
            return

        dest_paths = [Path(self.dest_list_widget.item(i).text()) for i in range(self.dest_list_widget.count())]
        if not dest_paths:
            QMessageBox.warning(self, "Warning", "Please add at least one destination folder.")
            return

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.set_controls_enabled(False)

        self.thread = QThread()
        self.worker = SyncWorker(self.source_dir, dest_paths, self.dry_run_checkbox.isChecked())
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_log)
        self.worker.total_files.connect(self.set_progress_max)
        self.worker.file_copied.connect(self.update_progress_bar)
        self.thread.finished.connect(self.sync_finished)

        self.thread.start()

    def cancel_sync(self):
        if self.worker:
            self.worker.request_cancellation()

    def sync_finished(self):
        self.set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "Success", "Synchronization process has finished.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SyncApp()
    window.show()
    sys.exit(app.exec())
